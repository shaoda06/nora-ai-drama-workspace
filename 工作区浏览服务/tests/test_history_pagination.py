from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from tests.http_case import HttpTestCase


class HistoryPaginationTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        docs = self.root / 'docs'
        docs.mkdir()
        self.source = docs / '版本记录.md'
        self.text = '# 版本记录\n\n' + ''.join(
            f'### v0.1.{n}：更新{n}\n\n开发记录：[W{n:03}](开发记录/W{n:03}-测试.md)。\n\n内容{n}。\n\n'
            for n in range(23, 0, -1))
        self.source.write_text(self.text, encoding='utf-8')
        (docs / '开发记录规范.md').write_text('# 开发记录规范\n\n### 示例\n\n原正文。', encoding='utf-8')
        override = patch.object(main, 'TOOL', self.root)
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(main.app, base_url='http://localhost:8780')
        self.addCleanup(self.client.close)

    def test_pages_preserve_complete_entries_and_links(self):
        seen = []
        for page, expected in [(1, list(range(23, 13, -1))), (2, list(range(13, 3, -1))), (3, [3, 2, 1])]:
            response = self.client.get('/api/history/document', params={'path': '版本记录.md', 'page': page})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual((data['page'], data['pageSize'], data['total']), (page, 10, 23))
            self.assertEqual(data['html'].count('<h3 '), len(expected))
            for n in expected:
                self.assertIn(f'内容{n}。', data['html'])
                self.assertIn(f'data-doc="开发记录/W{n:03}-测试.md"', data['html'])
            seen += expected
        self.assertEqual(seen, list(range(23, 0, -1)))
        self.assertEqual(self.source.read_text('utf-8'), self.text)

    def test_bounds_and_other_documents(self):
        params = {'path': '版本记录.md', 'page': 999}
        self.assertEqual(self.client.get('/api/history/document', params=params).json()['page'], 3)
        params['page'] = 0
        self.assertEqual(self.client.get('/api/history/document', params=params).status_code, 422)
        data = self.client.get('/api/history/document', params={'path': '开发记录规范.md'}).json()
        self.assertIn('原正文。', data['html'])
        self.assertNotIn('total', data)
        self.assertEqual(self.client.get('/api/history/document', params={'path': '../AGENTS.md'}).status_code, 404)

    def test_empty_version_file(self):
        self.source.write_text('# 版本记录\n', encoding='utf-8')
        data = self.client.get('/api/history/document', params={'path': '版本记录.md'}).json()
        self.assertEqual((data['page'], data['total']), (1, 0))
        self.assertIn('版本记录', data['html'])
