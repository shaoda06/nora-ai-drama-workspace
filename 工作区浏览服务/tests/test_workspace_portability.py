"""Relocate real task files and SQLite together, without an old-directory alias."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from backend.services import comfy_tasks as t
from backend.services.task_details import task_detail
from tests import test_comfy_tasks


class PortabilityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_comfy_tasks.TaskTests.asyncSetUp
    asyncTearDown = test_comfy_tasks.TaskTests.asyncTearDown
    seed = test_comfy_tasks.TaskTests.seed

    async def move_workspace(self):
        await self.store.close()
        target = self.root / 'another-device' / 'different workspace'
        target.mkdir(parents=True)
        shutil.move(str(self.root / 'projects'), target / 'projects')
        shutil.move(str(self.root / 'runtime'), target / 'runtime')
        self.store = t.TaskStore(target / 'runtime', target)
        return target

    async def test_relative_enqueue_persists_project_files_without_host_root(self):
        self.data.project = self.project.name
        self.data.record_dir = '执行附件/任务001'
        self.data.outputs[0].path = '候选/result.png'
        self.data.uploads = [{'file': 'reference.png', 'node': '1', 'input': 'seed',
                             'subfolder': '', 'response-name': '上传.json'}]
        self.data.start_paused = True
        with patch.object(self.store, 'read_session_name', return_value=None):
            result = await self.store.enqueue(self.data)
        payload = json.loads(self.store.db.execute('SELECT payload FROM tasks').fetchone()[0])
        self.assertEqual(payload['project'], self.project.name)
        self.assertEqual(payload['record_dir'], '执行附件/任务001')
        self.assertEqual(payload['uploads'][0]['file'], 'reference.png')
        self.assertEqual(payload['outputs'][0]['path'], '候选/result.png')
        target = await self.move_workspace()
        data = self.store.rows[result['local_task_id']]['input']
        self.assertEqual(Path(data.project), target / 'projects' / self.project.name)
        self.assertEqual(self.store.rows[result['local_task_id']]['state']['status'], 'paused')

    async def test_legacy_history_and_download_receipt_survive_move_without_redownload(self):
        self.seed('completed', 'acknowledged')
        output = Path(self.data.outputs[0].path)
        output.parent.mkdir()
        output.write_bytes(b'media')
        remote = {'filename': 'real.png', 'subfolder': '', 'type': 'output'}
        receipt = self.record / self.data.outputs[0].response_name
        receipt.write_text(json.dumps({'data': {'path': str(output), 'remote': remote, 'bytes': 5}}))
        original_receipt = receipt.read_bytes()
        self.store.record('task', 'download', 'success', path=str(output), receipt=str(receipt))
        self.store.save('task', saved_outputs=[str(output)], collected=1)
        # Simulate the pre-migration payload and event spelling, including Windows paths.
        legacy = self.data.model_dump()
        legacy['project'] = 'C:\\Old user\\Desktop\\workspace\\projects\\' + self.project.name
        legacy['record_dir'] = legacy['project'] + '\\执行附件\\任务001'
        legacy['outputs'][0]['path'] = legacy['project'] + '\\候选\\result.png'
        self.store.db.execute('UPDATE tasks SET payload=?', (json.dumps(legacy),))
        self.store.db.commit()
        target = await self.move_workspace()
        detail = await task_detail(self.store, 'task')
        self.assertEqual(detail['outputs'][0]['status'], 'saved')
        self.assertTrue(detail['outputs'][0]['available'])
        result = {'files': [{'node_id': '1', 'output_key': 'images', 'index': 0, 'file': remote}]}
        with patch.object(t.client, 'download') as download:
            self.assertEqual(await self.store.collect('task', result), [])
            download.assert_not_called()
        moved_receipt = target / 'projects' / self.project.name / '执行附件/任务001' / receipt.name
        self.assertEqual(moved_receipt.read_bytes(), original_receipt)
        self.assertFalse(self.project.exists())

    async def test_director_legacy_mapping_and_final_receipt_survive_move(self):
        self.data.task_type = 'video-first-pass'
        self.data.outputs = []
        self.data.workflow['1']['inputs']['timeline_data'] = json.dumps({'segments': [{}]})
        output = self.project / '候选/EP001-C001-P001-R001-一采.mp4'
        output.parent.mkdir()
        output.write_bytes(b'video')
        self.data.segment_plan = t.segments.SegmentPlan(director_node='1', report_node='2',
            output_root='/remote/output', targets=[dict(index=0, path=str(output), response_name='最终.json')])
        (self.record / '输入映射.json').write_text(json.dumps({'scene': 'EP001-C001', 'selected_indices': [0],
            'segments': [{'segment': 'EP001-C001-P001', 'round': 'R001', 'local_execution_dir': str(self.record)}]}))
        remote = {'filename': 'seg_0000_pre.mp4', 'subfolder': 'minimax_seg_export/job', 'type': 'output'}
        (self.record / '最终.json').write_text(json.dumps({'prompt_id': 'real-id',
            'data': {'path': str(output), 'remote': remote, 'bytes': 5}}))
        self.seed('completed', 'acknowledged')
        await self.move_workspace()
        result = {'history': {'outputs': {'2': {'text': [
            'Segment 1: 一采 mp4 saved → /remote/output/minimax_seg_export/job/seg_0000_pre.mp4']}}}}
        with patch.object(t.client, 'download') as download:
            self.assertEqual(await t.segments.finish(self.store, 'task', result), [])
            download.assert_not_called()
        self.assertEqual((await task_detail(self.store, 'task'))['outputs'][0]['status'], 'saved')

    async def test_new_input_cannot_rebind_another_root_or_escape_project(self):
        self.data.outputs[0].path = '../outside.png'
        with self.assertRaises(ValueError):
            self.store.resolve_input(self.data)
        self.data.outputs[0].path = 'C:/Old/projects/' + self.project.name + '/candidate.png'
        with self.assertRaises(ValueError):
            self.store.resolve_input(self.data)
        with self.assertRaises(ValueError):
            t.paths.project_file(self.project, 'C:/Old/projects/' + self.project.name + '/../../escape', recorded=True)

    async def test_repeated_project_prefix_rejected_before_registration(self):
        prefix = 'projects/' + self.project.name + '/'
        cases = ('record_dir', 'output', 'upload', 'segment')
        original = self.data.model_dump()
        for field in cases:
            with self.subTest(field=field):
                data = t.TaskInput.model_validate(original)
                if field == 'record_dir':
                    data.record_dir = prefix + '执行附件/任务001'
                elif field == 'output':
                    data.outputs[0].path = prefix + '候选/result.png'
                elif field == 'upload':
                    data.uploads = [{'file': prefix + 'ref.png'}]
                else:
                    data.segment_plan = t.segments.SegmentPlan(director_node='1', report_node='2',
                        output_root='/remote/output', targets=[dict(index=0, path=prefix + '候选/a.mp4', response_name='结果.json')])
                with patch.object(t.client, 'submit') as post, patch.object(t.client, 'upload') as upload:
                    with self.assertRaisesRegex(ValueError, '相对项目根目录'):
                        await self.store.enqueue(data)
                    post.assert_not_called()
                    upload.assert_not_called()
                self.assertFalse((self.project / 'projects').exists())
                self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)

    async def test_absolute_repeated_prefix_rejected_and_legacy_record_stays_readable(self):
        wrong = self.project / 'projects' / self.project.name / '执行附件/旧任务'
        with self.assertRaisesRegex(ValueError, '相对项目根目录'):
            t.paths.project_file(self.project, wrong)
        self.assertEqual(t.paths.project_file(self.project, wrong, recorded=True), wrong)
        self.data.record_dir = str(wrong)
        self.seed('cancelled', 'not_required')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(self.store.rows['task']['state']['status'], 'cancelled')
        self.assertEqual(Path(self.store.rows['task']['input'].record_dir), wrong)
