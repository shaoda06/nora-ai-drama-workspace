"""Reading the latest outcome through an older notice must not deliver it twice."""
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t
from tests import test_result_closeout as base


class NotificationConsumptionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.CloseoutTests.asyncSetUp
    asyncTearDown = base.CloseoutTests.asyncTearDown
    video = base.CloseoutTests.video
    setup_video = base.CloseoutTests.setup_video
    download = base.CloseoutTests.download

    async def notice(self, event='terminal'):
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', event, 'terminal', '任务结果')
            await self.store.notifiers['task']
        return self.store.db.execute('SELECT id FROM notification_batches ORDER BY rowid DESC').fetchone()[0]

    async def failed_notice(self):
        self.setup_video()
        self.store.save('task', status='collection_failed', error='output根目录错误',
                        failure_stage='collection', collection_attempt=1)
        batch = await self.notice()
        report = self.store.read_report(batch, self.data.thread_id)
        self.assertTrue(report['should_notify_user'])
        self.assertFalse(report['user_message_ready'])
        return batch

    async def recover(self):
        self.store.save('task', collection_attempt=2)
        with patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', self.terminal)
        await self.store.prepare_report(['task'])

    async def test_old_failure_report_consumes_latest_success_and_suppresses_pending_send(self):
        old_batch = await self.failed_notice()
        await self.recover()
        report = self.store.read_report(old_batch, self.data.thread_id)
        self.assertTrue(report['reused'])
        self.assertTrue(report['user_message_ready'])
        self.assertTrue(report['should_notify_user'])
        self.assertEqual(report['new_task_ids'], ['task'])
        with patch.object(self.store, 'desktop_call', AsyncMock()) as desktop, \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '恢复成功')
            await self.store.notifiers['task']
            desktop.assert_not_awaited()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0], 1)

    async def test_already_queued_success_notice_is_silent_when_it_arrives_late(self):
        old_batch = await self.failed_notice()
        await self.recover()
        new_batch = await self.notice()
        self.assertNotEqual(old_batch, new_batch)
        first = self.store.read_report(old_batch, self.data.thread_id)
        late = self.store.read_report(new_batch, self.data.thread_id)
        self.assertTrue(first['should_notify_user'])
        self.assertTrue(late['user_message_ready'])
        self.assertFalse(late['should_notify_user'])
        self.assertEqual(late['new_task_ids'], [])
        changes = self.store.db.total_changes
        self.assertFalse(self.store.read_report(new_batch, self.data.thread_id)['should_notify_user'])
        self.assertEqual(self.store.db.total_changes, changes)

    async def test_receipt_survives_restart_without_resending_consumed_result(self):
        old_batch = await self.failed_notice()
        await self.recover()
        self.store.read_report(old_batch, self.data.thread_id)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.queue_notifications = False
        self.assertFalse(self.store.read_report(old_batch, self.data.thread_id)['should_notify_user'])
        with patch.object(self.store, 'desktop_call', AsyncMock()) as desktop, \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'after-restart', 'terminal', '同一成功结果')
            await self.store.notifiers['task']
            desktop.assert_not_awaited()

    async def test_new_failure_and_real_recovery_are_not_suppressed_by_task_id(self):
        old_batch = await self.failed_notice()
        await self.recover()
        new_batch = await self.notice()
        recovered = self.store.read_report(new_batch, self.data.thread_id)
        self.assertTrue(recovered['should_notify_user'])
        self.store.save('task', status='collection_failed', error='新一轮取回失败', collection_attempt=3)
        next_batch = await self.notice()
        failure = self.store.read_report(next_batch, self.data.thread_id)
        self.assertTrue(failure['should_notify_user'])
        self.assertNotEqual(old_batch, next_batch)

    async def test_latest_report_read_during_connection_probe_cancels_unsent_notice(self):
        old_batch = await self.failed_notice()
        await self.recover()
        operations = []

        async def desktop(data, operation, prompt=''):
            operations.append(operation)
            if operation == 'read':
                self.assertTrue(self.store.read_report(old_batch, self.data.thread_id)['should_notify_user'])
                return {}
            raise AssertionError('已消费结果不应再发送')

        with patch.object(self.store, 'desktop_call', desktop), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '恢复成功')
            await self.store.notifiers['task']
        self.assertEqual(operations, ['read'])


if __name__ == '__main__':
    unittest.main()
