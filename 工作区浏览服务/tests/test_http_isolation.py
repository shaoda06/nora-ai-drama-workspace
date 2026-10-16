"""HTTP clients must leave an existing server's credentials and queue alone."""
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from backend import main
from backend.services.comfy_tasks import TaskStore
from tests.http_case import HttpTestCase


class HttpIsolationTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.formal = Path(temporary.name) / 'formal-service'
        self.runtime = self.formal / 'runtime'
        self.queue = TaskStore(self.runtime, self.formal)
        self.addCleanup(self.queue.db.close)
        self.queue.db.execute('INSERT INTO task_events (task_id, event) VALUES (?, ?)',
                              ('existing-task', '{"status":"completed"}'))
        self.queue.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)',
                              ('notice', 'source-thread', '[]', '{}', 'sent'))
        self.queue.db.commit()
        self.credentials = self.runtime / 'task-service.json'
        self.credentials.write_text(json.dumps({'url': 'http://127.0.0.1:8782',
                                                'token': self.queue.token}), encoding='utf-8')
        self.credential_bytes = self.credentials.read_bytes()
        self.credential_mtime = self.credentials.stat().st_mtime_ns
        self.database = self.runtime / 'comfy-tasks.sqlite'
        self.database_bytes = self.database.read_bytes()
        self.database_mtime = self.database.stat().st_mtime_ns
        # Stand in for an already-running formal server, entirely inside a temp dir.
        self.task_factory = Mock(side_effect=AssertionError('HTTP test started a task service'))
        self.download_cleanup = Mock()
        for override in (patch.object(main, 'TOOL', self.formal),
                         patch.object(main, 'WORKSPACE', self.formal),
                         patch.object(main, 'TaskStore', self.task_factory),
                         patch.object(main, 'clear_downloads', self.download_cleanup),
                         patch.object(main.app.state, 'comfy_tasks', self.queue, create=True)):
            override.start()
            self.addCleanup(override.stop)

    def assert_credentials_unchanged(self):
        self.assertEqual(self.credentials.read_bytes(), self.credential_bytes)
        self.assertEqual(self.credentials.stat().st_mtime_ns, self.credential_mtime)
        self.assertIs(main.app.state.comfy_tasks, self.queue)
        self.task_factory.assert_not_called()
        self.download_cleanup.assert_not_called()

    def assert_queue_unchanged(self):
        self.assert_credentials_unchanged()
        self.assertEqual(self.database.read_bytes(), self.database_bytes)
        self.assertEqual(self.database.stat().st_mtime_ns, self.database_mtime)
        self.assertEqual(self.queue.db.execute('SELECT task_id, event FROM task_events').fetchall(),
                         [('existing-task', '{"status":"completed"}')])

    def test_context_clients_do_not_replace_credentials_or_touch_task_database(self):
        with TestClient(main.app) as first:
            self.assertEqual(first.get('/api/service').status_code, 200)
            with TestClient(main.app) as second:
                self.assertEqual(second.get('/api/service').status_code, 200)
                self.assert_queue_unchanged()
            self.assert_queue_unchanged()
        self.assert_queue_unchanged()

    def test_client_exception_leaves_existing_credentials_and_queue_untouched(self):
        with self.assertRaisesRegex(RuntimeError, 'test interrupted'):
            with TestClient(main.app) as client:
                self.assertEqual(client.get('/api/service').status_code, 200)
                raise RuntimeError('test interrupted')
        self.assert_queue_unchanged()

    def test_original_token_can_acknowledge_after_http_context_exits(self):
        with TestClient(main.app) as client:
            self.assertEqual(client.get('/api/service').status_code, 200)
        self.assert_queue_unchanged()
        with TestClient(main.app, client=('127.0.0.1', 1234)) as client:
            # SQLite belongs to the ASGI thread while the endpoint handles it.
            connection = client.portal.call(sqlite3.connect, self.database)
            try:
                with patch.object(self.queue, 'db', connection):
                    url = '/api/internal/comfy/notifications/notice/ack'
                    body = {'thread_id': 'source-thread'}
                    headers = {'x-nora-task-token': json.loads(self.credentials.read_text('utf-8'))['token']}
                    self.assertEqual(client.post(url, json=body).status_code, 403)
                    self.assertEqual(client.post(url, json=body,
                                                 headers={**headers, 'origin': 'http://localhost'}).status_code, 403)
                    response = client.post(url, json=body, headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {'notification_id': 'notice', 'status': 'acknowledged', 'tasks': []})
            finally:
                client.portal.call(connection.close)
        self.assert_credentials_unchanged()
        self.assertEqual(self.queue.db.execute('SELECT state FROM notification_batches WHERE id=?',
                                              ('notice',)).fetchone(), ('acknowledged',))
