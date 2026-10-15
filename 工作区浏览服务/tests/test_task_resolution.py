"""Evidence-backed exception closure: preserve facts, remain terminal, no generation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend import main
from backend.services.comfy_tasks import TaskStore, TERMINAL
from backend.services.task_details import task_detail
from backend.services.task_history import task_history
from backend.services.task_resolution import ResolutionInput, resolve_task
from tests import test_comfy_tasks as fixtures


class ResolutionTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.TaskTests.asyncTearDown
    seed = fixtures.TaskTests.seed

    async def asyncSetUp(self):
        await fixtures.TaskTests.asyncSetUp(self)
        self.seed('needs_attention', 'sent')
        self.store.save('task', error='原队列及history均无此任务', error_details={'original': 'retained'}, collected=0, expected=1)
        evidence = self.record / '实际下载凭据.json'
        evidence.write_text('{"ok":true}', encoding='utf-8')
        self.plan = ResolutionInput(expected_prompt_id='real-id', summary='已有凭据确认取回；原终态未知',
                                    outcome='recovered', evidence=[str(evidence)])

    async def test_closure_preserves_original_facts_and_is_separate_from_success(self):
        before = deepcopy(self.store.rows['task']['state'])
        self.store.record('task', 'reconcile', 'unknown', error=before['error'])
        with patch.object(self.store.client, 'submit') as submit, patch.object(self.store.client, 'download') as download:
            result = resolve_task(self.store, 'task', self.plan)
            submit.assert_not_called()
            download.assert_not_called()
        after = self.store.rows['task']['state']
        self.assertEqual(result['status'], 'resolved')
        self.assertIn('resolved', TERMINAL)
        for field in ('prompt_id', 'error', 'error_details', 'collected', 'expected', 'notification'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after['resolution']['original_status'], 'needs_attention')
        self.assertEqual(task_history(self.store, self.data.url, result='abnormal')['total'], 0)
        self.assertEqual(task_history(self.store, self.data.url, result='completed')['total'], 0)
        self.assertEqual(task_history(self.store, self.data.url, result='resolved')['total'], 1)
        detail = await task_detail(self.store, 'task')
        self.assertEqual([item['result'] for item in detail['events']], ['unknown', 'resolved'])
        self.assertEqual(detail['summary']['error'], before['error'])
        self.assertIn('/files/', detail['resolution_evidence'][0]['url'])
        saved = json.loads((self.record / '后台任务状态.json').read_text('utf-8'))
        self.assertEqual(saved['resolution']['original_error'], before['error'])

    async def test_repeat_and_restart_do_not_duplicate_events_or_resume_generation(self):
        resolve_task(self.store, 'task', self.plan)
        count = self.store.db.execute('select count(*) from task_events').fetchone()[0]
        await self.store.close()
        self.store = TaskStore(self.root / 'runtime', self.root)
        self.assertTrue(resolve_task(self.store, 'task', self.plan)['duplicate'])
        self.assertEqual(self.store.db.execute('select count(*) from task_events').fetchone()[0], count)
        with patch.object(self.store, 'watch', AsyncMock()) as watch, patch.object(self.store, 'notify', AsyncMock()) as notify:
            await self.store.start()
            watch.assert_not_awaited()
            notify.assert_not_awaited()
        changed = self.plan.model_copy(update={'summary': '不同决定'})
        with self.assertRaisesRegex(ValueError, '不同的结案'):
            resolve_task(self.store, 'task', changed)

    async def test_invalid_identity_evidence_or_active_state_cannot_be_closed(self):
        for update in ({'expected_prompt_id': 'wrong'}, {'summary': ' '},
                       {'evidence': ['missing.json']}, {'evidence': ['../outside.json']},
                       {'outcome': 'superseded'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                resolve_task(self.store, 'task', self.plan.model_copy(update=update))
            self.assertEqual(self.store.rows['task']['state']['status'], 'needs_attention')
        self.store.save('task', status='running')
        with self.assertRaisesRegex(ValueError, '仅允许'):
            resolve_task(self.store, 'task', self.plan)

    async def test_replacement_must_be_completed_same_project_and_is_shown_in_details(self):
        data = self.data.model_copy(deep=True)
        data.record_dir = str(self.project / 'later-record')
        self.store.rows['later'] = {'input': data, 'state': {**self.store.rows['task']['state'],
                                                          'id': 'later', 'status': 'running'}}
        plan = self.plan.model_copy(update={'outcome': 'superseded', 'replacement_task_ids': ['later']})
        with self.assertRaisesRegex(ValueError, '已完成'):
            resolve_task(self.store, 'task', plan)
        self.store.rows['later']['state']['status'] = 'completed'
        data.project = str(self.root / 'projects/other')
        with self.assertRaisesRegex(ValueError, '本项目'):
            resolve_task(self.store, 'task', plan)
        data.project = str(self.project)
        resolve_task(self.store, 'task', plan)
        detail = await task_detail(self.store, 'task')
        self.assertEqual(detail['replacement_tasks'][0]['id'], 'later')
        self.assertEqual(detail['replacement_tasks'][0]['status'], 'completed')

    async def test_http_closure_requires_local_agent_token(self):
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/resolve/{key}', main.agent_resolve_task, methods=['POST'])
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            self.assertEqual((await client.post('/resolve/task', json=self.plan.model_dump())).status_code, 403)
            headers = {'x-nora-task-token': self.store.token}
            self.assertEqual((await client.post('/resolve/task', json=self.plan.model_dump(),
                                               headers={**headers, 'origin': 'http://127.0.0.1'})).status_code, 403)
            response = await client.post('/resolve/task', json=self.plan.model_dump(), headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'resolved')


if __name__ == '__main__':
    unittest.main()
