"""Recovery through real HTTP/WS transports and the unchanged Agent CLI, in isolation."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, WebSocket
from fastapi.responses import Response
from starlette.websockets import WebSocketDisconnect
import uvicorn

from backend import main
from backend.services import comfy_tasks as t, comfy_segments as s, task_notifications as notices
from tests import test_comfy_tasks as base


@asynccontextmanager
async def serving(app):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    url = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    running = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            await asyncio.sleep(.01)
        yield url
    finally:
        server.should_exit = True
        await running
        listener.close()


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.data.source_session_name = '隔离测试会话'
        self.api = FastAPI()
        self.api.state.comfy_tasks = self.store
        for route in main.app.routes:
            if getattr(route, 'path', '').startswith('/api/internal/comfy/'):
                self.api.add_api_route(route.path, route.endpoint, methods=route.methods)
        source = t.SKILL / 'scripts/browser_tasks.py'
        self.cli = self.root / '.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
        self.cli.parent.mkdir(parents=True)
        shutil.copyfile(source, self.cli)

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)

    def cli_config(self, url):
        path = self.root / '工作区浏览服务/runtime/task-service.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'url': url, 'token': self.store.token}), 'utf8')

    async def agent(self, *args):
        process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8', str(self.cli), *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, 'CODEX_THREAD_ID': self.data.thread_id})
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
        self.assertEqual(process.returncode, 0, stderr.decode('utf8'))
        return json.loads(stdout)

    def restart(self):
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.api.state.comfy_tasks = self.store

    def seven_segments(self):
        self.data.task_type = 'video-first-pass'
        self.data.outputs = []
        self.data.segment_plan = s.SegmentPlan(director_node='502', report_node='403',
            output_root='E:/Comfy/output', targets=[s.SegmentTarget(index=i,
                path=str(self.project / f'候选/agent-{i}.mp4'), response_name=f'receipt-{i}.json') for i in range(7)])
        self.data.workflow = {'502': {'class_type': 'MiniMaxH3Director', 'inputs': {
            'timeline_data': json.dumps({'output': {'exportMode': 'segments'}, 'segments': [{}] * 7,
                                        'runSelectEnabled': True, 'runSelection': list(range(7))})}},
            '403': {'class_type': 'ShowText', 'inputs': {'text': ['502', 5]}}}
        mapping = {'scene': 'EP001-C001', 'selected_indices': list(range(7)), 'segments': [
            {'segment': f'EP001-C001-P{i+1:03d}', 'round': 'R001',
             'local_execution_dir': f'09-剧集制作/EP001/其他资料/执行附件/EP001-C001-P{i+1:03d}-R001-一采'} for i in range(7)]}
        (self.record / '输入映射.json').write_text(json.dumps(mapping), 'utf8')
        base.TaskTests.seed(self, status='running', notification='sent')
        self.store.save('task', task_type=self.data.task_type, source_session_name=self.data.source_session_name,
            expected=7, segments={str(item['index']): {'identity': item['identity'], 'index': item['index'],
                'check': '未取回', 'error': None} for item in s.targets(self.data)})
        text = '\n'.join(f'Segment {i+1}/7: 一采 mp4 saved → E:\\Comfy\\output\\minimax_seg_export\\run001\\seg_{i:04d}_pre.mp4' for i in range(7))
        return {'state': 'success', 'history': {'outputs': {'403': {'text': [text]}}}, 'files': []}

    async def test_seven_segment_failure_restart_and_agent_retry_without_regeneration(self):
        result = self.seven_segments()
        remote = FastAPI()
        calls, fail = [0] * 7, {'enabled': True}
        @remote.get('/view')
        def view(filename: str):
            index = int(filename[4:8])
            calls[index] += 1
            return Response(status_code=503) if fail['enabled'] and index >= 3 else Response(f'segment-{index}'.encode())
        async with serving(remote) as remote_url, serving(self.api) as api_url:
            self.data.url = remote_url
            with patch.object(self.store, 'notify', AsyncMock()), patch.object(t.client, 'status', return_value=result), \
                    patch.object(t.client, 'submit') as submit:
                real_sleep = asyncio.sleep
                async def skip_retry_wait(seconds):
                    await real_sleep(0)
                with patch.object(t.asyncio, 'sleep', skip_retry_wait):
                    await self.store.reconcile('task')
                self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
                self.assertEqual(self.store.rows['task']['state']['collected'], 3)
                self.assertEqual(self.store.rows['task']['state']['collection_auto_retry'], 3)
                self.assertEqual(calls, [1, 1, 1, 4, 4, 4, 4])
                originals = [Path(item.path).stat().st_mtime_ns for item in self.data.segment_plan.targets[:3]]
                await self.store.close()
                self.restart()
                self.cli_config(api_url)
                self.assertEqual((await self.agent('status', '--task-id', 'task'))['collected'], 3)
                fail['enabled'] = False
                with patch.object(self.store, 'notify', AsyncMock()):
                    self.assertEqual((await self.agent('retry-collection', '--task-id', 'task'))['status'], 'collecting')
                    await asyncio.wait_for(self.store.workers['task'], 10)
                state = self.store.rows['task']['state']
                self.assertEqual((state['status'], state['collected'], state['prompt_id']), ('completed', 7, 'real-id'))
                self.assertEqual(calls, [1, 1, 1, 5, 5, 5, 5])
                self.assertEqual(originals, [Path(item.path).stat().st_mtime_ns for item in self.data.segment_plan.targets[:3]])
                for i, item in enumerate(self.data.segment_plan.targets):
                    self.assertEqual(Path(item.path).read_bytes(), f'segment-{i}'.encode())
                events = json.loads((self.record / '后台过程记录.json').read_text('utf8'))
                self.assertEqual(sum(item['stage'] == 'download' and item['result'] == 'failed' for item in events), 16)
                self.assertTrue(any(item['stage'] == 'collection_retry' for item in events))
                submit.assert_not_called()

    async def test_backend_restart_resumes_collecting_checkpoint(self):
        base.TaskTests.seed(self, status='collecting', notification='sent')
        self.store.save('task', source_session_name=self.data.source_session_name)
        result = {'state': 'success', 'history': {}, 'files': [
            {'node_id': '1', 'output_key': 'images', 'index': 0,
             'file': {'filename': 'result.png', 'subfolder': '', 'type': 'output'}}]}
        (self.record / self.data.history_name).write_text(json.dumps({'data': result}), 'utf8')
        remote = FastAPI()
        @remote.get('/view')
        def view():
            return Response(b'resumed-image')
        async with serving(remote) as url:
            self.data.url = url
            self.store.save('task')
            await self.store.close()
            self.restart()
            with patch.object(self.store, 'notify', AsyncMock()), patch.object(t.client, 'submit') as submit:
                await self.store.start()
                await asyncio.wait_for(self.store.workers['task'], 5)
                self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
                self.assertEqual(Path(self.data.outputs[0].path).read_bytes(), b'resumed-image')
                submit.assert_not_called()

    async def test_interrupted_http_download_keeps_no_partial_candidate_then_retries(self):
        base.TaskTests.seed(self, status='running', notification='sent')
        result = {'state': 'success', 'history': {}, 'files': [{'node_id': '1', 'output_key': 'images', 'index': 0,
            'file': {'filename': 'result.png', 'subfolder': '', 'type': 'output'}}]}
        calls = []
        async def interrupted(reader, writer):
            calls.append(await reader.readuntil(b'\r\n\r\n'))
            content = b'abc' if len(calls) == 1 else b'0123456789'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\n' + content)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(interrupted, '127.0.0.1', 0)
        self.data.url = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        (self.record / self.data.history_name).write_text(json.dumps({'data': result}), 'utf8')
        try:
            output = Path(self.data.outputs[0].path)
            async def waiting(seconds):
                self.assertAlmostEqual(seconds, 10, delta=.3)
                self.assertEqual(self.store.rows['task']['state']['status'], 'collecting')
                self.assertIn('content length mismatch', self.store.rows['task']['state']['error'])
                self.assertFalse(output.exists())
                self.assertFalse(list(output.parent.glob('.comfy-download-*')))
            with patch.object(self.store, 'notify', AsyncMock()), patch.object(t.client, 'submit') as submit, \
                    patch.object(t.asyncio, 'sleep', waiting):
                await self.store.finish_collection('task', result)
                self.assertEqual(output.read_bytes(), b'0123456789')
                self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
                self.assertEqual(self.store.rows['task']['state']['collection_auto_retry'], 1)
                self.assertEqual(len(calls), 2)
                submit.assert_not_called()
        finally:
            server.close()
            await server.wait_closed()

    async def reconnect_scenario(self, missing):
        base.TaskTests.seed(self, status='running', notification='sent')
        remote, connections = FastAPI(), []
        @remote.websocket('/ws')
        async def ws(websocket: WebSocket):
            await websocket.accept()
            connections.append(websocket.query_params['clientId'])
            if len(connections) == 1:
                await asyncio.sleep(.2)
                await websocket.close(code=1012)
            else:
                try:
                    await websocket.receive_text()
                except WebSocketDisconnect:
                    pass
        @remote.get('/queue')
        def queue():
            return {'queue_running': [[0, 'real-id']] if len(connections) < 2 else [], 'queue_pending': []}
        @remote.get('/history/real-id')
        def history():
            return {} if missing or len(connections) < 2 else {'real-id': {
                'status': {'completed': True, 'status_str': 'success'}, 'outputs': {
                    '1': {'images': [{'filename': 'result.png', 'subfolder': '', 'type': 'output'}]}}}}
        @remote.get('/view')
        def view():
            return Response(b'after-reconnect')
        async with serving(remote) as url:
            self.data.url = url
            with patch.object(self.store, 'notify', AsyncMock()), patch.object(t.client, 'submit') as submit:
                await asyncio.wait_for(self.store.watch('task'), 12)
                state = self.store.rows['task']['state']
                self.assertEqual(state['status'], 'needs_attention' if missing else 'completed')
                self.assertEqual(connections, ['listener-id', 'listener-id'])
                self.assertEqual(state['prompt_id'], 'real-id')
                events = json.loads((self.record / '后台过程记录.json').read_text('utf8'))
                self.assertTrue(any(event['stage'] == 'connection' and event['result'] == 'reconnecting' for event in events))
                submit.assert_not_called()
                if missing:
                    self.assertFalse(Path(self.data.outputs[0].path).exists())
                else:
                    self.assertEqual(Path(self.data.outputs[0].path).read_bytes(), b'after-reconnect')

    async def test_real_websocket_disconnect_reconciles_completed_original_id(self):
        await self.reconnect_scenario(False)

    async def test_real_websocket_disconnect_missing_task_never_resubmits(self):
        await self.reconnect_scenario(True)

    async def test_notification_outage_busy_merge_unknown_restart_and_agent_ack(self):
        base.TaskTests.seed(self, status='completed', notification='sent')
        self.store.rows['other'] = {'input': self.data.model_copy(deep=True), 'state': {
            **self.store.rows['task']['state'], 'id': 'other', 'title': '另一项', 'notices': []}}
        self.store.rows['other']['input'].record_dir = str(self.record.parent / '另一项')
        self.store.rows['other']['input'].title = '另一项'
        self.store.save('other')
        reads, sent, delays = [], [], []
        original_sleep = asyncio.sleep
        async def short_sleep(delay):
            delays.append(delay)
            await original_sleep(0)
        async def desktop(data, operation, prompt=''):
            if operation == 'send':
                sent.append(prompt)
                raise OSError('response lost after delivery')
            reads.append(operation)
            if len(reads) == 1:
                raise OSError('unavailable')
            status = 'inProgress' if len(reads) == 2 else 'idle'
            return {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': status}}})}]}
        async with serving(self.api) as api_url:
            with patch.object(notices.asyncio, 'sleep', short_sleep), patch.object(self.store, 'desktop_call', desktop):
                self.store.queue_notice('task', 'terminal', 'terminal', '完成')
                self.store.queue_notice('other', 'terminal', 'terminal', '完成')
                await asyncio.wait_for(asyncio.gather(self.store.notifiers['task'], self.store.notifiers['other']), 5)
            self.assertEqual(len(sent), 1)
            self.assertIn('本地任务ID：task', sent[0])
            self.assertIn('本地任务ID：other', sent[0])
            self.assertIn(30, delays)
            self.assertIn(15, delays)
            batch = self.store.db.execute('SELECT id FROM notification_batches').fetchone()[0]
            self.assertEqual(self.store.rows['task']['state']['notification'], 'delivery_unknown')
            await self.store.close()
            self.restart()
            self.cli_config(api_url)
            with patch.object(self.store, 'desktop_call', AsyncMock()) as resumed:
                await self.store.start()
                self.assertEqual((await self.agent('ack', '--notification-id', batch))['status'], 'acknowledged')
                self.assertEqual(self.store.rows['other']['state']['notification'], 'acknowledged')
                resumed.assert_not_called()
