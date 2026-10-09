"""H3 evidence binding, incremental publication, version recovery and terminal checks."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import unittest
import socket as sockets
from unittest.mock import AsyncMock, Mock, patch

import test_comfy_tasks as base
from backend.services import comfy_tasks as t
from backend.services import comfy_segments as s
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from starlette.websockets import WebSocketDisconnect
import uvicorn


class SegmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.data.task_type = 'video-first-pass'
        self.data.outputs = []
        self.data.segment_plan = s.SegmentPlan(director_node='502', report_node='403', output_root='E:/Comfy/output')
        self.data.workflow = {'502': {'class_type': 'MiniMaxH3Director', 'inputs': {'timeline_data': json.dumps({
            'output': {'exportMode': 'segments'}, 'segments': [{}, {}, {}], 'runSelectEnabled': True, 'runSelection': [0, 2]})}},
            '403': {'class_type': 'ShowText', 'inputs': {'text': ['502', 5]}}}
        self.mapping = {'scene': 'EP001-C001', 'selected_indices': [0, 2], 'segments': [
            {'segment': f'EP001-C001-P{i+1:03d}', 'round': 'R001',
             'local_execution_dir': f'09-剧集制作/EP001/其他资料/执行附件/EP001-C001-P{i+1:03d}-R001-一采'} for i in range(3)]}
        (self.record / '输入映射.json').write_text(json.dumps(self.mapping), 'utf8')
        base.TaskTests.seed(self, status='running')
        self.store.save('task', expected=2, node='502', segments={str(item['index']): {
            'identity': item['identity'], 'index': item['index'], 'check': '未取回', 'versions': [], 'error': None}
            for item in s.targets(self.data)}, segment_monitor={
                'started': True, 'cursor': '2026-10-09T01:00:00', 'run_dir': None, 'last_probe': 0, 'failures': 0})
        self.entries = []
        self.running = [[0, 'real-id']]
        def remote_json(route):
            if route == '/queue':
                return {'queue_running': self.running, 'queue_pending': []}
            if route == '/internal/logs/raw':
                return {'entries': self.entries, 'size': len(self.entries)}
            raise AssertionError(route)
        self.remote = Mock(json=Mock(side_effect=remote_json))
        self.remote_patch = patch.object(self.store, 'client_for', return_value=self.remote)
        self.remote_patch.start()
        self.media = b'first-version'
        self.downloads = []
        def download(remote, args):
            self.downloads.append((args.filename, args.subfolder))
            output = Path(args.output)
            if output.exists():
                raise AssertionError('Must preserve no-overwrite guard')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self.media)
            return {'path': str(output), 'bytes': len(self.media), 'sha256': hashlib.sha256(self.media).hexdigest(),
                    'remote': {'filename': args.filename, 'subfolder': args.subfolder, 'type': 'output'}}
        self.download_patch = patch.object(t.client, 'download', side_effect=download)
        self.download_patch.start()
        self.notify_patch = patch.object(self.store, 'notify', AsyncMock())
        self.notify_patch.start()

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)
        self.remote_patch.stop()
        self.download_patch.stop()
        self.notify_patch.stop()

    def log(self, second, message):
        self.entries.append({'t': f'2026-10-09T01:00:{second:02d}', 'm': message})

    def saved(self, second=2, index=0, run='run001', pre=True):
        self.log(second, f"MiniMax H3 Director segment #{index+1} {'first-pass ' if pre else ''}mp4 saved: E:\\Comfy\\output\\minimax_seg_export\\{run}\\seg_{index:04d}{'_pre' if pre else ''}.mp4")

    async def first(self):
        self.log(1, 'MiniMax H3 Director segment mp4 run dir: E:\\Comfy\\output\\minimax_seg_export\\run001')
        self.saved()
        await s.scan(self.store, 'task')

    def result(self, state='success', indices=(0, 2)):
        text = '\n'.join(f'Segment {index+1}/3: 一采 mp4 saved → E:\\Comfy\\output\\minimax_seg_export\\run001\\seg_{index:04d}_pre.mp4' for index in indices)
        return {'state': state, 'history': {'outputs': {'403': {'text': [text]}}}, 'files': []}

    async def test_native_plan_validates_real_indices_report_link_and_output_root(self):
        self.store.validate(self.data)
        self.assertEqual(s.remote_file('/Comfy/output', '/Comfy/output/minimax_seg_export/run/seg_0000.mp4'),
            {'filename': 'seg_0000.mp4', 'subfolder': 'minimax_seg_export/run', 'type': 'output'})
        self.data.workflow['403']['inputs']['text'] = ['502', 0]
        with self.assertRaises(ValueError):
            self.store.validate(self.data)
        for path in ('E:/Comfy/output/../secret.mp4', 'E:/other/minimax_seg_export/x/seg_0000.mp4',
                     'E:/Comfy/output/minimax_seg_cache/502/seg_0000.mp4'):
            with self.assertRaises(ValueError):
                s.remote_file('E:/Comfy/output', path)

    async def test_real_save_publishes_sparse_segment_once_and_keeps_evidence(self):
        await self.first()
        item = self.store.rows['task']['state']['segments']['0']
        self.assertEqual(Path(item['path']).read_bytes(), self.media)
        self.assertEqual(item['check'], '运行中已取回，待收尾核对')
        receipt = json.loads(Path(item['versions'][0]['receipt']).read_text('utf8'))
        self.assertEqual(receipt['prompt_id'], 'real-id')
        self.assertIn('mp4 saved:', receipt['source']['m'])
        await s.scan(self.store, 'task')
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(self.store.rows['task']['state']['collected'], 1)

    async def test_second_pass_ignores_first_pass_and_verifies_its_own_terminal_files(self):
        self.data.task_type = 'video-second-pass'
        for entry in self.mapping['segments']:
            entry['local_execution_dir'] = entry['local_execution_dir'].replace('一采', '二采')
        (self.record / '输入映射.json').write_text(json.dumps(self.mapping), 'utf8')
        self.store.save('task', segments={str(item['index']): {
            'identity': item['identity'], 'index': item['index'], 'check': '未取回', 'versions': [], 'error': None}
            for item in s.targets(self.data)})
        self.store.validate(self.data)
        await self.first()  # A first-pass save from this run is not a second-pass result.
        self.assertEqual(self.downloads, [])
        self.saved(second=3, index=0, pre=False)
        self.saved(second=4, index=2, pre=False)
        await s.scan(self.store, 'task')
        self.assertEqual([filename for filename, _ in self.downloads], ['seg_0000.mp4', 'seg_0002.mp4'])
        result = self.result()
        result['history']['outputs']['403']['text'][0] = result['history']['outputs']['403']['text'][0].replace('一采 mp4', 'mp4').replace('_pre.mp4', '.mp4')
        self.assertEqual(await s.finish(self.store, 'task', result), [])
        for item in self.store.rows['task']['state']['segments'].values():
            self.assertTrue(item['identity'].endswith('-二采'))
            self.assertEqual(item['check'], '已核对不变')
            self.assertEqual(len(item['versions']), 1)

    async def test_foreign_queue_and_missing_start_cannot_claim_output(self):
        self.running = [[0, 'other-id']]
        await self.first()
        self.assertEqual(self.downloads, [])
        self.running = [[0, 'real-id']]
        self.store.rows['task']['state']['segment_monitor']['started'] = False
        await s.scan(self.store, 'task')
        self.assertEqual(self.downloads, [])

    async def test_start_checkpoint_excludes_old_run_and_later_binds_only_new_run(self):
        self.log(1, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/old')
        self.log(2, '\x1b[32m[INFO]\x1b[0m Prompt executed in 00:12:10\n')
        runtime = self.store.rows['task']['state']['segment_monitor']
        runtime.update(started=False, run_dir=None)
        await s.scan(self.store, 'task', begin=True)
        self.log(3, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run001')
        self.saved(4, run='old')
        self.saved(5)
        self.saved(6, index=1)  # Unselected original index must never be compressed to P003.
        self.saved(7, index=2, pre=False)  # Wrong stage.
        await s.scan(self.store, 'task')
        self.assertEqual(self.downloads, [('seg_0000_pre.mp4', 'minimax_seg_export/run001')])

    async def test_buffered_run_and_save_are_collected_when_start_is_processed_late(self):
        runtime = self.store.rows['task']['state']['segment_monitor']
        runtime['started'] = False
        self.log(1, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run001')
        self.saved(2)
        await s.scan(self.store, 'task', begin=True)
        self.assertEqual(self.downloads, [('seg_0000_pre.mp4', 'minimax_seg_export/run001')])
        self.assertEqual(runtime['run_evidence']['t'], '2026-10-09T01:00:01')
        await s.scan(self.store, 'task', begin=True)
        self.assertEqual(len(self.downloads), 1)

    async def test_delayed_start_excludes_all_queued_predecessors_and_collects_current_run(self):
        runtime = self.store.rows['task']['state']['segment_monitor']
        runtime['started'] = False
        for second, run in ((1, 'foreign1'), (4, 'foreign2')):
            self.log(second, f'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/{run}')
            self.saved(second + 1, run=run)
            self.log(second + 2, '[INFO] Prompt executed in 12.34 seconds\n')
        self.log(7, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run001')
        self.saved(8)
        await s.scan(self.store, 'task', begin=True)
        self.assertEqual(self.downloads, [('seg_0000_pre.mp4', 'minimax_seg_export/run001')])

    async def test_missing_run_binding_recovers_retained_logs_after_restart(self):
        self.log(1, '[INFO] Prompt executed in 12.34 seconds\n')
        self.log(2, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run001')
        self.saved(3)
        self.store.rows['task']['state']['segment_monitor']['cursor'] = '2026-10-09T01:00:04'
        self.store.save('task')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'client_for', return_value=self.remote), patch.object(self.store, 'notify', AsyncMock()):
            await s.scan(self.store, 'task')
            await s.scan(self.store, 'task')
        self.assertEqual(self.downloads, [('seg_0000_pre.mp4', 'minimax_seg_export/run001')])

    async def test_queue_advancing_during_log_read_cannot_bind_or_download_next_job(self):
        self.log(1, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/foreign')
        self.saved(2, run='foreign')
        self.remote.json.side_effect = [
            {'queue_running': [[0, 'real-id']]}, {'entries': self.entries},
            {'queue_running': [[0, 'next-id']]}]
        await s.scan(self.store, 'task', begin=True)
        self.assertEqual(self.downloads, [])
        self.assertIsNone(self.store.rows['task']['state']['segment_monitor']['run_dir'])

    async def test_two_new_run_dirs_are_ambiguous_and_not_downloaded(self):
        for i in (1, 2):
            self.log(i, f'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run{i}')
        with self.assertRaises(ValueError):
            await s.scan(self.store, 'task')
        self.assertEqual(self.downloads, [])

    async def test_rewrite_stages_new_file_without_overwriting_old_or_reusing_approval(self):
        await self.first()
        candidate = Path(self.store.rows['task']['state']['segments']['0']['path'])
        original = candidate.read_bytes()
        self.media = b'rewritten-version'
        self.saved(4)
        await s.scan(self.store, 'task')
        item = self.store.rows['task']['state']['segments']['0']
        self.assertEqual(candidate.read_bytes(), original)
        self.assertEqual(Path(item['path']).read_bytes(), self.media)
        self.assertEqual(item['check'], '新文件已取回，待替换核对')
        self.assertEqual([notice['kind'] for notice in self.store.rows['task']['state']['notices']], ['segment', 'replacement'])

    async def test_terminal_verifies_identical_bytes_without_second_candidate_or_notice(self):
        await self.first()
        with patch.object(t.client, 'status', return_value=self.result()):
            await self.store.reconcile('task')
        state = self.store.rows['task']['state']
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['collected'], 2)
        self.assertEqual(len(state['segments']['0']['versions']), 1)
        self.assertEqual(state['segments']['0']['check'], '已核对不变')
        self.assertEqual(sum(n['kind'] == 'segment' for n in state['notices']), 2)

    async def test_terminal_missing_segment_never_becomes_full_success(self):
        with patch.object(t.client, 'status', return_value=self.result(indices=(0,))):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
        self.assertEqual(self.store.rows['task']['state']['segments']['2']['check'], '未取回')

    async def test_failure_preserves_already_collected_segments_and_original_id(self):
        await self.first()
        with patch.object(t.client, 'status', return_value={'state': 'failed', 'history': {}, 'files': []}), patch.object(t.client, 'submit') as post:
            await self.store.reconcile('task')
            post.assert_not_called()
        state = self.store.rows['task']['state']
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['segments']['0']['check'], '无法核对')
        self.assertTrue(Path(state['segments']['0']['path']).is_file())

    async def test_restart_resumes_save_cursor_and_does_not_download_twice(self):
        await self.first()
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'client_for', return_value=self.remote), patch.object(self.store, 'notify', AsyncMock()):
            await s.scan(self.store, 'task')
        self.assertEqual(len(self.downloads), 1)

    async def test_local_receipt_recovers_after_crash_between_publish_and_state_save(self):
        await self.first()
        item = self.store.rows['task']['state']['segments']['0']
        item.update(versions=[], downloaded_version=None, pending={'version': item['save_version'], 'number': 1})
        await s.retrieve(self.store, 'task', s.targets(self.data)[0], final=False)
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(len(item['versions']), 1)

    async def test_crash_after_link_before_unlink_recovers_without_overwrite(self):
        await self.first()
        item = self.store.rows['task']['state']['segments']['0']
        target = s.targets(self.data)[0]
        staged = target['record'] / 'seg_0000_pre.mp4'
        os.link(Path(item['path']), staged)
        item.update(versions=[], downloaded_version=None, pending={'version': item['save_version'], 'number': 1})
        await s.retrieve(self.store, 'task', target, final=False)
        self.assertFalse(staged.exists())
        self.assertEqual(len(self.downloads), 1)

    async def test_repeated_identical_save_then_changed_save_uses_fresh_receipt(self):
        await self.first()
        self.saved(4)
        await s.scan(self.store, 'task')
        self.media = b'new-after-identical-save'
        self.saved(5)
        await s.scan(self.store, 'task')
        item = self.store.rows['task']['state']['segments']['0']
        self.assertEqual(len(item['versions']), 2)
        self.assertTrue(item['versions'][-1]['receipt'].endswith('取回响应-003.json'))

    async def test_unavailable_logs_does_not_block_terminal_report_collection(self):
        self.store.rows['task']['state']['segment_monitor']['run_dir'] = 'E:/Comfy/output/minimax_seg_export/run001'
        self.remote.json.side_effect = OSError('logs unavailable')
        with patch.object(t.client, 'status', return_value=self.result()):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')

    async def test_failed_download_does_not_block_other_saved_segment_and_notifies_only_after_repeats(self):
        self.log(1, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run001')
        self.saved()
        self.saved(3, index=2)
        original_download = t.client.download.side_effect
        def download(remote, args):
            if args.filename == 'seg_0000_pre.mp4':
                raise OSError('network down')
            return original_download(remote, args)
        t.client.download.side_effect = download
        for _ in range(3):
            await s.scan(self.store, 'task')
        state = self.store.rows['task']['state']
        self.assertEqual(state['collected'], 1)
        self.assertTrue(Path(state['segments']['2']['path']).is_file())
        self.assertEqual(sum(n['kind'] == 'attention' for n in state['notices']), 1)

    async def test_progress_throttles_log_reads_and_public_snapshot_omits_receipts(self):
        await self.first()
        state = self.store.rows['task']['state']
        state['segment_monitor']['last_probe'] = __import__('time').monotonic()
        self.remote.json.reset_mock()
        await self.store.probe_segments('task')
        self.remote.json.assert_not_called()
        public = self.store.public()['tasks'][0]
        self.assertNotIn('segment_monitor', public)
        self.assertNotIn('notices', public)
        self.assertNotIn('versions', public['segments'][0])

    async def test_terminal_does_not_call_changed_local_file_unchanged(self):
        await self.first()
        item = self.store.rows['task']['state']['segments']['0']
        original = Path(item['path'])
        original.write_bytes(b'user-modified-file')
        with patch.object(t.client, 'status', return_value=self.result()):
            await self.store.reconcile('task')
        self.assertEqual(original.read_bytes(), b'user-modified-file')
        self.assertEqual(item['check'], '新文件已取回，待替换核对')
        self.assertEqual(self.store.rows['task']['state']['status'], 'needs_attention')

    async def test_failed_running_get_can_recover_from_terminal_report(self):
        original = t.client.download.side_effect
        t.client.download.side_effect = OSError('temporary download failure')
        await self.first()
        t.client.download.side_effect = original
        with patch.object(t.client, 'status', return_value=self.result()):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')

    async def test_native_wire_events_logs_incremental_download_and_terminal(self):
        self.remote_patch.stop()
        self.download_patch.stop()
        remote = FastAPI()
        saved = {'entries': [], 'posts': 0, 'completed': False, 'downloaded_while_running': False}
        checkpoint = asyncio.Event()
        first_target = s.targets(self.data)[0]['candidate']
        actual_probe = self.store.probe_segments
        async def probe(key, **kwargs):
            await actual_probe(key, **kwargs)
            if kwargs.get('begin'):
                checkpoint.set()
        @remote.websocket('/ws')
        async def ws(websocket: WebSocket):
            await websocket.accept()
            saved['socket'] = websocket
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                return
        @remote.get('/internal/logs/raw')
        def logs():
            return {'entries': saved['entries'], 'size': len(saved['entries'])}
        @remote.get('/queue')
        def queue():
            return {'queue_running': [] if saved['completed'] else [[0, 'wire-native']], 'queue_pending': []}
        @remote.get('/history/wire-native')
        def history():
            return {'wire-native': {'status': {'completed': True, 'status_str': 'success'},
                'outputs': self.result()['history']['outputs']}} if saved['completed'] else {}
        @remote.get('/view')
        def view(filename: str, subfolder: str, type: str):
            self.assertIn(filename, ('seg_0000_pre.mp4', 'seg_0002_pre.mp4'))
            self.assertEqual(subfolder, 'minimax_seg_export/run001')
            self.assertEqual(type, 'output')
            return Response(b'wire-native-media', media_type='video/mp4')
        @remote.post('/prompt')
        async def prompt(request: Request):
            payload = await request.json()
            self.assertIn('client_id', payload)
            saved['posts'] += 1
            # Both log lines arrive before the POST response and buffered start event.
            self.log(1, 'MiniMax H3 Director segment mp4 run dir: E:/Comfy/output/minimax_seg_export/run001')
            self.saved(2)
            saved['entries'] = self.entries.copy()
            await saved['socket'].send_json({'type': 'execution_start', 'data': {'prompt_id': 'wire-native'}})
            async def generate():
                await asyncio.wait_for(checkpoint.wait(), 3)
                await saved['socket'].send_json({'type': 'executing', 'data': {'prompt_id': 'wire-native', 'node': '502'}})
                for _ in range(100):
                    await saved['socket'].send_json({'type': 'minimax_director_progress', 'data': {
                        'node_id': '502', 'segment': 1, 'segment_total': 2, 'timeline_segment': 1,
                        'phase': 'sample', 'phase_label': '采样'}})
                    if first_target.exists():
                        saved['downloaded_while_running'] = not saved['completed']
                        break
                    await asyncio.sleep(.01)
                self.saved(3, index=2)
                saved['entries'] = self.entries.copy()
                saved['completed'] = True
                await saved['socket'].send_json({'type': 'execution_success', 'data': {'prompt_id': 'wire-native'}})
            saved['producer'] = asyncio.create_task(generate())
            return {'prompt_id': 'wire-native'}
        listener = sockets.socket()
        listener.bind(('127.0.0.1', 0))
        self.data.url = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [self.data.url]}))
        server = uvicorn.Server(uvicorn.Config(remote, log_level='error', lifespan='off'))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            await asyncio.sleep(.01)
        try:
            with patch.object(self.store, 'probe_segments', probe), patch.object(t, 'SEGMENT_CHECK_INTERVAL', .01):
                result = await self.store.submit(self.data)
                await asyncio.wait_for(self.store.workers[result['monitor_id']], 10)
            self.assertEqual(saved['posts'], 1)
            self.assertTrue(saved['downloaded_while_running'])
            self.assertEqual(first_target.read_bytes(), b'wire-native-media')
            state = self.store.rows[result['monitor_id']]['state']
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['collected'], 2)
        finally:
            if 'producer' in saved:
                await saved['producer']
            server.should_exit = True
            await serving
            listener.close()
