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

    def test_list_and_download_formal_pairs_only(self):
        content = '{"节点": 128}\n'.encode('utf-8')
        for suffix in ('workflow', 'api'):
            (self.root / f'视频-去油版.{suffix}.json').write_bytes(content)
        archive = self.root / '非正式工作流'
        archive.mkdir()
        (archive / '旧版.workflow.json').write_bytes(content)
        (self.root / 'notes.json').write_bytes(content)
        items = self.client.get('/api/workflows').json()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['explicitOnly'])
        for key in ('canvasUrl', 'apiUrl'):
            response = self.client.get(items[0][key])
            self.assertEqual(response.content, content)
            self.assertIn('attachment;', response.headers['content-disposition'])
        for path in ('notes.json', 'missing.api.json', '非正式工作流%2F旧版.workflow.json', '..%5Coutside.api.json'):
            self.assertEqual(self.client.get('/api/workflows/files/' + path).status_code, 404)

    def test_missing_api_is_not_a_download_link(self):
        (self.root / '图片.workflow.json').write_text('{}')
        self.assertIsNone(self.client.get('/api/workflows').json()[0]['apiUrl'])
