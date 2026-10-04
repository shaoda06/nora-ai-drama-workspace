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
                       'busy-pending-threshold': 2, 'default-only-task-types': ['video-second-pass']}
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
                    pending, running = state
                    return {'queue_pending': [['private inputs']] * pending, 'queue_running': [[]] * running}
                if route == '/prompt':
                    if self.url in owner.post_errors:
                        raise owner.post_errors[self.url]
                    pending, running = owner.queues[self.url]
                    owner.queues[self.url] = (pending + 1, running)
                    return {'prompt_id': f'job-{len(owner.calls)}'}
                raise AssertionError(route)

        self.patch_client = patch.object(d.client, 'Client', FakeClient)
        self.patch_client.start()
        self.addCleanup(self.patch_client.stop)
        self.patch_lock = patch.object(d, 'LOCK_PATH', self.root / 'shared.lock')
        self.patch_lock.start()
        self.addCleanup(self.patch_lock.stop)

    def write_config(self):
        (self.root / 'comfyui-config.json').write_text(json.dumps(self.config), encoding='utf-8')

    def args(self, name='first', **overrides):
        result = argparse.Namespace(project=str(self.root), workflow=str(self.path), task_type='image',
            record_dir=str(self.root / name), eligible_url=[A, B, C], uploads=None, timeout=30,
            attempt_name='submit-attempt.json', request_name='request.json', response_name='response.json')
        for key, value in overrides.items():
            setattr(result, key, value)
        return result

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

    def test_second_pass_stays_default_when_switch_is_on(self):
        self.queues[A] = (2, 1)
        result = d.dispatch(self.args(task_type='video-second-pass'))
        self.assertEqual(result['dispatch_state'], 'deferred')
        self.assertFalse(any(url != A for url, _, _ in self.calls))

    def test_batches_fill_default_before_overflow(self):
        urls = [d.dispatch(self.args(name=f'task-{i}'))['url'] for i in range(5)]
        self.assertEqual(urls, [A, A, B, B, C])

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
