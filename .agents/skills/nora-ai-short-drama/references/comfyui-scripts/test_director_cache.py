"""Cache isolation transport tests; all remote bytes and evidence live in test fixtures."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import comfyui_client as c
import director_cache as d


class MemoryRemote:
    url = 'http://example.invalid'

    def __init__(self):
        self.source = d.cache_folder('测试场次', '501')
        self.target = d.cache_folder('测试场次', '502')
        self.files = {(self.source, 'seg_0001' + suffix): suffix.encode() * 3 for suffix in (
            '.meta.json', '.av.pt', '.audio.pt', '.handoff.json', '.frames.mkv',
            '.pre.meta.json', '.pre.av.pt', '.pre.frames.mkv', '.pre.handoff.json')}
        self.uploads = []
        self.busy = False
        self.corrupt = False

    def json(self, route, data=None, headers=None):
        if route == '/queue':
            return {'queue_running': [[0, 'busy']] if self.busy else [], 'queue_pending': []}
        assert route == '/upload/image', route
        body = b''.join(data)
        boundary = headers['Content-Type'].split('boundary=')[1].encode()
        fields = {}
        for part in body.split(b'--' + boundary)[1:-1]:
            header, value = part.lstrip(b'\r\n').split(b'\r\n\r\n', 1)
            value = value[:-2]
            if b'name="image"' in header:
                name = header.split(b'filename="')[1].split(b'"')[0].decode()
                payload = value
            else:
                field = header.split(b'name="')[1].split(b'"')[0].decode()
                fields[field] = value.decode()
        assert fields['type'] == 'output'
        assert fields['overwrite'] == 'false'
        folder = fields['subfolder']
        assert (folder, name) not in self.files
        self.files[folder, name] = payload + (b'wrong' if self.corrupt else b'')
        self.uploads.append(name)
        return {'name': name, 'subfolder': folder, 'type': 'output'}

    def open(self, route, data=None, headers=None):
        query = {k: v[0] for k, v in parse_qs(urlparse(route).query).items()}
        key = query['subfolder'], query['filename']
        if key not in self.files:
            raise c.ClientError('http_error', 'missing', http_status=404)
        value = self.files[key]
        response = io.BytesIO(value[:1] if headers and 'Range' in headers else value)
        response.headers = {'Content-Length': str(len(value)), 'Last-Modified': 'stable'}
        if headers and 'Range' in headers:
            response.headers['Content-Range'] = 'bytes 0-0/' + str(len(value))
        return response


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.args = argparse.Namespace(cache_name='测试场次', source_node='501', target_node='502',
                                       indices='1', segment_count=3, record_dir=self.temp.name, apply=True)
        self.remote = MemoryRemote()

    def test_clone_preserves_source_and_copies_full_pre_and_final_sets(self):
        source = dict(self.remote.files)
        result = d.clone(self.remote, self.args)
        self.assertEqual(result['state'], 'cloned')
        for (folder, name), payload in source.items():
            self.assertEqual(self.remote.files[folder, name], payload)
            self.assertEqual(self.remote.files[self.remote.target, name], payload)
        self.assertTrue(all(name.endswith('.meta.json') for name in self.remote.uploads[-2:]))
        evidence = json.loads((Path(self.temp.name) / '缓存隔离结果.json').read_text('utf-8'))
        self.assertEqual(len(evidence['copied']), len(source))
        with self.assertRaisesRegex(ValueError, 'Existing clone receipt'):
            d.clone(self.remote, self.args)

    def test_preview_has_no_remote_or_local_writes(self):
        self.args.apply = False
        self.assertEqual(d.clone(self.remote, self.args)['state'], 'preview')
        self.assertFalse(self.remote.uploads)
        self.assertFalse(list(Path(self.temp.name).iterdir()))

    def test_busy_queue_and_occupied_unselected_slot_prevent_copy(self):
        self.remote.busy = True
        with self.assertRaisesRegex(ValueError, 'idle'):
            d.clone(self.remote, self.args)
        self.remote.busy = False
        self.remote.files[self.remote.target, 'seg_0002.pre.meta.json'] = b'other source'
        with self.assertRaisesRegex(ValueError, 'not empty'):
            d.clone(self.remote, self.args)
        self.assertFalse(self.remote.uploads)

    def test_missing_latent_does_not_publish_metadata(self):
        del self.remote.files[self.remote.source, 'seg_0001.pre.av.pt']
        with self.assertRaisesRegex(ValueError, 'Required source'):
            d.clone(self.remote, self.args)
        self.assertFalse(self.remote.uploads)

    def test_corrupted_target_stops_before_metadata_and_keeps_incomplete_receipt(self):
        self.remote.corrupt = True
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            d.clone(self.remote, self.args)
        self.assertFalse(any(name.endswith('.meta.json') for name in self.remote.uploads))
        evidence = json.loads((Path(self.temp.name) / '缓存隔离结果.json').read_text('utf-8'))
        self.assertEqual(evidence['state'], 'copying')

    def test_source_target_identity_and_path_boundaries(self):
        self.args.target_node = self.args.source_node
        with self.assertRaisesRegex(ValueError, 'must differ'):
            d.clone(self.remote, self.args)
        for name in ('../source', 'nested/source', 'source/../target'):
            with self.assertRaises(ValueError):
                d.cache_folder(name, '502')

    def test_upload_limit_failure_is_saved_without_losing_partial_copy_evidence(self):
        receipt = Path(self.temp.name) / '缓存隔离结果.json'
        receipt.write_text(json.dumps({'state': 'copying', 'copied': ['one verified file']}), 'utf-8')
        argv = ['director_cache.py', '--url', self.remote.url, '--cache-name', '测试场次',
                '--source-node', '501', '--target-node', '502', '--indices', '1',
                '--segment-count', '3', '--record-dir', self.temp.name, '--apply']
        error = c.ClientError('http_error', 'Upload rejected', http_status=413,
                              response='Maximum request body size 104857600 exceeded.')
        output = io.StringIO()
        with patch('sys.argv', argv), patch.object(d, 'clone', side_effect=error), redirect_stdout(output):
            self.assertEqual(d.main(), 1)
        self.assertEqual(json.loads(output.getvalue())['details']['http_status'], 413)
        evidence = json.loads(receipt.read_text('utf-8'))
        self.assertEqual(evidence['state'], 'failed')
        self.assertEqual(evidence['copied'], ['one verified file'])
        self.assertEqual(evidence['failure']['details']['http_status'], 413)


if __name__ == '__main__':
    unittest.main()
