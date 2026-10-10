"""H3 evidence binding, completed-report output mapping and retry receipts."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import unittest
import socket as sockets
from unittest.mock import AsyncMock, Mock, patch

from tests import test_comfy_tasks as base
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
        self.data.segment_plan = s.SegmentPlan(director_node='502', report_node='403', output_root='E:/Comfy/output', targets=[
            s.SegmentTarget(index=i, path=str(self.project / '候选' / f'agent-{i}.mp4'), response_name=f'receipt-{i}.json') for i in (0, 2)])
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

    def result(self, state='success', indices=(0, 2)):
        text = '\n'.join(f'Segment {index+1}/3: 一采 mp4 saved → E:\\Comfy\\output\\minimax_seg_export\\run001\\seg_{index:04d}_pre.mp4' for index in indices)
        return {'state': state, 'history': {'outputs': {'403': {'text': [text]}}}, 'files': []}

    async def test_native_plan_validates_real_indices_report_link_and_output_root(self):
        self.store.validate(self.data)
        self.data.workflow['403']['inputs']['text'] = ['502', 0]
        with self.assertRaises(ValueError):
            self.store.validate(self.data)
        for path in ('E:/Comfy/output/../secret.mp4', 'E:/other/minimax_seg_export/x/seg_0000.mp4',
                     'E:/Comfy/output/minimax_seg_cache/502/seg_0000.mp4'):
            with self.assertRaises(ValueError):
                s.remote_file('E:/Comfy/output', path)

    async def test_completed_report_saves_agent_names_and_downloads_once(self):
        result = self.result()
        with patch.object(t.client, 'status', return_value=result):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
        self.assertEqual([item[0] for item in self.downloads], ['seg_0000_pre.mp4', 'seg_0002_pre.mp4'])
        self.assertTrue((self.project / '候选/agent-0.mp4').is_file())
        await s.finish(self.store, 'task', result)
        self.assertEqual(len(self.downloads), 2)
        self.remote.json.assert_not_called()

    async def test_running_events_never_download_segments(self):
        with patch.object(t.client, 'status', return_value={'state': 'running', 'history': None, 'queue': {}}):
            self.assertFalse(await self.store.reconcile('task'))
        self.assertEqual(self.downloads, [])
        self.remote.json.assert_not_called()

    async def test_missing_segment_is_collection_failure_and_keeps_other_output(self):
        with patch.object(t.client, 'status', return_value=self.result(indices=(0,))):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
        self.assertEqual(self.store.rows['task']['state']['collected'], 1)
        self.assertTrue((self.project / '候选/agent-0.mp4').is_file())

    async def test_remote_failure_does_not_retrieve_partial_report(self):
        with patch.object(t.client, 'status', return_value=self.result(state='failed')):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'failed')
        self.assertEqual(self.downloads, [])

    async def test_second_pass_uses_only_its_own_final_paths(self):
        self.data.task_type = 'video-second-pass'
        result = self.result()
        text = result['history']['outputs']['403']['text'][0]
        result['history']['outputs']['403']['text'][0] += '\n'+text.replace('一采 mp4','mp4').replace('_pre.mp4','.mp4')
        await s.finish(self.store, 'task', result)
        self.assertEqual([item[0] for item in self.downloads], ['seg_0000.mp4', 'seg_0002.mp4'])

    async def test_occupied_target_is_not_overwritten(self):
        target = self.project / '候选/agent-0.mp4'
        target.parent.mkdir()
        target.write_bytes(b'approved-old')
        self.download_patch.stop()
        with patch.object(t.client, 'download', side_effect=t.client.ClientError('file_exists', '已存在')):
            problems = await s.finish(self.store, 'task', self.result())
        self.assertEqual(target.read_bytes(), b'approved-old')
        self.assertTrue(problems)
        self.download_patch.start()

    async def test_new_tasks_require_explicit_destinations(self):
        self.data.segment_plan.targets = []
        self.store.rows.clear()
        with self.assertRaisesRegex(ValueError, '显式'):
            await self.store.enqueue(self.data)

    async def test_sparse_destination_map_must_match_selection(self):
        self.data.segment_plan.targets = self.data.segment_plan.targets[:1]
        with self.assertRaises(ValueError):
            self.store.validate(self.data)
