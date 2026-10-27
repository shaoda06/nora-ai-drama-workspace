"""Read-only history/detail projections; no service, network or production files."""
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.task_history import task_history
from backend.services.task_details import task_detail


class CloseoutVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def row(self, key, closeout=None, status='completed'):
        state = dict(id=key, title=key, project='fixture', status=status, task_type='video-first-pass',
                     created_at='2026-10-27T01:00:00+00:00', collected=1, expected=1)
        if closeout is not None:
            state['closeout'] = closeout
        data = SimpleNamespace(url='http://fixture.invalid')
        data.model_copy = lambda **kwargs: data
        return dict(input=data, state=state)

    async def test_completed_closeout_failures_are_searchable_without_changing_execution_status(self):
        rows = {
            'ready': self.row('ready', {'status': 'completed'}),
            'registration': self.row('registration', {'status': 'registration_failed', 'error': 'write conflict', 'video_outputs': ['private']}),
            'browser': self.row('browser', {'status': 'browser_pending', 'error': 'parse error'}),
            'legacy': self.row('legacy'),
            'cancelled': self.row('cancelled', {'status': 'registration_failed'}, 'cancelled'),
        }
        store = SimpleNamespace(rows=rows)
        abnormal = task_history(store, result='abnormal')['items']
        self.assertEqual({item['id'] for item in abnormal}, {'registration', 'browser'})
        self.assertTrue(all(item['status'] == 'completed' for item in abnormal))
        self.assertNotIn('private', json.dumps(abnormal))
        self.assertEqual(task_history(store, result='completed')['total'], 4)
        rows['registration']['state']['closeout'] = {'status': 'completed'}
        self.assertEqual([item['id'] for item in task_history(store, result='abnormal')['items']], ['browser'])

    async def test_detail_exposes_closeout_reason_and_retry_without_internal_payload(self):
        row = self.row('task', {'status': 'browser_pending', 'error': 'source changed', 'record_updates': 'internal'})
        row['state']['closeout_next_retry_at'] = '2026-10-27T01:01:00+00:00'
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE task_events(id INTEGER, task_id TEXT, event TEXT)')
        store = SimpleNamespace(rows={'task': row}, db=db)
        with patch('backend.services.task_details.task_files', return_value={'outputs': [], 'records': []}):
            detail = await task_detail(store, 'task')
        self.assertEqual(detail['summary']['closeout'], {'status': 'browser_pending', 'error': 'source changed'})
        self.assertEqual(detail['summary']['closeout_next_retry_at'], row['state']['closeout_next_retry_at'])
        self.assertNotIn('internal', json.dumps(detail))


if __name__ == '__main__':
    unittest.main()
