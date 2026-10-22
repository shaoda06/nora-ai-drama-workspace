"""Playback plans and longer generation requests retain separate timing identities."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from generation_context import validate_segment_context


class DurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        manifest = self.project / '09-剧集制作/片尾/其他资料/工作稿/片尾-C001-场次修改轮次.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'episode': '片尾', 'scene': 'C001', 'rounds': [{
            'number': 1, 'script': {'file': 'script.md', 'version': 'v01'},
            'storyboard': {'file': 'board.md', 'version': 'v01'},
            'segments': [{'id': 'P001', 'duration': 3, 'stage': '一采', 'run': 'R001'}]}]}))
        self.mapping = {'scene': '片尾-C001', 'scene_modification_round': 1,
            'screenplay_version': 'v01', 'scene_storyboard_version': 'v01',
            'selected_indices': [0], 'segments': [{'segment': '片尾-C001-P001', 'round': 'R001',
                'duration_seconds': 4, 'playback_duration_seconds': 3,
                'local_execution_dir': '09-剧集制作/片尾/其他资料/执行附件/片尾-C001-P001-R001-一采'}]}

    def validate(self, seconds=4, mapping=None):
        workflow = {'502': {'class_type': 'MiniMaxH3Director', 'inputs': {
            'timeline_data': json.dumps({'segments': [{'durationSec': seconds}]})}}}
        return validate_segment_context(self.project, workflow, 'video-first-pass', mapping or self.mapping)

    def test_four_second_request_preserves_three_second_scene_plan(self):
        result = self.validate()
        self.assertEqual(result['timeline']['segments'][0]['durationSec'], 4)

    def test_existing_equal_duration_request_needs_no_new_field(self):
        del self.mapping['segments'][0]['playback_duration_seconds']
        self.mapping['segments'][0]['duration_seconds'] = 3
        self.validate(3)

    def test_longer_request_requires_explicit_playback_duration(self):
        del self.mapping['segments'][0]['playback_duration_seconds']
        with self.assertRaisesRegex(ValueError, '计划时长与场次修改轮次不一致'):
            self.validate()

    def test_wrong_playback_or_short_request_is_rejected(self):
        wrong = deepcopy(self.mapping)
        wrong['segments'][0]['playback_duration_seconds'] = 2
        with self.assertRaisesRegex(ValueError, '计划时长与场次修改轮次不一致'):
            self.validate(mapping=wrong)
        self.mapping['segments'][0]['duration_seconds'] = 2
        with self.assertRaisesRegex(ValueError, '生成请求时长不能短于成片计划时长'):
            self.validate(2)

    def test_actual_model_request_must_match_recorded_generation_duration(self):
        with self.assertRaisesRegex(ValueError, '实际执行选中段计划时长'):
            self.validate(5)


if __name__ == '__main__':
    unittest.main()
