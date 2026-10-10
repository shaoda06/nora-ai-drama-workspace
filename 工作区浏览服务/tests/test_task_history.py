"""History pagination, search, categories, node isolation and compact snapshots."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from backend import main
from backend.services.task_history import task_history
from tests import test_comfy_tasks as task_tests


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = task_tests.TaskTests.asyncSetUp
    asyncTearDown = task_tests.TaskTests.asyncTearDown

    def add(self, key, status='completed', url=None, title='测试图片', session='图片制作会话', time=None):
        self.store.rows[key] = {'input': self.data.model_copy(update={'url': url or self.data.url}),
                               'state': {'id': key, 'status': status, 'title': title, 'source_session_name': session,
                                         'task_type': 'image', 'project': self.project.name, 'created_at': time or '2026-10-11T00:00:00+08:00',
                                         'collected': 1, 'expected': 1, 'client_id': 'private', 'queue_order': 1,
                                         'notices': [{'delivery': 'sent', 'message': 'private'}]}}

    async def test_default_twenty_then_more_are_recent_and_do_not_overlap(self):
        start = datetime(2026, 10, 11, tzinfo=timezone(timedelta(hours=8)))
        for index in range(45):
            self.add(str(index), time=(start + timedelta(minutes=index)).isoformat())
        first = task_history(self.store, self.data.url)
        second = task_history(self.store, self.data.url, offset=first['next_offset'])
        last = task_history(self.store, self.data.url, offset=second['next_offset'])
        self.assertEqual([len(page['items']) for page in (first, second, last)], [20, 20, 5])
        self.assertEqual(first['total'], 45)
        self.assertEqual([row['id'] for page in (first, second, last) for row in page['items']], [str(index) for index in reversed(range(45))])
        self.assertIsNone(last['next_offset'])
        self.assertNotIn('private', json.dumps(first))

    async def test_search_title_or_session_can_combine_with_result_and_node(self):
        self.add('title', title='EP003 二采')
        self.add('session', session='EP003 会话', status='failed')
        self.add('other-node', title='EP003 二采', url='http://backup.invalid:8188')
        self.add('queued', title='EP003 二采', status='local_queued')
        self.add('paused', title='EP003 二采', status='paused')
        self.add('no-session', session=None)
        self.assertEqual({item['id'] for item in task_history(self.store, self.data.url + '/', ' ep003 ')['items']}, {'title', 'session'})
        self.assertEqual([item['id'] for item in task_history(self.store, self.data.url, 'ep003', 'abnormal')['items']], ['session'])
        self.assertEqual([item['id'] for item in task_history(self.store, 'http://backup.invalid:8188', 'ep003')['items']], ['other-node'])

    async def test_filter_categories_include_all_abnormal_states_but_not_collecting(self):
        states = ['completed', 'cancelled', 'failed', 'rejected', 'collection_failed', 'needs_attention', 'submission_unknown', 'collecting']
        for status in states:
            self.add(status, status=status)
        self.assertEqual(task_history(self.store, self.data.url, result='completed')['total'], 1)
        self.assertEqual(task_history(self.store, self.data.url, result='cancelled')['total'], 1)
        self.assertEqual({item['id'] for item in task_history(self.store, self.data.url, result='abnormal')['items']}, set(states[2:7]))
        self.assertEqual(task_history(self.store, self.data.url)['total'], 8)
        self.assertEqual(task_history(self.store, self.data.url, search='没有这条任务')['total'], 0)

    async def test_sort_uses_actual_end_time_with_timezone_and_stable_tie_break(self):
        self.add('a', time='2026-10-11T01:00:00+08:00')
        self.add('b', time='2026-10-11T02:00:00+08:00')
        self.add('c', time='2026-10-11T02:00:00+08:00')
        self.store.rows['a']['state']['ended_at'] = '2026-10-10T19:00:00+00:00'
        self.assertEqual([item['id'] for item in task_history(self.store, self.data.url)['items']], ['a', 'c', 'b'])

    async def test_compact_snapshot_preserves_queue_and_counts_without_historical_cards(self):
        for status in ['local_queued', 'paused', 'completed', 'collecting', 'running']:
            self.add(status, status=status)
        self.store.rows['completed']['state']['updated_at'] = '2026-10-11T03:00:00+08:00'
        snapshot = self.store.public(include_history=False)
        self.assertEqual({row['id'] for row in snapshot['tasks']}, {'local_queued', 'paused', 'running'})
        self.assertEqual({row['id'] for row in snapshot['local_tasks']}, {'local_queued', 'paused'})
        self.assertEqual(snapshot['local_counts'][self.data.url], {'queued': 1, 'paused': 1, 'history': 2})
        self.assertEqual(snapshot['history_updated_at'][self.data.url], '2026-10-11T03:00:00+08:00')
        self.assertEqual(len(self.store.public()['tasks']), 5)
        self.assertNotIn('local_counts', self.store.public())

    async def test_http_pagination_boundaries_and_read_only_queries(self):
        api = FastAPI()
        api.add_api_route('/history', main.comfy_history, methods=['GET'])
        api.add_api_route('/tasks', main.comfy_tasks, methods=['GET'])
        api.state.comfy_tasks = self.store
        self.add('one')
        before = self.store.db.total_changes
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url='http://test') as client:
            with patch.object(self.store.client, 'submit') as submit, patch.object(self.store.client, 'download') as download:
                response = await client.get('/history', params={'url': self.data.url})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['total'], 1)
                for params in ({'offset': -1}, {'limit': 0}, {'limit': 101}, {'result': 'unknown'}):
                    self.assertEqual((await client.get('/history', params={'url': self.data.url, **params})).status_code, 422)
                compact = (await client.get('/tasks?include_history=false')).json()
                self.assertEqual(compact['local_tasks'], [])
                self.assertEqual(compact['local_counts'][self.data.url]['history'], 1)
                submit.assert_not_called()
                download.assert_not_called()
        self.assertEqual(self.store.db.total_changes, before)


if __name__ == '__main__':
    unittest.main()
