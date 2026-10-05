"""Regression coverage for local browser origin checks; no resource writes."""
import http.client
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('updater_auth', Path(__file__).with_name('server.py'))
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class AuthorizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs = patch.object(u.Handler, 'log_message')
        cls.logs.start()
        cls.server = u.ThreadingHTTPServer(('127.0.0.1', 0), u.Handler)
        cls.port = cls.server.server_port
        cls.origin = f'http://127.0.0.1:{cls.port}'
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()
        cls.logs.stop()

    def post(self, overrides=None):
        headers = {'Origin': self.origin, 'Referer': self.origin + '/',
                   'Sec-Fetch-Site': 'same-origin', 'X-Krea-Token': u.TOKEN,
                   'Content-Type': 'application/json'}
        headers.update(overrides or {})
        headers = {k: v for k, v in headers.items() if v is not None}
        connection = http.client.HTTPConnection('127.0.0.1', self.port)
        # Invalid action proves authorization passed without performing an update.
        connection.request('POST', '/api/action', b'{"action":"diagnostic-invalid"}', headers)
        response = connection.getresponse()
        result = response.status, response.read().decode()
        connection.close()
        return result

    def test_normal_origin_passes_authorization(self):
        self.assertEqual(self.post()[0], 400)

    def test_port_stripped_origin_with_matching_browser_evidence(self):
        self.assertEqual(self.post({'Origin': 'http://127.0.0.1'})[0], 400)

    def test_port_stripped_origin_requires_exact_referer_and_same_origin(self):
        for overrides in [{'Referer': None}, {'Referer': 'http://127.0.0.1:1/'},
                          {'Referer': self.origin + '.evil.invalid/'},
                          {'Sec-Fetch-Site': None}, {'Sec-Fetch-Site': 'same-site'},
                          {'Sec-Fetch-Site': 'cross-site'}]:
            with self.subTest(overrides=overrides):
                self.assertEqual(self.post(dict(overrides, Origin='http://127.0.0.1'))[0], 403)

    def test_other_origins_are_rejected(self):
        for origin in [None, 'null', 'https://evil.invalid', 'http://127.0.0.1:1']:
            with self.subTest(origin=origin):
                self.assertEqual(self.post({'Origin': origin})[0], 403)

    def test_both_origin_paths_require_token(self):
        for origin in [self.origin, 'http://127.0.0.1']:
            for token in [None, 'old-session']:
                with self.subTest(origin=origin, token=token):
                    code, message = self.post({'Origin': origin, 'X-Krea-Token': token})
                    self.assertEqual(code, 403)
                    self.assertIn('凭证已失效', message)

    def test_host_remains_restricted(self):
        self.assertEqual(self.post({'Host': 'evil.invalid'})[0], 403)


if __name__ == '__main__':
    unittest.main()
