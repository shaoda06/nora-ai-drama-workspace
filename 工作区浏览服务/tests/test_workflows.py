import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.http_case import HttpTestCase
from backend import main
from workflow_paths import workflow_file


class WorkflowTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workflows'
        self.root.mkdir()
        override = patch.object(main, 'WORKFLOWS', self.root)
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_list_and_download_formal_and_backup_pairs(self):
        content = '{"节点": 128}\n'.encode('utf-8')
        for category, name in (('Qwen-image-2-1', '图片'), ('Minimax-H3', '视频'),
                               ('后处理综合', '后处理'), ('非正式工作流', '备用')):
            directory = self.root / category
            directory.mkdir()
            for suffix in ('workflow', 'api'):
                (directory / f'{name}.{suffix}.json').write_bytes(content)
        archive = self.root / '非正式工作流'
        nested = archive / '历史'
        nested.mkdir()
        (nested / '旧版.api.json').write_bytes(content)
        (self.root.parent / 'outside.api.json').write_bytes(content)
        (self.root / 'notes.json').write_bytes(content)
        (self.root / '未归类.api.json').write_bytes(content)
        other = self.root / '未登记目录'
        other.mkdir()
        (other / '其他.workflow.json').write_bytes(content)
        (other / '其他.api.json').write_bytes(content)
        items = self.client.get('/api/workflows').json()
        self.assertEqual(len(items), 4)
        self.assertEqual([item['group'] for item in items], ['formal', 'formal', 'formal', 'backup'])
        for item in items:
            for key in ('canvasUrl', 'apiUrl'):
                response = self.client.get(item[key])
                self.assertEqual(response.content, content)
                self.assertIn('attachment;', response.headers['content-disposition'])
        for path in ('notes.json', '未归类.api.json', '未登记目录/其他.api.json', 'missing.api.json', '非正式工作流/历史/旧版.api.json', '..%5Coutside.api.json', '非正式工作流%2F..%2F..%2Foutside.api.json'):
            self.assertEqual(self.client.get('/api/workflows/files/' + path).status_code, 404)

    def test_missing_api_is_not_a_download_link(self):
        category = self.root / 'Qwen-image-2-1'
        category.mkdir()
        (category / '图片.workflow.json').write_text('{}')
        self.assertIsNone(self.client.get('/api/workflows').json()[0]['apiUrl'])

    def test_formal_lookup_follows_category_move_and_rejects_ambiguity(self):
        first = self.root / 'Qwen-image-2-1'
        second = self.root / '后处理综合'
        first.mkdir()
        second.mkdir()
        source = first / '样例.workflow.json'
        source.write_text('{}')
        self.assertEqual(workflow_file('样例', root=self.root), source)
        moved = second / source.name
        source.rename(moved)
        self.assertEqual(workflow_file('样例', root=self.root), moved)
        source.write_text('{}')
        with self.assertRaisesRegex(ValueError, '2份'):
            workflow_file('样例', root=self.root)

    def test_formal_lookup_does_not_select_backup(self):
        backup = self.root / '非正式工作流'
        backup.mkdir()
        (backup / '样例.workflow.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '0份'):
            workflow_file('样例', root=self.root)
