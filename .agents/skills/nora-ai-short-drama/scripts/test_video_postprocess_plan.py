"""Postprocess assembly tests: temporary project, real baseline export, no generation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import video_postprocess_plan as tool
from workflow_baselines import Canvas


class PostprocessPlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.composition = {'number': 2, 'script': {'file': 'script.md', 'version': 'v01'}, 'scenes': {}}
        sources = []
        self.selected = {}
        for scene, run in [('C001', 'R003'), ('C002', 'R002')]:
            part = 'EP001-' + scene + '-P001'
            identity = part + '-' + run + '-二采'
            self.selected[part] = identity
            source = 'adopted/' + identity + '.mp4'
            self.put(source, b'video')
            sources.append({'identity': identity, 'selected_path': source})
            self.composition['scenes'][scene] = {
                'storyboard': {'file': scene + '.md', 'version': 'v02'},
                'segments': [{'id': 'P001', 'stage': '后处理', 'run': 'R001', 'duration': 6}]}
        self.manifest = {'episode': 'EP001', 'rounds': [self.composition]}
        self.put(tool.episode_manifest_key('EP001'), self.manifest)
        self.report = {'state': 'completed', 'finalization': {'stage': '二采', 'sources': sources}}
        self.put('approved.json', self.report)
        self.request = {'episode': 'EP001', 'round': 2, 'profile': 'crop', 'orientation': 'landscape',
                        'authorization': '请做这些已批准片段的后处理', 'approval_reports': ['approved.json'],
                        'output_root': 'E:/output'}

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())

    def build(self, output='plan.json'):
        with patch.object(tool.video_approve, 'selected', side_effect=lambda root, part, stage: self.selected.get(part)):
            return tool.build(self.root, self.request, output)

    def test_source_identity_order_and_workflow_export(self):
        for profile in ('crop', 'upscale'):
            for orientation in ('landscape', 'portrait'):
                with self.subTest(profile=profile, orientation=orientation):
                    self.request.update(profile=profile, orientation=orientation)
                    self.build()
                    plan = json.loads((self.root / 'plan.json').read_text())
                    self.assertEqual(plan['business_scope']['expected_video_count'], 2)
                    self.assertEqual([t['mapping']['segments'][0]['source'] for t in plan['tasks']], list(self.selected.values()))
                    for task in plan['tasks']:
                        canvas_path = self.root / task['canvas']
                        api = Canvas(json.loads(canvas_path.read_text())).api(['16'])
                        size = (1920, 1080) if orientation == 'landscape' else (1080, 1920)
                        fields = ('width', 'height') if profile == 'crop' else ('resize_type.width', 'resize_type.height')
                        self.assertEqual(tuple(api['1']['inputs'][f] for f in fields), size)
                        if profile == 'crop':
                            self.assertEqual((api['1']['inputs']['x'], api['1']['inputs']['y']),
                                             (0, 4) if orientation == 'landscape' else (4, 0))
                        self.assertEqual(api['6']['inputs']['file'], task['references'][0]['placeholder'])
                        self.assertEqual(api['16']['inputs']['frame_rate'], ['12', 1])
                        self.assertEqual(api['12']['inputs']['target_fps'], 30)
                        self.assertIn('audio', api['16']['inputs'])
                        canvas_path.unlink()
                    (self.root / 'plan.json').unlink()

    def test_stale_approval_and_missing_media_do_not_write(self):
        original = copy.deepcopy(self.selected)
        self.selected['EP001-C001-P001'] = 'EP001-C001-P001-R004-二采'
        with self.assertRaisesRegex(ValueError, '缺少当前采用'):
            self.build()
        self.assertFalse((self.root / 'plan.json').exists())
        self.selected = original
        (self.root / self.report['finalization']['sources'][1]['selected_path']).unlink()
        with self.assertRaisesRegex(ValueError, '文件缺失'):
            self.build()
        self.assertFalse(list(self.root.rglob('内容画布.workflow.json')))

    def test_existing_canvas_prevents_partial_writes(self):
        collision = '09-剧集制作/EP001/其他资料/执行附件/EP001-C002-P001-R001-后处理/内容画布.workflow.json'
        self.put(collision, b'existing')
        with self.assertRaisesRegex(ValueError, '目标已存在'):
            self.build()
        self.assertEqual((self.root / collision).read_bytes(), b'existing')
        self.assertEqual(len(list(self.root.rglob('内容画布.workflow.json'))), 1)
        self.assertFalse((self.root / 'plan.json').exists())

    def test_unfinished_approval_is_rejected(self):
        self.report['state'] = 'needs_attention'
        self.put('approved.json', self.report)
        with self.assertRaisesRegex(ValueError, '尚未完成'):
            self.build()


if __name__ == '__main__':
    unittest.main()
