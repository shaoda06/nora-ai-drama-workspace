import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main


class ReleaseTests(unittest.TestCase):
    def test_only_matching_built_frontend_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'release.json'
            with patch.object(main, 'FRONTEND_RELEASE', manifest), TestClient(main.app) as client:
                response = client.get('/api/service')
                self.assertFalse(response.json()['ready'])
                self.assertEqual(response.headers['cache-control'], 'no-store')
                manifest.write_text(json.dumps({'version': 'previous-release'}), encoding='utf-8')
                self.assertFalse(client.get('/api/service').json()['ready'])
                manifest.write_text(json.dumps({'version': main.VERSION}), encoding='utf-8')
                data = client.get('/api/service').json()
                self.assertTrue(data['ready'])
                self.assertEqual(data['version'], main.VERSION)

    def test_html_revalidates_on_refresh(self):
        with TestClient(main.app) as client:
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-cache')


if __name__ == '__main__':
    unittest.main()
