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
        self.config = {'remote-urls': [A, B, C]}
        self.write_config()
        self.workflow = {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'source.png', 'seed': 84781009642919}}}
        self.path = self.root / 'task.api.json'
        self.path.write_text(json.dumps(self.workflow), encoding='utf-8')
        self.post_errors = {}
        self.calls = []
        owner = self

        class FakeClient:
            def __init__(self, url, timeout):
                self.url, self.timeout = url.rstrip('/'), timeout

            def json(self, route, data=None, headers=None):
                owner.calls.append((self.url, route, data))
                if route == '/prompt':
                    if self.url in owner.post_errors:
                        raise owner.post_errors[self.url]
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
            record_dir=str(self.root / name), eligible_url=A, uploads=None, timeout=30,
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

    def test_video_context_failure_stops_before_post(self):
        self.save_context.side_effect = ValueError('当次分镜版本不一致')
        with self.assertRaisesRegex(ValueError, '当次分镜版本不一致'):
            d.dispatch(self.args(task_type='video-first-pass'))
        self.assertFalse(any(route == '/prompt' for _, route, _ in self.calls))
        self.assertFalse((self.root / 'first/submit-attempt.json').exists())

    def test_image_submission_does_not_save_video_context(self):
        d.dispatch(self.args())
        self.save_context.assert_not_called()

    def test_h3_rejects_incorrect_task_type(self):
        self.path.write_text(json.dumps({'1': {'class_type': 'MiniMaxH3Director', 'inputs': {}}}), encoding='utf-8')
        for kind in ('image', 'video-postprocess'):
            with self.subTest(kind=kind):
                with self.assertRaises(d.client.ClientError) as caught:
                    d.dispatch(self.args(task_type=kind))
                self.assertEqual(caught.exception.code, 'invalid_task_type')
        self.assertEqual(self.calls, [])

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

    def test_uploads_use_primary_endpoint_and_actual_returned_path(self):
        source = self.root / 'approved.png'
        source.write_bytes(b'file bytes')
        uploads = [{'file': str(source), 'node': '1', 'input': 'image',
                    'subfolder': 'inputs', 'response-name': 'upload.json'}]
        mapping = self.root / 'uploads.json'
        mapping.write_text(json.dumps(uploads), encoding='utf-8')
        with patch.object(d.client, 'upload', return_value={'input_path': 'inputs/renamed.png'}) as upload:
            result = d.dispatch(self.args(uploads=str(mapping)))
        self.assertEqual(result['url'], A)
        self.assertEqual(upload.call_args.args[0].url, A)
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
        self.assertEqual(self.calls, [])
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
        self.assertEqual(d.dispatch(self.args())['dispatch_state'], 'accepted')
        self.assertEqual(json.loads((self.root / 'comfyui-config.json').read_text()), self.config)

    def test_invalid_config_fails_before_network(self):
        self.config['remote-urls'] = []
        self.write_config()
        with self.assertRaises(d.client.ClientError):
            d.dispatch(self.args())
        self.assertEqual(self.calls, [])

    def test_all_task_types_submit_to_primary_without_reading_remote_queue(self):
        for kind in d.TASK_TYPES:
            with self.subTest(kind=kind):
                self.calls.clear()
                result = d.dispatch(self.args(name=kind, task_type=kind))
                self.assertEqual(result['url'], A)
                self.assertEqual([(url, route) for url, route, _ in self.calls], [(A, '/prompt')])
                request = json.loads((self.root / kind / 'request.json').read_text())
                self.assertEqual(request['prompt'], self.workflow)
        self.assertEqual(self.save_context.call_count, len(d.VIDEO_CONTEXT_TASK_TYPES))

    def test_nonprimary_eligibility_fails_before_network_or_evidence(self):
        with self.assertRaises(d.client.ClientError) as caught:
            d.dispatch(self.args(eligible_url=B))
        self.assertEqual(caught.exception.code, 'invalid_eligibility')
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'first').exists())

    def test_primary_post_timeout_is_not_retried_or_sent_to_backup(self):
        self.post_errors[A] = d.client.ClientError('transport_error', 'timeout')
        args = self.args()
        with self.assertRaises(d.client.ClientError):
            d.dispatch(args)
        with self.assertRaises(d.client.ClientError) as caught:
            d.dispatch(args)
        self.assertEqual(caught.exception.code, 'submission_guard')
        self.assertEqual([(url, route) for url, route, _ in self.calls], [(A, '/prompt')])
        marker = json.loads((self.root / 'first/submit-attempt.json').read_text())
        self.assertEqual(marker['url'], A)
        response = json.loads((self.root / 'first/response.json').read_text())
        self.assertEqual(response['submission_state'], 'unknown')

    def test_removed_routing_options_are_rejected(self):
        argv = ['--project', str(self.root), '--task-type', 'image', '--workflow', str(self.path),
                '--eligible-url', A, '--record-dir', str(self.root / 'first')]
        for option in (['--allow-queue'], ['--target-url', B]):
            with self.subTest(option=option):
                with self.assertRaises(d.client.ClientError):
                    d.parser().parse_args(argv + option)

    def test_removed_config_fields_are_rejected(self):
        self.config['enable-multi-remote'] = True
        self.write_config()
        with self.assertRaises(d.client.ClientError) as caught:
            d.dispatch(self.args())
        self.assertEqual(caught.exception.code, 'invalid_config')
        self.assertEqual(self.calls, [])

if __name__ == '__main__':
    unittest.main()
