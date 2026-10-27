import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import main
from backend.parsers.video_products import load_products
from backend.services.projects import ProjectStore
from backend.services.episode_downloads import completed_episode_videos, resources
from tests.http_case import HttpTestCase

class VideoProductTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.project = self.root / '示例项目'
        self.episode = '09-剧集制作/EP001'; self.identity = 'EP001-C001-P001-R001-后处理'
        self.manifest = self.episode + '/其他资料/执行附件/' + self.identity + '/后处理产物.json'
        self.write('00-项目定位/项目基本定位.md', '# 项目定位')
        self.write(self.episode + '/02-剧集剧本/EP001-本集剧本.md', '## 1. 故事剧本正文\n### EP001-C001\n剧情。')
        self.write(self.episode + '/03-分镜脚本/EP001-分镜索引.md', '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n| EP001-C001 | EP001-C001-P001 | 6 |')
        self.base = self.episode + '/06-阶段采用视频/03-后处理/C001-场次/' + self.identity + '.mp4'
        self.write(self.base, 'green')
        self.final = self.episode + '/其他资料/执行附件/' + self.identity + '/配套交付/transparent.mov'
        self.preview = self.final.replace('transparent.mov', 'preview.mp4')
        self.write(self.final, 'alpha'); self.write(self.preview, 'checker')
        self.rows = [{'id': 'alpha', 'label': '透明 MOV', 'role': '最终产物', 'file': self.final, 'preview': self.preview, 'previewNote': '棋盘格为预览'},
                     {'id': 'green', 'label': '绿底 MP4', 'role': '过程产物', 'file': self.base}]
        self.store = ProjectStore(self.root)
        override = patch.object(main, 'store', self.store); override.start(); self.addCleanup(override.stop)
        self.client = TestClient(main.app); self.addCleanup(self.client.close)

    def write(self, key, text):
        path = self.project / key; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)

    def save_manifest(self):
        self.write(self.manifest, json.dumps({'products': self.rows}))

    def parse(self):
        response = self.client.get('/api/projects/示例项目/episodes/EP001')
        self.assertEqual(response.status_code, 200, response.text[:300]); return response.json()

    def test_legacy_single_output_is_unchanged(self):
        videos = self.parse()['segments']['C001'][0]['videos']
        self.assertEqual(len(videos), 1); self.assertNotIn('products', videos[0]); self.assertEqual(videos[0]['key'], self.base)

    def approved_final(self):
        self.save_manifest()
        self.write(self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md', '''## 1. 当前选定结果
| 处理阶段 | 当前选定文件 | R编号 | 人工批准依据 |
| --- | --- | --- | --- |
| 后处理 | [透明](../执行附件/EP001-C001-P001-R001-后处理/配套交付/transparent.mov) | R001 | [采用](#审阅-透明交付) |
## 2. 修订记录
### R001-后处理
- 处理阶段：后处理
## 审阅-透明交付
- 对应具体输出：transparent.mov
- 决定：批准采用
''')

    def test_manifest_approval_preview_and_download_share_one_revision(self):
        self.approved_final()
        episode = self.parse(); videos = episode['segments']['C001'][0]['videos']; self.assertEqual(len(videos), 1)
        video = videos[0]; self.assertTrue(video['approved']); self.assertEqual(video['candidateNumber'], 1)
        self.assertEqual([p['role'] for p in video['products']], ['最终产物', '过程产物'])
        product = video['products'][0]
        self.assertEqual(self.client.get(product['url']).content, b'alpha')
        self.assertEqual(self.client.get(product['previewUrl']).content, b'checker')
        episode['productionComplete'] = True; episode['productionIssues'] = []
        data = {'catalogues': {'09-剧集制作': {'children': [episode]}}}
        self.assertEqual(completed_episode_videos(self.store, '示例项目', 'EP001', data)[0][0], (self.project / self.final).resolve())
        self.assertEqual(resources(self.store, '示例项目', 'EP001', data)['后处理']['videos'][0][0], (self.project / self.final).resolve())
        self.assertEqual(len(resources(self.store, '示例项目', 'EP001', data)['后处理']['videos']), 1)

    def test_review_must_name_the_exact_final_file(self):
        self.approved_final()
        draft = self.project / self.episode / '其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md'
        text = draft.read_text()
        for name in ('backup.transparent.mov', 'not-transparent.mov', 'transparent.mov.bak'):
            with self.subTest(name=name):
                draft.write_text(text.replace('- 对应具体输出：transparent.mov', '- 对应具体输出：' + name))
                store = ProjectStore(self.root)
                data = store.section('示例项目', '09-剧集制作', 'EP001')
                self.assertFalse(data['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos'][0]['approved'])

    def test_relative_path_spellings_share_the_approved_product_key(self):
        self.approved_final()
        for spelling in ('./' + self.final, self.final.replace('/', '\\')):
            with self.subTest(spelling=spelling):
                self.rows[0]['file'] = spelling
                self.rows[0]['preview'] = './' + self.preview
                self.save_manifest()
                store = ProjectStore(self.root)
                data = store.section('示例项目', '09-剧集制作', 'EP001')
                video = data['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos'][0]
                self.assertTrue(video['approved'])
                self.assertEqual(video['products'][0]['key'], self.final)
                self.assertEqual(completed_episode_videos(store, '示例项目', 'EP001', {
                    'catalogues': {'09-剧集制作': {'children': [{**data['catalogues']['09-剧集制作']['children'][0], 'productionComplete': True, 'productionIssues': []}]}}
                })[0][0], (self.project / self.final).resolve())

    def test_pre_normalized_product_cache_rebuilds_without_project_edits(self):
        self.approved_final()
        self.rows[0]['file'] = './' + self.final
        self.save_manifest()
        store = ProjectStore(self.root, cache_directory=self.root / '.cache')
        store.section('示例项目', '09-剧集制作', 'EP001', mode='playback')
        cache = self.root / '.cache/示例项目/09-剧集制作--EP001--playback.json'
        saved = json.loads(cache.read_text())
        saved['schema'] = 19
        saved['data']['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos'][0]['approved'] = False
        cache.write_text(json.dumps(saved))
        snapshot = store.snapshot(self.project)
        restart = ProjectStore(self.root, cache_directory=self.root / '.cache')
        data = restart.section('示例项目', '09-剧集制作', 'EP001', mode='playback')
        self.assertTrue(data['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos'][0]['approved'])
        self.assertEqual(json.loads(cache.read_text())['schema'], 20)
        self.assertEqual(restart.snapshot(self.project), snapshot)

    def test_manifest_does_not_approve_a_new_final_from_process_approval(self):
        self.save_manifest()
        self.write(self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md', """## 1. 当前选定结果
| 处理阶段 | 当前选定文件 | R编号 | 人工批准依据 |
| --- | --- | --- | --- |
| 后处理 | [绿底](../../06-阶段采用视频/03-后处理/C001-场次/EP001-C001-P001-R001-后处理.mp4) | R001 | [采用](#审阅-绿底) |
## 2. 修订记录
### R001-后处理
- 处理阶段：后处理
## 审阅-绿底
- 对应具体输出：EP001-C001-P001-R001-后处理.mp4
- 决定：批准采用
""")
        self.assertFalse(self.parse()['segments']['C001'][0]['videos'][0]['approved'])

    def test_invalid_manifest_fails_with_specific_error(self):
        cases = [([], '非空数组'), ([{**r, 'role': '过程产物'} for r in self.rows], '只能指定一项'),
                 ([self.rows[0], self.rows[0]], '不得重复'),
                 ([{**self.rows[0], 'file': '../outside.mov'}], '不存在或越出项目'),
                 ([{**self.rows[0], 'previewNote': ''}], 'previewNote')]
        for rows, message in cases:
            with self.subTest(message=message):
                self.rows = rows; self.save_manifest()
                with self.assertRaisesRegex(ValueError, message):
                    load_products(self.project, self.identity, lambda key, **kwargs: (self.project / key).read_text())
