"""Group boundaries and delivery with isolated SQLite and no remote generation."""
import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from tests import test_comfy_tasks as base
from tests import test_notification_handoffs as handoff
from backend.services import comfy_tasks as t


class GroupRegistrationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.TaskTests.asyncSetUp
    asyncTearDown = base.TaskTests.asyncTearDown
    async def test_group_atomic_membership_and_duplicate_restart(self):
        second = self.data.model_copy(deep=True)
        second.record_dir = str(self.record.parent / 'second')
        result = await self.store.enqueue_group([self.data, second], '整轮两项')
        ids = [item['local_task_id'] for item in result['tasks']]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.store.ordered(), ids)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        repeated = await self.store.enqueue_group([self.data, second], '整轮两项')
        self.assertEqual(result['group_id'], repeated['group_id'])
        self.assertEqual(len(self.store.rows), 2)
        with self.assertRaisesRegex(ValueError, '成员'):
            await self.store.enqueue_group([self.data], '不能拆开')

    async def test_invalid_later_member_leaves_no_partial_group(self):
        bad = self.data.model_copy(deep=True)
        bad.record_dir = str(self.record.parent / 'bad')
        bad.url = 'http://unconfigured.invalid'
        with self.assertRaises(ValueError):
            await self.store.enqueue_group([self.data, bad], '不完整提交')
        self.assertFalse(self.store.groups)
        self.assertFalse(self.store.rows)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)

    async def test_storage_failure_rolls_back_group_and_all_members(self):
        second = self.data.model_copy(deep=True)
        second.record_dir = str(self.record.parent / 'second')
        persist, count = self.store.persist, 0
        def fail(key):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('disk failure')
            persist(key)
        with patch.object(self.store, 'persist', side_effect=fail), self.assertRaises(OSError):
            await self.store.enqueue_group([self.data, second], '整组回滚')
        self.assertFalse(self.store.rows)
        self.assertFalse(self.store.groups)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM task_groups').fetchone()[0], 0)

    async def test_single_member_and_foreign_thread(self):
        second = self.data.model_copy(deep=True)
        second.record_dir = str(self.record.parent / 'other')
        second.thread_id = 'other'
        with self.assertRaisesRegex(ValueError, '来源会话'):
            await self.store.enqueue_group([self.data, second], '跨来源')
        result = await self.store.enqueue_group([self.data], '单项组')
        self.assertEqual(result['group']['expected_tasks'], 1)

    async def test_group_status_http_and_single_submit_create_group(self):
        import httpx
        from fastapi import FastAPI
        from backend import main
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/submit', main.comfy_submit, methods=['POST'])
        app.add_api_route('/groups/{group_id}', main.agent_group_status, methods=['GET'])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1234)), base_url='http://local') as client:
            headers = {'x-nora-task-token': self.store.token}
            submitted = await client.post('/submit', json=self.data.model_dump(), headers=headers)
            self.assertEqual(submitted.status_code, 200, submitted.text)
            group_id = submitted.json()['group_id']
            response = await client.get('/groups/' + group_id, headers=headers)
            self.assertEqual(response.json()['expected_tasks'], 1)
            denied = await client.get('/groups/' + group_id)
            self.assertEqual(denied.status_code, 403)
            repeated = await client.post('/submit', json=self.data.model_dump(), headers=headers)
            self.assertEqual(repeated.json()['group_id'], group_id)


class GroupNotificationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = handoff.NotificationHandoffTests.asyncSetUp
    asyncTearDown = handoff.NotificationHandoffTests.asyncTearDown
    task = handoff.NotificationHandoffTests.task
    notice = handoff.NotificationHandoffTests.notice
    reports = handoff.NotificationHandoffTests.reports
    def group(self, name, ids):
        self.store.groups[name] = dict(id=name, title=name, task_ids=ids, project=str(self.project), thread_id='isolated-thread')
        self.store.save_group(name)
        for key in ids:
            self.store.save(key, group_id=name)

    async def test_success_waits_for_all_closeouts_then_one_report(self):
        self.task('one'); self.task('two', status='running')
        self.group('group', ['one', 'two'])
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        sender.assert_not_awaited()
        self.store.save('two', status='completed')
        # Saved output alone is not complete: no finished closeout yet.
        await self.notice('two', sender)
        sender.assert_not_awaited()
        self.store.save('two', closeout=dict(status='completed', display_outputs=[]))
        with patch.object(self.store, 'desktop_call', sender), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            await self.store._notify_pending('two')
        self.assertEqual(sender.await_count, 1)
        batch, report = self.reports()[-1]
        self.assertEqual(report['groups'][0]['completed_tasks'], 2)
        self.assertEqual(len(report['tasks']), 2)
        self.assertTrue(report['user_message_ready'])
        prompt = sender.call_args.args[2]
        user_text, agent_text = prompt.split('Agent接续信息', 1)
        self.assertIn('\n任务组：group\n', user_text)
        self.assertNotIn('已完成', user_text)
        self.assertNotIn(batch, user_text)
        self.assertIn('--notification-id ' + batch, agent_text)
        self.assertIn('#后台通知接续', agent_text)
        self.assertLess(len(prompt), 800)
        self.store.read_report(batch, 'isolated-thread')
        self.store.wake_group('two')
        self.assertFalse(self.store.notification_pending('isolated-thread'))

    async def attention(self, key, sender, message='当次资料已冻结，不可覆盖：/isolated/source.md'):
        self.store.save(key, status='needs_attention', failure_stage='prepare', error=message)
        with patch.object(self.store, 'desktop_call', sender), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice(key, 'dispatch_issue', 'attention', message)
            await self.store.notifiers[key]

    async def test_same_issue_merges_into_unread_report_and_survives_restart(self):
        for key in ('one', 'two', 'three'):
            self.task(key, status='local_queued')
        self.group('group', ['one', 'two', 'three'])
        sender = AsyncMock(return_value={})
        await self.attention('one', sender)
        batch, report = self.reports()[0]
        self.assertEqual(report['handoff']['next_action'], 'repair-group-silently')
        await self.attention('two', sender, '当次资料已冻结，不可覆盖：/isolated/other.md')
        self.assertEqual(sender.await_count, 1)
        self.assertEqual(self.reports()[0][1]['groups'][0]['issues'][0]['task_ids'], ['one', 'two'])
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.prepare_report = AsyncMock(side_effect=lambda ids: self.store.result_report(ids))
        await self.attention('three', sender, '当次资料已冻结，不可覆盖：/isolated/third.md')
        self.assertEqual(sender.await_count, 1)
        report = self.store.read_report(batch, 'isolated-thread')
        self.assertEqual(report['new_task_ids'], ['one', 'two', 'three'])
        self.assertEqual(report['groups'][0]['issues'][0]['task_ids'], ['one', 'two', 'three'])
        self.assertFalse(self.store.notification_pending('isolated-thread'))

    async def test_new_peer_after_receipt_is_handed_back_for_silent_repair(self):
        self.task('one', status='local_queued'); self.task('two', status='local_queued')
        self.group('group', ['one', 'two'])
        sender = AsyncMock(return_value={})
        await self.attention('one', sender)
        self.store.read_report(self.reports()[0][0], 'isolated-thread')
        await self.attention('two', sender)
        self.assertEqual(sender.await_count, 2)
        report = self.reports()[-1][1]
        self.assertEqual(len(report['groups'][0]['issues']), 1)
        self.assertEqual(report['handoff']['next_action'], 'repair-group-silently')
        self.assertEqual(report['handoff']['user_notification'], 'decision-or-blocker-only')

    async def test_different_issue_or_group_is_not_hidden_by_unread_report(self):
        for key in ('one', 'two', 'other'):
            self.task(key, status='local_queued')
        self.group('group', ['one', 'two']); self.group('other-group', ['other'])
        sender = AsyncMock(return_value={})
        await self.attention('one', sender)
        await self.attention('two', sender, '素材不存在：/isolated/missing.png')
        await self.attention('other', sender)
        self.assertEqual(sender.await_count, 3)
        self.assertEqual(len(self.reports()[1][1]['groups'][0]['issues']), 2)

    async def test_unknown_send_coalesces_peers_but_completed_group_still_notifies(self):
        self.task('one', status='local_queued'); self.task('two', status='local_queued')
        self.group('group', ['one', 'two'])
        sender = AsyncMock(side_effect=OSError('unknown delivery'))
        await self.attention('one', sender)
        await self.attention('two', sender)
        self.assertEqual(sender.await_count, 1)
        for key in ('one', 'two'):
            self.store.save(key, status='completed', error=None, failure_stage=None,
                            closeout=dict(status='completed', display_outputs=[]))
        sender = AsyncMock(return_value={})
        with patch.object(self.store, 'desktop_call', sender), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.wake_group('one')
            await self.store.notifiers['one']
        self.assertEqual(sender.await_count, 1)
        self.assertEqual(self.reports()[-1][1]['handoff']['next_action'], 'resume-group-delivery')
        self.assertEqual(self.reports()[-1][1]['groups'][0]['issues'], [])

    async def test_exception_early_then_final_partial_keeps_success(self):
        self.task('one', status='failed'); self.task('two', status='running')
        self.group('group', ['one', 'two'])
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        self.assertEqual(sender.await_count, 1)
        batch, report = self.reports()[-1]
        self.assertFalse(report['groups'][0]['terminal'])
        self.store.read_report(batch, 'isolated-thread')
        self.store.save('two', status='completed', closeout=dict(status='completed', display_outputs=[]))
        await self.notice('two', sender)
        self.assertEqual(sender.await_count, 2)
        report = self.reports()[-1][1]
        self.assertEqual(report['groups'][0]['status'], 'terminal_partial')
        self.assertEqual(report['groups'][0]['missing_task_ids'], ['one'])
        self.assertEqual(len(report['tasks']), 2)

    async def test_same_thread_groups_never_coalesce(self):
        for key in ('one', 'two'):
            self.task(key); self.group(key, [key])
        with patch.object(self.store, 'notify', AsyncMock()):
            for key in ('one', 'two'):
                self.store.queue_notice(key, 'terminal', 'terminal', 'done')
        sender = AsyncMock(return_value={})
        with patch.object(self.store, 'desktop_call', sender), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            await self.store._notify_pending('one')
        self.assertEqual(sender.await_count, 2)
        self.assertEqual([len(r['tasks']) for _, r in self.reports()], [1, 1])

    async def test_cancel_releases_group_and_unknown_delivery_is_not_resent(self):
        self.task('one'); self.task('two', status='local_queued')
        self.group('group', ['one', 'two'])
        await self.notice('one')
        sender = AsyncMock(side_effect=OSError('unknown delivery'))
        with patch.object(self.store, 'desktop_call', sender), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.task_action('two', 'cancel')
            await self.store.notifiers['two']
            await self.store._notify_pending('one')
        self.assertEqual(sender.await_count, 1)
        self.assertEqual(self.reports()[-1][1]['groups'][0]['status'], 'terminal_partial')

    async def test_repaired_closeout_notifies_final_group_after_error_read(self):
        self.task('one')
        self.group('group', ['one'])
        self.store.save('one', closeout=dict(status='registration_failed', error='record conflict'), closeout_retry_stop='requires_attention')
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        self.store.read_report(self.reports()[-1][0], 'isolated-thread')
        self.store.save('one', closeout=dict(status='completed', display_outputs=[]))
        with patch.object(self.store, 'desktop_call', sender), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.wake_group('one')
            await self.store.notifiers['one']
        self.assertEqual(sender.await_count, 2)
        self.assertTrue(self.reports()[-1][1]['user_message_ready'])

    async def test_mixed_media_delivery_preserves_all_members_and_upscale_identity(self):
        self.task('image'); self.task('upscale', kind='image-upscale'); self.task('video', kind='video-first-pass')
        self.group('mixed', ['image', 'upscale', 'video'])
        report = self.store.result_report(['video'])
        self.assertEqual([item['task_type'] for item in report['delivery']['tasks']],
                         ['image', 'image-upscale', 'video-first-pass'])
        self.assertEqual(report['delivery']['completed'], 3)
        self.assertEqual(report['groups'][0]['completed_tasks'], 3)

    async def test_group_early_report_does_not_mark_running_peer_as_received(self):
        self.task('one', status='failed'); self.task('two', status='running')
        self.group('group', ['one', 'two'])
        await self.notice('one')
        report = self.store.read_report(self.reports()[-1][0], 'isolated-thread')
        self.assertEqual(report['new_task_ids'], ['one'])
        self.assertNotIn('reported_outcome', self.store.rows['two']['state'])

    async def test_new_group_upscale_silent_but_failed_group_still_finishes(self):
        self.task('one', kind='image-upscale'); self.task('two', kind='image-upscale', status='running')
        self.group('group', ['one', 'two'])
        sender = AsyncMock(return_value={})
        await self.notice('one', sender)
        sender.assert_not_awaited()
        self.store.save('two', status='completed', closeout=dict(status='completed', display_outputs=[]))
        await self.notice('two', sender)
        sender.assert_not_awaited()
        self.assertFalse(self.store.notification_pending('isolated-thread'))

    async def test_terminal_sent_receipt_survives_restart_without_resending(self):
        self.task('one'); self.group('group', ['one'])
        await self.notice('one')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        sender = AsyncMock(return_value={})
        self.store.wake_group('one')
        with patch.object(self.store, 'desktop_call', sender):
            await self.store._notify_pending('one')
        sender.assert_not_awaited()
        self.assertFalse(self.store.notification_pending('isolated-thread'))
