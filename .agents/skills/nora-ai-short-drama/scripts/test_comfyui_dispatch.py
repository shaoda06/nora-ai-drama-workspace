"""Dispatch behavior with fake HTTP responses; no server or media generation."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import comfyui_dispatch as d

A, B, C = ('http://a.invalid:8188', 'http://b.invalid:8188', 'http://c.invalid:8188')


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'enable-multi-remote': True, 'remote-urls': [A, B, C],
                       'busy-pending-threshold': 2, 'default-only-task-types': list(d.DEFAULT_ONLY_TASK_TYPES)}
        self.write_config()
        self.workflow = {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'source.png', 'seed': 84781009642919}}}
        self.path = self.root / 'task.api.json'
        self.path.write_text(json.dumps(self.workflow), encoding='utf-8')
        self.queues = {url: (0, 0) for url in (A, B, C)}
        self.post_errors = {}
        self.calls = []
        owner = self

        class FakeClient:
            def __init__(self, url, timeout):
                self.url, self.timeout = url.rstrip('/'), timeout

            def json(self, route, data=None, headers=None):
                owner.calls.append((self.url, route, data))
                if route == '/queue':
                    state = owner.queues[self.url]
                    if isinstance(state, Exception):
                        raise state
                    if isinstance(state, tuple):
                        pending, running = state
                        item = [0, 'existing-job', {'1': {'class_type': 'LoadImage',
                                'inputs': {'image': 'private inputs'}}}, {}, ['1']]
                        state = {'queue_pending': [item] * pending, 'queue_running': [item] * running}
                        owner.queues[self.url] = state
                    return state
                if route == '/prompt':
                    if self.url in owner.post_errors:
                        raise owner.post_errors[self.url]
                    request = json.loads(data)
                    owner.queues[self.url]['queue_pending'].append(
                        [0, 'new-job', request['prompt'], {}, list(request['prompt'])])
                    return {'prompt_id': f'job-{len(owner.calls)}'}
                raise AssertionError(route)

        self.patch_client = patch.object(d.client, 'Client', FakeClient)
        self.patch_client.start()
        self.addCleanup(self.patch_client.stop)
        self.patch_lock = patch.object(d, 'LOCK_PATH', self.root / 'shared.lock')
        self.patch_lock.start()
        self.addCleanup(self.patch_lock.stop)
        self.context_patch = patch.object(d, 'prepare_generation_context')
        self.save_context = self.context_patch.start()
        self.addCleanup(self.context_patch.stop)

    def write_config(self):
        (self.root / 'comfyui-config.json').write_text(json.dumps(self.config), encoding='utf-8')

    def args(self, name='first', **overrides):
        result = argparse.Namespace(project=str(self.root), workflow=str(self.path), task_type='image',
            record_dir=str(self.root / name), eligible_url=[A, B, C], target_url=None, allow_queue=False, uploads=None, timeout=30,
            attempt_name='submit-attempt.json', request_name='request.json', response_name='response.json',
            monitor='legacy', output_plan=None, segment_plan=None, task_title=None, thread_id=None, history_name='执行结果.json')
        for key, value in overrides.items():
            setattr(result, key, value)
        return result

    def test_browser_mode_hands_selected_workflow_to_service_without_direct_post(self):
        args = self.args(monitor='browser', output_plan='explicit-plan.json')
        with patch.object(d.browser_tasks, 'submit', return_value={'prompt_id': 'service-id', 'monitor': 'browser'}) as handoff:
            result = d.dispatch(args)
        self.assertEqual(result['prompt_id'], 'service-id')
        handoff.assert_called_once_with(args, self.workflow, A)
        self.assertFalse(any(route == '/prompt' for _, route, _ in self.calls))

    def test_browser_mode_requires_explicit_output_plan_before_remote_access(self):
        with self.assertRaises(ValueError):
            d.dispatch(self.args(monitor='browser'))
        self.assertEqual(self.calls, [])

    def test_native_browser_mode_requires_segment_registration_before_network(self):
        self.workflow = {'502': {'class_type': 'MiniMaxH3Director', 'inputs': {
            'timeline_data': json.dumps({'output': {'exportMode': 'segments'}})}}}
        self.path.write_text(json.dumps(self.workflow))
        with self.assertRaisesRegex(ValueError, 'segment-plan'):
            d.dispatch(self.args(monitor='browser', output_plan='empty.json', task_type='video-first-pass'))
        self.assertEqual(self.calls, [])

    def test_running_and_one_pending_still_use_default(self):
        self.queues[A] = (1, 1)
        result = d.dispatch(self.args())
        self.assertEqual(result['url'], A)
        self.assertFalse(any(url == B for url, _, _ in self.calls))
        request = json.loads((self.root / 'first/request.json').read_text())
        self.assertEqual(request['prompt'], self.workflow)

    def test_two_pending_overflow_uses_next_eligible(self):
        self.queues[A] = (2, 1)
        result = d.dispatch(self.args(eligible_url=[A, C]))
        self.assertEqual(result['url'], C)
        self.assertFalse(any(url == B for url, _, _ in self.calls))
        self.assertNotIn('private inputs', json.dumps(result))

    def test_disabled_never_checks_backup_even_when_default_is_full(self):
        self.config['enable-multi-remote'] = False
        self.write_config()
        self.queues[A] = (2, 1)
        result = d.dispatch(self.args())
        self.assertEqual(result['dispatch_state'], 'deferred')
        self.assertEqual([(url, route) for url, route, _ in self.calls], [(A, '/queue')])
        self.assertFalse((self.root / 'first/submit-attempt.json').exists())

    def test_video_passes_and_postprocess_stay_default_when_busy_or_offline(self):
        for kind in d.DEFAULT_ONLY_TASK_TYPES:
            for state in ((2, 1), d.client.ClientError('transport_error', 'offline')):
                with self.subTest(kind=kind, state=state):
                    self.calls.clear()
                    self.queues[A] = state
                    result = d.dispatch(self.args(task_type=kind))
                    self.assertEqual(result['dispatch_state'], 'deferred')
                    self.assertEqual([(url, route) for url, route, _ in self.calls], [(A, '/queue')])
                    self.assertFalse((self.root / 'first').exists())

    def test_authorized_queue_override_keeps_default_and_posts_once(self):
        self.queues[A] = {'queue_pending': [[0, 'waiting', {'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}]] * 2,
                          'queue_running': [[0, 'running', {'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}]]}
        args = self.args(task_type='video-first-pass', allow_queue=True)
        result = d.dispatch(args)
        self.assertEqual(result['url'], A)
        self.assertTrue(result['checks'][0]['allow_queue'])
        with self.assertRaises(d.client.ClientError) as caught:
            d.dispatch(args)
        self.assertEqual(caught.exception.code, 'submission_guard')
        self.assertEqual(sum(route == '/prompt' for _, route, _ in self.calls), 1)
        self.assertFalse(any(url != A for url, _, _ in self.calls))

    def test_queue_override_does_not_submit_with_unknown_queue(self):
        self.queues[A] = d.client.ClientError('transport_error', 'offline')
        result = d.dispatch(self.args(task_type='video-first-pass', allow_queue=True))
        self.assertEqual(result['dispatch_state'], 'deferred')
        self.assertEqual(result['checks'][0]['state'], 'unknown')
        self.assertFalse((self.root / 'first').exists())
        self.assertFalse(any(route == '/prompt' for _, route, _ in self.calls))

    def test_only_image_tasks_overflow_to_backup(self):
        for kind in ('image', 'image-upscale'):
            with self.subTest(kind=kind):
                self.queues = {A: (2, 1), B: (0, 0), C: (0, 0)}
                self.assertEqual(d.dispatch(self.args(name=kind, task_type=kind))['url'], B)

    def test_batches_fill_default_before_overflow(self):
        urls = [d.dispatch(self.args(name=f'task-{i}'))['url'] for i in range(5)]
        self.assertEqual(urls, [A, A, B, B, C])

    def test_running_or_pending_video_blocks_all_new_task_types(self):
        for node in ('MiniMaxH3Director', 'MiniMaxH3ReferenceToVideo'):
            for field in ('queue_running', 'queue_pending'):
                for kind in d.TASK_TYPES:
                    with self.subTest(node=node, field=field, kind=kind):
                        self.queues = {url: (0, 0) for url in (A, B, C)}
                        item = [0, 'manual-video', {'1': {'class_type': node,
                                'inputs': {'prompt': 'private inputs'}}}, {}, ['1']]
                        self.queues[A] = {'queue_running': [], 'queue_pending': []}
                        self.queues[A][field] = [item]
                        result = d.dispatch(self.args(name=f'{node}-{field}-{kind}', task_type=kind))
                        self.assertEqual(result['checks'][0]['video_jobs'], 1)
                        self.assertEqual(result['checks'][0]['reason'], 'video_generation')
                        self.assertNotIn('private inputs', json.dumps(result))
                        if kind in d.DEFAULT_ONLY_TASK_TYPES:
                            self.assertEqual(result['dispatch_state'], 'deferred')
                        else:
                            self.assertEqual(result['url'], B)

    def test_disabled_defers_while_default_video_is_running(self):
        self.config['enable-multi-remote'] = False
        self.write_config()
        self.queues[A] = {'queue_pending': [], 'queue_running': [
            [0, 'video', {'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}]]}
        result = d.dispatch(self.args())
        self.assertEqual(result['dispatch_state'], 'deferred')
        self.assertEqual([(url, route) for url, route, _ in self.calls], [(A, '/queue')])
        self.assertFalse((self.root / 'first').exists())

    def test_video_batch_stays_default_and_defers_next_job(self):
        self.path.write_text(json.dumps({'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}), encoding='utf-8')
        results = [d.dispatch(self.args(name=f'video-{i}', task_type='video-first-pass')) for i in range(4)]
        self.assertEqual(results[0]['url'], A)
        self.assertTrue(all(r['dispatch_state'] == 'deferred' for r in results[1:]))
        self.assertFalse(any(url != A for url, _, _ in self.calls))
        self.assertFalse((self.root / 'video-1').exists())
        self.assertEqual(self.save_context.call_count, 1)

    def test_video_context_failure_stops_before_post(self):
        self.save_context.side_effect = ValueError('当次分镜版本不一致')
        with self.assertRaisesRegex(ValueError, '当次分镜版本不一致'):
            d.dispatch(self.args(task_type='video-first-pass'))
        self.assertFalse(any(route == '/prompt' for _, route, _ in self.calls))
        self.assertFalse((self.root / 'first/submit-attempt.json').exists())

    def test_image_submission_does_not_save_video_context(self):
        d.dispatch(self.args())
        self.save_context.assert_not_called()

    def test_user_selected_endpoint_overrides_default_for_video_passes_and_postprocess(self):
        for kind in d.DEFAULT_ONLY_TASK_TYPES:
            with self.subTest(kind=kind):
                self.queues = {url: (0, 0) for url in (A, B, C)}
                result = d.dispatch(self.args(name=kind, task_type=kind, target_url=B))
                self.assertEqual(result['url'], B)
                self.assertEqual(result['checks'][0]['url'], B)
        self.assertFalse(any(url != B for url, _, _ in self.calls))

    def test_explicit_target_is_allowed_with_automatic_overflow_disabled(self):
        self.config['enable-multi-remote'] = False
        self.write_config()
        self.assertEqual(d.dispatch(self.args(target_url=B))['url'], B)
        self.assertFalse(any(url != B for url, _, _ in self.calls))

    def test_busy_or_unreachable_target_never_falls_back(self):
        for state in ((2, 0), d.client.ClientError('transport_error', 'offline')):
            with self.subTest(state=state):
                self.queues[B] = state
                result = d.dispatch(self.args(target_url=B))
                self.assertEqual(result['dispatch_state'], 'deferred')
                self.assertFalse((self.root / 'first').exists())
        self.assertTrue(all(url == B and route == '/queue' for url, route, _ in self.calls))

    def test_target_must_be_configured_and_eligible(self):
        for target, eligible in ((B, [A]), ('http://other.invalid:8188', [A, B])):
            with self.subTest(target=target):
                with self.assertRaises(d.client.ClientError) as caught:
                    d.dispatch(self.args(target_url=target, eligible_url=eligible))
                self.assertEqual(caught.exception.code, 'invalid_target')
        self.assertEqual(self.calls, [])

    def test_deferred_task_can_submit_once_capacity_returns(self):
        args = self.args(task_type='video-first-pass')
        self.queues[A] = (2, 0)
        self.assertEqual(d.dispatch(args)['dispatch_state'], 'deferred')
        self.assertFalse((self.root / 'first').exists())
        self.queues[A] = (0, 0)
        self.assertEqual(d.dispatch(args)['url'], A)
        with self.assertRaises(d.client.ClientError) as caught:
            d.dispatch(args)
        self.assertEqual(caught.exception.code, 'submission_guard')
        self.assertEqual(sum(route == '/prompt' for _, route, _ in self.calls), 1)

    def test_h3_cannot_bypass_video_routing_by_mislabeling_as_image(self):
        self.path.write_text(json.dumps({'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}), encoding='utf-8')
        for kind in ('image', 'video-postprocess'):
            with self.subTest(kind=kind):
                with self.assertRaises(d.client.ClientError) as caught:
                    d.dispatch(self.args(task_type=kind))
                self.assertEqual(caught.exception.code, 'invalid_task_type')
        self.assertEqual(self.calls, [])

    def test_legacy_second_pass_only_list_still_pins_all_video_stages(self):
        self.config['default-only-task-types'] = ['video-second-pass']
        self.write_config()
        self.queues[A] = (2, 0)
        for kind in d.DEFAULT_ONLY_TASK_TYPES:
            with self.subTest(kind=kind):
                self.assertEqual(d.dispatch(self.args(task_type=kind))['dispatch_state'], 'deferred')
        self.assertFalse(any(url != A for url, _, _ in self.calls))
        self.assertEqual(json.loads((self.root / 'comfyui-config.json').read_text()), self.config)

    def test_postprocess_does_not_reserve_endpoint_and_completed_video_releases_it(self):
        self.queues[A] = {'queue_pending': [], 'queue_running': [
            [0, 'postprocess', {'1': {'class_type': 'VHS_VideoCombine', 'inputs': {}}}]]}
        result = d.dispatch(self.args())
        self.assertEqual(result['url'], A)
        self.assertEqual(result['checks'][0]['video_jobs'], 0)
        self.queues[A] = {'queue_pending': [], 'queue_running': [
            [0, 'video', {'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}]]}
        self.assertEqual(d.dispatch(self.args(name='during-video'))['url'], B)
        self.queues[A] = (0, 0)
        self.assertEqual(d.dispatch(self.args(name='after-completion'))['url'], A)

    def test_unreadable_queue_is_unknown_and_not_available(self):
        for item in ([], [0, 'job', None], [0, 'job', {'1': {}}]):
            with self.subTest(item=item):
                self.queues = {url: (0, 0) for url in (A, B, C)}
                self.queues[A] = {'queue_pending': [], 'queue_running': [item]}
                result = d.dispatch(self.args(name=f'malformed-{len(self.calls)}'))
                self.assertEqual(result['checks'][0]['state'], 'unknown')
                self.assertEqual(result['url'], B)

    def test_all_busy_defer_without_post_or_evidence(self):
        self.queues = {url: (2, 1) for url in (A, B, C)}
        self.assertEqual(d.dispatch(self.args())['dispatch_state'], 'deferred')
        self.assertTrue(all(route == '/queue' for _, route, _ in self.calls))
        self.assertFalse((self.root / 'first').exists())

    def test_unreachable_before_submit_can_skip_but_post_timeout_cannot(self):
        self.queues[A] = d.client.ClientError('transport_error', 'offline')
        self.assertEqual(d.dispatch(self.args())['url'], B)
        self.calls.clear()
        self.queues[A] = (0, 0)
        self.post_errors[A] = d.client.ClientError('transport_error', 'timeout')
        with self.assertRaises(d.client.ClientError):
            d.dispatch(self.args(name='new'))
        self.assertFalse(any(url != A for url, _, _ in self.calls))
        marker = json.loads((self.root / 'new/submit-attempt.json').read_text())
        self.assertEqual(marker['url'], A)
        self.assertEqual(json.loads((self.root / 'new/response.json').read_text())['submission_state'], 'unknown')

    def test_existing_attempt_is_not_redispatched_after_default_changes(self):
        args = self.args()
        d.dispatch(args)
        self.config['remote-urls'] = [B, A, C]
        self.write_config()
        self.calls.clear()
        with self.assertRaises(d.client.ClientError) as caught:
            d.dispatch(args)
        self.assertEqual(caught.exception.code, 'submission_guard')
        self.assertEqual(self.calls, [])
        marker = json.loads((self.root / 'first/submit-attempt.json').read_text())
        self.assertEqual(marker['url'], A)

    def test_uploads_use_selected_endpoint_and_actual_returned_path(self):
        self.queues[A] = (2, 1)
        source = self.root / 'approved.png'
        source.write_bytes(b'file bytes')
        uploads = [{'file': str(source), 'node': '1', 'input': 'image',
                    'subfolder': 'inputs', 'response-name': 'upload.json'}]
        mapping = self.root / 'uploads.json'
        mapping.write_text(json.dumps(uploads), encoding='utf-8')
        with patch.object(d.client, 'upload', return_value={'input_path': 'inputs/renamed.png'}) as upload:
            result = d.dispatch(self.args(uploads=str(mapping)))
        self.assertEqual(result['url'], B)
        self.assertEqual(upload.call_args.args[0].url, B)
        request = json.loads((self.root / 'first/request.json').read_text())
        self.assertEqual(request['prompt']['1']['inputs']['image'], 'inputs/renamed.png')
        self.assertEqual(json.loads(self.path.read_text()), self.workflow)

    def test_upload_failure_stops_without_post_or_fallback(self):
        source = self.root / 'approved.png'
        source.write_bytes(b'x')
        mapping = self.root / 'uploads.json'
        mapping.write_text(json.dumps([{'file': str(source), 'node': '1', 'input': 'image',
                                       'subfolder': '', 'response-name': 'upload.json'}]), encoding='utf-8')
        with patch.object(d.client, 'upload', side_effect=d.client.ClientError('transport_error', 'timeout')):
            with self.assertRaises(d.client.ClientError):
                d.dispatch(self.args(uploads=str(mapping)))
        self.assertTrue(all(route == '/queue' for _, route, _ in self.calls))
        self.assertFalse(any(url != A for url, _, _ in self.calls))
        self.assertFalse(json.loads((self.root / 'first/upload.json').read_text())['ok'])

    def test_lock_rejects_second_session_until_first_finishes(self):
        with d.submission_lock():
            with self.assertRaises(d.client.ClientError) as caught:
                d.dispatch(self.args())
        self.assertEqual(caught.exception.code, 'dispatcher_busy')
        self.assertEqual(self.calls, [])
        self.assertEqual(d.dispatch(self.args())['dispatch_state'], 'accepted')

    def test_legacy_config_is_single_endpoint_without_rewriting(self):
        self.config = {'remote-url': A}
        self.write_config()
        self.queues[A] = (2, 0)
        self.assertEqual(d.dispatch(self.args(eligible_url=[A]))['dispatch_state'], 'deferred')
        self.assertEqual(json.loads((self.root / 'comfyui-config.json').read_text()), self.config)

    def test_invalid_config_fails_before_network(self):
        self.config['enable-multi-remote'] = 'false'
        self.write_config()
        with self.assertRaises(d.client.ClientError):
            d.dispatch(self.args())
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
