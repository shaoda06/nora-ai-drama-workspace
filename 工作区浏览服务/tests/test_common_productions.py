"""Shared opening/ending units use the normal production lifecycle in temporary projects."""
import json
from pathlib import Path
import tempfile
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
            self.assertEqual(video_archive_name('项目', name), f'项目-{name}-正式版视频.zip')
        catalogue = self.projects.section(self.project.name, '09-剧集制作')['catalogues']['09-剧集制作']
        self.assertEqual([item['name'] for item in catalogue['children']], ['片头', '片尾', 'EP001'])
        self.assertEqual(catalogue['statistics'], {'total': 1, 'completed': 1, 'notStarted': 0, 'running': 0})
        self.assertEqual(self.client.get(f'/api/projects/{self.project.name}/episodes/自定义目录').status_code, 422)

    def test_native_image_registration_materials_and_original_file_download(self):
        for name in ('片头', '片尾'):
            base, _, _ = self.unit(name)
            request = self.write(base + '/其他资料/执行附件/请求.json', json.dumps({
                'kind': '剧集素材', 'object': name, 'image_type': '片尾静态图',
                'title': '独立共用对象', 'purpose': '临时测试',
                'draft': base + '/其他资料/工作稿/' + name + '-专用素材制作-工作稿.md',
                'output': base + '/其他资料/工作稿/素材/' + name + '-候选-v01.png',
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
