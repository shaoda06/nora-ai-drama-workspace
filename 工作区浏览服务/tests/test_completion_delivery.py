"""Isolated completion -> automatic review registration -> one report read -> user handoff."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from backend import main
from backend.services import comfy_tasks as t, comfy_segments as segments, result_registration as registration
from backend.services.result_summary import batch_tasks
from tests import test_result_closeout as old


class CompletionDeliveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = old.CloseoutTests.asyncSetUp
    asyncTearDown = old.CloseoutTests.asyncTearDown
    video = old.CloseoutTests.video
    setup_video = old.CloseoutTests.setup_video
    download = old.CloseoutTests.download

    async def collect_and_notice(self):
        return await old.CloseoutTests.collect_and_notice(self, automatic=True)

    async def test_automatic_registration_and_browser_ready_before_send(self):
        candidate, draft = self.setup_video()
        observations = []
        # Observe actual send boundary, not the later Agent read.
        async def sent(data, operation, prompt=''):
            if operation == 'read':
                return {'content': [{'type': 'text', 'text': '{"thread":{"status":{"type":"idle"}}}'}]}
            observations.append(prompt)
            self.assertIn('- 决定：待审核', draft.read_text('utf-8'))
            self.assertEqual(self.store.rows['task']['state']['closeout']['status'], 'completed')
            snapshot = json.loads(self.store.db.execute('SELECT report FROM notification_reports').fetchone()[0])
            self.assertTrue(snapshot['user_message_ready'])
            return {}
        with patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', self.terminal)
        with patch.object(self.store, 'desktop_call', sent), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        self.assertEqual(len(observations), 1)
        self.assertIn('browser_tasks.py report', observations[0])
        self.assertNotIn('请先调用 browser_tasks.py ack', observations[0])
        self.assertEqual(self.store.rows['task']['state']['notification'], 'sent')
        self.assertTrue(candidate.is_file())

    async def test_single_report_http_read_authenticates_once_and_acknowledges(self):
        self.setup_video()
        batch = await self.collect_and_notice()
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/report/{batch_id}', main.agent_result_report, methods=['POST'])
        with patch('backend.services.task_notifications.batch_tasks', wraps=batch_tasks) as auth, \
                patch.object(registration, 'register', side_effect=AssertionError('read must not register')), \
                patch.object(self.projects, 'get', side_effect=AssertionError('read must not scan')), \
                patch.object(t.client, 'status', side_effect=AssertionError('no remote')), \
                patch.object(self.store, 'portable_input', side_effect=AssertionError('no full input expansion')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                    headers={'x-nora-task-token': self.store.token}) as http:
                response = await http.post('/report/' + batch, json={'thread_id': self.data.thread_id})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()['user_message_ready'])
                self.assertEqual(response.json()['status'], 'acknowledged')
                self.assertEqual(auth.call_count, 1)
                changes = self.store.db.total_changes
                again = await http.post('/report/' + batch, json={'thread_id': self.data.thread_id})
                self.assertTrue(again.json()['reused'])
                self.assertEqual(self.store.db.total_changes, changes)
                wrong = await http.post('/report/' + batch, json={'thread_id': 'unrelated'})
                self.assertEqual(wrong.status_code, 409)
            self.assertEqual(self.store.rows['task']['state']['notification'], 'acknowledged')

    async def test_saved_report_survives_restart_without_reentering_closeout(self):
        self.setup_video()
        batch = await self.collect_and_notice()
        expected = self.store.read_report(batch, self.data.thread_id)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(registration, 'register', side_effect=AssertionError('no registration')), \
                patch.object(t.client, 'status', side_effect=AssertionError('no remote')):
            restored = self.store.read_report(batch, self.data.thread_id)
        self.assertEqual(restored['tasks'], expected['tasks'])
        self.assertEqual(restored['reported_at'], expected['reported_at'])
        self.assertTrue(restored['reused'])

    async def test_browser_retry_reuses_registration_and_notifies_only_final_result(self):
        _, draft = self.setup_video()
        with patch.object(registration, 'verify', side_effect=[ValueError('scanning'), ValueError('scanning'),
                {'status': 'verified', 'review_path': '/#/projects/test'}]) as verify, \
                patch.object(registration, 'register', wraps=registration.register) as register:
            batch = await self.collect_and_notice()
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(register.call_count, 3)  # Later calls read the completed checkpoint, never edit again.
        self.assertEqual(draft.read_text('utf-8').count('- 决定：待审核'), 1)
        self.assertEqual(self.store.rows['task']['state']['closeout_attempts'], 3)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0], 1)
        self.assertTrue(self.store.read_report(batch, self.data.thread_id)['user_message_ready'])

    async def test_restart_resumes_persisted_closeout_retry_without_resetting_budget(self):
        _, draft = self.setup_video()
        with patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', self.terminal)
        with patch.object(registration, 'verify', side_effect=ValueError('scanning')), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.store.prepare_report(['task'])
        state = self.store.rows['task']['state']
        self.assertEqual(state['closeout_attempts'], 1)
        self.assertIsNotNone(state['closeout_next_retry_at'])
        before = draft.read_bytes()
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.projects = self.projects
        with patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()), \
                patch.object(registration, 'verify', return_value={'status': 'verified', 'review_path': '/test'}):
            report = await self.store.prepare_report(['task'])
        self.assertTrue(report['user_message_ready'])
        self.assertEqual(self.store.rows['task']['state']['closeout_attempts'], 2)
        self.assertEqual(draft.read_bytes(), before)

    async def test_exhaustion_reports_source_and_never_resets_automatically(self):
        self.setup_video()
        with patch.object(registration, 'verify', side_effect=OSError('web unavailable')) as verify:
            batch = await self.collect_and_notice()
        report = self.store.read_report(batch, self.data.thread_id)
        self.assertFalse(report['user_message_ready'])
        self.assertEqual(verify.call_count, 4)
        self.assertEqual(report['results'][0]['status'], 'browser_pending')
        self.assertTrue(report['tasks'][0]['outputs'][0]['path'])
        self.assertEqual(self.store.rows['task']['state']['closeout_retry_stop'], 'exhausted')
        with patch.object(registration, 'register', side_effect=AssertionError('no new budget')):
            again = await self.store.prepare_report(['task'])
        self.assertFalse(again['user_message_ready'])

    async def test_conflict_is_reported_once_without_overwriting_or_retry(self):
        _, draft = self.setup_video()
        draft.write_text(draft.read_text('utf-8') + '\n### R001-一采\n冲突。\n', 'utf-8')
        before = draft.read_bytes()
        batch = await self.collect_and_notice()
        report = self.store.read_report(batch, self.data.thread_id)
        self.assertEqual(report['results'][0]['status'], 'registration_failed')
        self.assertEqual(self.store.rows['task']['state']['closeout_attempts'], 1)
        self.assertFalse(report['user_message_ready'])
        self.assertEqual(draft.read_bytes(), before)

    async def test_image_keeps_image_review_branch_and_failed_task_does_not_register(self):
        from tests.test_comfy_tasks import TaskTests
        TaskTests.seed(self, status='completed')
        with patch.object(registration, 'register', side_effect=AssertionError('images not registered')):
            report = await self.store.prepare_report(['task'])
        self.assertEqual(report['tasks'][0]['next_action'], 'image-review-workflow')
        self.store.rows['task']['state'].update(status='collection_failed', collected=0, error='missing')
        with patch.object(registration, 'register', side_effect=AssertionError('partial not registered')):
            report = await self.store.prepare_report(['task'])
        self.assertFalse(report['user_message_ready'])

    async def test_native_retry_reuses_checked_remote_mapping_but_observes_local_changes(self):
        candidate, _ = self.setup_video()
        with patch.object(t.client, 'download', side_effect=self.download), \
                patch.object(segments, 'remote_file', wraps=segments.remote_file) as remote:
            await self.store.finish_collection('task', self.terminal)
            self.assertEqual(await segments.finish(self.store, 'task', self.terminal), [])
            self.assertEqual(remote.call_count, 1)
            # A new terminal evidence object must establish the mapping again.
            self.assertEqual(await segments.finish(self.store, 'task', deepcopy(self.terminal)), [])
            self.assertEqual(remote.call_count, 2)
            candidate.write_bytes(b'changed bytes')
            problems = await segments.finish(self.store, 'task', self.terminal)
            self.assertTrue(problems)
            self.assertEqual(candidate.read_bytes(), b'changed bytes')

    async def test_postcompletion_input_serialized_once_and_state_save_skips_unchanged_event_file(self):
        self.setup_video()
        row = self.store.rows['task']
        self.store.record('task', 'existing', 'event')
        row['state']['status'] = 'collecting'
        writes = []
        write = Path.write_text
        def observed(path, *args, **kwargs):
            writes.append(path.name)
            return write(path, *args, **kwargs)
        with patch.object(self.store, 'portable_input', wraps=self.store.portable_input) as portable, \
                patch.object(Path, 'write_text', observed):
            self.store.save('task', progress=1)
            self.store.save('task', progress=2)
            self.store.record('task', 'new', 'event', _changes={'progress': 3})
            self.store.save('task', progress=4)
        self.assertEqual(portable.call_count, 1)
        self.assertEqual(writes.count('后台过程记录.json'), 1)
        events = json.loads((self.record / '后台过程记录.json').read_text('utf-8'))
        self.assertNotIn(b'\r\n', (self.record / '后台过程记录.json').read_bytes())
        self.assertEqual([item['stage'] for item in events], ['existing', 'new'])
        self.assertEqual(json.loads((self.record / '后台任务状态.json').read_text('utf-8'))['progress'], 4)
        self.assertTrue(json.loads(self.store.db.execute('SELECT payload FROM tasks WHERE id=?', ('task',)).fetchone()[0])['workflow'])

    async def test_optional_update_reuses_report_and_text_digest_once_per_read(self):
        self.setup_video()
        batch = await old.CloseoutTests.collect_and_notice(self)
        progress = self.project / '项目进度.md'
        progress.write_text('| EP001 | 原状态 |\n', 'utf-8')
        updates = [{'path': '项目进度.md', 'old': '| EP001 | 原状态 |', 'new': '| EP001 | 已取回待审 |'}]
        read = Path.read_text
        reports = []
        def observed(path, *args, **kwargs):
            if path.name == registration.REPORT: reports.append(path)
            return read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', observed), patch.object(registration, 'digest', wraps=registration.digest) as digest:
            result = await registration.closeout(self.store, self.projects, batch, self.data.thread_id, updates)
        self.assertTrue(result['user_message_ready'])
        self.assertEqual(len(reports), 0)  # Initial register creates its report and passes that object to updates.
        self.assertEqual(sum(call.args[0] == '| EP001 | 原状态 |\n' for call in digest.call_args_list), 1)

    async def test_report_during_send_wakes_waiter_and_preserves_received_state(self):
        self.setup_video()
        with patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', self.terminal)
        async def adapter(data, operation, prompt=''):
            if operation == 'read': return {'content': [{'type': 'text', 'text': '{"thread":{"status":{"type":"idle"}}}'}]}
            batch = self.store.db.execute('SELECT id FROM notification_batches').fetchone()[0]
            self.assertTrue(self.store.read_report(batch, data.thread_id)['user_message_ready'])
            raise OSError('send response lost after receiver read')
        with patch.object(self.store, 'desktop_call', adapter), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        self.assertEqual(self.store.rows['task']['state']['notification'], 'acknowledged')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0], 1)

    async def test_real_agent_cli_reads_one_report_without_ack_or_registration_requests(self):
        from tests.test_queue_recovery import serving
        self.setup_video()
        batch = await self.collect_and_notice()
        app = FastAPI()
        app.state.comfy_tasks = self.store
        # Only report is exposed: separate ack/register calls would fail this integration test.
        app.add_api_route('/api/internal/comfy/notifications/{batch_id}/report', main.agent_result_report, methods=['POST'])
        cli = self.root / '.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
        cli.parent.mkdir(parents=True)
        shutil.copyfile(t.SKILL / 'scripts/browser_tasks.py', cli)
        async with serving(app) as url:
            config = self.root / '工作区浏览服务/runtime/task-service.json'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(json.dumps({'url': url, 'token': self.store.token}), 'utf-8')
            with patch.object(registration, 'register', side_effect=AssertionError('no registration')), \
                    patch.object(t.client, 'submit', side_effect=AssertionError('no submission')), \
                    patch.object(t.client, 'status', side_effect=AssertionError('no remote')):
                process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8', str(cli), 'report',
                    '--notification-id', batch, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, 'CODEX_THREAD_ID': self.data.thread_id})
                stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        self.assertEqual(process.returncode, 0, stderr.decode('utf-8'))
        self.assertTrue(json.loads(stdout)['user_message_ready'])
        self.assertEqual(self.store.rows['task']['state']['notification'], 'acknowledged')

    async def test_restart_restores_pending_notice_and_does_not_resend_unknown_delivery(self):
        self.setup_video()
        with patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', self.terminal)
        with patch.object(self.store, 'notify', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.projects = self.projects
        idle = {'content': [{'type': 'text', 'text': '{"thread":{"status":{"type":"idle"}}}'}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[idle, OSError('unknown send')])) as adapter, \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            await self.store.start()
            await self.store.notifiers['task']
        self.assertEqual(adapter.call_count, 2)
        batch = self.store.db.execute('SELECT id FROM notification_batches').fetchone()[0]
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=AssertionError('no resend'))):
            await self.store.start()
            report = self.store.read_report(batch, self.data.thread_id)
            await asyncio.wait_for(self.store.notifiers['ack:' + batch], 1)
        self.assertTrue(report['user_message_ready'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0], 1)

    async def test_restart_between_last_attempt_and_stop_marker_does_not_grant_fifth_attempt(self):
        self.setup_video()
        self.store.save('task', status='completed', collected=1, closeout_attempts=4,
            closeout={'status': 'browser_pending', 'error': 'last attempt failed'})
        with patch.object(registration, 'closeout_tasks', side_effect=AssertionError('no fifth attempt')):
            result = await self.store.prepare_report(['task'])
        self.assertFalse(result['user_message_ready'])
        self.assertEqual(self.store.rows['task']['state']['closeout_retry_stop'], 'exhausted')

    async def test_generic_selection_cached_per_terminal_and_rebuilt_for_new_terminal(self):
        from tests.test_comfy_tasks import TaskTests
        TaskTests.seed(self, status='collecting')
        terminal = {'files': [{'node_id': '1', 'output_key': 'images', 'index': 0,
            'file': {'filename': 'result.png', 'subfolder': '', 'type': 'output'}}]}
        with patch.object(t.client, 'download', side_effect=self.download) as download:
            self.assertEqual(await self.store.collect('task', terminal), [])
            class Selected(dict):
                def get(self, *args, **kwargs):
                    raise AssertionError('fixed selector was rechecked')
            self.store.rows['task']['_output_index'] = Selected(self.store.rows['task']['_output_index'])
            self.assertEqual(await self.store.collect('task', terminal), [])
            self.assertEqual(await self.store.collect('task', deepcopy(terminal)), [])
        download.assert_called_once()

    async def test_event_tail_recovers_from_interrupted_write_on_restart(self):
        self.setup_video()
        self.store.record('task', 'existing', 'event', _changes={'status': 'collecting'})
        history = self.record / '后台过程记录.json'
        history.write_bytes(b'[{"interrupted":')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.save('task', progress=9)
        events = json.loads(history.read_text('utf-8'))
        self.assertEqual([event['stage'] for event in events], ['existing'])

    async def test_source_change_during_registration_is_not_retried_as_temporary_failure(self):
        _, draft = self.setup_video()
        read = Path.read_text
        draft_reads = 0
        def concurrent(path, *args, **kwargs):
            nonlocal draft_reads
            if path == draft:
                draft_reads += 1
                if draft_reads == 2:
                    path.write_text(read(path, 'utf-8') + '\n用户编辑。', 'utf-8')
            return read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', concurrent):
            batch = await self.collect_and_notice()
        report = self.store.read_report(batch, self.data.thread_id)
        self.assertEqual(report['results'][0]['status'], 'registration_failed')
        self.assertEqual(self.store.rows['task']['state']['closeout_attempts'], 1)
        self.assertIn('用户编辑。', draft.read_text('utf-8'))
        self.assertNotIn('- 决定：待审核', draft.read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
