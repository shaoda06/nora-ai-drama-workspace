"""Shared opening/ending units use the normal production lifecycle in temporary projects."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.parsers.scene_rounds import rounds
from backend.services import imagegen_results as native
from backend.services.episode_downloads import video_archive_name
from backend.services.projects import ProjectStore
from tests.http_case import HttpTestCase
from tests.test_image_closeout import png


class CommonProductionTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.project = self.root / '共用素材项目'
        self.project.mkdir()
        self.projects = ProjectStore(self.root)
        override = patch.object(main, 'store', self.projects)
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.write('项目进度.md', '# 项目进度\n| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n'
                   '| --- | --- | --- | --- | --- | --- |\n'
                   '| EP001制作 | 本会话 | 已完成 | 无 | 无 | 无 |\n'
                   '| 片头制作 | 本会话 | 进行中 | 无 | 无 | 无 |\n'
                   '| 片尾制作 | 本会话 | 待确认 | 无 | 无 | 无 |\n')

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def unit(self, name):
        base = '09-剧集制作/' + name
        script = base + '/02-剧集剧本/' + name + '-本集剧本.md'
        board = base + '/03-分镜脚本/' + name + '-C001-场次分镜.md'
        self.write(script, f'# 内容稿\n- 文档版本：v01\n## 1. 故事剧本正文\n### {name}-C001\n纸飞机飞走。\n')
        self.write(board, f'# 分镜\n- 文档版本：v01\n## 1. 镜头正文\n### 分段 P001\n'
                   f'#### {name}-C001-SH001\n**时长**：4秒\n纸飞机飞走。\n')
        self.write(base + '/03-分镜脚本/' + name + '-分镜索引.md',
                   '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                   f'| {name}-C001 | {name}-C001-P001 | 4 |\n')
        self.write(base + '/其他资料/工作稿/' + name + '-C001-P001-视频制作-工作稿.md',
                   '# 工作稿\n### R001-一采\n- 用户决定：待审核\n')
        video = self.project / (base + '/其他资料/候选视频/' + name + '-C001-P001-R001-一采.mp4')
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b'isolated-video-fixture')
        return base, script, board

    def test_shared_units_use_episode_http_and_rounds_without_changing_episode_counts(self):
        self.unit('EP001')
        for name in ('片头', '片尾'):
            base, script, board = self.unit(name)
            rounds.create_round(self.project, name, 'C001', {
                'note': '共用对象正常制作', 'script': {'file': script, 'version': 'v01'},
                'storyboard': {'file': board, 'version': 'v01'},
                'segments': [{'id': 'P001', 'stage': '一采', 'run': 'R001', 'duration': 4}]})
            response = self.client.get(f'/api/projects/{self.project.name}/episodes/{name}')
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertIsNone(data['previousEpisode'])
            self.assertEqual(data['scenes'], ['C001'])
            self.assertEqual(data['productionIssues'], [])
            self.assertEqual(data['sceneRounds']['C001'][0]['segments'][0]['id'], 'P001')
            self.assertEqual(data['segments']['C001'][0]['videos'][0]['run'], 'R001')
            self.assertEqual(video_archive_name('项目', name), f'项目-{name}-已采用视频.zip')
        catalogue = self.projects.section(self.project.name, '09-剧集制作')['catalogues']['09-剧集制作']
        self.assertEqual([item['name'] for item in catalogue['children']], ['片头', '片尾', 'EP001'])
        self.assertEqual(catalogue['statistics'], {'total': 1, 'completed': 1, 'notStarted': 0, 'running': 0})
        self.assertEqual(self.client.get(f'/api/projects/{self.project.name}/episodes/自定义目录').status_code, 422)

    def test_native_image_registration_materials_and_original_file_download(self):
        for name in ('片头', '片尾'):
            base, _, _ = self.unit(name)
            request = self.write(base + '/其他资料/执行附件/请求.json', json.dumps({
                'kind': '剧集素材', 'object': name, 'image_type': name + '静态图',
                'title': '独立共用对象', 'purpose': '临时测试',
                'draft': base + '/其他资料/工作稿/' + name + '-专用素材制作-工作稿.md',
                'formal': base + '/04-专用素材/' + name + '-静态图.png',
                'output': base + '/其他资料/工作稿/素材/' + name + '-静态图-候选-v01.png',
                'prompt': '测试原文', 'authorization': '隔离测试，不调用生成',
                'ratio': '16:9', 'formal_size': [1920, 1080]}, ensure_ascii=False))
            job = native.prepare(self.project, request)
            source = self.root / (name + '.png')
            source.write_bytes(png(7, 5))
            receipt = self.write(job['record'] + '/实际调用结果.json', json.dumps({
                'source': str(source), 'actual_prompt': '测试原文'}))
            result = native.complete(self.project, job['manifest'], receipt, self.projects)
            self.assertTrue(result['user_message_ready'])
            response = self.client.get(f'/api/projects/{self.project.name}/episodes/{name}')
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual([item['key'] for item in data['materials']], [job['candidate']])
            self.assertEqual(data['materialRecord']['key'], job['draft'])
            image = self.client.get(data['materials'][0]['url'])
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, source.read_bytes())
            before = (self.project / job['draft']).read_bytes()
            again = native.complete(self.project, job['manifest'], receipt, self.projects)
            self.assertTrue(again['user_message_ready'])
            self.assertEqual((self.project / job['draft']).read_bytes(), before)

    def test_design_drafts_are_readable_before_any_video_or_round_exists(self):
        for name in ('片头', '片尾', 'EP002'):
            base = '09-剧集制作/' + name
            work = base + '/其他资料/工作稿/'
            chapter = '1. 故事剧本正文' if name.startswith('EP') else '3. 动画内容'
            for identity, body in (
                (name + '-本集剧本', f'## {chapter}\n### {name}-C001\n纸飞机沿弧线飞走。'),
                (name + '-C001-场次分镜', f'## 1. 镜头正文\n### 分段 P001\n#### {name}-C001-SH001\n**时长**：3秒\n原图文字保持。'),
                (name + '-分镜索引', '## 分段索引\n| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n' + f'| {name}-C001 | {name}-C001-P001 | 3 |'),
                (name + '-生成说明', '## 1. 制作依据\n生成4秒，采用0至3秒。'),
                (name + '-C001-P001-视频提示词', '## 提交给模型的完整提示词\n纸飞机飞走。'),
            ):
                content = f'# {identity}\n- 文档版本：v01\n- 确认状态：待确认\n\n' + body
                content = '\n'.join('##' + line if line.startswith('#') else line for line in content.splitlines())
                self.write(work + identity + '-工作稿.md', '# 工作稿\n- 当前稿版本：v01\n\n## 1. 当前内容\n\n' + content + '\n\n## 2. 讨论与修改\n')
            response = self.client.get(f'/api/projects/{self.project.name}/episodes/{name}')
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data['productionIssues'], [])
            self.assertEqual(data['scenes'], ['C001'])
            self.assertEqual(data['segments']['C001'][0]['duration'], 3)
            self.assertEqual(data['segments']['C001'][0]['videos'], [])
            self.assertEqual(data['sceneRounds']['C001'], [])
            for item in (data['script'], data['storyboards']['C001'], data['storyboardIndex'], data['generationPlan'], data['videoPrompts'][0]):
                self.assertIn('-工作稿.md', item['key'])
                self.assertEqual(item['doc']['meta']['确认状态'], '待确认')
            self.assertIn('采用0至3秒', data['generationPlan']['doc']['html'])

    def test_storyboard_remains_readable_without_script_or_segment_index(self):
        self.write('09-剧集制作/片尾/03-分镜脚本/片尾-C001-场次分镜.md',
                   '# 分镜\n## 1. 镜头正文\n飞机起飞，文字保持。')
        data = self.client.get(f'/api/projects/{self.project.name}/episodes/片尾').json()
        self.assertIsNone(data['script'])
        self.assertEqual(data['scenes'], ['C001'])
        self.assertIn('飞机起飞', data['storyboards']['C001']['doc']['html'])
        self.assertEqual(data['segments']['C001'], [])

    def test_out_of_script_board_keeps_document_and_reports_source_conflict(self):
        self.unit('片尾')
        self.write('09-剧集制作/片尾/03-分镜脚本/片尾-C002-场次分镜.md',
                   '# 待核对分镜\n## 1. 镜头正文\n独立正文。')
        data = self.client.get(f'/api/projects/{self.project.name}/episodes/片尾').json()
        self.assertEqual(data['scenes'], ['C001'])
        self.assertIn('C002', data['storyboards'])
        self.assertTrue(any('未在上游正文中定义' in item['message'] for item in data['productionIssues']))

    def test_execution_preflight_accepts_shared_design_chapter(self):
        from backend.services.execution_checks import storyboard_index_checks
        for name in ('片头', '片尾'):
            _, script, _ = self.unit(name)
            self.write(script, f'# 内容稿\n## 3. 动画内容\n### {name}-C001\n飞机飞走。')
            result = storyboard_index_checks(SimpleNamespace(project=self.project), {'scene': name + '-C001'})
            self.assertTrue(result['ok'])
            self.assertEqual(result['rows'], 1)
