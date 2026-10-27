"""Queue controls at await boundaries; temporary state and mocked workers only."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as tasks, execution_checks


class QueueControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'projects/test'
        self.project.mkdir(parents=True)
        self.url, self.backup = 'http://primary.invalid', 'http://backup.invalid'
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [self.url, self.backup]}))
        self.store = tasks.TaskStore(self.root / 'runtime', self.root)
        self.store.queue_notifications = False
        self.enterContext(patch.object(self.store, 'read_session_name', AsyncMock()))
        self.data = tasks.TaskInput(project=str(self.project), title='test', task_type='image',
            url=self.url, workflow={'1': {'class_type': 'SaveImage', 'inputs': {'seed': 1}}},
            record_dir=str(self.project / 'records/new'), attempt_name='attempt.json',
            request_name='request.json', response_name='response.json',
            outputs=[dict(node_id='1', output_key='images', index=0,
                          path=str(self.project / 'result.png'), response_name='download.json')],
            thread_id='test-thread', desktop=dict(node='unused', server='unused', pipe='unused', caller_thread='test-thread'))

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    async def add(self, name):
        data = self.data.model_copy(deep=True)
        data.record_dir = str(self.project / 'records' / name)
        data.outputs[0].path = str(self.project / (name + '.png'))
        return (await self.store.enqueue(data))['local_task_id']

    def node(self, url):
        self.store.remote_queues.states[url] = dict(connection='connected', queue_error=None,
            updated_at=tasks.client.now(), running_count=0, queued_count=0)

    async def reconcile_window(self, change):
        old, key = await self.add('old'), await self.add('new')
        self.store.save(old, status='running', prompt_id='accepted-original')
        self.node(self.url)
        entered, release = asyncio.Event(), asyncio.Event()

        async def reconcile(*args, **kwargs):
            entered.set()
            await release.wait()

        with patch.object(self.store, 'reconcile', reconcile), \
                patch.object(self.store, 'prepare', AsyncMock(return_value={})) as prepare, \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            dispatch = asyncio.create_task(self.store.dispatch_node(self.url))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                await change(key)
            finally:
                release.set()
                await dispatch
            return key, prepare, submit

    async def test_cancel_while_reconciling_never_prepares_or_submits(self):
        async def change(key):
            self.assertEqual(self.store.task_action(key, 'cancel')['status'], 'cancelled')
        key, prepare, submit = await self.reconcile_window(change)
        prepare.assert_not_awaited()
        submit.assert_not_awaited()
        self.assertEqual(self.store.rows[key]['state']['status'], 'cancelled')

    async def test_pause_while_reconciling_never_prepares_or_submits(self):
        async def change(key):
            self.store.task_action(key, 'pause')
        key, prepare, submit = await self.reconcile_window(change)
        prepare.assert_not_awaited()
        submit.assert_not_awaited()
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')

    async def test_transfer_while_reconciling_only_dispatches_on_target(self):
        async def change(key):
            self.store.transfer(key, self.backup)
        key, prepare, submit = await self.reconcile_window(change)
        prepare.assert_not_awaited()
        submit.assert_not_awaited()
        self.node(self.backup)
        with patch.object(self.store, 'prepare', AsyncMock(return_value={})) as prepare, \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_node(self.backup)
            prepare.assert_awaited_once_with(key)
            self.assertEqual(submit.await_args.args[0].url, self.backup)

    async def test_drag_started_during_reconcile_blocks_preparation(self):
        async def change(key):
            self.store.drag(url=self.url)
        _, prepare, submit = await self.reconcile_window(change)
        prepare.assert_not_awaited()
        submit.assert_not_awaited()

    async def test_new_queue_order_during_reconcile_is_respected(self):
        async def change(key):
            other = await self.add('inserted')
            self.store.task_action(other, 'insert')
        _, prepare, submit = await self.reconcile_window(change)
        prepare.assert_not_awaited()
        submit.assert_not_awaited()

    async def test_unchanged_queue_still_dispatches_once(self):
        async def change(key):
            pass
        key, prepare, submit = await self.reconcile_window(change)
        prepare.assert_awaited_once_with(key)
        submit.assert_awaited_once()

    async def test_reprepare_blocks_controls_and_duplicate_prepare_until_finished(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        updated = self.data.model_copy(deep=True)
        updated.workflow['1']['inputs']['seed'] = 2
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        transfer_states = []

        def prepare_report(*args):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError('test did not release preparation')
            return {'ok': True}

        with patch.object(execution_checks, 'prepare_report', prepare_report), \
                patch.object(self.store, 'publish', side_effect=lambda: transfer_states.append(self.store.can_transfer(key))), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            preparing = asyncio.create_task(self.store.prepare_only(updated))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
                for action in ('resume', 'insert', 'immediate', 'cancel', 'pause'):
                    with self.subTest(action=action), self.assertRaisesRegex(ValueError, '正在重新准备'):
                        self.store.task_action(key, action)
                self.assertFalse(self.store.can_transfer(key))
                with self.assertRaises(ValueError):
                    self.store.transfer(key, self.backup)
                with self.assertRaisesRegex(ValueError, '正在重新准备'):
                    await self.store.prepare_only(updated)
                self.node(self.url)
                await self.store.dispatch_node(self.url)
                submit.assert_not_awaited()
            finally:
                release.set()
                result = await preparing
        self.assertEqual(result['local_task_id'], key)
        self.assertIs(self.store.rows[key]['input'], updated)
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertFalse(transfer_states[0])
        self.assertTrue(transfer_states[-1])
        self.assertEqual(self.store.task_action(key, 'resume')['status'], 'local_queued')

    async def test_failed_reprepare_releases_controls_and_preserves_input(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        updated = self.data.model_copy(deep=True)
        with patch.object(execution_checks, 'prepare_report', side_effect=ValueError('invalid fixture')):
            with self.assertRaisesRegex(ValueError, 'invalid fixture'):
                await self.store.prepare_only(updated)
        self.assertIs(self.store.rows[key]['input'], self.data)
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertTrue(self.store.can_transfer(key))
        self.assertEqual(self.store.task_action(key, 'cancel')['status'], 'cancelled')

    async def test_cancelled_prepare_caller_keeps_controls_blocked_until_writer_stops(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def prepare_report(*args):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError('test did not release preparation')
            return {'ok': True}

        with patch.object(execution_checks, 'prepare_report', prepare_report):
            preparing = asyncio.create_task(self.store.prepare_only(self.data.model_copy(deep=True)))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                preparing.cancel()
                await asyncio.sleep(0)
                with self.assertRaisesRegex(ValueError, '正在重新准备'):
                    self.store.task_action(key, 'resume')
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await preparing
        self.assertIs(self.store.rows[key]['input'], self.data)
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertEqual(self.store.task_action(key, 'cancel')['status'], 'cancelled')

    async def test_image_batch_cancel_queues_terminal_notice_after_old_notice_is_superseded(self):
        self.data.image_batch_id = 'approved-list.json'
        key = (await self.store.enqueue(self.data))['local_task_id']
        self.store.rows[key]['state']['notices'] = [{'delivery': 'pending', 'event': 'old'}]
        with patch.object(self.store, 'notify', AsyncMock()):
            self.store.task_action(key, 'cancel')
            await self.store.notifiers[key]
        state = self.store.rows[key]['state']
        self.assertEqual(state['notices'][0]['delivery'], 'superseded')
        self.assertEqual(state['notices'][-1]['kind'], 'terminal')
        self.assertEqual(state['notices'][-1]['delivery'], 'pending')
        self.assertEqual(state['notification'], 'waiting')

    async def test_standalone_cancel_keeps_existing_silent_behavior(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(self.store, 'queue_notice') as notice:
            self.store.task_action(key, 'cancel')
            notice.assert_not_called()
        self.assertEqual(self.store.rows[key]['state']['notification'], 'not_required')


if __name__ == '__main__':
    unittest.main()
