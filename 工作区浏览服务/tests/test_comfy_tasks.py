"""Task lifecycle and trust boundaries; temporary projects and simulated remote media only."""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import socket as sockets
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from starlette.websockets import WebSocketDisconnect
import uvicorn
from backend import main
from backend.services import comfy_tasks as t


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'projects/测试项目'
        self.project.mkdir(parents=True)
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': ['http://comfy.invalid:8188']}))
        self.record = self.project / '执行附件/任务001'
        self.record.mkdir(parents=True)
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.data = t.TaskInput(project=str(self.project), title='测试图', task_type='image',
            url='http://comfy.invalid:8188', workflow={'1': {'class_type': 'SaveImage', 'inputs': {'seed': 9223372036854775807}}},
            record_dir=str(self.record), attempt_name='提交尝试.json', request_name='请求.json', response_name='提交响应.json',
            outputs=[dict(node_id='1', output_key='images', index=0, path=str(self.project / '候选/result.png'), response_name='取回响应.json')],
            thread_id='authorized-target', desktop=dict(node='node', server='server.mjs', pipe='private-pipe', caller_thread='real-caller'))

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    def seed(self, status='queued', notification='waiting'):
        self.store.rows['task'] = {'input': self.data, 'state': {
            'id': 'task', 'project': self.project.name, 'title': '测试图', 'task_type': 'image',
            'prompt_id': 'real-id', 'client_id': 'listener-id', 'status': status, 'notification': notification,
            'created_at': t.client.now(), 'collected': 0, 'expected': 1}}
        self.store.save('task')

    async def test_websocket_opens_before_post_and_same_client_id(self):
        order = []
        socket = AsyncMock()
        async def connected(url, **kwargs):
            order.append(('ws', url))
            return socket
        def submit(remote, args, workflow, client_id):
            order.append(('post', client_id))
            self.assertEqual(workflow['1']['inputs']['seed'], 9223372036854775807)
            return {'prompt_id': 'new-id', 'client_id': client_id, 'submission_state': 'accepted'}
        with patch.object(t, 'connect', connected), patch.object(t.client, 'submit', submit), patch.object(self.store, 'watch', AsyncMock()):
            result = await self.store.submit(self.data)
            self.assertIn('clientId=' + order[1][1], order[0][1])
            self.assertEqual(result['monitor'], 'browser')
            self.assertEqual(self.store.rows[result['monitor_id']]['state']['prompt_id'], 'new-id')

    async def test_post_timeout_is_recorded_and_never_retried_on_restart(self):
        with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), patch.object(t.client, 'submit', side_effect=t.client.ClientError('submission_unknown', 'timeout')) as post:
            with self.assertRaises(t.client.ClientError):
                await self.store.submit(self.data)
            await self.store.start()
            self.assertEqual(post.call_count, 1)
            self.assertEqual(next(iter(self.store.rows.values()))['state']['status'], 'submission_unknown')

    async def test_restart_recovers_existing_id_without_post(self):
        self.seed()
        with patch.object(self.store, 'watch', AsyncMock()) as watch, patch.object(t.client, 'submit') as post:
            await self.store.start()
            await asyncio.sleep(0)
            watch.assert_awaited_once_with('task')
            post.assert_not_called()

    async def test_restart_recovers_saved_submit_response_and_preserves_unknown_delivery(self):
        self.seed()
        self.store.save('task', prompt_id=None, status='submitting')
        (self.record / self.data.response_name).write_text(json.dumps({'prompt_id': 'recovered-id'}))
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'watch', AsyncMock()) as watch, patch.object(t.client, 'submit') as post:
            await self.store.start()
            await asyncio.sleep(0)
            self.assertEqual(self.store.rows['task']['state']['prompt_id'], 'recovered-id')
            watch.assert_awaited_once_with('task')
            post.assert_not_called()
        self.store.save('task', status='completed', notification='sending')
        with patch.object(self.store, 'notify', AsyncMock()) as notify:
            await self.store.start()
            self.assertEqual(self.store.rows['task']['state']['notification'], 'delivery_unknown')
            notify.assert_not_awaited()

    async def test_success_collects_exact_output_and_preserves_history(self):
        self.seed()
        identity = {'filename': 'real.png', 'subfolder': 'task', 'type': 'output'}
        result = {'state': 'success', 'history': {'status': {'completed': True}}, 'files': [
            {'node_id': '1', 'output_key': 'images', 'index': 0, 'file': identity}]}
        def download(remote, args):
            target = Path(args.output)
            target.parent.mkdir()
            target.write_bytes(b'media')
            return {'path': str(target), 'remote': identity, 'bytes': 5}
        with patch.object(t.client, 'status', return_value=result), patch.object(t.client, 'download', download):
            self.assertTrue(await self.store.reconcile('task'))
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
        self.assertEqual(json.loads((self.record / '执行结果.json').read_text('utf-8'))['data']['history'], result['history'])
        self.assertTrue((self.record / '取回响应.json').is_file())

    async def test_missing_output_is_not_reported_as_downloaded(self):
        self.seed()
        with patch.object(t.client, 'status', return_value={'state': 'success', 'history': {}, 'files': []}):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
        self.assertEqual(self.store.rows['task']['state']['collected'], 0)

    async def test_failed_task_is_not_downloaded(self):
        self.seed()
        with patch.object(t.client, 'status', return_value={'state': 'failed', 'history': {}, 'files': []}), patch.object(t.client, 'download') as download:
            await self.store.reconcile('task')
            download.assert_not_called()
        self.assertEqual(self.store.rows['task']['state']['status'], 'failed')

    async def test_duplicate_notification_and_unknown_delivery_do_not_resend(self):
        self.seed('completed')
        read = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[read, OSError('response lost')])) as bridge:
            await self.store.notify('task')
            await self.store.notify('task')
            self.assertEqual(bridge.await_count, 2)
        self.assertEqual(self.store.rows['task']['state']['notification'], 'delivery_unknown')

    async def test_busy_thread_waits_before_one_send(self):
        self.seed('completed')
        def read(status):
            return {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': status}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[read('active'), read('idle'), {'isError': False}])) as bridge, patch.object(t.asyncio, 'sleep', AsyncMock()):
            await self.store.notify('task')
            self.assertEqual([call.args[1] for call in bridge.await_args_list], ['read', 'read', 'send'])
        self.assertEqual(self.store.rows['task']['state']['notification'], 'sent')

    async def test_busy_thread_coalesces_segments_replacement_and_terminal_in_one_message(self):
        self.seed('running')
        reads = 0
        async def bridge(data, operation, prompt=''):
            nonlocal reads
            if operation == 'read':
                reads += 1
                if reads == 1:
                    self.store.queue_notice('task', 'segment:P002:1', 'segment', 'P002已取回')
                    self.store.queue_notice('task', 'replacement:P001:2', 'replacement', 'P001改写待核对')
                    self.store.save('task', status='completed')
                    self.store.queue_notice('task', 'terminal', 'terminal', '整轮结束')
                return {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'active' if reads == 1 else 'idle'}}})}]}
            for text in ('P001已取回', 'P002已取回', 'P001改写待核对', '整轮结束'):
                self.assertIn(text, prompt)
            return {'isError': False}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=bridge)) as call, patch.object(t.asyncio, 'sleep', AsyncMock()):
            self.store.queue_notice('task', 'segment:P001:1', 'segment', 'P001已取回')
            await self.store.notifiers['task']
            self.store.queue_notice('task', 'terminal', 'terminal', '整轮结束')
            self.assertEqual(sum(item.args[1] == 'send' for item in call.await_args_list), 1)
        self.assertTrue(all(item['delivery'] == 'sent' for item in self.store.rows['task']['state']['notices']))

    async def test_multiple_delivery_batches_and_uncertain_event_are_not_resent_after_restart(self):
        self.seed('running')
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[idle, OSError('lost reply'), idle, {}])) as call, patch.object(t.asyncio, 'sleep', AsyncMock()):
            self.store.queue_notice('task', 'segment:P001:1', 'segment', 'P001已取回')
            await self.store.notifiers['task']
            self.store.queue_notice('task', 'segment:P002:1', 'segment', 'P002已取回')
            await self.store.notifiers['task']
            self.assertEqual(sum(item.args[1] == 'send' for item in call.await_args_list), 2)
            self.assertNotIn('P001已取回', call.await_args_list[-1].args[2])
            self.assertEqual(self.store.public()['tasks'][0]['notification_unknown'], 1)
        self.store.save('task', status='completed')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'desktop_call', AsyncMock()) as call:
            await self.store.start()
            await asyncio.sleep(0)
            call.assert_not_awaited()

    async def test_progress_and_short_disconnect_do_not_enqueue_attention(self):
        self.seed('running')
        self.store.save('task', progress={'value': 1, 'max': 9}, connection='reconnecting')
        self.assertNotIn('notices', self.store.rows['task']['state'])

    async def test_paths_and_remote_endpoint_are_checked(self):
        self.data.outputs[0].path = str(self.root / 'escape.png')
        with self.assertRaises(ValueError):
            self.store.validate(self.data)
        self.data.outputs[0].path = str(self.project / 'ok.png')
        self.data.url = 'http://other.invalid'
        with self.assertRaises(ValueError):
            self.store.validate(self.data)

    async def test_public_snapshot_has_no_desktop_connection(self):
        self.seed()
        raw = json.dumps(self.store.public())
        self.assertNotIn('private-pipe', raw)
        self.assertNotIn('real-caller', raw)
        self.assertNotIn('server.mjs', raw)

    async def test_public_nodes_follow_config_order_and_task_remote(self):
        urls = ['http://comfy.invalid:8188', 'http://comfy.invalid:8189',
                'http://comfy.invalid:8190', 'http://comfy.invalid:8191']
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': urls}))
        second_project = self.root / 'projects/另一项目'
        second_project.mkdir()
        (second_project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': urls}))
        self.data.url = urls[1] + '/'
        self.seed()
        self.store.save('task', node='H3')
        snapshot = self.store.public()
        self.assertEqual(snapshot['remote_nodes'], [
            {'url': url, 'name': name} for url, name in zip(urls, ['默认节点', '备用1', '备用2', '备用3'])])
        self.assertEqual(snapshot['tasks'][0]['remote_url'], urls[1])
        self.assertEqual(snapshot['tasks'][0]['node'], 'H3')

    async def test_public_nodes_include_idle_legacy_config(self):
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-url': self.data.url + '/'}))
        self.assertEqual(self.store.public(), {'tasks': [], 'remote_nodes': [
            {'url': self.data.url, 'name': '默认节点'}]})

    async def test_foreign_events_are_ignored_and_terminal_event_wakes_once(self):
        self.seed()
        socket = AsyncMock()
        socket.recv.side_effect = [
            b'preview',
            json.dumps({'type': 'progress', 'data': {'prompt_id': 'other-user', 'value': 99, 'max': 100}}),
            json.dumps({'type': 'executing', 'data': {'prompt_id': 'real-id', 'node': '1'}}),
            json.dumps({'type': 'progress', 'data': {'prompt_id': 'real-id', 'value': 3, 'max': 20}}),
            json.dumps({'type': 'execution_success', 'data': {'prompt_id': 'real-id'}})]
        async def reconcile(key):
            if self.store.rows[key]['state'].get('progress'):
                self.assertEqual(self.store.rows[key]['state']['progress'], {'value': 3, 'max': 20})
                self.store.save(key, status='completed')
                return True
            return False
        with patch.object(self.store, 'reconcile', reconcile), patch.object(self.store, 'notify', AsyncMock()) as notify:
            await self.store.watch('task', socket)
            notify.assert_awaited_once_with('task')
            socket.close.assert_awaited_once()

    async def test_disconnect_reconciles_existing_id_without_post(self):
        self.seed()
        original, restored = AsyncMock(), AsyncMock()
        original.recv.side_effect = OSError('connection lost')
        async def reconcile(key):
            if self.store.rows[key]['state']['connection'] == 'connected' and original.close.await_count:
                self.store.save(key, status='completed')
                return True
            return False
        with patch.object(t, 'connect', AsyncMock(return_value=restored)), patch.object(t.asyncio, 'sleep', AsyncMock()), \
                patch.object(self.store, 'reconcile', reconcile), patch.object(self.store, 'notify', AsyncMock()), \
                patch.object(t.client, 'submit') as post:
            await self.store.watch('task', original)
            post.assert_not_called()
            original.close.assert_awaited_once()
            restored.close.assert_awaited_once()


    async def test_real_websocket_http_submit_history_and_download(self):
        remote = FastAPI()
        saved = {'socket': None, 'posts': 0, 'completed': False}
        @remote.websocket('/ws')
        async def ws(websocket: WebSocket):
            await websocket.accept()
            saved['socket'] = websocket
            saved['client_id'] = websocket.query_params['clientId']
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                return
        @remote.post('/prompt')
        async def prompt(request: Request):
            payload = await request.json()
            self.assertEqual(payload['client_id'], saved['client_id'])
            self.assertEqual(payload['prompt']['1']['inputs']['seed'], 9223372036854775807)
            saved['posts'] += 1
            async def finish():
                await asyncio.sleep(.1)
                saved['completed'] = True
                await saved['socket'].send_json({'type': 'execution_success', 'data': {'prompt_id': 'wire-id'}})
            asyncio.create_task(finish())
            return {'prompt_id': 'wire-id'}
        @remote.get('/queue')
        def queue():
            return {'queue_pending': [[0, 'wire-id']], 'queue_running': []}
        @remote.get('/history/wire-id')
        def history():
            return {'wire-id': {'status': {'completed': True, 'status_str': 'success'}, 'outputs': {
                '1': {'images': [{'filename': 'wire.png', 'subfolder': '', 'type': 'output'}]}}}} if saved['completed'] else {}
        @remote.get('/view')
        def view(filename: str):
            self.assertEqual(filename, 'wire.png')
            return Response(b'wire-media', media_type='image/png')
        listener = sockets.socket()
        listener.bind(('127.0.0.1', 0))
        url = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(remote, log_level='error', lifespan='off'))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            await asyncio.sleep(.01)
        self.data.url = url
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [url]}))
        try:
            with patch.object(self.store, 'notify', AsyncMock()) as notify:
                result = await self.store.submit(self.data)
                await asyncio.wait_for(self.store.workers[result['monitor_id']], 5)
                self.assertEqual(saved['posts'], 1)
                self.assertEqual(Path(self.data.outputs[0].path).read_bytes(), b'wire-media')
                self.assertEqual(self.store.rows[result['monitor_id']]['state']['status'], 'completed')
                notify.assert_awaited_once()
        finally:
            server.should_exit = True
            await serving
            listener.close()


class ApiBoundaryTests(unittest.TestCase):
    def test_browser_cannot_submit_even_from_loopback(self):
        with tempfile.TemporaryDirectory() as folder:
            store = t.TaskStore(Path(folder), Path(folder))
            main.app.state.comfy_tasks = store
            data = dict(project=folder, title='invalid', task_type='image', url='http://remote.invalid', workflow={},
                record_dir=folder, attempt_name='a', request_name='b', response_name='c', outputs=[], thread_id='t',
                desktop=dict(node='node', server='server', pipe='secret', caller_thread='t'))
            # No lifespan here: never touch the real runtime in this boundary test.
            main.app.state.comfy_tasks = store
            api = TestClient(main.app, client=('127.0.0.1', 1234))
            try:
                self.assertEqual(api.post('/api/internal/comfy/submit', json=data).status_code, 403)
                self.assertEqual(api.post('/api/internal/comfy/submit', json=data,
                    headers={'origin': 'http://localhost', 'x-nora-task-token': store.token}).status_code, 403)
                snapshot = api.get('/api/comfy/tasks').json()
                self.assertEqual(snapshot, {'tasks': [], 'remote_nodes': []})
                self.assertEqual(api.delete('/api/comfy/tasks').status_code, 405)
            finally:
                api.close()
                store.db.close()
