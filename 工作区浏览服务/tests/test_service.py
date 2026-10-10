import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.parsers import project as parser
from backend.services.projects import ProjectStore


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        (self.project / '00-项目定位').mkdir(parents=True)
        self.source = self.project / '00-项目定位/项目基本定位.md'
        self.source.write_text('# 项目定位\n\n## 内容\n第一版。\n', encoding='utf-8')
        self.store = ProjectStore(self.root)
        self.override = patch.object(main, 'store', self.store)
        self.override.start()
        self.client = TestClient(main.app, base_url='http://localhost:8780')

    def tearDown(self):
        self.client.close()
        self.override.stop()
        self.temp.cleanup()

    def test_formal_image_count_requires_approval_and_existing_media(self):
        data = {}
        for group in ('people', 'props', 'scenes'):
            prefix = {'people': 'people', 'props': 'prop', 'scenes': 'scene'}[group]
            data[prefix + 'Index'] = group + '.md'
            data[prefix + 'Groups'] = []
            data[group] = [{'id': '001', 'name': '测试', 'role': '资产', 'cover': None,
                            'pendingCount': 0, 'voice': None, 'card': {'confirmationHtml': '已确认'},
                            'formal': [{'media': {'key': 'approved.png'}, 'approved': True},
                                       {'media': {'key': 'rejected.png'}, 'approved': False},
                                       {'media': None, 'approved': True}],
                            'auxiliary': [{'media': {'key': 'aux.png'}, 'approved': True}],
                            'candidates': []}]
        with patch.object(main, 'entry', return_value={'data': data}):
            for section in ('03-人物资料', '04-场景资料', '05-道具资料'):
                with self.subTest(section=section):
                    response = self.client.get('/api/projects/示例项目/sections/' + section)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['items'][0]['formalCount'], 2)

    def test_people_voice_uses_card_voice_field_and_existing_formal_audio(self):
        people = self.project / '03-人物资料'
        people.mkdir()
        rows = []
        for number, voice in [('CH001', '[音色](../../07-参考音频/正式素材/RA001-音色.wav)'),
                              ('CH002', '[音色](../../07-参考音频/正式素材/不存在.wav)'),
                              ('CH003', '待确认')]:
            folder = people / (number + '-人物')
            folder.mkdir()
            (folder / (number + '-人物资料卡.md')).write_text(
                '# 人物资料卡\n\n## 5. 语言与声音特征\n'
                '- 说话声音参考音频（可选）：' + voice + '\n'
                '## 9. 其他备注\n[历史音频](../../07-参考音频/正式素材/RA001-音色.wav)\n', encoding='utf-8')
            rows.append(f'| {number} | 人物 | 配角 | [资料卡]({number}-人物/{number}-人物资料卡.md) |')
        (people / '人物索引.md').write_text(
            '| 人物编号 | 姓名 | 人物定位 | 资料卡入口 |\n| --- | --- | --- | --- |\n' + '\n'.join(rows), encoding='utf-8')
        audio = self.project / '07-参考音频/正式素材/RA001-音色.wav'
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b'audio fixture')
        items = self.client.get('/api/projects/示例项目/sections/03-人物资料').json()['items']
        self.assertEqual(items[0]['voice']['kind'], 'audio')
        self.assertTrue(items[0]['voice']['url'].startswith('/api/projects/'))
        self.assertEqual(items[0]['voice']['key'], '07-参考音频/正式素材/RA001-音色.wav')
        self.assertIsNone(items[1]['voice'])
        self.assertIsNone(items[2]['voice'])

    def test_production_titles_from_current_outline_and_existing_directories(self):
        outlines = self.project / '06-分集大纲'
        outlines.mkdir()
        for number, text in (('EP001', '本集题名：先撑过今晚。来源范围：旧场次。'),
                             ('EP002', '- 本集题名：婶子也不能白拿。'),
                             ('EP003', '- 一句话概要：没有题名。'),
                             ('EP004', '本集题名：仅有大纲，没有制作目录。')):
            (outlines / (number + '-分集大纲.md')).write_text('# 分集大纲\n\n' + text + '\n', encoding='utf-8')
        (outlines / '分集索引.md').write_text(
            '| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n'
            '| EP004 | 四 | [大纲](EP004-分集大纲.md) |\n', encoding='utf-8')
        for number in ('EP001', 'EP002', 'EP003', 'EP005'):
            folder = self.project / '09-剧集制作' / number / '02-剧集剧本'
            folder.mkdir(parents=True)
            (folder / (number + '-本集剧本.md')).write_text('# 本集剧本\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertEqual([(item['name'], item['title']) for item in data['children']],
                         [('EP001', '先撑过今晚'), ('EP002', '婶子也不能白拿'), ('EP003', ''),
                          ('EP004', '仅有大纲，没有制作目录'), ('EP005', '')])
        self.assertIn('EP001-本集剧本.md', str(data['children'][0]['children']))
        self.assertIn('未开始', data['children'][3]['statusHtml'])
        self.assertEqual(data['children'][3]['children'], [])
        self.assertFalse((self.project / '09-剧集制作/EP004').exists())

    def test_production_statistics_count_episodes_not_preparation_states(self):
        outlines = self.project / '06-分集大纲'
        outlines.mkdir()
        (outlines / '分集索引.md').write_text(
            '# 分集索引\n\n| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n'
            '| EP001 | 一 | [大纲](EP001-分集大纲.md) |\n'
            '| EP002 | 二 | [大纲](EP002-分集大纲.md) |\n'
            '| EP002 | 重复条目 | [大纲](EP002-分集大纲.md) |\n'
            '| EP003 | 三 | [大纲](EP003-分集大纲.md) |\n', encoding='utf-8')
        for number in ('EP001', 'EP002', 'EP004'):
            (self.project / '09-剧集制作' / number).mkdir(parents=True)
        (self.project / '项目进度.md').write_text(
            '# 项目进度\n\n| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n'
            '| --- | --- | --- | --- | --- | --- |\n'
            '| EP001 制作 | 无 | 已完成 | 无 | 无 | 无 |\n'
            '| EP002 制作 | 无 | 进行中 | 无 | 无 | 无 |\n'
            '| EP003 剧本 | 无 | 已完成 | 无 | 无 | 无 |\n'
            '| EP004 分镜 | 无 | 已完成 | 无 | 无 | 无 |\n'
            '| EP004 制作 | 无 | 已确认 | 无 | 无 | 无 |\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertEqual(data['statistics'], {'total': 4, 'completed': 1, 'notStarted': 1, 'running': 2})
        self.assertEqual([item['name'] for item in data['children']], ['EP001', 'EP002', 'EP003', 'EP004'])
        self.assertIn('未开始', data['children'][2]['statusHtml'])
        self.assertIn('进行中', data['children'][3]['statusHtml'])
        self.assertNotIn('已完成', data['children'][3]['statusHtml'])

    def test_episode_review_is_running_and_explicit_unstarted_is_kept(self):
        production = self.project / '09-剧集制作'
        for number in ('EP001', 'EP002', 'EP003'):
            (production / number).mkdir(parents=True)
        progress = self.project / '项目进度.md'
        progress.write_text(
            '| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n'
            '| --- | --- | --- | --- | --- | --- |\n'
            '| EP001 制作 | 无 | 待确认 | 无 | 审阅视频 | 无 |\n'
            '| EP002 制作 | 无 | 未开始 | 无 | 无 | 无 |\n', encoding='utf-8')
        source = progress.read_bytes()
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertEqual(data['statistics'], {'total': 3, 'completed': 0, 'notStarted': 1, 'running': 2})
        self.assertIn('进行中', data['children'][0]['statusHtml'])
        self.assertNotIn('待确认', data['children'][0]['statusHtml'])
        self.assertIn('未开始', data['children'][1]['statusHtml'])
        self.assertIn('进行中', data['children'][2]['statusHtml'])
        self.assertEqual(progress.read_bytes(), source)

    def test_episode_scenes_follow_current_story_body_only(self):
        story_folder = self.project / '01-主旨与简介'
        story_folder.mkdir()
        (story_folder / '主旨与简介.md').write_text(
            '# 主旨与简介\n\n## 1. 主旨\n主旨正文保留。\n', encoding='utf-8')
        folder = self.project / '09-剧集制作/EP001/02-剧集剧本'
        folder.mkdir(parents=True)
        script = folder / 'EP001-本集剧本.md'
        script.write_text('# 本集剧本\n\n## 1. 故事剧本正文\n'
                          '### EP001-C002\n剧情。\n### EP001-C001\n剧情。\n'
                          '### EP001-C002\n重复标题。\n### EP002-C003\n其他集。\n'
                          '## 2. 其他备注\n### EP001-C004\n不属于正文。\n', encoding='utf-8')
        source = script.read_bytes()
        history = self.project / '09-剧集制作/EP001/其他资料/历史版本'
        history.mkdir(parents=True)
        (history / 'EP001-本集剧本-旧版.md').write_text(
            '## 1. 故事剧本正文\n### EP001-C009\n', encoding='utf-8')
        outlines = self.project / '06-分集大纲'
        outlines.mkdir()
        (outlines / '分集索引.md').write_text(
            '| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n'
            '| EP002 | 二 | [大纲](EP002-分集大纲.md) |\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertEqual(data['children'][0]['scenes'], ['C002', 'C001'])
        self.assertEqual(data['children'][1]['scenes'], [])
        story = self.client.get('/api/projects/示例项目/sections/01-主旨与简介')
        self.assertEqual(story.status_code, 200)
        self.assertIn('主旨正文保留。', story.json()['bodyHtml'])
        self.assertEqual(script.read_bytes(), source)

    def test_latest_pending_episode_documents_are_available_for_review(self):
        episode = self.project / '09-剧集制作/EP001'
        formal = episode / '02-剧集剧本/EP001-本集剧本.md'
        formal.parent.mkdir(parents=True)
        formal.write_text('# 正式剧本\n- 文档版本：v10\n- 确认状态：已确认\n\n'
                          '## 1. 故事剧本正文\n### EP001-C009\n旧正文。\n', encoding='utf-8')
        source = formal.read_bytes()
        work = episode / '其他资料/工作稿'
        work.mkdir(parents=True)
        (work / 'EP001-本集剧本-工作稿.md').write_text(
            '# 剧本工作稿\n- 当前稿版本：v11\n\n## 1. 当前内容\n'
            '### 最新剧本v11\n- 文档版本：v11\n- 确认状态：待审核\n\n'
            '#### 1. 故事剧本正文\n##### EP001-C001\n新正文。\n'
            '## 2. 讨论与修改\n### 历史v99\n- 文档版本：v99\n旧讨论。\n', encoding='utf-8')
        boards = episode / '03-分镜脚本'
        boards.mkdir()
        (boards / 'EP001-C001-场次分镜.md').write_text(
            '# 旧分镜\n- 文档版本：v07\n\n## 1. 镜头正文\n### 分段 P001\n#### EP001-SH001\n旧镜头。\n', encoding='utf-8')
        (work / 'EP001-C001-场次分镜-工作稿.md').write_text(
            '# 分镜工作稿\n\n## 1. 当前内容\n### 新分镜v08\n'
            '- 文档版本：v08\n- 确认状态：待审核\n\n#### 1. 镜头正文\n'
            '##### 分段 P001\n###### EP001-SH001\n新镜头。\n## 2. 讨论与修改\n旧镜头讨论。\n', encoding='utf-8')
        index = '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n| EP001-C001 | EP001-C001-P001 | {} |\n'
        old_index = boards / 'EP001-分镜索引.md'
        new_index = work / 'EP001-分镜索引-工作稿.md'
        old_index.write_text('# 索引\n- 文档版本：v02\n\n' + index.format(11), encoding='utf-8')
        new_index.write_text('# 索引工作稿\n- 当前稿版本：v02\n\n## 1. 当前内容\n'
                             '### 新索引\n- 确认状态：待审核\n\n' + index.format(10)
                             + '\n## 2. 讨论与修改\n旧索引。\n', encoding='utf-8')
        os.utime(old_index, (1_700_000_000, 1_700_000_000))
        os.utime(new_index, (1_700_000_001, 1_700_000_001))
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        script = data['script']
        self.assertTrue(script['key'].endswith('本集剧本-工作稿.md'))
        self.assertTrue(script['url'].startswith('/api/projects/'))
        self.assertEqual(script['doc']['meta'], {'文档版本': 'v11', '确认状态': '待审核'})
        self.assertIn('新正文', script['doc']['contentHtml'])
        self.assertNotIn('旧讨论', script['doc']['html'])
        self.assertEqual(data['scenes'], ['C001'])
        self.assertEqual(data['storyboards']['C001']['doc']['meta']['文档版本'], 'v08')
        self.assertEqual(data['segments']['C001'][0]['duration'], 10)
        self.assertIn('新镜头', data['segments']['C001'][0]['scriptHtml'])
        self.assertNotIn('旧镜头', data['segments']['C001'][0]['scriptHtml'])
        self.assertEqual(formal.read_bytes(), source)

    def test_approved_episode_work_copies_use_same_version_formal_content(self):
        episode = self.project / '09-剧集制作/EP001'
        work = episode / '其他资料/工作稿'
        work.mkdir(parents=True)
        script = episode / '02-剧集剧本/EP001-本集剧本.md'
        script.parent.mkdir()
        script.write_text('# 本集剧本\n- 文档版本：v08\n- 确认状态：已确认\n\n'
                          '## 1. 故事剧本正文\n### EP001-C001\n正式正文。\n', encoding='utf-8')
        boards = episode / '03-分镜脚本'
        boards.mkdir()
        storyboard = boards / 'EP001-C001-场次分镜.md'
        storyboard.write_text('# 场次分镜\n- 文档版本：v23\n- 确认状态：已确认\n\n'
                              '## 1. 镜头正文\n### 分段 P001\n#### EP001-SH001\n正式镜头。\n', encoding='utf-8')
        (boards / 'EP001-分镜索引.md').write_text(
            '# 分镜索引\n- 文档版本：v09\n\n'
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
            '| EP001-C001 | EP001-C001-P001 | 10 |\n', encoding='utf-8')
        original = {file: file.read_bytes() for file in (script, storyboard)}
        for file, version, content in (
            (script, 'v08', '##### 1. 故事剧本正文\n##### EP001-C001\n留存正文。\n'),
            (storyboard, 'v23', '##### 1. 镜头正文\n##### 分段 P001\n###### EP001-SH001\n留存镜头。\n'),
        ):
            draft = work / (file.stem + '-工作稿.md')
            draft.write_text('# 工作稿\n\n## 1. 当前内容\n### 留存正文\n'
                             '- 文档版本：' + version + '\n- 确认状态：C001全场当前版本均已由用户批准采用\n\n'
                             + content, encoding='utf-8')
            os.utime(file, (1_700_000_000, 1_700_000_000))
            os.utime(draft, (1_700_000_001, 1_700_000_001))
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], ['C001'])
        self.assertTrue(data['script']['key'].endswith('/02-剧集剧本/EP001-本集剧本.md'))
        self.assertTrue(data['storyboards']['C001']['key'].endswith('/03-分镜脚本/EP001-C001-场次分镜.md'))
        self.assertEqual(len(data['segments']['C001']), 1)
        self.assertIn('正式镜头', data['segments']['C001'][0]['scriptHtml'])
        for file, content in original.items():
            self.assertEqual(file.read_bytes(), content)

    def test_episode_reference_only_worklog_does_not_replace_formal_index(self):
        episode = self.project / '09-剧集制作/EP001'
        script = episode / '02-剧集剧本/EP001-本集剧本.md'
        script.parent.mkdir(parents=True)
        script.write_text('# 本集剧本\n## 1. 故事剧本正文\n### EP001-C001\n正文。\n', encoding='utf-8')
        index = episode / '03-分镜脚本/EP001-分镜索引.md'
        index.parent.mkdir()
        index.write_text('# 分镜索引\n- 文档版本：v03\n\n'
                         '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                         '| EP001-C001 | EP001-C001-P002 | 15 |\n'
                         '| EP001-C001 | EP001-C001-P001 | 10 |\n', encoding='utf-8')
        work = episode / '其他资料/工作稿/EP001-分镜索引-工作稿.md'
        work.parent.mkdir(parents=True)
        work.write_text('# 工作稿\n- 当前稿版本：v04\n\n## 1. 当前内容\n'
                        '已同步的正式段表：[分镜索引v03](../../03-分镜脚本/EP001-分镜索引.md)。\n\n'
                        '#### 当前审批与准备安排\n| 顺序 | 当前状态 |\n| --- | --- |\n| 1 | 已批准采用 |\n'
                        '## 2. 讨论与修改\n### 历史正文\n- 文档版本：v99\n', encoding='utf-8')
        source = work.read_bytes()
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], ['C001'])
        self.assertEqual([(item['id'], item['duration']) for item in data['segments']['C001']],
                         [('P002', 15), ('P001', 10)])
        self.assertEqual(work.read_bytes(), source)

    def test_episode_latest_version_selection_supports_draft_only_and_newer_formal(self):
        work = self.project / '09-剧集制作/EP001/其他资料/工作稿'
        work.mkdir(parents=True)
        draft = work / 'EP001-本集剧本-工作稿.md'
        draft.write_text('# 工作稿\n\n## 1. 当前内容\n### 新稿\n- 文档版本：v02\n'
                         '- 确认状态：待审核\n\n#### 1. 故事剧本正文\n##### EP001-C001\n草稿正文。\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], ['C001'])
        self.assertTrue(data['script']['key'].endswith('工作稿.md'))
        formal = self.project / '09-剧集制作/EP001/02-剧集剧本/EP001-本集剧本.md'
        formal.parent.mkdir()
        formal.write_text('# 正式稿\n- 文档版本：v03\n- 确认状态：已确认\n\n'
                          '## 1. 故事剧本正文\n### EP001-C002\n正式新正文。\n', encoding='utf-8')
        os.utime(draft, (1_900_000_000, 1_900_000_000))
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], ['C002'])
        self.assertTrue(data['script']['key'].endswith('/02-剧集剧本/EP001-本集剧本.md'))
        self.assertEqual(data['script']['doc']['meta']['文档版本'], 'v03')

    def test_episode_structure_issues_identify_script_and_index_without_hiding_valid_data(self):
        episode = self.project / '09-剧集制作/EP001'
        script = episode / '02-剧集剧本/EP001-本集剧本.md'
        script.parent.mkdir(parents=True)
        script.write_text('# 本集剧本\n### 1. 故事剧本正文\n### EP001-C001\n正文。\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], [])
        self.assertEqual(data['productionIssues'][0]['key'], '09-剧集制作/EP001/02-剧集剧本/EP001-本集剧本.md')
        self.assertIn('二级标题', data['productionIssues'][0]['message'])
        script.write_text('# 本集剧本\n## 1. 故事剧本正文\n### EP001-C001\n正文。\n', encoding='utf-8')
        index = episode / '03-分镜脚本/EP001-分镜索引.md'
        index.parent.mkdir()
        index.write_text('# 分镜索引\n| 场次 | 分段 | 时长 |\n| --- | --- | --- |\n'
                         '| EP001-C001 | EP001-C001-P001 | 10 |\n', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], ['C001'])
        self.assertEqual(data['segments']['C001'], [])
        self.assertEqual(data['productionIssues'][0]['key'], '09-剧集制作/EP001/03-分镜脚本/EP001-分镜索引.md')
        self.assertIn('分段计划时长（秒）', data['productionIssues'][0]['message'])
        index.write_text('# 分镜索引\n| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                         '| EP001-C001 | EP001-C001-P001 | 10 |\n'
                         '| EP001-C001 | EP001-C002-P002 | 11 |\n', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual([item['id'] for item in data['segments']['C001']], ['P001'])
        self.assertIn('不匹配', data['productionIssues'][0]['message'])

    def test_episode_storyboard_structure_issues_have_scene_and_source(self):
        episode = self.project / '09-剧集制作/EP001'
        script = episode / '02-剧集剧本/EP001-本集剧本.md'
        script.parent.mkdir(parents=True)
        script.write_text('# 本集剧本\n## 1. 故事剧本正文\n### EP001-C001\n正文。\n', encoding='utf-8')
        board = episode / '03-分镜脚本/EP001-C001-场次分镜.md'
        board.parent.mkdir()
        board.write_text('# 场次分镜\n### 1. 镜头正文\n### 分段 P001\n镜头。\n', encoding='utf-8')
        index = board.parent / 'EP001-分镜索引.md'
        index.write_text('| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                         '| EP001-C001 | EP001-C001-P001 | 10 |\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(len(data['segments']['C001']), 1)
        issue = data['productionIssues'][0]
        self.assertTrue(issue['key'].endswith('EP001-C001-场次分镜.md'))
        self.assertEqual(issue['scene'], 'C001')
        self.assertIn('1. 镜头正文', issue['message'])
        board.write_text('# 场次分镜\n## 1. 镜头正文\n### 分段 P002\n#### EP001-SH001\n镜头。\n', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertIn('分段 P001', data['productionIssues'][0]['message'])

    def test_unstarted_episode_has_no_structure_error(self):
        (self.project / '09-剧集制作/EP001').mkdir(parents=True)
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['scenes'], [])
        self.assertEqual(data['productionIssues'], [])

    def test_segments_use_current_index_and_match_story_scenes(self):
        episode = self.project / '09-剧集制作/EP001'
        (episode / '02-剧集剧本').mkdir(parents=True)
        (episode / '02-剧集剧本/EP001-本集剧本.md').write_text(
            '## 1. 故事剧本正文\n### EP001-C002\n第二场。\n### EP001-C001\n第一场。\n', encoding='utf-8')
        (episode / '03-分镜脚本').mkdir()
        index = episode / '03-分镜脚本/EP001-分镜索引.md'
        index.write_text('| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                         '| EP001-C001 | EP001-C001-P002 | 5.5 |\n'
                         '| EP001-C002 | EP001-C002-P001 | 11 |\n'
                         '| EP001-C001 | EP001-C001-P001 | 4.75 |\n'
                         '| EP002-C001 | EP002-C001-P009 | 9 |\n'
                         '| EP001-C003 | EP001-C003-P001 | 10 |\n'
                         '| EP001-C001 | EP001-C002-P002 | 7 |\n', encoding='utf-8')
        source = index.read_bytes()
        history = episode / '其他资料/历史版本'
        history.mkdir(parents=True)
        (history / 'EP001-分镜索引-旧版.md').write_text(
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
            '| EP001-C001 | EP001-C001-P099 | 15 |\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]
        self.assertEqual(data['segments'], {'C002': [{'id': 'P001', 'duration': 11, 'scriptHtml': '', 'videos': []}],
                                           'C001': [{'id': 'P002', 'duration': 5.5, 'scriptHtml': '', 'videos': []}, {'id': 'P001', 'duration': 4.75, 'scriptHtml': '', 'videos': []}]})
        self.assertEqual(index.read_bytes(), source)

    def test_segment_script_uses_only_current_shot_body(self):
        episode = self.project / '09-剧集制作/EP001'
        (episode / '02-剧集剧本').mkdir(parents=True)
        (episode / '02-剧集剧本/EP001-本集剧本.md').write_text(
            '## 1. 故事剧本正文\n### EP001-C001\n第一场。\n### EP001-C002\n第二场。\n', encoding='utf-8')
        (episode / '03-分镜脚本').mkdir()
        (episode / '03-分镜脚本/EP001-分镜索引.md').write_text(
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
            '| EP001-C001 | EP001-C001-P001 | 5 |\n'
            '| EP001-C001 | EP001-C001-P002 | 10 |\n'
            '| EP001-C002 | EP001-C002-P001 | 7 |\n', encoding='utf-8')
        source = episode / '03-分镜脚本/EP001-C001-场次分镜.md'
        source.write_text('# 场次分镜\n\n场头说明。\n## 1. 镜头正文\n'
                          '### 分段 P001\n**对应视频分段**：EP001-C001-P001；**计划时长**：5秒。\n'
                          '#### EP001-SH001\n\n**镜号**：EP001-SH001\n\n**景别**：近景。\n'
                          '**台词**：第一段原对白。\n[资料](../../../03-人物资料/CH001-资料卡.md)\n<script>正文文字</script>\n'
                          '### 分段 P002\n#### EP001-SH002\n**镜号**：EP001-SH099\n**台词**：第二段原对白。\n'
                          '## 2. 视频分段\n### 分段 P001\n资源规划，不是镜头正文。\n', encoding='utf-8')
        before = source.read_bytes()
        (episode / '03-分镜脚本/EP001-C002-场次分镜.md').write_text(
            '## 1. 镜头正文\n### 分段 P001\n#### EP001-SH003\n另一场正文。\n', encoding='utf-8')
        history = episode / '其他资料/历史版本'
        history.mkdir(parents=True)
        (history / 'EP001-C001-场次分镜-旧版.md').write_text(
            '## 1. 镜头正文\n### 分段 P001\n旧版正文。\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']
        first = data['C001'][0]['scriptHtml']
        self.assertIn('<strong>景别</strong>：近景。', first)
        self.assertIn('第一段原对白。', first)
        self.assertIn('/api/projects/', first)
        self.assertIn('03-', first)
        self.assertIn('&lt;script&gt;正文文字&lt;/script&gt;', first)
        self.assertIn('<h4 id="ep001-sh001">EP001-SH001</h4>', first)
        self.assertNotIn('镜号', first)
        self.assertNotIn('对应视频分段', first)
        self.assertNotIn('<h3', first)
        source_url = data['C001'][0]['scriptUrl']
        self.assertTrue(source_url.startswith('/api/projects/'))
        self.assertTrue(source_url.endswith('EP001-C001-%E5%9C%BA%E6%AC%A1%E5%88%86%E9%95%9C.md'))
        self.assertEqual(self.client.get(source_url).content, before)
        self.assertIn('<strong>镜号</strong>：EP001-SH099', data['C001'][1]['scriptHtml'])
        for excluded in ('第二段原对白。', '场头说明。', '资源规划', '另一场正文。', '旧版正文。'):
            self.assertNotIn(excluded, first)
        self.assertIn('第二段原对白。', data['C001'][1]['scriptHtml'])
        self.assertIn('另一场正文。', data['C002'][0]['scriptHtml'])
        self.assertEqual(source.read_bytes(), before)

    def test_segment_videos_match_identity_and_sort_execution_numbers(self):
        episode = self.project / '09-剧集制作/EP001'
        (episode / '02-剧集剧本').mkdir(parents=True)
        (episode / '02-剧集剧本/EP001-本集剧本.md').write_text(
            '## 1. 故事剧本正文\n### EP001-C001\n剧情。\n', encoding='utf-8')
        (episode / '03-分镜脚本').mkdir()
        (episode / '03-分镜脚本/EP001-分镜索引.md').write_text(
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
            '| EP001-C001 | EP001-C001-P001 | 5 |\n', encoding='utf-8')
        candidates = episode / '其他资料/候选视频'
        candidates.mkdir(parents=True)
        for name in ('EP001-C001-P001-R010-二采.mp4', 'EP001-C001-P001-R002-一采.mp4',
                     'EP001-C001-P002-R001-一采.mp4', 'EP001-C002-P001-R001-一采.mp4',
                     'EP002-C001-P001-R001-一采.mp4', 'EP001-C001-场次成片-v01.mp4'):
            (candidates / name).write_bytes(b'video candidate')
        attachments = episode / '其他资料/执行附件'
        attachments.mkdir()
        (attachments / 'EP001-C001-P001-R011-后处理.mp4').write_bytes(b'not a final candidate')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']['C001'][0]['videos']
        self.assertEqual([(v['candidateNumber'], v['run'], v['stage'], v['approved']) for v in data],
                         [(1, 'R002', '一采', False), (1, 'R010', '二采', False)])
        self.assertEqual(self.client.get(data[0]['url']).content, b'video candidate')
        self.assertTrue(data[0]['url'].startswith('/api/projects/'))
        self.assertTrue((candidates / 'EP001-C001-P001-R002-一采.mp4').is_file())

    def test_stage_formal_uses_current_adoption_and_preserves_candidate_numbers(self):
        episode = self.project / '09-剧集制作/EP001'
        (episode / '02-剧集剧本').mkdir(parents=True)
        (episode / '02-剧集剧本/EP001-本集剧本.md').write_text(
            '## 1. 故事剧本正文\n### EP001-C001\n剧情。\n', encoding='utf-8')
        (episode / '03-分镜脚本').mkdir()
        (episode / '03-分镜脚本/EP001-分镜索引.md').write_text(
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
            '| EP001-C001 | EP001-C001-P001 | 5 |\n', encoding='utf-8')
        candidates = episode / '其他资料/候选视频'
        candidates.mkdir(parents=True)
        names = ['EP001-C001-P001-R001-一采.mp4', 'EP001-C001-P001-R002-一采.mp4',
                 'EP001-C001-P001-R003-一采.mp4', 'EP001-C001-P001-R004-二采.mp4']
        for name in names:
            (candidates / name).write_bytes(name.encode())
        adopted = episode / '其他资料/阶段采用视频/01-一采/C001-场次'
        adopted.mkdir(parents=True)
        (candidates / names[1]).rename(adopted / names[1])
        work = episode / '其他资料/工作稿'
        work.mkdir()
        record = work / 'EP001-C001-P001-视频制作-工作稿.md'
        def write_record(run, filename, decision):
            record.write_text('## 1. 当前选定结果\n'
                '| 处理阶段 | 当前选定文件 | R编号 | 来源任务 | 人工批准依据 |\n'
                '| --- | --- | --- | --- | --- |\n'
                f'| 一采 | [选定](../阶段采用视频/01-一采/C001-场次/{filename}) | {run} | 本次任务 | 用户批准 |\n'
                f'## 2. 逐次执行与采用记录\n### {run}\n- 处理阶段：一采\n- 用户决定：{decision}\n', encoding='utf-8')
        def videos():
            return parser.build_data(self.project, web_episode_navigation=True)['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos']
        # Directory placement cannot substitute for the adoption decision.
        write_record('R002', names[1], '待审核')
        self.assertFalse(any(v['approved'] for v in videos()))
        write_record('R001', names[1], '批准采用')
        self.assertFalse(any(v['approved'] for v in videos()))
        write_record('R002', names[1], '批准采用')
        data = videos()
        self.assertEqual([(v['run'], v['candidateNumber'], v['approved']) for v in data],
                         [('R001', 1, False), ('R002', 2, True), ('R003', 3, False), ('R004', 1, False)])
        self.assertEqual(len(data), 4)
        self.assertEqual((adopted / names[1]).read_bytes(), names[1].encode())
        # Replacing the adopted version restores the old candidate's original number.
        (adopted / names[1]).rename(candidates / names[1])
        (candidates / names[2]).rename(adopted / names[2])
        write_record('R003', names[2], '批准采用')
        data = videos()
        self.assertEqual([(v['run'], v['candidateNumber'], v['approved']) for v in data[:3]],
                         [('R001', 1, False), ('R002', 2, False), ('R003', 3, True)])
        # Unmigrated projects still read their existing generation record.
        legacy = episode / '其他资料/执行附件'
        legacy.mkdir()
        text = record.read_text(encoding='utf-8').replace('### R003\n', '### R003整场返修\n')
        record.unlink()
        (legacy / 'EP001-C001-P001-生成记录.md').write_text(text, encoding='utf-8')
        self.assertEqual([(v['run'], v['approved']) for v in videos()[:3]],
                         [('R001', False), ('R002', False), ('R003', True)])

    def test_segment_duration_must_be_positive(self):
        episode = self.project / '09-剧集制作/EP001'
        (episode / '02-剧集剧本').mkdir(parents=True)
        (episode / '02-剧集剧本/EP001-本集剧本.md').write_text(
            '## 1. 故事剧本正文\n### EP001-C001\n剧情。\n', encoding='utf-8')
        (episode / '03-分镜脚本').mkdir()
        (episode / '03-分镜脚本/EP001-分镜索引.md').write_text(
            '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
            '| EP001-C001 | EP001-C001-P001 | 0 |\n', encoding='utf-8')
        response = self.client.get('/api/projects/示例项目/sections/09-剧集制作')
        self.assertEqual(response.status_code, 503)
        self.assertIn('分段计划时长必须为正数秒', response.json()['detail'])

    def test_discovery_and_dynamic_document(self):
        self.assertEqual(self.client.get('/api/projects').json()[0]['name'], '示例项目')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位')
        self.assertIn('第一版', section.json()['bodyHtml'])
        previous = self.store.status('示例项目')['revision']
        self.source.write_text('# 项目定位\n\n## 内容\n第二版，增加内容。\n', encoding='utf-8')
        self.store.get('示例项目')['checked'] = 0
        self.store.status('示例项目')
        for _ in range(100):
            if not self.store.get('示例项目')['updating']:
                break
            time.sleep(.01)
        self.assertGreater(self.store.status('示例项目')['revision'], previous)
        self.assertIn('第二版', self.client.get('/api/projects/示例项目/sections/00-项目定位').json()['bodyHtml'])
        (self.root / '新项目').mkdir()
        self.assertEqual(len(self.client.get('/api/projects').json()), 2)

    def test_file_boundaries_and_range(self):
        video = self.project / '测试.mp4'
        video.write_bytes(bytes(range(100)))
        ranged = self.client.get('/api/projects/示例项目/files/测试.mp4', headers={'Range': 'bytes=10-19'})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.content, bytes(range(10, 20)))
        with self.assertRaises(FileNotFoundError):
            self.store.file('示例项目', '../outside.md')
        hidden = self.project / '.private'
        hidden.write_text('private')
        self.assertEqual(self.client.get('/api/projects/示例项目/files/.private').status_code, 404)
        self.assertEqual(self.client.get('/api/history/document?path=../../AGENTS.md').status_code, 404)
        self.assertEqual(self.client.get('/api/krea2/files/../使用说明.md').status_code, 404)

    def test_changes_include_additions_removal_and_rename(self):
        before = self.store.snapshot(self.project)
        path = self.project / '新增.txt'
        path.write_text('hello')
        self.assertNotEqual(before, self.store.snapshot(self.project))
        current = self.store.snapshot(self.project)
        path.rename(self.project / '改名.txt')
        self.assertNotEqual(current, self.store.snapshot(self.project))
        (self.project / '改名.txt').unlink()
        self.assertEqual(before, self.store.snapshot(self.project))

    def test_refresh_failure_retains_previous_data_and_reports_error(self):
        entry = self.store.get('示例项目')
        data = entry['data']
        with self.assertLogs('backend.services.projects', level='ERROR') as log, patch(
                'backend.services.projects.build_data', side_effect=ValueError('错误源文件')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        self.assertIs(entry['data'], data)
        self.assertEqual(entry['error'], '错误源文件')
        self.assertEqual(entry['error_kind'], 'read_failed')
        self.assertIn('示例项目', log.output[0])
        self.assertIn('错误源文件', log.output[0])

    def test_failed_refresh_retries_unchanged_files_after_delay_and_recovers(self):
        entry = self.store.get('示例项目')
        data = entry['data']
        with patch('backend.services.projects.time.monotonic', return_value=100), patch(
                'backend.services.projects.time.time', return_value=1000), self.assertLogs(
                'backend.services.projects', level='ERROR'), patch(
                'backend.services.projects.build_data', side_effect=RuntimeError('读取期间文件变化')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        with patch('backend.services.projects.time.monotonic', return_value=110), patch(
                'backend.services.projects.threading.Thread') as worker:
            state = self.store.status('示例项目')
            worker.assert_not_called()
            self.assertEqual(state['retryAt'], 1030000)
            self.assertEqual(state['errorKind'], 'read_failed')
        with patch('backend.services.projects.time.monotonic', return_value=130), patch(
                'backend.services.projects.threading.Thread') as worker:
            state = self.store.status('示例项目')
            worker.return_value.start.assert_called_once()
            self.assertTrue(state['updating'])
        self.assertIs(entry['data'], data)
        self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        self.assertIsNone(entry['error'])
        self.assertIsNone(entry['error_kind'])
        self.assertEqual(entry['retry_at_time'], 0)
        self.assertFalse(entry['updating'])
        self.assertEqual(entry['revision'], 2)

    def test_source_edit_is_classified_without_error_log_and_preserves_data(self):
        entry = self.store.get('示例项目')
        data = entry['data']
        with self.assertLogs('backend.services.projects', level='INFO') as log, patch(
                'backend.services.projects.build_data', side_effect=parser.SourceChangedError('Source changed while reading; rerun: 定位.md')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        self.assertIs(entry['data'], data)
        self.assertEqual(entry['error_kind'], 'source_changed')
        self.assertEqual(log.records[0].levelname, 'INFO')
        self.assertIn('定位.md', log.output[0])

    def test_parser_identifies_source_edited_during_read(self):
        read_bytes = Path.read_bytes

        def edit_after_read(path):
            raw = read_bytes(path)
            if path == self.source:
                self.source.write_text('# 写入中的新资料\n', encoding='utf-8')
            return raw

        with patch.object(Path, 'read_bytes', edit_after_read), self.assertRaises(parser.SourceChangedError):
            parser.build_data(self.project, web_episode_navigation=True)

    def test_due_retry_is_not_delayed_by_recent_scan(self):
        entry = self.store.get('示例项目')
        with patch('backend.services.projects.time.monotonic', return_value=100), self.assertLogs(
                'backend.services.projects', level='ERROR'), patch(
                'backend.services.projects.build_data', side_effect=ValueError('错误源文件')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        entry['checked'] = 129
        with patch('backend.services.projects.time.monotonic', return_value=130), patch(
                'backend.services.projects.threading.Thread') as worker:
            state = self.store.status('示例项目')
            worker.return_value.start.assert_called_once()
            self.assertTrue(state['updating'])

    def test_new_file_change_retries_before_failure_delay(self):
        entry = self.store.get('示例项目')
        with patch('backend.services.projects.time.monotonic', return_value=100), self.assertLogs(
                'backend.services.projects', level='ERROR'), patch(
                'backend.services.projects.build_data', side_effect=ValueError('错误源文件')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        self.source.write_text('# 已修正的资料', encoding='utf-8')
        with patch('backend.services.projects.time.monotonic', return_value=110), patch(
                'backend.services.projects.threading.Thread') as worker:
            self.store.status('示例项目')
            worker.return_value.start.assert_called_once()

    def test_lan_can_manage_with_same_origin_and_token(self):
        lan = TestClient(main.app, base_url='http://192.168.10.15:8780', client=('192.168.10.30', 44321))
        state = lan.get('/api/krea2/state').json()
        self.assertTrue(state['canManage'])
        self.assertEqual(state['token'], main.krea2.updater.TOKEN)
        with patch.object(main.krea2.updater, 'start_job') as job:
            result = lan.post('/api/krea2/action', headers={'Origin': 'http://192.168.10.15:8780', 'X-Krea-Token': main.krea2.updater.TOKEN}, json={'source': 'clio', 'action': 'apply'})
            self.assertEqual(result.status_code, 202)
            job.assert_called_once_with('apply', 'clio')
            job.reset_mock()
            payload = {'source': 'clio', 'action': 'check'}
            for headers in (
                {'Origin': 'http://outside.site', 'X-Krea-Token': state['token']},
                {'Origin': 'http://192.168.10.15:8780', 'X-Krea-Token': 'wrong-token'},
                {'Origin': 'http://192.168.10.15', 'Sec-Fetch-Site': 'same-origin', 'X-Krea-Token': state['token']},
            ):
                self.assertEqual(lan.post('/api/krea2/action', headers=headers, json=payload).status_code, 403)
            job.assert_not_called()
            self.assertEqual(lan.post('/api/krea2/action', headers={'Origin': 'http://192.168.10.15', 'Referer': 'http://192.168.10.15:8780/', 'Sec-Fetch-Site': 'same-origin', 'X-Krea-Token': state['token']}, json=payload).status_code, 202)
            job.assert_called_once_with('check', 'clio')
        lan.close()

    def test_public_peer_or_non_lan_host_cannot_manage(self):
        for host, peer in (('192.168.10.15', '8.8.8.8'), ('outside.site', '192.168.10.30'), ('8.8.8.8', '192.168.10.30')):
            with TestClient(main.app, base_url=f'http://{host}:8780', client=(peer, 44321)) as client:
                state = client.get('/api/krea2/state').json()
                self.assertFalse(state['canManage'])
                self.assertNotIn('token', state)
                with patch.object(main.krea2.updater, 'start_job') as job:
                    result = client.post('/api/krea2/action', headers={'Origin': f'http://{host}:8780', 'X-Krea-Token': main.krea2.updater.TOKEN}, json={'source': 'ray', 'action': 'restore'})
                    self.assertEqual(result.status_code, 403)
                    job.assert_not_called()

    def test_local_management_requires_origin_and_token(self):
        state = self.client.get('/api/krea2/state').json()
        self.assertTrue(state['canManage'])
        with patch.object(main.krea2.updater, 'start_job') as job:
            payload = {'source': 'ray', 'action': 'check'}
            headers = {'Origin': 'http://localhost:8780', 'X-Krea-Token': state['token']}
            self.assertEqual(self.client.post('/api/krea2/action', headers=headers, json=payload).status_code, 202)
            job.assert_called_once_with('check', 'ray')
            for invalid in ({'Origin': 'http://other.site', 'X-Krea-Token': state['token']}, {'Origin': 'http://localhost:8780'}):
                self.assertEqual(self.client.post('/api/krea2/action', headers=invalid, json=payload).status_code, 403)

    def test_catalog_is_paged_and_resource_remains_readable(self):
        first = self.client.get('/api/krea2/catalog').json()
        self.assertEqual(len(first['items']), 36)
        self.assertGreater(first['total'], 36)
        second = self.client.get('/api/krea2/catalog?page=2').json()
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        style = self.client.get('/api/krea2/styles/' + first['items'][0]['id']).json()
        self.assertEqual(self.client.get('/api/krea2/files/' + style['folder'] + '/positive.txt').text, style['prompt'])

    def test_krea_management_retains_origin_and_payload_boundaries(self):
        token = main.krea2.updater.TOKEN
        payload = {'source': 'clio', 'action': 'check'}
        with patch.object(main.krea2.updater, 'start_job') as job:
            for origin in (None, 'null', 'http://localhost:1', 'https://localhost:8780'):
                headers = {'X-Krea-Token': token}
                if origin is not None:
                    headers['Origin'] = origin
                self.assertEqual(self.client.post('/api/krea2/action', headers=headers, json=payload).status_code, 403)
            for referer, site in ((None, 'same-origin'), ('http://localhost:1/', 'same-origin'),
                                  ('http://localhost:8780.evil.invalid/', 'same-origin'),
                                  ('http://localhost:8780/', None), ('http://localhost:8780/', 'same-site'),
                                  ('http://localhost:8780/', 'cross-site')):
                headers = {'Origin': 'http://localhost', 'X-Krea-Token': token}
                if referer is not None:
                    headers['Referer'] = referer
                if site is not None:
                    headers['Sec-Fetch-Site'] = site
                self.assertEqual(self.client.post('/api/krea2/action', headers=headers, json=payload).status_code, 403)
            headers = {'Origin': 'http://localhost:8780', 'X-Krea-Token': token}
            self.assertEqual(self.client.post('/api/krea2/action', headers=headers,
                                             json=dict(payload, extra='x' * 4096)).status_code, 413)
            for invalid in (dict(payload, action='unknown'), dict(payload, source='unknown')):
                self.assertEqual(self.client.post('/api/krea2/action', headers=headers, json=invalid).status_code, 422)
            job.assert_not_called()

    def test_generation_record_urls_use_project_endpoint_and_keep_fragment(self):
        result = main.view({'recordUrl': '03-test%5C记录.md#生成记录-001', 'sourceUrl': 'https://example.com/source'}, '示例项目')
        self.assertEqual(result['recordUrl'], '/api/projects/%E7%A4%BA%E4%BE%8B%E9%A1%B9%E7%9B%AE/files/03-test/记录.md#生成记录-001')
        self.assertEqual(result['sourceUrl'], 'https://example.com/source')

    def test_markdown_table_with_blank_lines_keeps_rows_and_links(self):
        rendered = parser.markdown('| 类型 | 种子 | 来源 |\n\n| --- | --- | --- |\n\n| 肖像 | 123 | [记录](记录.md) |\n\n| 六视图 | 456 | 已采用 |\n\n下一段。', parser.POSITION)
        self.assertEqual(rendered.count('<table>'), 1)
        self.assertEqual(rendered.count('<td>'), 6)
        self.assertIn('data-doc="00-项目定位/记录.md"', rendered)
        self.assertIn('</table></div>\n<p>下一段。</p>', rendered)

    def test_phase_status_targets_the_matching_progress_row(self):
        progress = '| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n| --- | --- | --- | --- | --- | --- |\n| 人物资料卡 | 会话 | 待确认 | 资料卡 | CH042细节待确认 | 按用户意见修订 |\n'
        (self.project / '项目进度.md').write_text(progress, encoding='utf-8')
        data = self.store.get('示例项目')['data']
        stage = next(item for item in data['active'] if item['name'] == '人物资料卡')
        self.assertIn('id="' + stage['anchor'] + '"', data['documents']['项目进度.md']['html'])
        self.assertIn('CH042细节待确认', data['documents']['项目进度.md']['html'])

    def test_phase_table_with_blank_lines_reads_all_actual_states(self):
        progress = ('| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n\n'
                    '| --- | --- | --- | --- | --- | --- |\n\n'
                    '| 人物资料卡 | 会话 | 待确认 | 卡 | 待审 | 修改 |\n\n'
                    '| EP001 制作 | 会话 | 进行中 | 剧本 | 待审 | 制作 |\n\n'
                    '| 分集大纲 | 会话 | 已完成 | 大纲 | 无 | 接续 |\n\n## 其他内容\n')
        path = self.project / '项目进度.md'
        path.write_text(progress, encoding='utf-8')
        value = self.client.get('/api/projects/示例项目/overview').json()
        self.assertEqual([(item['name'], item['status']) for item in value['active']],
                         [('人物资料卡', '待确认'), ('EP001 制作', '进行中')])
        self.assertEqual(path.read_text(encoding='utf-8'), progress)

    def test_phase_lists_preserve_document_links_and_escape_other_html(self):
        progress = ('| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n'
                    '| --- | --- | --- | --- | --- | --- |\n'
                    '| 项目基本定位 | 会话 | 进行中 | 定位 | - 地理待定<br>- 核对[画风正文v11](00-项目定位/项目基本定位.md#画风与美术实现正文) | - 检查<script>内容</script> |\n')
        (self.project / '项目进度.md').write_text(progress, encoding='utf-8')
        data = self.store.get('示例项目')['data']
        stage = data['active'][0]
        self.assertTrue(stage['pendingHtml'].startswith('<ul><li>地理待定</li><li>核对<a '))
        self.assertIn('data-doc="00-项目定位/项目基本定位.md"', stage['pendingHtml'])
        self.assertIn('#%E7%94%BB', stage['pendingHtml'])
        self.assertEqual(stage['nextHtml'], '<ul><li>检查&lt;script&gt;内容&lt;/script&gt;</li></ul>')
        document = data['documents']['项目进度.md']['html']
        self.assertIn(stage['pendingHtml'], document)
        self.assertIn(stage['nextHtml'], document)
        self.assertEqual(parser.phase_list('旧说明；保留原意', parser.PROGRESS), '<ul><li>旧说明；保留原意</li></ul>')

    def test_document_header_preserves_extra_fields_and_source_links(self):
        source = ('# 项目定位\n\n- 项目名称或代号：示例项目\n- 文档版本：v03\n'
                  '- 更新日期：2026-10-06\n- 确认状态：部分确认；旧限定说明。\n'
                  '- 确认范围：主线已确认\n- 确认依据：[决定](决定.md)\n'
                  '- 旧制作目标：全部保留\n\n额外说明也保留。\n\n## 正文\n'
                  '- 确认范围：这是正文字段。\n')
        self.source.write_text(source, encoding='utf-8')
        value = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertIn('旧制作目标：全部保留', value['headerHtml'])
        self.assertIn('旧限定说明', value['headerHtml'])
        self.assertIn('额外说明也保留', value['headerHtml'])
        self.assertIn('data-doc="00-项目定位/决定.md"', value['headerHtml'])
        self.assertNotIn('这是正文字段', value['headerHtml'])
        preview = self.client.get('/api/projects/示例项目/document', params={'path': parser.POSITION}).json()
        self.assertEqual(preview['headerHtml'], value['headerHtml'])
        self.assertNotIn('旧制作目标', preview['contentHtml'])
        self.assertIn('这是正文字段', preview['contentHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)

    def test_sample_resolution_moves_to_title_and_keeps_three_record_fields(self):
        source = ('#### 男性样例\n\n![男性](男.png)\n\n'
                  '- 分辨率：1024×1024\n- 样例版本：v15\n'
                  '- 确认依据：旧说明有512×512；[采用](采用.md)\n'
                  '- 执行记录：[生成](生成.md)\n\n'
                  '#### 女性样例\n\n- 分辨率：待确认\n- 样例版本：v05\n'
                  '- 确认依据：尚未确认\n- 执行记录：[旧试验](试验.md)\n')
        rendered = parser.markdown(source, parser.POSITION)
        self.assertIn('<h4 id="男性样例">男性样例，1024×1024</h4>', rendered)
        self.assertIn('<h4 id="女性样例">女性样例，待确认</h4>', rendered)
        self.assertNotIn('<li>分辨率', rendered)
        self.assertEqual(rendered.count('<li>'), 6)
        self.assertEqual(rendered.count('class="style-sample-card"'), 1)
        self.assertIn('旧说明有512×512', rendered)
        self.assertIn('data-doc="00-项目定位/采用.md"', rendered)
        self.assertIn('data-doc="00-项目定位/生成.md"', rendered)
        old = parser.markdown('#### 男性样例\n\n![男性](男.png)\n\n- 确认依据：旧尺寸512×512\n', parser.POSITION)
        self.assertIn('<h4 id="男性样例">男性样例</h4>', old)
        self.assertNotIn('男性样例，512', old)

    def test_position_title_and_status_do_not_change_the_source(self):
        source = '# 项目定位\n\n- 项目名称：示例项目，全名。\n\n## 视觉表现\n\n- 画风确认状态：已确认；采用依据保留。\n'
        self.source.write_text(source, encoding='utf-8')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertEqual(section['title'], '示例项目，全名')
        overview = self.client.get('/api/projects/示例项目/overview').json()
        self.assertEqual(overview['positionTitle'], section['title'])
        self.assertEqual(overview['project'], '示例项目')
        self.assertEqual(section['introHtml'], '')
        self.assertIn('status-green', section['bodyHtml'])
        self.assertIn('采用依据保留', section['bodyHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)

    def test_position_template_preserves_scope_evidence_and_sample_ownership(self):
        source = ('# 项目基本定位\n\n- 项目名称或代号：模板项目\n- 文档版本：v2\n'
                  '- 更新日期：2026-10-06\n- 确认状态：部分确认\n- 确认范围：仅EP001\n'
                  '- 确认依据：[决定](决定.md)\n\n## 5. 视觉表现形式\n\n### 视觉规格\n'
                  '- 正式画幅：待确认\n- 画幅待确认事项：候选16:9或9:16\n'
                  '- 画幅确认状态：待确认\n\n### 画风与美术实现正文\n\n#### 中文\n'
                  '~~~text\n完整中文正文\n~~~\n\n#### 英文\n'
                  '- 对应中文版本：v1\n- 适配确认状态：已确认\n\n~~~text\nFull English text\n~~~\n'
                  '\n### 已确认画风样例\n\n#### 男性样例\n\n![男性](男.png)\n'
                  '\n- 样例版本：v3\n- 确认依据：[男性决定](男.md)\n'
                  '\n#### 女性样例\n\n- 样例版本：待确认\n- 确认依据：尚未确认\n')
        self.source.write_text(source, encoding='utf-8')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertEqual(section['title'], '模板项目')
        self.assertIn('仅EP001', section['summaryHtml'])
        self.assertNotIn('仅EP001', section['introHtml'])
        self.assertIn('data-doc="00-项目定位/决定.md"', section['introHtml'])
        self.assertNotIn('项目名称或代号', section['introHtml'])
        self.assertIn('status-orange', section['confirmationHtml'])
        self.assertIn('正式画幅：待确认', section['bodyHtml'])
        self.assertIn('候选16:9或9:16', section['bodyHtml'])
        self.assertIn('完整中文正文', section['bodyHtml'])
        self.assertIn('Full English text', section['bodyHtml'])
        self.assertEqual(section['bodyHtml'].count('class="style-sample-card"'), 1)
        self.assertIn('data-gender="male"', section['bodyHtml'])
        self.assertIn('男性决定', section['bodyHtml'])
        self.assertIn('女性样例', section['bodyHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)

    def test_root_history_replaces_other_materials_without_mixing_stage_records(self):
        root_record = self.project / '历史版本/项目进度-归档.md'
        legacy_record = self.project / '其他资料/历史版本/旧位置.md'
        stage_record = self.project / '00-项目定位/其他资料/工作稿/定位-工作稿.md'
        for path in (root_record, legacy_record, stage_record):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# 记录\n\n原始依据。', encoding='utf-8')
        overview = self.client.get('/api/projects/示例项目/overview').json()
        directories = [item['name'] for item in overview['directories']]
        self.assertIn('历史版本', directories)
        self.assertNotIn('其他资料', directories)
        response = self.client.get('/api/projects/示例项目/sections/历史版本')
        self.assertEqual(response.status_code, 200)
        files = response.json()['children']
        self.assertEqual([item['key'] for item in files], ['历史版本/项目进度-归档.md'])
        preview = self.client.get('/api/projects/示例项目/document', params={'path': files[0]['key']})
        self.assertIn('原始依据', preview.json()['html'])
        stage = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertIn('其他资料/工作稿/定位-工作稿.md', str(stage))
        self.assertNotIn('历史版本/项目进度-归档.md', str(stage))
        self.assertEqual(self.client.get('/api/projects/示例项目/sections/其他资料').status_code, 404)
        self.assertEqual(self.client.get('/api/projects/示例项目/sections/不存在').status_code, 404)

    def test_common_header_keeps_scope_and_legacy_notes_separate(self):
        for directory, name in [('01-主旨与简介', '主旨与简介'), ('02-故事大纲', '故事大纲')]:
            path = self.project / directory / (name + '.md')
            path.parent.mkdir(parents=True, exist_ok=True)
            source = ('# ' + name + '\n\n- 项目名称或代号：示例项目\n'
                      '- 文档版本：v02\n- 更新日期：2026-10-06\n'
                      '- 确认状态：部分确认\n- 确认范围：主线已确认，细节待定。\n'
                      '- 确认依据：[决定](决定.md)\n- 确认说明：旧说明完整保留。\n'
                      '\n## 正文\n\n- 确认范围：这是正文原句，不是头部字段。\n')
            path.write_text(source, encoding='utf-8')
        for directory, name in [('01-主旨与简介', '主旨与简介'), ('02-故事大纲', '故事大纲')]:
            with self.subTest(document=name):
                path = self.project / directory / (name + '.md')
                source = path.read_text(encoding='utf-8')
                value = self.client.get('/api/projects/示例项目/sections/' + directory).json()
                self.assertIn('主线已确认，细节待定', value['summaryHtml'])
                self.assertNotIn('主线已确认', value['introHtml'])
                self.assertIn('旧说明完整保留', value['introHtml'])
                self.assertIn('data-doc="' + directory + '/决定.md"', value['introHtml'])
                self.assertIn('这是正文原句', value['bodyHtml'])
                self.assertNotIn('这是正文原句', value['summaryHtml'])
                self.assertEqual(path.read_text(encoding='utf-8'), source)

    def test_position_current_fields_are_separate_from_adoption_history(self):
        source = ('# 项目定位\n\n- 确认范围：画幅已确认，地理待定。\n'
                  '- 单集目标时长：1—2分钟\n- 确认依据：[采用](采用.md)\n'
                  '- 采用经过：旧42集改为71集，依据保留。\n\n## 1. 正文\n'
                  '单集目标时长：这句话属于正文，应完整保留。\n'
                  '\n### 制作规格\n\n- 单集目标时长：2—3分钟\n')
        self.source.write_text(source, encoding='utf-8')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertIn('地理待定', section['summaryHtml'])
        self.assertNotIn('单集目标时长', section['summaryHtml'])
        self.assertIn('1—2分钟', section['introHtml'])
        self.assertNotIn('采用经过', section['summaryHtml'])
        self.assertNotIn('地理待定', section['introHtml'])
        self.assertIn('旧42集改为71集', section['introHtml'])
        self.assertIn('data-doc="00-项目定位/采用.md"', section['introHtml'])
        self.assertIn('这句话属于正文，应完整保留', section['bodyHtml'])
        self.assertIn('制作规格', section['bodyHtml'])
        self.assertIn('2—3分钟', section['bodyHtml'])
        self.assertNotIn('2—3分钟', section['introHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)


if __name__ == '__main__':
    unittest.main()
