import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main


class WorkflowTests(unittest.TestCase):
    def setUp(self):
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
        for suffix in ('workflow', 'api'):
            (self.root / f'视频-去油版.{suffix}.json').write_bytes(content)
        archive = self.root / '非正式工作流'
        archive.mkdir()
        for suffix in ('workflow', 'api'):
            (archive / f'备用.{suffix}.json').write_bytes(content)
        nested = archive / '历史'
        nested.mkdir()
        (nested / '旧版.api.json').write_bytes(content)
        (self.root.parent / 'outside.api.json').write_bytes(content)
        (self.root / 'notes.json').write_bytes(content)
        items = self.client.get('/api/workflows').json()
        self.assertEqual(len(items), 2)
        self.assertEqual([item['group'] for item in items], ['formal', 'backup'])
        self.assertTrue(items[0]['explicitOnly'])
        for item in items:
            for key in ('canvasUrl', 'apiUrl'):
                response = self.client.get(item[key])
                self.assertEqual(response.content, content)
                self.assertIn('attachment;', response.headers['content-disposition'])
        for path in ('notes.json', 'missing.api.json', '非正式工作流/历史/旧版.api.json', '..%5Coutside.api.json', '非正式工作流%2F..%2F..%2Foutside.api.json'):
            self.assertEqual(self.client.get('/api/workflows/files/' + path).status_code, 404)

    def test_missing_api_is_not_a_download_link(self):
        (self.root / '图片.workflow.json').write_text('{}')
        self.assertIsNone(self.client.get('/api/workflows').json()[0]['apiUrl'])
