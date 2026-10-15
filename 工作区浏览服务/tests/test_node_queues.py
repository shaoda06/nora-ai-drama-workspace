"""Independent node queues, transfers and real mock HTTP/WS lifecycle."""
import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from backend import main
from backend.services import comfy_tasks as t
from tests import test_local_queue as local
from tests.test_queue_recovery import serving


class NodeQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await local.QueueTests.asyncSetUp(self)
        self.primary = self.data.url
        self.backup = 'http://backup.invalid:8188'
        self.configure()

    async def asyncTearDown(self):
        await local.QueueTests.asyncTearDown(self)

    def configure(self):
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [self.primary, self.backup]}))

    async def add(self, name, url=None):
        key = await local.QueueTests.add(self, name)
        if url:
            self.store.transfer(key, url)
        return key

    def node(self, url, running=0):
        self.store.remote_queues.states[url] = {'connection': 'connected', 'queue': [],
            'running_count': running, 'queued_count': 0, 'updated_at': t.client.now(), 'queue_error': None}

    async def test_transfer_moves_identity_outputs_and_position_to_target_tail(self):
        a, b, c = await self.add('a'), await self.add('b'), await self.add('c', self.backup)
        original = self.store.rows[a]['input'].model_copy(deep=True)
        self.store.task_action(a, 'immediate')
        self.store.transfer(a, self.backup + '/')
        self.assertEqual(self.store.ordered(self.primary), [b])
        self.assertEqual(self.store.ordered(self.backup), [c, a])
        self.assertFalse(self.store.rows[a]['state']['immediate'])
        self.assertEqual(self.store.rows[a]['input'].outputs, original.outputs)
        self.assertEqual((await self.store.enqueue(original))['local_task_id'], a)
        public = {item['id']: item for item in self.store.public()['local_tasks']}
        self.assertEqual([public[x]['queue_position'] for x in (b, c, a)], [1, 1, 2])
        self.assertEqual(public[a]['transfer_targets'], [{'url': self.primary, 'name': '默认节点'}])
        events = json.loads((Path(original.record_dir) / '后台过程记录.json').read_text('utf8'))
        self.assertEqual(events[-1]['target_url'], self.backup)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(self.store.ordered(self.backup), [c, a])
        self.assertEqual(self.store.rows[a]['input'].url, self.backup)

    async def test_paused_transfer_stays_paused_and_resume_goes_to_target_tail(self):
        a, b = await self.add('a'), await self.add('b', self.backup)
        self.store.task_action(a, 'pause')
        self.store.transfer(a, self.backup)
        self.assertEqual(self.store.rows[a]['state']['status'], 'paused')
        self.assertEqual(self.store.ordered(self.backup), [b])
        self.store.task_action(a, 'resume')
        self.assertEqual(self.store.ordered(self.backup), [b, a])
        self.store.task_action(a, 'insert')
        self.assertEqual(self.store.ordered(self.backup), [a, b])

    async def test_start_paused_prevents_idle_dispatch_until_transferred_and_resumed(self):
        self.data.start_paused = True
        original = self.data.model_copy(deep=True)
        result = await self.store.enqueue(self.data)
        key = result['local_task_id']
        self.assertEqual(result['status'], 'paused')
        self.node(self.primary)
        self.node(self.backup)
        with patch.object(self.store, 'prepare', AsyncMock(return_value=self.data.workflow)) as prepare, \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            prepare.assert_not_awaited()
            self.store.transfer(key, self.backup)
            await self.store.dispatch_once()
            submit.assert_not_awaited()
            self.assertEqual((await self.store.enqueue(original))['local_task_id'], key)
            self.store.task_action(key, 'resume')
            await self.store.dispatch_once()
            submit.assert_awaited_once()
            self.assertEqual(submit.await_args.args[0].url, self.backup)
            self.assertEqual(submit.await_args.kwargs['key'], key)

    async def test_start_paused_survives_restart(self):
        self.data.start_paused = True
        key = (await self.store.enqueue(self.data))['local_task_id']
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertTrue(self.store.rows[key]['input'].start_paused)
        self.assertEqual(self.store.ordered(self.primary), [])

    async def test_transfer_rejects_other_project_node_and_started_tasks(self):
        key = await self.add('a')
        other = self.root / 'projects/other'
        other.mkdir()
        (other / 'comfyui-config.json').write_text(json.dumps({'remote-urls': ['http://other.invalid']}))
        for url in (self.primary, 'http://other.invalid', 'http://arbitrary.invalid'):
            with self.assertRaises(ValueError):
                self.store.transfer(key, url)
        for status in ('preparing', 'submitting', 'running', 'completed', 'submission_unknown'):
            self.store.save(key, status=status)
            with self.assertRaises(ValueError):
                self.store.transfer(key, self.backup)
        self.store.save(key, status='paused', preparation_attempt=1)
        with self.assertRaises(ValueError):
            self.store.transfer(key, self.backup)
        self.assertFalse(next(x for x in self.store.public()['local_tasks'] if x['id'] == key)['can_transfer'])

    async def test_drag_and_reorder_only_lock_and_change_one_node(self):
        a, b, c = await self.add('a'), await self.add('b'), await self.add('c', self.backup)
        token = self.store.drag(url=self.primary)['token']
        self.assertTrue(self.store.active_drag(self.primary))
        self.assertFalse(self.store.active_drag(self.backup))
        self.store.reorder([b, a], token)
        self.assertEqual(self.store.ordered(self.backup), [c])
        with self.assertRaises(ValueError):
            self.store.reorder([b, a, c], token)
        with self.assertRaises(ValueError):
            self.store.transfer(c, self.primary)
        self.store.task_action(c, 'pause')
        self.store.drag(token, release=True)
        self.store.transfer(c, self.primary)

    async def test_busy_or_dragged_primary_does_not_block_backup(self):
        await self.add('a')
        b = await self.add('b', self.backup)
        self.node(self.primary, running=1)
        self.node(self.backup)
        with patch.object(self.store, 'prepare', AsyncMock(return_value=self.data.workflow)), \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            self.assertEqual(submit.await_args.kwargs['key'], b)
            submit.reset_mock()
            self.node(self.primary)
            self.store.drag(url=self.primary)
            await self.store.dispatch_once()
            self.assertEqual(submit.await_args.kwargs['key'], b)

    async def test_slow_primary_does_not_block_multiple_backup_submissions(self):
        a, b, c = await self.add('a'), await self.add('b', self.backup), await self.add('c', self.backup)
        self.node(self.primary)
        self.node(self.backup)
        held, entered, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        submitted = []
        async def prepare(key):
            self.store.save(key, status='preparing')
            if key == a:
                entered.set()
                await held.wait()
            return self.data.workflow
        async def submit(data, key, workflow):
            self.store.save(key, status='completed')
            submitted.append(key)
            if c in submitted:
                finished.set()
        with patch.object(self.store, 'prepare', prepare), patch.object(self.store, 'submit', submit), \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()):
            self.store.scheduler = asyncio.create_task(self.store.schedule())
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(finished.wait(), 2)
            self.assertEqual(submitted, [b, c])
            held.set()
            await self.store.close()
            self.store = t.TaskStore(self.root / 'runtime', self.root)

    async def test_same_node_concurrent_dispatch_does_not_duplicate(self):
        key = await self.add('a')
        self.node(self.primary)
        async def submit(data, key, workflow):
            await asyncio.sleep(.02)
            self.store.save(key, status='completed')
        with patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock(side_effect=submit)) as post:
            await asyncio.gather(self.store.dispatch_node(self.primary), self.store.dispatch_node(self.primary))
            post.assert_awaited_once()

    async def test_transferred_task_does_not_query_remote_capabilities(self):
        key = await self.add('direct-submit', self.backup)
        self.store.rows[key]['input'].workflow = {'1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'remote-model.safetensors'}}}
        self.node(self.backup)
        with patch.object(t.client.Client, 'json') as query, patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_node(self.backup)
            query.assert_not_called()
            submit.assert_awaited_once()

    async def test_target_second_pass_cache_is_checked_with_actual_workflow(self):
        workflow = json.loads((t.SKILL / 'references/comfyui-workflow/Minimax-H3-导演台-视频生成-标准版.api.json').read_text('utf8'))
        key = await self.add('second-pass', self.backup)
        self.store.rows[key]['input'].workflow = workflow
        self.store.rows[key]['input'].task_type = 'video-second-pass'
        self.node(self.backup)
        checked = []
        def query(remote, route, data=None, headers=None):
            self.assertEqual(remote.url, self.backup)
            self.assertEqual(route, '/minimax/director/first_pass_cache_status')
            payload = json.loads(data)
            self.assertEqual(payload['node_id'], '502')
            self.assertEqual(payload['seed'], workflow['502']['inputs']['seed'])
            self.assertTrue(payload['refine']['confirm_first_pass'])
            self.assertTrue(payload['refine']['has_sigmas_tensor'])
            checked.append(payload)
            return {'can_confirm_refine': bool(len(checked) > 1), 'diff_keys': ['<missing-cache>'] if len(checked) == 1 else []}
        with patch.object(t.client.Client, 'json', query), \
                patch('backend.services.director_uploads.save_uploaded_workflow'), \
                patch.object(self.store.generation_context, 'prepare_generation_context'), \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_node(self.backup)
            self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
            self.assertEqual(self.store.rows[key]['state']['failure_stage'], 'target_cache')
            submit.assert_not_awaited()
            self.store.task_action(key, 'resume')
            await self.store.dispatch_node(self.backup)
            submit.assert_awaited_once()
        events = json.loads((Path(self.store.rows[key]['input'].record_dir) / '后台过程记录.json').read_text('utf8'))
        self.assertEqual(len([event for event in events if event['stage'] == 'target_cache' and event['result'] == 'checked']), 2)

    async def test_transfer_http_boundary(self):
        key = await self.add('a')
        api = FastAPI()
        api.state.comfy_tasks = self.store
        api.add_api_route('/api/comfy/tasks/{key}/transfer', main.local_task_transfer, methods=['POST'])
        async with AsyncClient(transport=ASGITransport(app=api), base_url='http://127.0.0.1') as client:
            route = '/api/comfy/tasks/' + key + '/transfer'
            self.assertEqual((await client.post(route, json={'url': self.backup})).status_code, 403)
            headers = {'origin': 'http://127.0.0.1'}
            self.assertEqual((await client.post(route, json={'url': 'http://unknown.invalid'}, headers=headers)).status_code, 409)
            self.assertEqual((await client.post(route, json={'url': self.backup}, headers=headers)).status_code, 200)
            self.assertEqual((await client.post(route, json={'url': self.backup}, headers=headers)).status_code, 409)

    async def test_transferred_first_pass_checks_stage_and_unselected_previous_cache(self):
        workflow = json.loads((t.SKILL / 'references/comfyui-workflow/Minimax-H3-导演台-视频生成-标准版.api.json').read_text('utf8'))
        key = await self.add('partial-first', self.backup)
        self.store.rows[key]['input'].workflow = workflow
        self.store.rows[key]['input'].task_type = 'video-first-pass'
        timeline = json.loads(workflow['502']['inputs']['timeline_data'])
        timeline.update(runSelectEnabled=True, runSelection=[1])
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        self.node(self.backup)
        cache = {'can_confirm_refine': True, 'segments': []}
        def query(remote, route, *args):
            self.assertEqual(route, '/minimax/director/first_pass_cache_status')
            return cache
        with patch.object(t.client.Client, 'json', query), \
                patch('backend.services.director_uploads.save_uploaded_workflow'), \
                patch.object(self.store.generation_context, 'prepare_generation_context'), \
                patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_node(self.backup)
            self.assertIn('进入二采', self.store.rows[key]['state']['error'])
            submit.assert_not_awaited()
            cache['can_confirm_refine'] = False
            self.store.task_action(key, 'resume')
            await self.store.dispatch_node(self.backup)
            self.assertIn('前段衔接缓存', self.store.rows[key]['state']['error'])
            submit.assert_not_awaited()
            cache['segments'] = [{'index': 0, 'final_matches': True}]
            self.store.task_action(key, 'resume')
            await self.store.dispatch_node(self.backup)
            submit.assert_awaited_once()

    async def test_transferred_task_submits_and_collects_from_target_over_real_transport(self):
        state = {'posts': 0, 'done': False}
        primary, remote = FastAPI(), FastAPI()
        @primary.post('/prompt')
        def forbidden():
            self.fail('Transferred task submitted to primary')
        @remote.websocket('/ws')
        async def ws(socket: WebSocket):
            await socket.accept()
            state['socket'] = socket
            try:
                await socket.receive_text()
            except WebSocketDisconnect:
                return
        @remote.post('/prompt')
        async def prompt(request: Request):
            payload = await request.json()
            self.assertEqual(payload['prompt']['1']['inputs']['seed'], 'inputs/source.png')
            state['posts'] += 1
            async def finish():
                await asyncio.sleep(.05)
                state['done'] = True
                await state['socket'].send_json({'type': 'execution_success', 'data': {'prompt_id': 'backup-id'}})
            asyncio.create_task(finish())
            return {'prompt_id': 'backup-id'}
        @remote.post('/upload/image')
        async def upload(request: Request):
            self.assertIn(b'test-source-image', await request.body())
            state['uploads'] = state.get('uploads', 0) + 1
            return {'name': 'source.png', 'subfolder': 'inputs', 'type': 'input'}
        @remote.get('/queue')
        def queue():
            return {'queue_pending': [], 'queue_running': []}
        @remote.get('/history/backup-id')
        def history():
            return {'backup-id': {'status': {'completed': True, 'status_str': 'success'},
                'outputs': {'1': {'images': [{'filename': 'target.png', 'subfolder': '', 'type': 'output'}]}}}} if state['done'] else {}
        @remote.get('/view')
        def view():
            return Response(b'target-node-image', media_type='image/png')
        async with serving(primary) as self.primary, serving(remote) as self.backup:
            self.data.url = self.primary
            self.configure()
            source = self.project / 'source.png'
            source.write_bytes(b'test-source-image')
            self.data.uploads = [{'file': str(source), 'node': '1', 'input': 'seed',
                'subfolder': 'inputs', 'response-name': 'upload.json'}]
            key = await self.add('wire', self.backup)
            self.node(self.primary, running=1)
            self.node(self.backup)
            with patch.object(self.store, 'notify', AsyncMock()) as notice:
                await self.store.dispatch_once()
                await asyncio.wait_for(self.store.workers[key], 5)
                self.assertEqual(state['posts'], 1)
                self.assertEqual(state['uploads'], 1)
                self.assertEqual(self.store.rows[key]['state']['prompt_id'], 'backup-id')
                self.assertEqual(self.store.rows[key]['state']['status'], 'completed')
                self.assertEqual(Path(self.store.rows[key]['input'].outputs[0].path).read_bytes(), b'target-node-image')
                notice.assert_awaited_once_with(key)
