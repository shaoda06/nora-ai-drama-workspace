import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.parsers.project import build_data
from backend.services.projects import ProjectStore


class GenerationContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / '示例项目'
        self.episode = '09-剧集制作/EP001'
        self.write(self.episode + '/02-剧集剧本/EP001-本集剧本.md',
                   '## 1. 故事剧本正文\n### EP001-C001\n场次。\n')
        self.write(self.episode + '/03-分镜脚本/EP001-分镜索引.md',
                   '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                   '| EP001-C001 | EP001-C001-P001 | 11 |\n')
        self.write(self.episode + '/03-分镜脚本/EP001-C001-场次分镜.md',
                   self.storyboard('v99', '最新版不应出现'))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, key, text):
        path = self.project / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def storyboard(self, version, body):
        return f'- 文档版本：{version}\n## 1. 镜头正文\n### 分段 P001\n说明不展示。\n' \
            f'#### EP001-SH001\n**镜号**：EP001-SH001\n**时间**：00:00-00:03\n' \
            f'**景别**：{body}\n**时长**：3秒\n### 分段 P002\n#### EP001-SH002\n其他分段不展示。\n'

    def add_run(self, run, stage='一采', source=None):
        identity = 'EP001-C001-P001-' + run + '-' + stage
        root = self.episode + '/其他资料/执行附件/' + identity
        candidate = self.episode + '/其他资料/候选视频/' + identity + '.mp4'
        self.write(candidate, identity)
        if source:
            context = {'identity': identity, 'source': source}
        else:
            storyboard = self.episode + '/其他资料/历史版本/分镜-' + run + '.md'
            self.write(storyboard, self.storyboard('v' + run[1:], run + '当次原文'))
            self.write(root + '/模型提示词.txt', run + ' actual submitted prompt')
            self.write(root + '/中文提示词参考版.txt', run + ' 当次中文')
            for name in ('公共图.png', '首帧.png'):
                self.write(root + '/输入素材/' + name, run + name)
            context = {'identity': identity, 'storyboard': {'file': storyboard, 'version': 'v' + run[1:]},
                       'prompts': {'english': root + '/模型提示词.txt', 'chinese': root + '/中文提示词参考版.txt'},
                       'references': {'common': [{'file': root + '/输入素材/公共图.png', 'label': 'Picture 1'}],
                                      'segment': [{'file': root + '/输入素材/首帧.png', 'label': 'Picture 2'}]}}
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}, ensure_ascii=False))
        return context, root, candidate

    def videos(self):
        return build_data(self.project, web_episode_navigation=True)['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos']

    def test_all_four_surfaces_follow_exact_run_and_original_file_links(self):
        self.add_run('R001')
        self.add_run('R002')
        with patch.object(main, 'store', ProjectStore(self.project.parent)):
            with TestClient(main.app) as client:
                videos = client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']['C001'][0]['videos']
                for video in videos:
                    run = video['run']
                    context = video['context']
                    self.assertIn(run + '当次原文', context['scriptHtml'])
                    for excluded in ('最新版', '其他分段', '说明不展示', '镜号'):
                        self.assertNotIn(excluded, context['scriptHtml'])
                    self.assertEqual(context['prompts']['english'], run + ' actual submitted prompt')
                    self.assertEqual(context['prompts']['chinese'], run + ' 当次中文')
                    self.assertEqual(context['issues'], [])
                    self.assertLess(context['scriptHtml'].index('时间'), context['scriptHtml'].index('时长'))
                    self.assertLess(context['scriptHtml'].index('时长'), context['scriptHtml'].index('景别'))
                    self.assertEqual([(shot['id'], shot['duration']) for shot in context['shots']], [('EP001-SH001', 3)])
                    self.assertIn(run + '当次原文', context['shots'][0]['html'])
                    self.assertIn(run, client.get(context['scriptUrl']).text)
                    self.assertEqual(client.get(context['references']['common'][0]['url']).text, run + '公共图.png')
                    self.assertEqual(client.get(context['references']['segment'][0]['url']).text, run + '首帧.png')

    def test_shared_mapping_can_hold_different_segment_run_numbers(self):
        first, root, _ = self.add_run('R003')
        other, other_root, _ = self.add_run('R002', '二采')
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [first, other]}))
        (self.project / (other_root + '/输入映射.json')).unlink()
        self.assertEqual(self.videos()[0]['context']['prompts']['english'], 'R002 actual submitted prompt')
        self.assertEqual(self.videos()[1]['context']['prompts']['english'], 'R003 actual submitted prompt')

    def test_large_mapping_is_not_limited_to_the_text_preview_prefix(self):
        context, root, _ = self.add_run('R001')
        self.write(root + '/输入映射.json', json.dumps({'recorded_request': 'x' * (300 * 1024),
                                                     'generation_contexts': [context]}))
        self.assertEqual(self.videos()[0]['context']['prompts']['english'], 'R001 actual submitted prompt')

    def test_postprocess_inherits_recorded_source_not_newest_candidate(self):
        self.add_run('R001')
        self.add_run('R002')
        self.add_run('R003', '二采', source='EP001-C001-P001-R001-一采')
        self.add_run('R004', '后处理', source='EP001-C001-P001-R003-二采')
        context = self.videos()[-1]['context']
        self.assertIn('R001当次原文', context['scriptHtml'])
        self.assertEqual(context['prompts']['english'], 'R001 actual submitted prompt')
        self.assertEqual(context['source'], 'EP001-C001-P001-R003-二采')
        self.assertEqual(context['shots'], self.videos()[0]['context']['shots'])

    def test_second_pass_uses_its_own_snapshot_and_retains_source(self):
        self.add_run('R001')
        context, root, _ = self.add_run('R002', '二采')
        context['source'] = 'EP001-C001-P001-R001-一采'
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        result = self.videos()[-1]['context']
        self.assertEqual(result['prompts']['english'], 'R002 actual submitted prompt')
        self.assertIn('R002当次原文', result['scriptHtml'])
        self.assertEqual(result['source'], 'EP001-C001-P001-R001-一采')

    def test_adoption_keeps_generation_context_and_candidate_identity(self):
        self.add_run('R001')
        _, _, candidate = self.add_run('R002')
        before = self.videos()[1]['context']
        adopted = self.episode + '/其他资料/阶段采用视频/01-一采/C001-场次/EP001-C001-P001-R002-一采.mp4'
        (self.project / adopted).parent.mkdir(parents=True)
        (self.project / candidate).rename(self.project / adopted)
        self.write(self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md',
                   '## 1. 当前选定结果\n| 处理阶段 | 当前选定文件 | R编号 | 来源任务 | 人工批准依据 |\n'
                   '| --- | --- | --- | --- | --- |\n'
                   '| 一采 | [选定](../阶段采用视频/01-一采/C001-场次/EP001-C001-P001-R002-一采.mp4) | R002 | 当次任务 | 用户批准 |\n'
                   '## 2. 逐次执行与采用记录\n### R002\n- 处理阶段：一采\n- 用户决定：批准采用\n')
        current = self.videos()[1]
        self.assertTrue(current['approved'])
        self.assertEqual(current['candidateNumber'], 2)
        self.assertEqual(current['context'], before)

    def test_missing_or_mismatched_history_never_uses_current_sources(self):
        context, root, _ = self.add_run('R001')
        self.write(context['storyboard']['file'], self.storyboard('v99', '错误版本'))
        (self.project / (root + '/输入素材/首帧.png')).unlink()
        result = self.videos()[0]['context']
        self.assertEqual(result['scriptHtml'], '')
        self.assertEqual(result['shots'], [])
        self.assertTrue(result['references']['segment'][0]['missing'])
        self.assertIn('文件版本与记录不一致', ' '.join(result['issues']))
        (self.project / (root + '/输入映射.json')).unlink()
        result = self.videos()[0]['context']
        self.assertEqual(result['scriptHtml'], '')
        self.assertEqual(result['prompts']['english'], '')

    def test_shots_keep_historical_order_durations_and_scene_times(self):
        context, _, _ = self.add_run('R001')
        text = ('- 文档版本：v001\n## 1. 镜头正文\n### 分段 P001\n'
                '#### EP001-SH003\n**时间**：00:11-00:14\n**时长**：3秒\n**景别**：第一镜。\n'
                '#### EP001-SH004\n**时间**：00:14-00:17.5\n**时长**：3.5秒。\n**景别**：第二镜。\n'
                '### 分段 P002\n#### EP001-SH005\n**时长**：9秒\n下一段。\n')
        self.write(context['storyboard']['file'], text)
        result = self.videos()[0]['context']
        self.assertEqual([(shot['id'], shot['duration']) for shot in result['shots']],
                         [('EP001-SH003', 3), ('EP001-SH004', 3.5)])
        self.assertIn('00:11-00:14', result['shots'][0]['html'])
        self.assertIn('第一镜', result['shots'][0]['html'])
        self.assertNotIn('第二镜', result['shots'][0]['html'])
        self.assertNotIn('下一段', result['shots'][1]['html'])
        self.assertEqual(result['issues'], [])
        self.assertEqual((self.project / context['storyboard']['file']).read_text(encoding='utf-8'), text)

    def test_missing_or_invalid_shot_duration_is_not_invented(self):
        context, _, _ = self.add_run('R001')
        for value in ('', '**时长**：0秒', '**时长**：待定', '**时长**：-3秒'):
            with self.subTest(value=value):
                self.write(context['storyboard']['file'], self.storyboard('v001', '原文保持').replace('**时长**：3秒', value))
                result = self.videos()[0]['context']
                self.assertIsNone(result['shots'][0]['duration'])
                self.assertIn('原文保持', result['scriptHtml'])
                self.assertIn('无法跟视频对齐', ' '.join(result['issues']))

    def test_context_sources_cannot_escape_project_or_form_a_cycle(self):
        context, root, _ = self.add_run('R001')
        context['storyboard']['file'] = '../outside.md'
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        with self.assertRaisesRegex(ValueError, '越出项目'):
            self.videos()
        context = {'identity': context['identity'], 'source': context['identity']}
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        with self.assertRaisesRegex(ValueError, '来源循环'):
            self.videos()

    def test_archived_chinese_requires_same_submitted_english(self):
        context, root, _ = self.add_run('R001')
        archive = self.episode + '/其他资料/历史版本/提示词旧版.md'
        context['prompts']['chinese'] = archive
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        for english, expected in [('R001 actual submitted prompt', '对应翻译'), ('新版不同的英文', '')]:
            self.write(archive, '## 提交给模型的完整提示词\n```text\n' + english + '\n```\n'
                       '## 中文提示词参考版\n```text\n对应翻译\n```\n')
            self.assertEqual(self.videos()[0]['context']['prompts']['chinese'], expected)
        self.write(root + '/模型提示词.txt', 'R001 actual submitted prompt\r\n')
        self.write(archive, '## 提交给模型的完整提示词\n```text\nR001 actual submitted prompt\n```\n'
                   '## 中文提示词参考版\n```text\n对应翻译\n```\n')
        self.assertEqual(self.videos()[0]['context']['prompts']['chinese'], '对应翻译')
