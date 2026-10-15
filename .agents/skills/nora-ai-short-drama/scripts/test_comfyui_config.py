"""Shared configuration boundaries; no real endpoints or credentials."""
import json
from pathlib import Path
import tempfile
import unittest

import comfyui_config as config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'comfyui-config.json'

    def write(self, nodes):
        self.path.write_text(json.dumps({'remote-nodes': nodes}), encoding='utf-8')

    def test_projects_share_one_source_and_project_files_never_override(self):
        self.write([{'url': 'https://primary.invalid/'}, {'url': 'https://backup.invalid'}])
        for name in ('one', 'two'):
            project = self.root / 'projects' / name
            project.mkdir(parents=True)
            (project / 'comfyui-config.json').write_text('{"remote-urls":["http://obsolete.invalid"]}')
            self.assertEqual(config.remote_urls(config.workspace_for_project(project)),
                             ['https://primary.invalid', 'https://backup.invalid'])
        self.path.unlink()
        with self.assertRaises(config.client.ClientError):
            config.remote_urls(self.root)

    def test_credentials_are_per_node_and_never_applied_to_historical_other_address(self):
        self.write([{'url': 'https://primary.invalid', 'auth': {'type': 'basic', 'username': 'alice', 'password': 'private'}},
                    {'url': 'https://backup.invalid', 'auth': {'type': 'basic', 'username': 'bob', 'password': 'other'}}])
        first = config.client_for(self.root, 'https://primary.invalid/', 30)
        second = config.client_for(self.root, 'https://backup.invalid', 30)
        self.assertNotEqual(first.headers, second.headers)
        self.assertEqual(config.client_for(self.root, 'http://old.invalid', 30).headers, {})
        self.assertEqual(config.remote_urls(self.root)[0], 'https://primary.invalid')

    def test_missing_auth_fails_locally_without_disclosing_values(self):
        self.write([{'url': 'https://primary.invalid', 'auth': {'type': 'basic', 'username': 'private-name', 'password': ''}}])
        self.assertEqual(config.remote_urls(self.root), ['https://primary.invalid'])
        with self.assertRaises(config.client.ClientError) as result:
            config.client_for(self.root, 'https://primary.invalid', 30)
        self.assertEqual(result.exception.code, 'missing_auth')
        self.assertNotIn('private-name', str(result.exception))

    def test_invalid_config_and_duplicate_nodes_are_rejected(self):
        for nodes in ([], [{'url': 'https://same.invalid/'}, {'url': 'https://same.invalid'}],
                      [{'url': 'https://user:password@server.invalid'}],
                      [{'url': 'https://server.invalid', 'auth': {'type': 'form'}}],
                      [{'url': 'https://server.invalid', 'auth': {'type': 'basic', 'username': 'a:b', 'password': 'p'}}]):
            self.write(nodes)
            with self.subTest(nodes=nodes), self.assertRaises(config.client.ClientError):
                config.load_config(self.root)


if __name__ == '__main__':
    unittest.main()
