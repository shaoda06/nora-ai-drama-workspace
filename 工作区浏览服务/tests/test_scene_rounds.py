import json
from pathlib import Path
import tempfile
import unittest

from backend.parsers.project import build_data
from backend.parsers.scene_rounds import rounds
from backend.services.projects import ProjectStore
from tests.test_generation_context import writer


class SceneRoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / '示例项目'
        self.root = '09-剧集制作/EP001'
        self.script = self.root + '/02-剧集剧本/EP001-本集剧本.md'
        self.board = self.root + '/03-分镜脚本/EP001-C001-场次分镜.md'
        self.write(self.script, '# 剧本\n- 文档版本：v1\n## 1. 故事剧本正文\n### EP001-C001\n本场。\n')
        self.write('03-人物资料/说明.md', '原始资料。')
        self.layout(['P001', 'P002', 'P003'], 'v1')
        for segment in ['P001', 'P002', 'P003']:
            self.write(self.root + '/其他资料/工作稿/EP001-C001-' + segment + '-视频制作-工作稿.md',
                       '# 工作稿\n### R001-一采\n- 用户决定：旧审核原文保留\n')
            self.write(self.root + '/其他资料/候选视频/EP001-C001-' + segment + '-R001-一采.mp4', 'old video')

    def tearDown(self):
        self.temp.cleanup()

    def write(self, key, text):
        p = self.project / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def layout(self, ids, version):
        body = '# 分镜\n- 文档版本：' + version + '\n[人物](../../../03-人物资料/说明.md)\n## 1. 镜头正文\n'
        for i, segment in enumerate(ids):
            body += f'### 分段 {segment}\n#### EP001-C001-SH{i+1:03d}\n**时长**：3秒\n**台词**：{version}-{segment}\n'
        self.write(self.board, body)
        self.write(self.root + '/03-分镜脚本/EP001-分镜索引.md', '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n' + ''.join(f'| EP001-C001 | EP001-C001-{segment} | 3 |\n' for segment in ids))

    def plan(self, ids=('P001', 'P002', 'P003'), version='v1', replacements=None):
        return {'note': '集中修改', 'script': {'file': self.script, 'version': 'v1'},
                'storyboard': {'file': self.board, 'version': version},
                'segments': [{'id': segment, 'stage': '一采', 'run': (replacements or {}).get(segment, 'R001'), 'duration': 3} for segment in ids]}

    def create(self, plan=None):
        return rounds.create_round(self.project, 'EP001', 'C001', plan or self.plan())

    def episode(self):
        data = build_data(self.project, web_episode_navigation=True, load_scope='09-剧集制作', episode_id='EP001')
        return data['catalogues']['09-剧集制作']['children'][0]

    def test_compositions_keep_independent_runs_and_original_reviews(self):
        record = self.project / (self.root + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md')
        before = record.read_bytes()
        self.create()
        self.layout(['P001', 'P002', 'P003'], 'v2')
        self.create(self.plan(version='v2', replacements={'P002': 'R002'}))
        episode = self.episode()
        first, second = episode['sceneRounds']['C001']
        self.assertEqual([p['run'] for p in second['segments']], ['R001', 'R002', 'R001'])
        self.assertEqual(first['script']['key'], second['script']['key'], 'unchanged document copied again')
        self.assertNotEqual(first['storyboard']['key'], second['storyboard']['key'])
        self.assertIn('v1-P002', first['segments'][1]['scriptHtml'])
        self.assertIn('v2-P002', second['segments'][1]['scriptHtml'])
        pending = next(v for v in episode['segments']['C001'][1]['videos'] if v['run'] == 'R002')
        self.assertEqual(pending['url'], '')
        self.assertFalse(pending['approved'])
        self.assertEqual(before, record.read_bytes())
        self.assertEqual(first['issues'] + second['issues'], [])
        self.assertIn('03-', first['storyboard']['doc']['html'])
        self.assertNotIn('../../../03-', first['storyboard']['doc']['html'])

    def test_old_layout_retains_removed_segment_and_new_order(self):
        self.create()
        self.layout(['P004', 'P002'], 'v2')
        self.create(self.plan(ids=['P004', 'P002'], version='v2', replacements={'P004': 'R001', 'P002': 'R002'}))
        episode = self.episode()
        self.assertEqual([p['id'] for p in episode['sceneRounds']['C001'][1]['segments']], ['P004', 'P002'])
        old = next(p for p in episode['segments']['C001'] if p['id'] == 'P003')
        self.assertTrue(old['historical'])
        self.assertTrue(old['videos'][0]['url'])
        self.assertFalse(any(issue.get('scene') == 'C001' for issue in episode['productionIssues']))

    def test_pending_inputs_are_read_without_a_video(self):
        self.create(self.plan(replacements={'P002': 'R002'}))
        record = self.root + '/其他资料/执行附件/EP001-C001-P002-R002-一采'
        self.write(record + '/模型提示词.txt', 'Prepared exact prompt')
        self.write(record + '/输入映射.json', json.dumps({'generation_contexts': [{
            'identity': 'EP001-C001-P002-R002-一采',
            'storyboard': {'file': self.board, 'version': 'v1'},
            'prompts': {'english': record + '/模型提示词.txt'},
            'references': {'common': [], 'segment': []}}]}, ensure_ascii=False))
        video = next(v for v in self.episode()['segments']['C001'][1]['videos'] if v['run'] == 'R002')
        self.assertEqual(video['url'], '')
        self.assertEqual(video['context']['prompts']['english'], 'Prepared exact prompt')
        self.assertIn('v1-P002', video['context']['scriptHtml'])

    def test_missing_or_changed_snapshot_does_not_use_current_document(self):
        result = self.create()
        data = json.loads(Path(result['file']).read_text('utf-8'))
        (self.project / data['rounds'][0]['storyboard']['file']).unlink()
        round_item = self.episode()['sceneRounds']['C001'][0]
        self.assertIsNone(round_item['storyboard'])
        self.assertTrue(round_item['issues'])
        self.assertEqual(round_item['segments'][0]['scriptHtml'], '')

    def test_bad_plan_is_rejected_without_changing_history(self):
        result = self.create()
        before = Path(result['file']).read_bytes()
        plan = self.plan(); plan['segments'][1]['id'] = 'P001'
        with self.assertRaisesRegex(ValueError, '重复'):
            self.create(plan)
        plan = self.plan(); plan['script']['file'] = '../outside.md'
        with self.assertRaisesRegex(ValueError, '越出'):
            self.create(plan)
        self.assertEqual(before, Path(result['file']).read_bytes())

    def test_round_updates_invalidate_playback_cache(self):
        self.create()
        store = ProjectStore(self.project.parent)
        first = store.snapshot(self.project)
        self.create(self.plan(replacements={'P002': 'R002'}))
        self.assertNotEqual(first, store.snapshot(self.project))

    def test_opt_in_submission_identity_is_checked_without_requiring_legacy_field(self):
        self.create()
        directory = self.root + '/其他资料/执行附件/EP001-C001-P001-R001-一采'
        mapping = {'scene': 'EP001-C001', 'selected_indices': [0], 'scene_storyboard_version': 'v1',
                   'segments': [{'segment': 'EP001-C001-P001', 'round': 'R001', 'local_execution_dir': directory}]}
        workflow = {'1': {'class_type': 'MiniMaxH3Director', 'inputs': {'timeline_data': json.dumps({'segments': [{}]})}}}
        writer.validate_segment_context(self.project, workflow, 'video-first-pass', mapping)
        mapping['scene_modification_round'] = 1
        writer.validate_segment_context(self.project, workflow, 'video-first-pass', mapping)
        mapping['segments'][0].update(round='R002', local_execution_dir=directory.replace('R001', 'R002'))
        with self.assertRaisesRegex(ValueError, '分段身份'):
            writer.validate_segment_context(self.project, workflow, 'video-first-pass', mapping)

    def test_historical_compositions_use_explicit_order_not_run_numbers(self):
        old = self.plan(replacements={'P001': 'R009', 'P002': 'R003'})
        old.update(historical_at='2026-10-01T09:00:00+08:00', basis='preserved-input-mapping.json')
        self.create(old)
        self.layout(['P004', 'P002'], 'v2')
        new = self.plan(ids=['P004', 'P002'], version='v2', replacements={'P004': 'R001', 'P002': 'R004'})
        new.update(historical_at='2026-10-02T09:00:00+08:00', basis='later-input-mapping.json')
        self.create(new)
        entries = self.episode()['sceneRounds']['C001']
        self.assertEqual([x['number'] for x in entries], [1, 2])
        self.assertEqual(entries[0]['historical_at'], old['historical_at'])
        self.assertEqual(entries[0]['basis'], old['basis'])
        self.assertNotEqual(entries[0]['created_at'], old['historical_at'])
        self.assertEqual([x['run'] for x in entries[0]['segments']], ['R009', 'R003', 'R001'])
        self.assertEqual([x['id'] for x in entries[1]['segments']], ['P004', 'P002'])
        self.assertIn('v1-P001', entries[0]['segments'][0]['scriptHtml'])
        self.assertIn('v2-P004', entries[1]['segments'][0]['scriptHtml'])

    def test_second_pass_keeps_scene_sequence_and_independent_run(self):
        result = self.create(self.plan(replacements={'P001': 'R009'}))
        first = json.loads(Path(result['file']).read_text('utf-8'))['rounds'][0]
        record = self.project / (self.root + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md')
        before = record.read_bytes()
        plan = self.plan(replacements={'P001': 'R001'})
        plan['segments'][0]['stage'] = '二采'
        self.create(plan)
        entries = self.episode()['sceneRounds']['C001']
        self.assertEqual([x['number'] for x in entries], [1, 2])
        self.assertEqual([(s['stage'], s['run']) for s in entries[1]['segments']],
                         [('二采', 'R001'), ('一采', 'R001'), ('一采', 'R001')])
        self.assertEqual(first, json.loads(Path(result['file']).read_text('utf-8'))['rounds'][0])
        self.assertEqual(before, record.read_bytes())


if __name__ == '__main__':
    unittest.main()
