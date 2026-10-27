"""On-demand loading, data preservation and persistent cache behavior."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.http_case import HttpTestCase
from backend import main
from backend.parsers import project as parser
from backend.services.projects import ProjectStore
from backend.services.revision_notes import NoteChange, RevisionNotes


class ProjectLoadingTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        position = self.project / '00-项目定位/项目基本定位.md'
        position.parent.mkdir(parents=True)
        position.write_text('# 项目定位\n\n## 正文\n项目介绍。', encoding='utf-8')
        self.store = ProjectStore(self.root, cache_directory=self.root / '.cache', version='1.0')
        override = patch.object(main, 'store', self.store)
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_unopened_bad_execution_json_does_not_block_home_or_episode_list(self):
        mapping = self.project / '09-剧集制作/EP001/其他资料/执行附件/任务/输入映射.json'
        mapping.parent.mkdir(parents=True)
        mapping.write_text('{invalid', encoding='utf-8')
        self.assertEqual(self.client.get('/api/projects/示例项目/overview').status_code, 200)
        listing = self.client.get('/api/projects/示例项目/sections/09-剧集制作')
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn('segments', listing.json()['children'][0])
        self.assertEqual(self.client.get('/api/projects/示例项目/episodes/EP001').status_code, 503)
        self.assertEqual(mapping.read_text('utf-8'), '{invalid')
        self.assertEqual(self.store.status('示例项目')['errorKind'], 'read_failed')
        mapping.write_text('{}', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        self.assertEqual(self.client.get('/api/projects/示例项目/episodes/EP001').status_code, 200)
        self.assertIsNone(self.store.status('示例项目')['error'])

    def test_history_preview_loads_current_content_without_initializing_other_columns(self):
        history = self.project / '00-项目定位/其他资料/历史版本/说明.md'
        history.parent.mkdir(parents=True)
        history.write_text('# 历史说明\n原文保留。', encoding='utf-8')
        self.client.get('/api/projects/示例项目/overview').raise_for_status()
        base = self.store.get('示例项目')['data']
        self.assertNotIn(history.relative_to(self.project).as_posix(), base['documents'])
        preview = self.client.get('/api/projects/示例项目/document', params={'path': history.relative_to(self.project).as_posix()})
        self.assertIn('原文保留', preview.json()['html'])
        self.assertEqual(self.client.get('/api/projects/示例项目/document', params={'path': '../outside.md'}).status_code, 404)

    def test_release_version_changes_reuse_compatible_overview_and_section_cache(self):
        first = self.store.get('示例项目')['data']
        section = self.store.section('示例项目', '00-项目定位')
        second = ProjectStore(self.root, cache_directory=self.root / '.cache', version='2.0')
        with patch('backend.services.projects.build_data', side_effect=AssertionError('unexpected rebuild')):
            self.assertEqual(second.get('示例项目')['data'], first)
            self.assertEqual(second.section('示例项目', '00-项目定位'), section)

    def test_source_refresh_invalidates_loaded_section_and_keeps_original_file(self):
        first = self.store.section('示例项目', '00-项目定位')
        source = self.project / '00-项目定位/项目基本定位.md'
        source.write_text('# 项目定位\n\n## 正文\n新的介绍。', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        second = self.store.section('示例项目', '00-项目定位')
        self.assertNotEqual(first['positionHtml'], second['positionHtml'])
        self.assertIn('新的介绍', second['positionHtml'])
        self.assertIn('新的介绍', source.read_text('utf-8'))

    def test_missing_episode_and_scope_do_not_read_outside_project(self):
        self.assertEqual(self.client.get('/api/projects/示例项目/episodes/EP999').status_code, 404)
        self.assertEqual(self.client.get('/api/projects/示例项目/sections/not-a-column').status_code, 404)
        with self.assertRaises(FileNotFoundError):
            self.store.section('示例项目', '../outside')

    def test_episode_detail_keeps_previous_ending_and_first_episode_has_none(self):
        for number, scene, segment in [('EP001', 'C002', 'P009'), ('EP002', 'C001', 'P001')]:
            root = self.project / '09-剧集制作' / number
            script = root / '02-剧集剧本' / (number + '-本集剧本.md')
            script.parent.mkdir(parents=True)
            script.write_text('# 剧本\n## 1. 故事剧本正文\n### ' + number + '-' + scene + '\n正文。', encoding='utf-8')
            index = root / '03-分镜脚本' / (number + '-分镜索引.md')
            index.parent.mkdir()
            index.write_text('| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n| ' + number + '-' + scene + ' | ' + number + '-' + scene + '-' + segment + ' | 8 |\n', encoding='utf-8')
            if number == 'EP001':
                with index.open('a', encoding='utf-8') as stream:
                    stream.write('| EP001-C002 | EP001-C002-P003 | 4 |\n')
        first = self.client.get('/api/projects/示例项目/episodes/EP001').json()
        second = self.client.get('/api/projects/示例项目/episodes/EP002').json()
        self.assertIsNone(first['previousEpisode'])
        self.assertEqual(second['previousEpisode']['name'], 'EP001')
        self.assertEqual(second['previousEpisode']['scenes'], ['C002'])
        self.assertEqual([item['id'] for item in second['previousEpisode']['segments']['C002']], ['P003'])
        self.assertEqual([item['id'] for item in first['segments']['C002']], ['P009', 'P003'])
        self.assertEqual(second['segments']['C001'][0]['id'], 'P001')

    def test_episode_list_retains_source_warnings(self):
        index = self.project / '06-分集大纲/分集索引.md'
        index.parent.mkdir()
        index.write_text('| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n| EP001 | 测试 | 错误入口 |\n', encoding='utf-8')
        listing = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertTrue(any('EP001大纲入口未识别' in warning for warning in listing['warnings']))

    def test_pre_director_sheet_cache_is_rebuilt_without_editing_source_images(self):
        image = self.project / '09-剧集制作/EP001/03-分镜脚本/导演分镜表/EP001-C001-手绘导演分镜表-第01页.png'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'unchanged image fixture')
        self.store.section('示例项目', '09-剧集制作', 'EP001', mode='playback')
        cache = self.root / '.cache/示例项目/09-剧集制作--EP001--playback.json'
        saved = json.loads(cache.read_text('utf-8'))
        saved['schema'] = 8
        del saved['data']['catalogues']['09-剧集制作']['children'][0]['directorSheets']
        cache.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        restart = ProjectStore(self.root, cache_directory=self.root / '.cache', version='new-release')
        parsed = restart.section('示例项目', '09-剧集制作', 'EP001', mode='playback')
        sheets = parsed['catalogues']['09-剧集制作']['children'][0]['directorSheets']['C001']
        self.assertEqual(len(sheets['formal']), 1)
        self.assertEqual(image.read_bytes(), b'unchanged image fixture')

    def test_pre_sc_view_cache_rebuilds_classification_without_source_edits(self):
        folder = self.project / '04-场景资料/SC001-办公室'
        folder.mkdir(parents=True)
        (folder / 'SC001-办公室-资料卡.md').write_text('# 办公室\n独立场景。\n', encoding='utf-8')
        (folder.parent / '场景索引.md').write_text(
            '| 场景编号 | 名称 | 场景类型 | 资料卡入口 |\n| --- | --- | --- | --- |\n'
            '| SC001 | 办公室 | 室内 | [资料卡](SC001-办公室/SC001-办公室-资料卡.md) |\n', encoding='utf-8')
        image = folder / '参考图/SC001-V001-场景参考图.png'
        image.parent.mkdir()
        image.write_bytes(b'unchanged scene image fixture')
        self.store.section('示例项目', '04-场景资料')
        cache = self.root / '.cache/示例项目/04-场景资料.json'
        saved = json.loads(cache.read_text('utf-8'))
        saved['schema'] = 18
        scene = saved['data']['scenes'][0]
        scene['auxiliary'] = scene['formal']
        scene['formal'] = []
        cache.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        snapshot = self.store.snapshot(self.project)

        restart = ProjectStore(self.root, cache_directory=self.root / '.cache', version='1.0')
        parsed = restart.section('示例项目', '04-场景资料')
        scene = parsed['scenes'][0]
        self.assertEqual(len(scene['formal']), 1)
        self.assertEqual(scene['formal'][0]['state'], 'V001')
        self.assertFalse(scene['formal'][0]['approved'])
        self.assertEqual(scene['auxiliary'], [])
        self.assertIsNone(scene['cover'])
        self.assertEqual(json.loads(cache.read_text('utf-8'))['schema'], 21)
        self.assertEqual(self.store.snapshot(self.project), snapshot)
        self.assertEqual(image.read_bytes(), b'unchanged scene image fixture')

    def test_playback_cache_survives_unrelated_edits_and_restart_but_refreshes_own_episode(self):
        root = self.project / '09-剧集制作/EP001'
        root.mkdir(parents=True)
        first = self.store.section('示例项目', '09-剧集制作', 'EP001', mode='playback')
        unrelated = self.project / '09-剧集制作/EP002/其他资料/工作稿/备注.md'
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('另一集改动', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        self.assertIs(self.store.section('示例项目', '09-剧集制作', 'EP001', mode='playback'), first)
        restart = ProjectStore(self.root, cache_directory=self.root / '.cache', version='new-release')
        with patch('backend.services.projects.build_data', side_effect=AssertionError('unrelated edit rebuilt EP001')):
            self.assertEqual(restart.section('示例项目', '09-剧集制作', 'EP001', mode='playback'), first)
        (root / '备注.md').write_text('本集改动', encoding='utf-8')
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        self.assertIsNot(self.store.section('示例项目', '09-剧集制作', 'EP001', mode='playback'), first)

    def test_review_note_save_preserves_playback_cache_in_memory_and_after_restart(self):
        (self.project / '09-剧集制作/EP001').mkdir(parents=True)
        first = self.store.section('示例项目', '09-剧集制作', 'EP001', mode='playback')
        RevisionNotes().save(self.project, 'EP001', 'C001', NoteChange(
            segment='P001', stage='一采', run='R001', text='动作需连贯', fileRevision='123-456', expectedText=''))
        self.assertIs(self.store.section('示例项目', '09-剧集制作', 'EP001', mode='playback'), first)
        restart = ProjectStore(self.root, cache_directory=self.root / '.cache', version='new-release')
        with patch('backend.services.projects.build_data', side_effect=AssertionError('note save rebuilt playback')):
            self.assertEqual(restart.section('示例项目', '09-剧集制作', 'EP001', mode='playback'), first)
