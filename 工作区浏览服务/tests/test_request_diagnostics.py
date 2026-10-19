import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.services.request_diagnostics import RequestDiagnostics, RequestDiagnosticsMiddleware


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.monitor = RequestDiagnostics(Path(self.directory.name))
        self.addCleanup(self.monitor.close_logs)

    def events(self):
        return [json.loads(line) for line in (Path(self.directory.name) / 'request-diagnostics.jsonl').read_text('utf-8').splitlines()]

    def test_fast_request_creates_no_log_and_slow_request_records_bounded_fields(self):
        with patch('backend.services.request_diagnostics.time.monotonic', side_effect=[10, 11, 20, 22.5]):
            self.monitor.finish(self.monitor.begin('GET', '/api/service'), 200)
            self.assertFalse(list(Path(self.directory.name).iterdir()))
            self.monitor.finish(self.monitor.begin('GET', '/api/projects/示例项目/status'), 200)
        record = self.events()[0]
        self.assertEqual(record['event'], 'slow_request')
        self.assertEqual(record['seconds'], 2.5)
        self.assertEqual(record['status'], 200)
        self.assertEqual(record['phase'], 'response_headers')
        self.assertTrue(record['time'].endswith('+00:00'))
        self.assertNotIn('query', record)
        self.assertNotIn('body', record)

    def test_stalled_request_logs_once_until_recovery_and_captures_real_threads(self):
        with patch('backend.services.request_diagnostics.time.monotonic', return_value=100):
            key = self.monitor.begin('GET', '/api/projects/示例项目/episodes/EP003')
        with patch('backend.services.request_diagnostics.time.monotonic', return_value=116):
            self.monitor.last_heartbeat = 116
            self.monitor.check_stalls()
            self.monitor.check_stalls()
            self.monitor.finish(key, 200)
            self.monitor.check_stalls()
        self.assertEqual([item['event'] for item in self.events()], ['service_stalled', 'slow_request', 'service_recovered'])
        self.assertEqual(self.events()[0]['overdue_count'], 1)
        stacks = (Path(self.directory.name) / 'request-stacks.log').read_text('utf-8')
        self.assertIn('test_stalled_request_logs_once', stacks)
        self.assertIn('native_id', stacks)

    def test_event_loop_stall_is_detected_without_an_accepted_request(self):
        self.monitor.last_heartbeat = 100
        with patch('backend.services.request_diagnostics.time.monotonic', return_value=116), patch.object(self.monitor, 'dump_stacks') as dump:
            self.monitor.check_stalls()
            self.monitor.check_stalls()
            self.assertEqual(dump.call_count, 1)
        self.assertEqual(self.events()[0]['overdue_count'], 0)
        self.assertEqual(self.events()[0]['loop_lag_seconds'], 16)

    def test_diagnostic_disk_failure_does_not_fail_the_request(self):
        with patch('backend.services.request_diagnostics.time.monotonic', return_value=100):
            key = self.monitor.begin('GET', '/api/service')
        with patch('backend.services.request_diagnostics.time.monotonic', return_value=103), patch.object(
                Path, 'mkdir', side_effect=PermissionError('diagnostic directory unavailable')), self.assertLogs(
                'backend.services.request_diagnostics', level='ERROR') as logs:
            self.monitor.finish(key, 200)
        self.assertEqual(self.monitor.pending, {})
        self.assertIn('diagnostic directory unavailable', logs.output[0])

    def test_logs_rotate_and_stack_history_is_bounded(self):
        self.monitor.handler.maxBytes = 300
        for _ in range(20):
            self.monitor.write('test', text='bounded log')
        logs = list(Path(self.directory.name).glob('request-diagnostics.jsonl*'))
        self.assertLessEqual(len(logs), 3)
        self.assertGreater(len(logs), 1)
        stack = Path(self.directory.name) / 'request-stacks.log'
        stack.write_bytes(b'x' * (2 * 1024 * 1024))
        self.monitor.dump_stacks()
        self.assertEqual(stack.with_suffix('.log.1').stat().st_size, 2 * 1024 * 1024)
        self.assertLess(stack.stat().st_size, 2 * 1024 * 1024)


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.monitor = RequestDiagnostics(Path(self.directory.name))
        self.addCleanup(self.monitor.close_logs)
        self.scope = {'type': 'http', 'method': 'GET', 'path': '/api/comfy/events',
                      'query_string': b'token=must-not-be-recorded',
                      'app': SimpleNamespace(state=SimpleNamespace(request_diagnostics=self.monitor))}

    async def send(self, message):
        pass

    async def test_streaming_headers_end_measurement_before_stream_closes(self):
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            self.assertEqual(self.monitor.pending, {})
            await asyncio.sleep(0)
            await send({'type': 'http.response.body', 'body': b'data', 'more_body': True})
        await RequestDiagnosticsMiddleware(app)(self.scope, None, self.send)
        self.assertFalse(list(Path(self.directory.name).iterdir()))

    async def test_exception_and_cancellation_clear_pending_requests(self):
        for failure in (ValueError('invalid'), asyncio.CancelledError()):
            async def app(scope, receive, send):
                raise failure
            with self.assertRaises(type(failure)):
                await RequestDiagnosticsMiddleware(app)(self.scope, None, self.send)
            self.assertEqual(self.monitor.pending, {})

    async def test_slow_request_never_records_query_headers_or_body(self):
        async def app(scope, receive, send):
            with patch('backend.services.request_diagnostics.time.monotonic', return_value=103):
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        with patch('backend.services.request_diagnostics.time.monotonic', return_value=100):
            await RequestDiagnosticsMiddleware(app)(self.scope, None, self.send)
        text = (Path(self.directory.name) / 'request-diagnostics.jsonl').read_text('utf-8')
        self.assertNotIn('must-not-be-recorded', text)
        self.assertIn('slow_request', text)

    async def test_watchdog_captures_stacks_while_the_event_loop_is_blocked(self):
        self.monitor.stalled_seconds = .05
        self.monitor.start()
        try:
            await asyncio.sleep(0)
            time.sleep(1.2)  # Deliberate isolated reproduction of a blocked ASGI loop.
            self.assertIn('service_stalled', (Path(self.directory.name) / 'request-diagnostics.jsonl').read_text('utf-8'))
            self.assertIn('test_watchdog_captures_stacks', (Path(self.directory.name) / 'request-stacks.log').read_text('utf-8'))
        finally:
            await self.monitor.close()

    async def test_watchdog_writes_no_idle_stall_and_closes_its_thread(self):
        self.monitor.start()
        await asyncio.sleep(0)
        worker = self.monitor.worker
        self.assertTrue(worker.is_alive())
        await self.monitor.close()
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.monitor.heartbeat_task.done())
        self.assertFalse(list(Path(self.directory.name).iterdir()))


if __name__ == '__main__':
    unittest.main()
