"""Read-only release directory browsing; fixtures never use real projects."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.parsers.project import build_data
from backend.services.projects import ProjectStore
from tests.http_case import HttpTestCase


class ReleaseFilmsTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / '示例项目'
        self.project.mkdir()
        self.release = self.project / '98-发布成片'
        self.store = ProjectStore(self.root, cache_directory=self.root / '.cache')
        override = patch.object(main, 'store', self.store)
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def put(self, key, content=b'user-owned bytes'):
        target = self.release / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def tree(self):
        return build_data(self.project, load_scope='98-发布成片')['catalogues']['98-发布成片']

    def test_directory_navigation_and_original_structure_without_index_or_approval(self):
        self.put('最终 成片.MP4')
        self.put('分平台/竖屏版.mov')
        self.put('分平台/字幕/说明.srt')
        self.put('原工程.prproj')
        self.put('随附说明.md', b'\xff\xfe')  # Listing must not parse arbitrary user text.
        (self.release / '待导出/空子目录').mkdir(parents=True)
        data = build_data(self.project, load_scope='98-发布成片')
        self.assertEqual(data['directories'], [{'name': '98-发布成片', 'label': '发布成片', 'url': '98-%E5%8F%91%E5%B8%83%E6%88%90%E7%89%87/'}])
        children = data['catalogues']['98-发布成片']['children']
        self.assertEqual([item['kind'] for item in children[:3]], ['file', 'video', 'document'])
        self.assertEqual([item['name'] for item in children[3:]], ['分平台', '待导出'])
        self.assertEqual(children[-1]['children'][0]['children'], [])
        self.assertEqual(children[1]['key'], '98-发布成片/最终 成片.MP4')
        self.assertNotIn('statusHtml', children[1])
        self.assertNotIn('prompts', children[1])
        self.assertNotIn('98-发布成片/随附说明.md', data['sources'])
        self.assertEqual(children[3]['children'][1]['children'][0]['name'], '说明.srt')

    def test_missing_and_empty_directory_do_not_create_any_file(self):
        self.assertEqual(self.tree()['children'], [])
        self.assertFalse(self.release.exists())
        self.release.mkdir()
        self.assertEqual(self.tree()['children'], [])
        self.assertEqual(list(self.release.iterdir()), [])

    def test_preview_download_and_range_are_get_only_and_preserve_bytes(self):
        target = self.put('平台 A/最终版 #1.webm', bytes(range(64)))
        before = (target.read_bytes(), target.stat().st_mtime_ns)
        overview = self.client.get('/api/projects/示例项目/overview').json()
        self.assertIn('98-发布成片', [item['name'] for item in overview['directories']])
        response = self.client.get('/api/projects/示例项目/sections/98-发布成片')
        self.assertEqual(response.status_code, 200)
        video = response.json()['children'][0]['children'][0]
        self.assertIn('/api/projects/', video['url'])
        download = self.client.get(video['url'] + '?download=true')
        self.assertEqual(download.content, before[0])
        self.assertIn('attachment;', download.headers['content-disposition'])
        partial = self.client.get(video['url'], headers={'Range': 'bytes=3-8'})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, before[0][3:9])
        for method in ('post', 'put', 'delete'):
            self.assertEqual(getattr(self.client, method)(video['url']).status_code, 405)
        self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)
        self.assertEqual([path.relative_to(self.release).as_posix() for path in self.release.rglob('*')], ['平台 A', '平台 A/最终版 #1.webm'])

    def test_empty_directory_changes_invalidate_the_existing_snapshot(self):
        initial = self.store.snapshot(self.project)
        self.release.mkdir()
        self.assertNotEqual(initial, self.store.snapshot(self.project))
        initial = self.store.snapshot(self.project)
        (self.release / '空目录').mkdir()
        changed = self.store.snapshot(self.project)
        self.assertNotEqual(initial, changed)
        self.store.get('示例项目')
        self.assertEqual(self.store.section('示例项目', '98-发布成片')['catalogues']['98-发布成片']['children'][0]['name'], '空目录')
        (self.release / '空目录').rmdir()
        self.store.refresh('示例项目', self.store.get('示例项目'), self.store.snapshot(self.project))
        self.assertEqual(self.store.section('示例项目', '98-发布成片')['catalogues']['98-发布成片']['children'], [])

    def test_listing_excludes_hidden_files_and_symlink_escape_or_cycles(self):
        self.put('.temporary.mp4')
        self.put('.private/hidden.mp4')
        outside = self.root / 'outside.mp4'
        outside.write_bytes(b'outside')
        try:
            (self.release / 'escape.mp4').symlink_to(outside)
            (self.release / 'cycle').symlink_to(self.release, target_is_directory=True)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows未授予创建符号链接权限')
            raise
        self.assertEqual(self.tree()['children'], [])
        self.assertEqual(self.client.get('/api/projects/示例项目/files/98-发布成片/escape.mp4').status_code, 404)

    def test_overview_does_not_walk_release_contents_or_parse_user_files(self):
        self.put('最终版.mp4')
        with patch.object(Path, 'iterdir', autospec=True, side_effect=Path.iterdir) as walk:
            # Normal overview may read the project root, but not this release tree.
            build_data(self.project, load_scope='overview')
            self.assertNotIn(self.release, [call.args[0] for call in walk.call_args_list])
