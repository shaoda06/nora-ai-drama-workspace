"""Batch image notifications and quiet upscales, with isolated tasks and fake delivery."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from backend.services import comfy_tasks as t
from tests import test_comfy_tasks as base


class ImageNotificationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.TaskTests.asyncSetUp
    asyncTearDown = base.TaskTests.asyncTearDown

    def task(self, key, *, batch='batch-one', size=2, task_type='image', status='running', project=None):
        data = self.data.model_copy(deep=True)
        data.image_batch_id, data.image_batch_size, data.task_type, data.title = batch, size, task_type, key
        if project:
            data.project = str(self.root / 'projects' / project)
            Path(data.project).mkdir(exist_ok=True)
            data.outputs[0].path = str(Path(data.project) / '候选/result.png')
        data.record_dir = str(Path(data.project) / '执行附件' / key)
        Path(data.record_dir).mkdir(parents=True, exist_ok=True)
        self.store.rows[key] = {'input': data, 'state': dict(id=key, project=Path(data.project).name,
            status=status, notification='waiting', created_at=t.client.now(), collected=0, expected=1)}
        self.store.save(key)

    def complete(self, key):
        self.store.save(key, status='completed', collected=1,
                        closeout={'status': 'completed', 'display_outputs': []})

    async def notify(self, key, event='terminal'):
        with patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice(key, event, 'terminal', '结果')
            await self.store.notifiers[key]

    def reports(self):
        return [json.loads(row[0]) for row in self.store.db.execute('SELECT report FROM notification_reports')]

    async def test_staggered_images_wait_then_send_one_report_with_both(self):
        self.task('first'); self.task('second'); self.complete('first')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('first')
            send.assert_not_awaited()
            self.assertEqual(self.store.rows['first']['state']['notice_wait_reason'], 'image_batch')
            self.assertTrue(self.store.notifiers['first'].done())
            self.complete('second'); await self.notify('second')
            self.assertEqual(sum(c.args[1] == 'send' for c in send.call_args_list), 1)
        self.assertEqual({x['id'] for x in self.reports()[0]['tasks']}, {'first', 'second'})
        self.assertTrue(self.reports()[0]['user_message_ready'])
        self.assertEqual(len(self.reports()), 1)

    async def test_repair_during_connection_probe_updates_report_before_send(self):
        self.task('first', size=1, status='completed')
        self.store.save('first', closeout={'status': 'browser_pending', 'error': '网页缺项'},
                        closeout_retry_stop='exhausted')
        async def desktop(data, operation, prompt=''):
            if operation == 'read':
                self.complete('first')
            else:
                self.assertTrue(self.reports()[0]['user_message_ready'])
            return {}
        with patch.object(self.store, 'desktop_call', side_effect=desktop):
            await self.notify('first')

    async def test_old_completed_image_reports_without_display_fields_remain_readable(self):
        for kind in ('image', 'image-upscale'):
            with self.subTest(kind=kind):
                self.task(kind, batch=None, size=1, task_type=kind, status='completed')
                self.store.save(kind, closeout={'status': 'completed', 'report': '结果收尾报告.json'})
                self.store.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)',
                                     (kind, self.data.thread_id, json.dumps([kind]), 'historical notice', 'sent'))
                self.store.db.execute('INSERT INTO notification_reports VALUES (?, ?)',
                                     (kind, json.dumps({'tasks': [], 'results': [], 'user_message_ready': False})))
                self.store.db.commit()
                with patch.object(self.store, 'prepare_report', AsyncMock(side_effect=AssertionError('no closeout'))), \
                        patch.object(self.store, 'desktop_call', AsyncMock(side_effect=AssertionError('no send'))):
                    report = self.store.read_report(kind, self.data.thread_id)
                self.assertTrue(report['user_message_ready'])
                self.assertNotIn('delivery', report)
                self.assertEqual(report['tasks'][0]['task_type'], kind)

    async def test_old_ack_does_not_replace_newer_notification_state(self):
        self.task('first', size=1, status='collection_failed')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})):
            await self.notify('first', 'failure')
            old_batch = self.store.rows['first']['state']['notices'][0]['batch_id']
            self.complete('first')
            await self.notify('first', 'recovered')
        state = self.store.rows['first']['state']
        new_batch = state['notices'][-1]['batch_id']
        self.assertNotEqual(old_batch, new_batch)
        old = self.store.read_report(old_batch, self.data.thread_id)
        self.assertTrue(old['user_message_ready'])
        self.assertEqual(state['notification'], 'sent')
        self.assertNotIn('notification_acknowledged_at', state)
        self.assertEqual(state['notices'][-1]['delivery'], 'sent')
        self.store.read_report(new_batch, self.data.thread_id)
        self.assertEqual(state['notification'], 'acknowledged')

    async def test_old_upscale_error_ack_does_not_undo_quiet_success(self):
        self.task('upscale', batch=None, size=1, task_type='image-upscale', status='collection_failed')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('upscale', 'failure')
            state = self.store.rows['upscale']['state']
            batch = state['notices'][0]['batch_id']
            self.complete('upscale')
            await self.notify('upscale', 'recovered')
            self.assertEqual(sum(c.args[1] == 'send' for c in send.call_args_list), 1)
        self.assertEqual(state['notification'], 'not_required')
        report = self.store.read_report(batch, self.data.thread_id)
        self.assertEqual(report['delivery']['tasks'][0]['task_type'], 'image-upscale')
        self.assertEqual(state['notification'], 'not_required')

    async def test_batch_wait_survives_restart(self):
        self.task('first'); self.task('second'); self.complete('first')
        with patch.object(self.store, 'desktop_call', AsyncMock()) as send:
            await self.notify('first'); send.assert_not_awaited()
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(self.store.rows['first']['input'].image_batch_id, 'batch-one')
        self.assertTrue(self.store.image_batch_waiting('first'))
        self.complete('second')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('second')
            self.assertEqual(sum(c.args[1] == 'send' for c in send.call_args_list), 1)

    async def test_partial_enqueue_does_not_shrink_expected_batch(self):
        self.task('first'); self.complete('first')
        with patch.object(self.store, 'desktop_call', AsyncMock()) as send:
            await self.notify('first'); send.assert_not_awaited()

    async def test_ready_batches_each_keep_their_own_report(self):
        self.task('first', size=1); self.complete('first')
        self.task('second', batch='another', size=1); self.complete('second')
        with patch.object(self.store, 'notify', AsyncMock()):
            for key in ['first', 'second']:
                self.store.queue_notice(key, 'terminal', 'terminal', '完成')
                await self.store.notifiers[key]
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            await self.store.notify('first')
        self.assertEqual([[x['id'] for x in a['tasks']] for a in self.reports()], [['first'], ['second']])

    async def test_closeout_failure_notifies_while_successful_sibling_waits(self):
        self.task('first'); self.task('second'); self.complete('first')
        self.store.save('second', status='completed', closeout={'status': 'browser_pending', 'error': '网页核验失败'},
                        closeout_retry_stop='exhausted')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})):
            await self.notify('first'); await self.notify('second')
        self.assertEqual([[x['id'] for x in a['tasks']] for a in self.reports()], [['second']])
        self.assertFalse(self.reports()[0]['user_message_ready'])

    async def test_other_batches_and_projects_neither_block_nor_fill_batch(self):
        self.task('first'); self.complete('first')
        self.task('unrelated', batch='another', size=1); self.complete('unrelated')
        self.task('other-project', project='另一项目'); self.complete('other-project')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('first'); await self.notify('other-project'); send.assert_not_awaited()
            await self.notify('unrelated')
        self.assertEqual([[x['id'] for x in a['tasks']] for a in self.reports()], [['unrelated']])

    async def test_failure_reports_early_and_recovery_delivers_full_batch(self):
        self.task('first'); self.complete('first'); self.task('second')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('first')
            self.store.save('second', status='collection_failed', error='下载失败')
            await self.notify('second')
            self.assertEqual([[x['id'] for x in a['tasks']] for a in self.reports()], [['second']])
            self.complete('second'); await self.notify('second', 'recovered')
            self.assertEqual({x['id'] for x in self.reports()[-1]['tasks']}, {'first', 'second'})
            self.assertEqual(sum(c.args[1] == 'send' for c in send.call_args_list), 2)

    async def test_upscale_finishes_closeout_but_never_sends(self):
        self.task('upscale', task_type='image-upscale', batch=None, size=1, status='completed')
        self.store.projects = object()
        async def closeout(store, projects, ids):
            self.assertEqual(ids, ['upscale'])
            self.complete('upscale')
            (Path(self.store.rows['upscale']['input'].record_dir) / '结果收尾报告.json').write_text('{"status":"completed"}')
        with patch('backend.services.result_registration.closeout_tasks', side_effect=closeout) as finish, \
                patch.object(self.store, 'desktop_call', AsyncMock()) as send:
            await self.notify('upscale'); finish.assert_awaited_once(); send.assert_not_awaited()
        self.assertEqual(self.store.rows['upscale']['state']['notification'], 'not_required')
        self.assertFalse(self.store.notification_pending(self.data.thread_id))
        self.assertFalse(self.reports())
        await self.store.close(); self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'desktop_call', AsyncMock()) as send:
            await self.store.notify('upscale'); send.assert_not_awaited()

    async def test_upscale_closeout_error_is_not_silenced(self):
        self.task('upscale', task_type='image-upscale', batch=None, size=1, status='completed')
        self.store.save('upscale', closeout={'status': 'registration_failed', 'error': '正式保存冲突'},
                        closeout_retry_stop='requires_attention')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('upscale')
            self.assertEqual(sum(c.args[1] == 'send' for c in send.call_args_list), 1)

    async def test_upscale_does_not_hold_image_batch_open(self):
        self.task('first', size=1); self.complete('first')
        self.task('upscale', task_type='image-upscale', batch=None, size=1)
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send:
            await self.notify('first')
            self.assertEqual(sum(c.args[1] == 'send' for c in send.call_args_list), 1)
