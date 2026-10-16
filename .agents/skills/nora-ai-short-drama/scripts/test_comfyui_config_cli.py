"""Workspace CLI routing against a local fake server; no production credentials or tasks."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

import comfyui_config as config


class ConfigCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.requests = []
        self.fail_core = False
        self.fail_category = False
        self.username, self.password = 'fixture-user', 'fixture-password'
        self.authorization = 'Basic ' + base64.b64encode(
            (self.username + ':' + self.password).encode()).decode()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                authorized = self.headers.get('Authorization') == fixture.authorization
                fixture.requests.append(('GET', self.path, authorized))
                if not authorized:
                    self.send_error(401)
                    return
                route = urlsplit(self.path)
                if route.path == '/system_stats' and fixture.fail_core:
                    self.send_error(503)
                    return
                if route.path == '/models/checkpoints' and fixture.fail_category:
                    self.send_error(503)
                    return
                data = {
                    '/system_stats': {'system': {'comfyui_version': 'fixture'}},
                    '/object_info': {'FixtureNode': {'python_module': 'fixture'}},
                    '/models': ['checkpoints'], '/models/checkpoints': ['fixture.safetensors'],
                    '/queue': {'queue_running': [], 'queue_pending': []},
                    '/history/fixture-id': {},
                }
                if route.path not in data:
                    self.send_error(404)
                    return
                body = json.dumps(data[route.path]).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                fixture.requests.append(('POST', self.path, False))
                self.send_error(405)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'
        self.write_config(self.password)

    def write_config(self, password):
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-nodes': [{
            'url': self.url, 'auth': {'type': 'basic', 'username': self.username,
                                    'password': password}}]}), encoding='utf-8')

    def call(self, *args):
        result = subprocess.run([sys.executable, '-X', 'utf8', config.__file__,
                                 '--workspace', str(self.root), *args],
                                env={**os.environ, 'COMFYUI_URL': self.url},
                                capture_output=True, encoding='utf-8', timeout=15)
        for secret in (self.username, self.password, self.authorization):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def assert_authenticated_reads_only(self):
        self.assertTrue(self.requests)
        self.assertTrue(all(method == 'GET' and authorized
                            for method, _, authorized in self.requests))

    def test_upload_and_submit_rejected_before_network_or_evidence(self):
        for operation in ('upload', 'submit'):
            with self.subTest(operation=operation):
                result = self.call(operation, '--url', self.url, '--record-dir', str(self.root / 'attempt'))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)['error']['code'], 'arguments')
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root / 'attempt').exists())

    def test_missing_explicit_url_never_uses_environment_or_localhost(self):
        for operation, extra in (('status', ['--prompt-id', 'fixture-id']), ('inventory', [])):
            with self.subTest(operation=operation):
                result = self.call(operation, *extra)
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [])

    def test_status_reads_shared_credentials(self):
        result = self.call('status', '--url', self.url, '--prompt-id', 'fixture-id')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['data']['state'], 'unknown')
        self.assert_authenticated_reads_only()

    def test_inventory_authenticates_core_and_category_reads(self):
        output = self.root / 'inventory.json'
        result = self.call('inventory', '--url', self.url, '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(output.read_text('utf-8'))
        self.assertTrue(data['complete'])
        self.assertEqual(data['models']['checkpoints'], ['fixture.safetensors'])
        self.assertNotIn(self.password, output.read_text('utf-8'))
        self.assertEqual({route for _, route, _ in self.requests},
                         {'/system_stats', '/object_info', '/models', '/models/checkpoints'})
        self.assert_authenticated_reads_only()

    def test_core_error_preserves_previous_inventory(self):
        output = self.root / 'inventory.json'
        output.write_text('previous inventory', encoding='utf-8')
        self.fail_core = True
        result = self.call('inventory', '--url', self.url, '--output', str(output))
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['cache_updated'])
        self.assertEqual(output.read_text('utf-8'), 'previous inventory')

    def test_category_error_reports_partial_inventory(self):
        output = self.root / 'inventory.json'
        self.fail_category = True
        result = self.call('inventory', '--url', self.url, '--output', str(output))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(json.loads(result.stdout)['cache_updated'])
        self.assertFalse(json.loads(output.read_text('utf-8'))['complete'])

    def test_missing_credentials_prevents_inventory_requests(self):
        self.write_config('')
        result = self.call('inventory', '--url', self.url, '--output', str(self.root / 'inventory.json'))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root / 'inventory.json').exists())

if __name__ == '__main__':
    unittest.main()
