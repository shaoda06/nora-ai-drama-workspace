"""Workspace node editing against temporary files and an isolated task store."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from backend import main
from backend.services import node_config as editor
from tests import test_comfy_tasks as task_tests


class NodeConfigTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = task_tests.TaskTests.asyncSetUp
    asyncTearDown = task_tests.TaskTests.asyncTearDown

    def config_path(self):
        return self.root / 'comfyui-config.json'

    def edit(self, nodes):
        return editor.ConfigEdit(revision=editor.file_revision(self.config_path()), nodes=nodes)

    async def test_read_legacy_format_is_read_only_and_credentials_are_never_returned(self):
        path = self.config_path()
        before = path.read_bytes()
        nodes, revision = editor.read_config(self.store)
        self.assertEqual(editor.snapshot(self.store, nodes, revision)['nodes'][0]['url'], self.data.url)
        self.assertEqual(path.read_bytes(), before)
        path.write_text(json.dumps({'remote-nodes': [{'url': self.data.url,
            'auth': {'type': 'basic', 'username': 'private-user', 'password': 'private-password'}}]}))
        public = editor.snapshot(self.store, *editor.read_config(self.store))
        self.assertTrue(public['nodes'][0]['has_auth'])
        self.assertNotIn('private-', json.dumps(public))

    async def test_initial_setup_creates_only_workspace_config(self):
        self.config_path().unlink()
        self.assertEqual(editor.snapshot(self.store, *editor.read_config(self.store)), {'revision': None, 'nodes': []})
        result = editor.save_config(self.store, self.edit([{'url': 'https://new.invalid/'}]))
        self.assertEqual(result['nodes'][0]['url'], 'https://new.invalid')
        self.assertEqual(self.store.remote_urls(), ['https://new.invalid'])
        self.assertEqual(self.store.rows, {})
        self.assertFalse((self.project / 'comfyui-config.json').exists())

    async def test_reorder_add_and_remove_keep_task_addresses_and_records(self):
        task_tests.TaskTests.seed(self, status='running')
        before_rows = {key: (row['input'].model_dump(), deepcopy(row['state'])) for key, row in self.store.rows.items()}
        before_changes = self.store.db.total_changes
        before_records = {path: path.read_bytes() for path in self.record.iterdir() if path.is_file()}
        edit = self.edit([{'url': 'https://backup.invalid'}, {'url': self.data.url}])
        editor.save_config(self.store, edit)
        self.assertEqual(self.store.remote_urls(), ['https://backup.invalid', self.data.url])
        self.assertEqual({key: (row['input'].model_dump(), row['state']) for key, row in self.store.rows.items()}, before_rows)
        self.assertEqual(self.store.db.total_changes, before_changes)
        self.assertEqual({path: path.read_bytes() for path in self.record.iterdir() if path.is_file()}, before_records)
        editor.save_config(self.store, self.edit([{'url': self.data.url}]))
        self.assertEqual(self.store.remote_urls(), [self.data.url])
        self.assertTrue(self.store.remote_queues.config_changed.is_set())

    async def test_preserve_replace_and_remove_auth_without_echoing_secrets(self):
        self.config_path().write_text(json.dumps({'remote-nodes': [{'url': self.data.url,
            'auth': {'type': 'basic', 'username': 'old-user', 'password': 'old-password'}}]}))
        kept = editor.save_config(self.store, self.edit([{'url': self.data.url, 'original_url': self.data.url, 'auth_mode': 'keep'}]))
        self.assertNotIn('old-', json.dumps(kept))
        self.assertEqual(editor.config.load_config(self.root)[0]['auth']['password'], 'old-password')
        replaced = editor.save_config(self.store, self.edit([{'url': self.data.url, 'auth_mode': 'basic',
                                                           'username': 'new-user', 'password': 'new-password'}]))
        self.assertNotIn('new-', json.dumps(replaced))
        self.assertEqual(editor.config.load_config(self.root)[0]['auth']['password'], 'new-password')
        editor.save_config(self.store, self.edit([{'url': self.data.url}]))
        self.assertNotIn('auth', editor.config.load_config(self.root)[0])

    async def test_auth_cannot_be_carried_to_a_different_host(self):
        self.config_path().write_text(json.dumps({'remote-nodes': [{'url': self.data.url,
            'auth': {'type': 'basic', 'username': 'user', 'password': 'password'}}]}))
        before = self.config_path().read_bytes()
        with self.assertRaisesRegex(ValueError, '重新填写'):
            editor.save_config(self.store, self.edit([{'url': 'https://other.invalid', 'original_url': self.data.url, 'auth_mode': 'keep'}]))
        self.assertEqual(self.config_path().read_bytes(), before)

    async def test_stale_editor_and_changes_during_write_do_not_overwrite(self):
        edit = self.edit([{'url': 'https://edited.invalid'}])
        self.config_path().write_text(json.dumps({'remote-url': 'https://agent.invalid'}))
        before = self.config_path().read_bytes()
        with self.assertRaises(editor.ConfigConflict):
            editor.save_config(self.store, edit)
        self.assertEqual(self.config_path().read_bytes(), before)
        with patch.object(editor, 'file_revision', side_effect=['current', 'current', 'changed']):
            with self.assertRaises(editor.ConfigConflict):
                editor.save_config(self.store, editor.ConfigEdit(revision='current', nodes=[{'url': 'https://edited.invalid'}]))
        self.assertEqual(self.config_path().read_bytes(), before)
        self.assertEqual(list(self.root.glob('.comfyui-config-*.tmp')), [])

    async def test_atomic_write_failure_preserves_original(self):
        before = self.config_path().read_bytes()
        with patch.object(editor.os, 'replace', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                editor.save_config(self.store, self.edit([{'url': 'https://edited.invalid'}]))
        self.assertEqual(self.config_path().read_bytes(), before)
        self.assertEqual(list(self.root.glob('.comfyui-config-*.tmp')), [])

    async def test_active_pending_and_unresolved_nodes_cannot_be_removed_or_replaced(self):
        for status in ('local_queued', 'paused', 'preparing', 'submitting', 'queued', 'running', 'collecting',
                       'collection_failed', 'needs_attention', 'submission_unknown'):
            self.store.rows['active'] = {'input': self.data, 'state': {'status': status}}
            before = self.config_path().read_bytes()
            with self.assertRaises(editor.ConfigConflict, msg=status):
                editor.save_config(self.store, self.edit([{'url': 'https://replacement.invalid'}]))
            self.assertEqual(self.config_path().read_bytes(), before)
        self.store.rows.clear()
        self.store.remote_queues.states[self.data.url] = {'queue': [{'prompt_id': 'external-task'}]}
        with self.assertRaises(editor.ConfigConflict):
            editor.save_config(self.store, self.edit([{'url': 'https://replacement.invalid'}]))

    async def test_historical_task_does_not_block_removal(self):
        self.store.rows['old'] = {'input': self.data, 'state': {'status': 'completed'}}
        editor.save_config(self.store, self.edit([{'url': 'https://new.invalid'}]))
        self.assertEqual(self.store.rows['old']['input'].url, self.data.url)

    async def test_validation_rejects_empty_duplicate_embedded_credentials_and_bad_auth(self):
        for nodes in ([], [{'url': self.data.url}, {'url': self.data.url + '/'}],
                      [{'url': 'https://user:password@node.invalid'}], [{'url': 'file:///tmp/node'}],
                      [{'url': self.data.url, 'auth_mode': 'basic', 'username': 'a:b', 'password': 'pw'}],
                      [{'url': self.data.url, 'auth_mode': 'basic'}]):
            before = self.config_path().read_bytes()
            with self.assertRaises((ValueError, editor.config.client.ClientError)):
                editor.save_config(self.store, self.edit(nodes))
            self.assertEqual(self.config_path().read_bytes(), before)

    async def test_http_origin_redaction_and_save(self):
        api = FastAPI()
        api.state.comfy_tasks = self.store
        api.add_api_route('/api/comfy/config', main.comfy_config, methods=['GET'])
        api.add_api_route('/api/comfy/config', main.save_comfy_config, methods=['PUT'])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url='http://localhost') as client:
            first = await client.get('/api/comfy/config')
            self.assertEqual(first.headers['cache-control'], 'no-store')
            payload = {'revision': first.json()['revision'], 'nodes': [{'url': self.data.url}]}
            self.assertEqual((await client.put('/api/comfy/config', json=payload)).status_code, 403)
            self.assertEqual((await client.put('/api/comfy/config', headers={'origin': 'http://evil.invalid'}, json=payload)).status_code, 403)
            malformed = await client.put('/api/comfy/config', headers={'origin': 'http://localhost'},
                                         json={'nodes': [{'password': 'never-echo-this'}]})
            self.assertEqual(malformed.status_code, 422)
            self.assertNotIn('never-echo-this', malformed.text)
            valid = await client.put('/api/comfy/config', headers={'origin': 'http://localhost'}, json=payload)
            self.assertEqual(valid.status_code, 200)
            stale = await client.put('/api/comfy/config', headers={'origin': 'http://localhost'}, json=payload)
            self.assertEqual(stale.status_code, 409)

    async def test_config_change_wakes_single_observer_without_waiting_for_poll(self):
        observer = self.store.remote_queues
        observer.sync = AsyncMock()
        observer.manager = asyncio.create_task(observer.follow_config())
        observer.config_changed.set()
        for _ in range(5):
            await asyncio.sleep(0)
            if observer.sync.await_count:
                break
        observer.sync.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
