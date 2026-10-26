"""Temporary project compositions: one episode number, selective scenes and old evidence."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.parsers.scene_rounds import rounds
from episode_rounds import create_episode_round, episode_manifest_key
from tests import test_scene_rounds as fixture


class EpisodeRoundTests(unittest.TestCase):
    setUp = fixture.SceneRoundTests.setUp
    tearDown = fixture.SceneRoundTests.tearDown
    write = fixture.SceneRoundTests.write
    layout = fixture.SceneRoundTests.layout
    plan = fixture.SceneRoundTests.plan
    episode = fixture.SceneRoundTests.episode

    def two_scenes(self):
        self.write(self.script, '# 剧本\n- 文档版本：v1\n## 1. 故事剧本正文\n### EP001-C001\n一。\n### EP001-C002\n二。\n')
        board = self.board.replace('C001', 'C002')
        self.write(board, '# 分镜\n- 文档版本：v1\n## 1. 镜头正文\n### 分段 P001\n#### EP001-C002-SH001\n**时长**：3秒\n**台词**：原镜头\n')
        first = self.plan(replacements={'P001': 'R003', 'P003': 'R007'})
        second = {**self.plan(ids=['P001']), 'storyboard': {'file': board, 'version': 'v1'}}
        for scene, number, plan in [('C001', 5, first), ('C002', 7, second)]:
            self.write(rounds.manifest_key('EP001', scene), json.dumps({'episode': 'EP001', 'scene': scene,
                'rounds': [{**plan, 'number': number, 'created_at': '2026-10-25T00:00:00+08:00'}]}))
        self.write(self.root + '/03-分镜脚本/EP001-分镜索引.md',
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n' +
            ''.join(f'| EP001-C001 | EP001-C001-P{i:03d} | 3 |\n' for i in range(1, 4)) +
            '| EP001-C002 | EP001-C002-P001 | 3 |\n')
        return first, second

    def test_first_new_batch_continues_maximum_and_leaves_legacy_bytes(self):
        self.two_scenes()
        paths = [self.project / rounds.manifest_key('EP001', scene) for scene in ['C001', 'C002']]
        before = [path.read_bytes() for path in paths]
        saved = create_episode_round(self.project, 'EP001', {'scenes': {'C001': {
            'base_round': 5, 'segment_changes': [{'id': 'P002', 'duration': 3, 'stage': '一采', 'run': 'R004'}]}}})
        self.assertEqual(saved['number'], 8)
        self.assertEqual([path.read_bytes() for path in paths], before)
        for scene in ['C001', 'C002']:
            value = rounds.referenced_round(self.project, 'EP001-' + scene, 8)
            self.assertEqual(value['number'], 8)
        self.assertEqual([p['run'] for p in rounds.referenced_round(self.project, 'EP001-C001', 8)['segments']], ['R003', 'R004', 'R007'])
        self.assertEqual(rounds.referenced_round(self.project, 'EP001-C002', 8)['segments'][0]['run'], 'R001')
        episode = self.episode()
        self.assertEqual(episode['episodeRounds'], [{'number': 8, 'scenes': ['C001', 'C002']}])
        self.assertEqual([r['number'] for r in episode['sceneRounds']['C001']], [5, 8])
        self.assertEqual([r['number'] for r in episode['sceneRounds']['C002']], [7, 8])
        self.assertEqual(rounds.referenced_round(self.project, 'EP001-C001', 5)['segments'][0]['run'], 'R003')

    def test_two_scene_changes_are_one_round_and_later_partial_inherits_everything(self):
        first, second = self.two_scenes()
        first['segments'][0]['run'] = 'R010'
        second['segments'][0].update(stage='二采', run='R002')
        saved = create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': first, 'C002': second}})
        before = json.loads(Path(saved['file']).read_text())['rounds'][0]
        result = create_episode_round(self.project, 'EP001', {'base_round': 8, 'scenes': {'C001': {
            'segment_changes': [{'id': 'P002', 'duration': 3, 'stage': '一采', 'run': 'R005'}]}}})
        data = json.loads(Path(result['file']).read_text())
        self.assertEqual([r['number'] for r in data['rounds']], [8, 9])
        self.assertEqual(data['rounds'][0], before)
        self.assertEqual(data['rounds'][1]['scenes']['C002'], before['scenes']['C002'])
        self.assertEqual(data['rounds'][1]['script'], before['script'])
        self.assertEqual(data['rounds'][1]['changed_scenes'], ['C001'])

    def test_incomplete_initial_scene_plan_fails_without_writing_a_round(self):
        first, second = self.two_scenes()
        (self.project / rounds.manifest_key('EP001', 'C002')).unlink()
        with self.assertRaisesRegex(ValueError, '全部场次'):
            create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': first}})
        self.assertFalse((self.project / episode_manifest_key('EP001')).exists())
        self.assertFalse((self.project / episode_manifest_key('EP001')).with_suffix('.lock').exists())
        create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': first, 'C002': second}})

    def test_script_scene_changes_need_complete_new_scene_and_keep_old_history(self):
        first, second = self.two_scenes()
        create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': first}})
        script = self.project / self.script
        script.write_text(script.read_text().replace('v1', 'v2') + '### EP001-C003\n三。\n')
        plan = {'script': {'file': self.script, 'version': 'v2'}, 'base_round': 8, 'scenes': {'C001': {
            'segments': first['segments']}}}
        with self.assertRaisesRegex(ValueError, '全部场次'):
            create_episode_round(self.project, 'EP001', plan)
        board = self.board.replace('C001', 'C003')
        self.write(board, (self.project / self.board).read_text().replace('C001', 'C003'))
        plan['scenes']['C003'] = {'storyboard': {'file': board, 'version': 'v1'}, 'segments': second['segments']}
        self.assertEqual(create_episode_round(self.project, 'EP001', plan)['number'], 9)
        script.write_text(script.read_text().replace('v2', 'v3').replace('### EP001-C002\n二。\n', ''))
        plan = {'script': {'file': self.script, 'version': 'v3'}, 'scenes': {'C001': {'segments': first['segments']}}}
        saved = create_episode_round(self.project, 'EP001', plan)
        self.assertEqual(saved['number'], 10)
        self.assertEqual(saved['scenes'], ['C001', 'C003'])
        self.assertEqual(rounds.referenced_round(self.project, 'EP001-C002', 9)['number'], 9)

    def test_lock_prevents_concurrent_number_allocation(self):
        first, _ = self.two_scenes()
        path = self.project / episode_manifest_key('EP001')
        lock = path.with_suffix('.lock'); lock.touch()
        with self.assertRaises(FileExistsError):
            create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': first}})
        self.assertFalse(path.exists())
        lock.unlink()

    def test_later_bad_plan_keeps_record_and_snapshot_unchanged(self):
        first, _ = self.two_scenes()
        result = create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': first}})
        before = Path(result['file']).read_bytes()
        bad = deepcopy(first); bad['storyboard']['file'] = '../outside.md'
        with self.assertRaisesRegex(ValueError, '越出'):
            create_episode_round(self.project, 'EP001', {'script': first['script'], 'scenes': {'C001': bad}})
        self.assertEqual(Path(result['file']).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
