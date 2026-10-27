"""Project previews are documents, not trusted workbench code. Temp files only."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.services.projects import ProjectStore
from tests.http_case import HttpTestCase


class ProjectFileSecurityTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / '预览示例'
        self.project.mkdir()
        override = patch.object(main, 'store', ProjectStore(self.root))
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_active_project_documents_have_opaque_origin_and_no_api_connections(self):
        for name in ('preview.html', 'preview.xhtml', 'preview.svg', 'preview.xml'):
            with self.subTest(name=name):
                (self.project / name).write_text('<script>document.title="预览"</script>', 'utf-8')
                response = self.client.get('/api/projects/预览示例/files/' + name)
                self.assertEqual(response.status_code, 200)
                policy = response.headers['Content-Security-Policy']
                directives = dict((part.strip().split(' ', 1) + [''])[:2] for part in policy.split(';'))
                self.assertEqual(directives['sandbox'], 'allow-scripts')
                self.assertEqual(directives['connect-src'], "'none'")
                self.assertEqual(directives['form-action'], "'none'")
                self.assertEqual(directives['base-uri'], "'none'")
                self.assertIn('预览', response.text)

    def test_explicit_download_still_returns_original_bytes_as_attachment(self):
        content = b'<html>download example</html>'
        (self.project / 'preview.html').write_bytes(content)
        response = self.client.get('/api/projects/预览示例/files/preview.html?download=true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)
        self.assertEqual(response.headers['content-type'], 'application/octet-stream')
        self.assertIn('attachment;', response.headers['content-disposition'])

    def test_video_range_response_keeps_streaming_bytes(self):
        (self.project / 'video.webm').write_bytes(b'0123456789')
        response = self.client.get('/api/projects/预览示例/files/video.webm', headers={'Range': 'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'2345')
        self.assertEqual(response.headers['content-range'], 'bytes 2-5/10')
