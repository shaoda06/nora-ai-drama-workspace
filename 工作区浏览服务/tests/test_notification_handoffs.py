"""Notification handoffs use temporary state and mocked senders; no service or network."""
import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
import errno
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t
from backend.services.task_notifications import NotificationNotStarted


class NotificationHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'projects/隔离通知'
        self.project.mkdir(parents=True)
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.queue_notifications = True
        self.store.prepare_report = AsyncMock(side_effect=lambda ids: self.store.result_report(ids))

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    def task(self, key, *, status='completed', batch=None, size=1, kind='image'):
        record = self.project / '执行附件' / key
        record.mkdir(parents=True)
        data = t.TaskInput(project=str(self.project), title=key, task_type=kind,
            url='http://comfy.invalid', workflow={}, record_dir=str(record),
            attempt_name='attempt.json', request_name='request.json', response_name='response.json',
            outputs=[], thread_id='isolated-thread', image_batch_id=batch, image_batch_size=size,
            desktop=dict(node='unused', server='unused', pipe='unused', caller_thread='isolated-thread', cli='/isolated/codex'))
        self.store.rows[key] = {'input': data, 'state': dict(id=key, project=self.project.name,
            status=status, notification='waiting', created_at=t.client.now(), collected=1, expected=1)}
        if status == 'completed':
            self.store.rows[key]['state']['closeout'] = dict(status='completed', display_outputs=[], video_outputs=[])
        self.store.save(key)
        return data

    async def notice(self, key, sender=None):
        with patch.object(self.store, 'desktop_call', sender or AsyncMock(return_value={})), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice(key, 'terminal', 'terminal', '隔离结果')
            await self.store.notifiers[key]

    def reports(self):
        return [(row[0], json.loads(row[1])) for row in self.store.db.execute(
            'SELECT batch_id, report FROM notification_reports ORDER BY rowid')]

    async def test_cancelled_peer_releases_waiting_success_and_is_not_all_success(self):
        self.task('one', batch='batch', size=2)
        self.task('two', batch='batch', size=2, status='local_queued')
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        sender.assert_not_awaited()
        self.store.save('two', status='cancelled')
        await self.notice('two', sender)
        self.assertEqual(sender.await_count, 1)
        report = self.reports()[-1][1]
        self.assertEqual({task['id']: task['status'] for task in report['tasks']},
                         {'one': 'completed', 'two': 'cancelled'})
        self.assertFalse(report['user_message_ready'])
        self.assertEqual(report['delivery']['completed'], 1)

    async def test_consumed_cancellation_remains_in_final_batch_report(self):
        self.task('one', batch='batch', size=2, status='running')
        self.task('two', batch='batch', size=2, status='cancelled')
        await self.notice('two')
        batch, _ = self.reports()[-1]
        self.store.read_report(batch, 'isolated-thread')
        self.store.save('one', status='completed', closeout=dict(status='completed', display_outputs=[]))
        await self.notice('one')
        report = self.reports()[-1][1]
        self.assertEqual({task['id'] for task in report['tasks']}, {'one', 'two'})
        self.assertFalse(report['user_message_ready'])

    async def test_missing_registered_batch_member_still_waits(self):
        self.task('one', batch='batch', size=2)
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        sender.assert_not_awaited()

    async def test_old_cancellation_report_consumes_later_success_without_duplicate_notice(self):
        self.task('one', batch='batch', size=2, status='running')
        self.task('two', batch='batch', size=2, status='cancelled')
        foreign = self.task('foreign', batch='batch', size=2)
        foreign.thread_id = 'another-source'
        self.store.save('foreign')
        await self.notice('two')
        batch, _ = self.reports()[-1]
        self.store.read_report(batch, 'isolated-thread')
        self.store.save('one', status='completed', closeout=dict(status='completed', display_outputs=[]))
        latest = self.store.read_report(batch, 'isolated-thread')
        self.assertEqual({task['id'] for task in latest['tasks']}, {'one', 'two'})
        self.assertTrue(latest['should_notify_user'])
        self.assertEqual(latest['new_task_ids'], ['one'])
        self.assertEqual(self.store.rows['one']['state']['reported_outcome'], self.store.notice_outcome('one'))
        self.assertNotIn('reported_outcome', self.store.rows['foreign']['state'])
        changes = self.store.db.total_changes
        repeated = self.store.read_report(batch, 'isolated-thread')
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertEqual(repeated['tasks'], latest['tasks'])
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        sender.assert_not_awaited()
        self.assertFalse(self.store.read_report(batch, 'isolated-thread')['should_notify_user'])

    async def test_read_receipt_keeps_handoff_after_restart_without_resending(self):
        self.task('one', kind='video-first-pass')
        await self.notice('one')
        batch, _ = self.reports()[0]
        first = self.store.read_report(batch, 'isolated-thread')
        self.assertTrue(first['should_notify_user'])
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        later = self.store.read_report(batch, 'isolated-thread')
        self.assertFalse(later['should_notify_user'])
        self.assertEqual(later['new_task_ids'], [])
        self.assertEqual(later['handoff'], {'receipt_only': True, 'scope': 'notification',
            'next_action': 'resume-round-delivery', 'record_dirs': ['执行附件/one']})

    async def test_distinct_video_notifications_keep_receipts_and_round_instruction(self):
        self.task('one', kind='video-first-pass')
        self.task('two', kind='video-first-pass')
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        first_batch, _ = self.reports()[0]
        self.store.read_report(first_batch, 'isolated-thread')
        await self.notice('two', sender)
        second_batch, report = self.reports()[-1]
        self.assertEqual([item['id'] for item in report['tasks']], ['two'])
        self.assertEqual(self.store.read_report(second_batch, 'isolated-thread')['new_task_ids'], ['two'])
        prompt = sender.call_args.args[2]
        self.assertIn('汇总此前已读与本次新增结果', prompt)
        self.assertIn('不代表整轮齐备', prompt)
        self.assertIn('needs_attention', prompt)

    async def test_business_attention_and_handoff_survive_compact_cli_report(self):
        data = self.task('one', kind='video-first-pass')
        business = {'status': 'needs_attention', 'needs_attention': True,
                    'paths': ['项目进度.md'], 'next_action': 'sync-business-records'}
        self.store.rows['one']['state']['closeout']['business_sync'] = business
        await self.notice('one')
        batch, _ = self.reports()[0]
        report = self.store.read_report(batch, data.thread_id)
        self.assertEqual(report['business_sync'], [{'task_id': 'one', **business}])
        spec = importlib.util.spec_from_file_location('isolated_browser_tasks', t.SKILL / 'scripts/browser_tasks.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        output = io.StringIO()
        with patch.object(cli, 'service_call', return_value=report), \
                patch.dict(cli.os.environ, {'CODEX_THREAD_ID': 'isolated-thread'}), \
                patch('sys.argv', ['browser_tasks.py', 'report', '--notification-id', batch]), redirect_stdout(output):
            cli.main()
        compact = json.loads(output.getvalue())
        self.assertEqual(compact['business_sync'], report['business_sync'])
        self.assertEqual(compact['handoff'], report['handoff'])
        self.assertNotIn('tasks', compact)

    async def test_cli_missing_before_launch_has_retryable_class(self):
        data = self.task('one')
        data.desktop.cli = None
        with patch.dict(t.os.environ, {}, clear=True), patch.object(t.shutil, 'which', return_value=None), \
                patch.object(t.subprocess, 'run') as run:
            with self.assertRaises(NotificationNotStarted):
                await self.store.desktop_call(data, 'send', 'isolated')
            run.assert_not_called()

    async def test_cli_launch_failures_retry_but_keep_attempt_receipt(self):
        errors = [FileNotFoundError('missing executable'), PermissionError('not executable'),
                  OSError(errno.ENOEXEC, 'Exec format error')]
        if hasattr(errno, 'EBADARCH'):
            errors.append(OSError(errno.EBADARCH, 'Bad CPU type in executable'))
        for index, error in enumerate(errors):
            with self.subTest(error=type(error).__name__):
                key = f'{index}-{type(error).__name__}'
                self.task(key)
                with patch.object(t.subprocess, 'run', side_effect=[error, subprocess.CompletedProcess([], 0, 'Queued message isolated-id', '')]) as run, \
                        patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
                    self.store.queue_notice(key, 'terminal', 'terminal', '隔离结果')
                    await self.store.notifiers[key]
                self.assertEqual(run.call_count, 2)
                self.assertEqual(self.store.rows[key]['state']['notification'], 'sent')
        states = [row[0] for row in self.store.db.execute('SELECT state FROM notification_batches ORDER BY rowid')]
        self.assertEqual(states, ['not_started', 'sent'] * len(errors))

    async def test_started_sender_failure_remains_unknown_and_is_not_retried(self):
        for index, result in enumerate((subprocess.CompletedProcess([], 1, '', 'unknown'),
                                        subprocess.TimeoutExpired('codex', 40),
                                        OSError(errno.EIO, 'Unknown I/O failure'), OSError('Unknown transport failure'))):
            with self.subTest(result=result):
                key = str(index)
                self.task(key)
                kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with patch.object(t.subprocess, 'run', **kwargs) as run, \
                        patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
                    self.store.queue_notice(key, 'terminal', 'terminal', '隔离结果')
                    await self.store.notifiers[key]
                    await self.store.notify(key)
                run.assert_called_once()
                self.assertEqual(self.store.rows[key]['state']['notification'], 'delivery_unknown')


if __name__ == '__main__':
    unittest.main()
