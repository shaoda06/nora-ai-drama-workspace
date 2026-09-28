"""Tests for resource replacement and external ZIP boundaries; no network access."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('updater', Path(__file__).with_name('server.py'))
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class UpdatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        u.RES = self.root / 'resources'
        u.WORK = self.root / 'work'
        u.RES.mkdir()
        u.WORK.mkdir()
        u.PLANS.clear()
        self.entries = []
        for source, lib in u.SOURCES.items():
            folder = lib + '/old'
            (u.RES / folder).mkdir(parents=True)
            (u.RES / folder / 'positive.txt').write_text('old ' + source)
            self.entries.append(dict(id=source, name=source, name_cn=source, library=lib, folder=folder,
                                     category=source, category_name=source, image=None, prompt='old ' + source,
                                     negative_prompt=''))
        u.write_json(u.RES / 'catalog.json', {'styles': self.entries, 'categories': []})
        (u.RES / 'catalog.js').write_text('old catalog')
        u.write_json(u.RES / 'versions.json', {'ray': {'revision': 'unchanged'}})

    def tearDown(self):
        self.tmp.cleanup()

    def incoming(self):
        stage = u.WORK / 'stage'
        folder = stage / 'krea2_styles/new'
        folder.mkdir(parents=True)
        (folder / 'positive.txt').write_text('new')
        info = {'styles': [dict(self.entries[0], prompt='new', folder='krea2_styles/new')],
                'categories': [], 'version': {'revision': 'new'}}
        u.write_json(stage / 'library.json', info)
        return stage, info

    def test_update_restore_preserves_other_source(self):
        stage, info = self.incoming()
        u.commit_library('clio', stage, info)
        self.assertEqual(u.versions()['ray']['revision'], 'unchanged')
        self.assertEqual((u.RES / 'Krea2_moodboard/old/positive.txt').read_text(), 'old ray')
        u.restore('clio')
        self.assertEqual((u.RES / 'krea2_styles/old/positive.txt').read_text(), 'old clio')
        self.assertNotIn('clio', u.versions())
        self.assertEqual(u.versions()['ray']['revision'], 'unchanged')
        u.restore('clio')
        self.assertEqual((u.RES / 'krea2_styles/new/positive.txt').read_text(), 'new')

    def test_failed_write_rolls_back_and_keeps_prepared_data(self):
        stage, info = self.incoming()
        write = u.write_json
        def failing(path, data):
            if path == u.RES / 'catalog.json':
                raise OSError('simulated disk write failure')
            return write(path, data)
        with patch.object(u, 'write_json', side_effect=failing), self.assertRaises(OSError):
            u.commit_library('clio', stage, info)
        self.assertEqual((u.RES / 'krea2_styles/old/positive.txt').read_text(), 'old clio')
        self.assertTrue((stage / 'krea2_styles/new/positive.txt').exists())
        self.assertEqual(u.catalog()['styles'], self.entries)

    def test_reject_path_traversal(self):
        archive = self.root / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../escape.txt', 'bad')
        with self.assertRaisesRegex(ValueError, '不安全'):
            u.build_library('ray', archive, u.WORK / 'stage', {'url':u.RAY,'revision':'x'})
        self.assertFalse((self.root / 'escape.txt').exists())
        self.assertEqual(u.catalog()['styles'], self.entries)

    def test_download_progress_with_and_without_total(self):
        payload = b'x' * (2 * 1024 * 1024)
        for source, length in [('clio', str(len(payload))), ('ray', '')]:
            with self.subTest(source=source):
                snapshots = []
                response = io.BytesIO(payload)
                response.headers = {'Content-Length': length}
                read = response.read

                def read_chunk(size):
                    snapshots.append((dict(u.JOB['download']), u.JOB['message']))
                    return read(size)

                response.read = read_chunk
                meta = {'label': 'test', 'download': 'https://example.test/archive.zip'}
                with patch.object(u, 'fetch_meta', return_value=meta), \
                     patch.object(u, 'request', return_value=response), \
                     patch.object(u, 'build_library', return_value={'count': 1}) as build:
                    u.prepare(source)
                self.assertEqual([p['received'] for p, _ in snapshots],
                                 [0, 1024 * 1024, len(payload)])
                self.assertEqual(snapshots[-1][0]['total'], len(payload) if length else None)
                self.assertIn('50.0%' if length else '总大小未知', snapshots[1][1])
                self.assertIn('2.1 MB', snapshots[-1][1])
                self.assertIsNone(u.JOB['download'])
                self.assertIn('资源已准备好', u.JOB['message'])
                self.assertFalse(build.call_args.args[1].exists())
                self.assertEqual(u.catalog()['styles'], self.entries)

    def test_incomplete_download_is_not_prepared(self):
        response = io.BytesIO(b'partial')
        response.headers = {'Content-Length': '100'}
        meta = {'label': 'test', 'download': 'https://example.test/archive.zip'}
        with patch.object(u, 'fetch_meta', return_value=meta), \
             patch.object(u, 'request', return_value=response), \
             patch.object(u, 'build_library') as build:
            with self.assertRaisesRegex(ValueError, '下载大小'):
                u.prepare('clio')
        build.assert_not_called()
        self.assertNotIn('clio', u.PLANS)
        self.assertEqual(list(u.WORK.iterdir()), [])

    def test_wrong_package_does_not_touch_library(self):
        archive = self.root / 'wrong.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('styles.json', '[]')
        with self.assertRaisesRegex(ValueError, 'Moodboard'):
            u.build_library('ray', archive, u.WORK / 'stage', {'url':u.RAY,'revision':'x'})
        self.assertEqual(u.catalog()['styles'], self.entries)


if __name__ == '__main__':
    unittest.main()
