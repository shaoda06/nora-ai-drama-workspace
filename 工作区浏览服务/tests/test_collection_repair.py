"""Scoped root repair, immutable generation inputs and original-task collection."""
import json
from contextlib import asynccontextmanager
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from backend.services import comfy_tasks as t
from backend.services.collection_repair import CollectionRepairInput, repair_collection
from tests.http_case import HttpTestCase
from tests import test_comfy_segments as base


class CollectionRepairTests(unittest.IsolatedAsyncioTestCase):
    result = base.SegmentTests.result

    async def asyncSetUp(self):
        await base.SegmentTests.asyncSetUp(self)
        self.data.desktop.caller_thread = self.data.thread_id
        self.data.segment_plan.output_root = 'E:/wrong/output'
        self.store.save('task', status='collection_failed')
        self.store.rows['task'].pop('_completion_input', None)
        self.store.persist('task')
        self.store.db.commit()
        self.write_history(self.result())
        self.repair = CollectionRepairInput(expected_prompt_id='real-id',
            output_root='E:/Comfy/output', reason='原终态报告确认实际导出根目录',
            thread_id=self.data.thread_id)

    async def asyncTearDown(self):
        await base.SegmentTests.asyncTearDown(self)

    def write_history(self, result):
        result['prompt_id'] = 'real-id'
        (self.record / self.data.history_name).write_text(json.dumps({'data': result}))

    async def test_repair_then_retry_collects_original_task_without_generation(self):
        original = self.data.model_dump()
        with patch.object(t.client, 'submit') as submit, patch.object(self.store, 'queue_notice'):
            result = repair_collection(self.store, 'task', self.repair)
            self.assertFalse(result['duplicate'])
            self.assertEqual(self.downloads, [])
            self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
            await self.store.retry_collection('task')
            await self.store.workers['task']
            submit.assert_not_called()
        state = self.store.rows['task']['state']
        self.assertEqual((state['status'], state['prompt_id'], state['collected']), ('completed', 'real-id', 2))
        self.assertEqual(self.data.model_dump(), original)
        events = json.loads((self.record / '后台过程记录.json').read_text())
        repairs = [e for e in events if e['stage'] == 'collection_repair']
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]['old_output_root'], 'E:/wrong/output')
        self.assertEqual(self.downloads, [('seg_0000_pre.mp4', 'minimax_seg_export/run001'),
                                          ('seg_0002_pre.mp4', 'minimax_seg_export/run001')])

    async def test_override_survives_restart_and_original_payload_is_preserved(self):
        repair_collection(self.store, 'task', self.repair)
        self.assertTrue(repair_collection(self.store, 'task', self.repair)['duplicate'])
        restored = t.TaskStore(self.root / 'runtime', self.root)
        try:
            row = restored.rows['task']
            self.assertEqual(row['state']['collection_output_root'], 'E:/Comfy/output')
            self.assertEqual(row['input'].segment_plan.output_root, 'E:/wrong/output')
        finally:
            await restored.close()

    async def test_rejects_wrong_owner_prompt_state_and_unproven_root(self):
        for updates in ({'thread_id': 'another-chat'}, {'expected_prompt_id': 'another-prompt'},
                        {'output_root': 'E:/'}, {'output_root': 'E:/elsewhere'}, {'reason': ' '}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                repair_collection(self.store, 'task', self.repair.model_copy(update=updates))
        self.store.save('task', status='completed')
        with self.assertRaises(ValueError):
            repair_collection(self.store, 'task', self.repair)
        self.assertNotIn('collection_output_root', self.store.rows['task']['state'])

    async def test_requires_successful_original_report_and_every_selected_path(self):
        for result in (self.result('failed'), self.result(indices=(0,))):
            with self.subTest(result=result):
                self.write_history(result)
                with self.assertRaises(ValueError):
                    repair_collection(self.store, 'task', self.repair)
        result = self.result()
        result['history']['outputs']['403']['text'][0] = result['history']['outputs']['403']['text'][0].replace(
            'seg_0002_pre.mp4', 'seg_0001_pre.mp4')
        self.write_history(result)
        with self.assertRaises(ValueError):
            repair_collection(self.store, 'task', self.repair)


class CollectionRepairHttpTests(HttpTestCase):
    def test_route_preserves_task_store_sqlite_thread(self):
        @asynccontextmanager
        async def lifespan(app):
            app.state.comfy_tasks = SimpleNamespace(token='test-token', db=sqlite3.connect(':memory:'))
            try:
                yield
            finally:
                app.state.comfy_tasks.db.close()

        def repair(store, key, data):
            store.db.execute('SELECT 1').fetchone()
            return {'status': 'repaired'}

        body = {'thread_id': 'caller', 'expected_prompt_id': 'original',
                'output_root': 'E:/Comfy/output', 'reason': '实际报告中的路径'}
        with patch.object(main.app.router, 'lifespan_context', lifespan), \
                patch.object(main, 'repair_collection', side_effect=repair), \
                TestClient(main.app, client=('127.0.0.1', 1234)) as client:
            response = client.post('/api/internal/comfy/tasks/task/repair-collection',
                                   json=body, headers={'x-nora-task-token': 'test-token'})
            self.assertEqual(response.json(), {'status': 'repaired'})

    def test_authenticated_route_and_conflict_response(self):
        store = SimpleNamespace(token='test-token')
        body = {'thread_id': 'caller', 'expected_prompt_id': 'original',
                'output_root': 'E:/Comfy/output', 'reason': '实际报告中的路径'}
        with patch.object(main.app.state, 'comfy_tasks', store, create=True), \
                TestClient(main.app, client=('127.0.0.1', 1234)) as client:
            url = '/api/internal/comfy/tasks/task/repair-collection'
            self.assertEqual(client.post(url, json=body).status_code, 403)
            with patch.object(main, 'repair_collection', return_value={'status': 'repaired'}) as repair:
                response = client.post(url, json=body, headers={'x-nora-task-token': 'test-token'})
                self.assertEqual(response.json(), {'status': 'repaired'})
                self.assertEqual(repair.call_args.args[2].expected_prompt_id, 'original')
            with patch.object(main, 'repair_collection', side_effect=ValueError('原任务不符')):
                response = client.post(url, json=body, headers={'x-nora-task-token': 'test-token'})
                self.assertEqual(response.status_code, 409)


if __name__ == '__main__':
    unittest.main()
