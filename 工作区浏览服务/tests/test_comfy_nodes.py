"""Persistent node observers: real local sockets, no real workflows or media."""
import asyncio
import base64
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, WebSocket
from fastapi.responses import Response
from starlette.websockets import WebSocketDisconnect
import uvicorn

from backend.services import comfy_nodes as n
from backend.services.comfy_tasks import TaskStore, client


class NodeWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'projects/test'
        self.project.mkdir(parents=True)
        self.queues = {
            'one': {'queue_running': [[1, 'own-id', {'secret-workflow': 'private'}]],
                    'queue_pending': [[2, 'foreign-id', {}, {'client_id': 'foreign-client'}]]},
            'two': {'queue_running': [], 'queue_pending': []},
        }
        self.sockets = {'one': {}, 'two': {}}
        self.methods = []
        self.ids = []
        self.auth = {'type': 'basic', 'username': 'test-user', 'password': 'private-password'}
        self.expected_auth = 'Basic ' + base64.b64encode(b'test-user:private-password').decode()
        remote = FastAPI()

        @remote.middleware('http')
        async def authenticated(request, call_next):
            if request.headers.get('authorization') != self.expected_auth:
                return Response(status_code=401, headers={'WWW-Authenticate': 'Basic realm="test"'})
            return await call_next(request)

        @remote.get('/{node}/queue')
        async def queue(node: str):
            self.methods.append(('GET', node))
            return self.queues[node]

        @remote.websocket('/{node}/ws')
        async def websocket(ws: WebSocket, node: str):
            if ws.headers.get('authorization') != self.expected_auth:
                await ws.close()
                return
            await ws.accept()
            sid = ws.query_params['clientId']
            self.ids.append((node, sid))
            self.sockets[node][sid] = ws
            try:
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                del self.sockets[node][sid]

        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        base = 'http://127.0.0.1:' + str(self.listener.getsockname()[1])
        self.urls = [base + '/one', base + '/two']
        self.config = self.root / 'comfyui-config.json'
        self.config.write_text(json.dumps({'remote-nodes': [{'url': url, 'auth': self.auth} for url in self.urls]}))
        self.server = uvicorn.Server(uvicorn.Config(remote, log_level='error', lifespan='off'))
        self.serving = asyncio.create_task(self.server.serve(sockets=[self.listener]))
        await self.until(lambda: self.server.started)
        self.store = TaskStore(self.root / 'runtime', self.root)
        await self.store.remote_queues.start()
        await self.until(lambda: all(state['updated_at'] and state['connection'] == 'connected'
                                    for state in self.store.remote_queues.states.values()))

    async def asyncTearDown(self):
        await self.store.close()
        self.server.should_exit = True
        await self.serving
        self.listener.close()
        self.temp.cleanup()

    async def until(self, condition):
        async with asyncio.timeout(4):
            while not condition():
                await asyncio.sleep(.01)

    async def emit(self, node):
        for ws in list(self.sockets[node].values()):
            await ws.send_json({'type': 'status', 'data': {'status': {'exec_info': {'queue_remaining': 999}}}})

    async def test_two_idle_observers_share_no_client_id_and_only_expose_queue_identity(self):
        nodes = self.store.public()['remote_nodes']
        self.assertEqual([(node['running_count'], node['queued_count']) for node in nodes], [(1, 1), (0, 0)])
        self.assertTrue(all(node['connection'] == 'connected' for node in nodes))
        self.assertEqual(len(set(sid for _, sid in self.ids)), 2)
        public = json.dumps(nodes)
        self.assertNotIn('secret-workflow', public)
        self.assertNotIn('foreign-client', public)
        self.assertFalse(self.store.subscribers)  # No browser is needed to keep monitoring.
        self.assertNotIn('private-password', json.dumps(self.store.public()))
        self.assertNotIn(self.expected_auth, json.dumps(self.store.public()))
        self.assertEqual(set(self.methods), {('GET', 'one'), ('GET', 'two')})

    async def test_password_edit_reconnects_observers_without_url_change(self):
        original_ids = {sid for _, sid in self.ids}
        self.auth['password'] = 'new-password'
        self.expected_auth = 'Basic ' + base64.b64encode(b'test-user:new-password').decode()
        self.config.write_text(json.dumps({'remote-nodes': [{'url': url, 'auth': self.auth} for url in self.urls]}))
        await self.store.remote_queues.sync()
        await self.until(lambda: all(state['connection'] == 'connected' for state in self.store.remote_queues.states.values()))
        self.assertEqual(len(self.ids), 4)
        self.assertFalse(original_ids.intersection(sid for _, sid in self.ids[2:]))

    async def test_missing_credentials_keep_node_waiting_without_network_submission(self):
        self.config.write_text(json.dumps({'remote-nodes': [
            {'url': self.urls[0], 'auth': {'type': 'basic', 'username': '', 'password': ''}},
            {'url': self.urls[1], 'auth': self.auth}]}))
        await self.store.remote_queues.sync()
        await self.until(lambda: self.store.remote_queues.states[self.urls[0]]['connection'] == 'reconnecting')
        self.assertIsNone(self.store.remote_queues.states[self.urls[0]]['running_count'])

    async def test_status_refreshes_full_queue_and_drops_departed_tasks(self):
        self.queues['one'] = {'queue_running': [[2, 'foreign-id']],
                              'queue_pending': [[3, 'next'], [4, 'last']]}
        await self.emit('one')
        await self.until(lambda: self.store.remote_queues.states[self.urls[0]]['queued_count'] == 2)
        state = self.store.remote_queues.states[self.urls[0]]
        self.assertEqual(state['running_count'], 1)
        self.assertEqual(state['queue'], [
            {'prompt_id': 'foreign-id', 'status': 'running', 'queue_position': None},
            {'prompt_id': 'next', 'status': 'queued', 'queue_position': 1},
            {'prompt_id': 'last', 'status': 'queued', 'queue_position': 2}])

    async def test_disconnect_retains_last_queue_and_reconnect_refreshes_without_submission(self):
        with patch.object(n, 'RETRY_DELAYS', (.15,)):
            await next(iter(self.sockets['one'].values())).close()
            await self.until(lambda: self.store.remote_queues.states[self.urls[0]]['connection'] == 'reconnecting')
            state = self.store.remote_queues.states[self.urls[0]]
            self.assertEqual((state['running_count'], state['queued_count']), (1, 1))
            self.assertEqual(self.store.remote_queues.states[self.urls[1]]['connection'], 'connected')
            self.queues['one'] = {'queue_running': [], 'queue_pending': []}
            await self.until(lambda: self.store.remote_queues.states[self.urls[0]]['queued_count'] == 0
                             and self.store.remote_queues.states[self.urls[0]]['connection'] == 'connected')
            self.assertEqual(state['connection'], 'connected')
            self.assertEqual(len(set(sid for node, sid in self.ids if node == 'one')), 1)
        self.assertTrue(all(method == 'GET' for method, _ in self.methods))

    async def test_bad_queue_retains_data_and_does_not_fake_empty_or_disconnect(self):
        self.queues['one'] = {'queue_running': 'invalid', 'queue_pending': []}
        await self.emit('one')
        await self.until(lambda: self.store.remote_queues.states[self.urls[0]]['queue_error'])
        state = self.store.remote_queues.states[self.urls[0]]
        self.assertEqual(state['connection'], 'connected')
        self.assertEqual(state['running_count'], 1)
        self.queues['one'] = {'queue_running': [], 'queue_pending': []}
        await self.emit('one')
        await self.until(lambda: state['running_count'] == 0)
        self.assertIsNone(state['queue_error'])

    async def test_pending_heap_is_displayed_in_execution_order(self):
        self.queues['one'] = {'queue_running': [],
                              'queue_pending': [[1, 'first'], [3, 'last'], [2, 'second']]}
        await self.emit('one')
        await self.until(lambda: self.store.remote_queues.states[self.urls[0]]['queued_count'] == 3)
        self.assertEqual([(item['prompt_id'], item['queue_position'])
                          for item in self.store.remote_queues.states[self.urls[0]]['queue']],
                         [('first', 1), ('second', 2), ('last', 3)])

    async def test_offline_node_keeps_unknown_counts_and_does_not_block_other_nodes(self):
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        offline_url = 'http://127.0.0.1:' + str(probe.getsockname()[1])
        probe.close()
        self.config.write_text(json.dumps({'remote-nodes': [{'url': url, 'auth': self.auth} for url in [*self.urls, offline_url]]}))
        await self.store.remote_queues.sync()
        await self.until(lambda: self.store.remote_queues.states[offline_url]['connection'] == 'reconnecting')
        offline = self.store.remote_queues.states[offline_url]
        self.assertIsNone(offline['running_count'])
        self.assertIsNone(offline['queued_count'])
        self.assertIsNone(offline['updated_at'])
        self.assertTrue(all(self.store.remote_queues.states[url]['connection'] == 'connected' for url in self.urls))

    async def test_removed_node_closes_socket_and_shutdown_closes_remaining_observers(self):
        self.config.write_text(json.dumps({'remote-nodes': [{'url': url, 'auth': self.auth} for url in self.urls[1:]]}))
        await self.store.remote_queues.sync()
        await self.until(lambda: not self.sockets['one'])
        self.assertEqual(list(self.store.remote_queues.states), self.urls[1:])
        await self.store.remote_queues.close()
        await self.until(lambda: not self.sockets['two'])
        self.assertTrue(all(worker.done() for worker in self.store.remote_queues.workers.values()))
        self.assertTrue(self.store.remote_queues.manager.done())


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_continues_at_cap_and_uses_handshake_timeout_and_heartbeat(self):
        observer = n.RemoteQueues(client, lambda: [], lambda: None)
        url = 'http://remote.invalid'
        observer.states[url] = n.initial_state()
        delays = []
        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 9:
                raise asyncio.CancelledError
        with patch.object(n, 'connect', side_effect=OSError('offline')) as connect, patch.object(n.asyncio, 'sleep', sleep):
            with self.assertRaises(asyncio.CancelledError):
                await observer.watch(url)
        self.assertEqual(delays, [0, 1, 2, 5, 10, 30, 30, 30, 30])
        self.assertEqual(connect.call_count, 9)
        options = connect.call_args.kwargs
        self.assertEqual((options['open_timeout'], options['ping_interval'], options['ping_timeout']), (10, 20, 20))
        self.assertIsNone(observer.states[url]['running_count'])

    async def test_stable_connection_resets_retry_delay(self):
        observer = n.RemoteQueues(client, lambda: [], lambda: None)
        url = 'http://remote.invalid'
        observer.states[url] = n.initial_state()
        socket = AsyncMock()
        socket.recv.side_effect = OSError('lost after a minute')
        context = AsyncMock()
        context.__aenter__.return_value = socket
        delays = []
        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 2:
                raise asyncio.CancelledError
        with patch.object(n, 'connect', side_effect=[OSError('offline'), context]), \
                patch.object(observer, 'refresh', AsyncMock()), \
                patch.object(n, 'monotonic', side_effect=[0, 61]), \
                patch.object(n.asyncio, 'sleep', sleep):
            with self.assertRaises(asyncio.CancelledError):
                await observer.watch(url)
        self.assertEqual(delays, [0, 0])
