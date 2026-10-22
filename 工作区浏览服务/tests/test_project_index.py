"""Project ordering and initialization use isolated workspaces."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.http_case import HttpTestCase
from backend import main
from backend.services.projects import ProjectStore
from project_init import initialize


class ProjectIndexTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'projects'
        self.root.mkdir()
        self.index = self.root / '项目总索引.md'
        for name in ('甲项目', '乙项目', '丙项目'):
            (self.root / name).mkdir()
        self.store = ProjectStore(self.root)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        override = patch.object(main, 'store', self.store)
        override.start()
        self.addCleanup(override.stop)

    def names(self):
        response = self.client.get('/api/projects')
        response.raise_for_status()
        return [row['name'] for row in response.json()]

    def test_api_uses_index_order_and_reads_edits_without_restart_or_rewrite(self):
        self.index.write_text('# 项目总索引\n\n1. 甲项目\n2. 丙项目\n3. 乙项目\n', encoding='utf-8')
        self.assertEqual(self.names(), ['甲项目', '丙项目', '乙项目'])
        source = '# 项目总索引\r\n\r\n1. 乙项目\r\n2. 甲项目\r\n3. 丙项目\r\n'
        self.index.write_bytes(source.encode('utf-8-sig'))
        self.assertEqual(self.names(), ['乙项目', '甲项目', '丙项目'])
        self.assertEqual(self.index.read_bytes(), source.encode('utf-8-sig'))

    def test_unlisted_projects_append_and_stale_or_duplicate_entries_do_not_add_cards(self):
        self.index.write_text('# 项目总索引\n\n1. 甲项目\n2. 已移除项目\n3. 甲项目\n', encoding='utf-8')
        self.assertEqual(self.names(), ['甲项目', *sorted(['乙项目', '丙项目'])])

    def test_missing_index_keeps_discovery_and_excludes_hidden_directories_and_files(self):
        (self.root / '.hidden').mkdir()
        (self.root / 'README.md').write_text('说明', encoding='utf-8')
        self.assertEqual(self.names(), sorted(['甲项目', '乙项目', '丙项目']))
        self.assertFalse(self.index.exists())

    def test_initialization_appends_project_to_api_and_episode_keeps_order(self):
        self.index.write_text('# 项目总索引\n\n1. 甲项目\n2. 丙项目\n3. 乙项目\n', encoding='utf-8')
        project = self.root / '新项目'
        self.assertTrue(initialize(project)['index_added'])
        self.assertEqual(self.names(), ['甲项目', '丙项目', '乙项目', '新项目'])
        self.assertFalse(initialize(project)['index_added'])
        initialize(project, 'EP001')
        self.assertEqual(self.names(), ['甲项目', '丙项目', '乙项目', '新项目'])

    def test_index_document_renders_actual_source_read_only_and_reads_changes(self):
        source = '# 项目总索引\n\n1. 甲项目\n2. <script>乙项目</script>\n'
        self.index.write_text(source, encoding='utf-8-sig')
        response = self.client.get('/api/project-index')
        response.raise_for_status()
        self.assertEqual(response.json()['title'], '项目总索引')
        self.assertIn('<ol>', response.json()['html'])
        self.assertIn('&lt;script&gt;', response.json()['html'])
        self.assertNotIn('<script>', response.json()['html'])
        self.assertNotIn('url', response.json())
        self.assertEqual(self.index.read_text(encoding='utf-8-sig'), source)
        self.index.write_text('# 项目总索引\n\n1. 乙项目\n', encoding='utf-8')
        self.assertIn('乙项目', self.client.get('/api/project-index').json()['html'])
        self.assertNotIn('甲项目', self.client.get('/api/project-index').json()['html'])

    def test_missing_index_document_reports_missing_without_creating_file(self):
        response = self.client.get('/api/project-index')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['detail'], '项目总索引尚未建立')
        self.assertFalse(self.index.exists())
