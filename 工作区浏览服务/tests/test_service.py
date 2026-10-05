import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.services.projects import ProjectStore


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        (self.project / '00-项目定位').mkdir(parents=True)
        self.source = self.project / '00-项目定位/项目基本定位.md'
        self.source.write_text('# 项目定位\n\n## 内容\n第一版。\n', encoding='utf-8')
        self.store = ProjectStore(self.root)
        self.override = patch.object(main, 'store', self.store)
        self.override.start()
        self.client = TestClient(main.app, base_url='http://localhost:8780')

    def tearDown(self):
        self.client.close()
        self.override.stop()
        self.temp.cleanup()

    def test_discovery_and_dynamic_document(self):
        self.assertEqual(self.client.get('/api/projects').json()[0]['name'], '示例项目')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位')
        self.assertIn('第一版', section.json()['bodyHtml'])
        previous = self.store.status('示例项目')['revision']
        self.source.write_text('# 项目定位\n\n## 内容\n第二版，增加内容。\n', encoding='utf-8')
        self.store.get('示例项目')['checked'] = 0
        self.store.status('示例项目')
        for _ in range(100):
            if not self.store.get('示例项目')['updating']:
                break
            time.sleep(.01)
        self.assertGreater(self.store.status('示例项目')['revision'], previous)
        self.assertIn('第二版', self.client.get('/api/projects/示例项目/sections/00-项目定位').json()['bodyHtml'])
        (self.root / '新项目').mkdir()
        self.assertEqual(len(self.client.get('/api/projects').json()), 2)

    def test_file_boundaries_and_range(self):
        video = self.project / '测试.mp4'
        video.write_bytes(bytes(range(100)))
        ranged = self.client.get('/api/projects/示例项目/files/测试.mp4', headers={'Range': 'bytes=10-19'})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.content, bytes(range(10, 20)))
        with self.assertRaises(FileNotFoundError):
            self.store.file('示例项目', '../outside.md')
        hidden = self.project / '.private'
        hidden.write_text('private')
        self.assertEqual(self.client.get('/api/projects/示例项目/files/.private').status_code, 404)
        self.assertEqual(self.client.get('/api/history/document?path=../../AGENTS.md').status_code, 404)
        self.assertEqual(self.client.get('/api/krea2/files/../使用说明.md').status_code, 404)

    def test_changes_include_additions_removal_and_rename(self):
        before = self.store.snapshot(self.project)
        path = self.project / '新增.txt'
        path.write_text('hello')
        self.assertNotEqual(before, self.store.snapshot(self.project))
        current = self.store.snapshot(self.project)
        path.rename(self.project / '改名.txt')
        self.assertNotEqual(current, self.store.snapshot(self.project))
        (self.project / '改名.txt').unlink()
        self.assertEqual(before, self.store.snapshot(self.project))

    def test_refresh_failure_retains_previous_data_and_reports_error(self):
        entry = self.store.get('示例项目')
        data = entry['data']
        with patch('backend.services.projects.build_data', side_effect=ValueError('错误源文件')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        self.assertIs(entry['data'], data)
        self.assertEqual(entry['error'], '错误源文件')

    def test_lan_cannot_manage_and_token_not_exposed(self):
        lan = TestClient(main.app, base_url='http://192.168.10.15:8780', client=('192.168.10.30', 44321))
        state = lan.get('/api/krea2/state').json()
        self.assertFalse(state['canManage'])
        self.assertNotIn('token', state)
        with patch.object(main.krea2.updater, 'start_job') as job:
            result = lan.post('/api/krea2/action', headers={'Origin': 'http://192.168.10.15:8780', 'X-Krea-Token': main.krea2.updater.TOKEN}, json={'source': 'clio', 'action': 'apply'})
            self.assertEqual(result.status_code, 403)
            job.assert_not_called()
        lan.close()

    def test_local_management_requires_origin_and_token(self):
        state = self.client.get('/api/krea2/state').json()
        self.assertTrue(state['canManage'])
        with patch.object(main.krea2.updater, 'start_job') as job:
            payload = {'source': 'ray', 'action': 'check'}
            headers = {'Origin': 'http://localhost:8780', 'X-Krea-Token': state['token']}
            self.assertEqual(self.client.post('/api/krea2/action', headers=headers, json=payload).status_code, 202)
            job.assert_called_once_with('check', 'ray')
            for invalid in ({'Origin': 'http://other.site', 'X-Krea-Token': state['token']}, {'Origin': 'http://localhost:8780'}):
                self.assertEqual(self.client.post('/api/krea2/action', headers=invalid, json=payload).status_code, 403)

    def test_catalog_is_paged_and_resource_remains_readable(self):
        first = self.client.get('/api/krea2/catalog').json()
        self.assertEqual(len(first['items']), 36)
        self.assertGreater(first['total'], 36)
        second = self.client.get('/api/krea2/catalog?page=2').json()
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        style = self.client.get('/api/krea2/styles/' + first['items'][0]['id']).json()
        self.assertEqual(self.client.get('/api/krea2/files/' + style['folder'] + '/positive.txt').text, style['prompt'])

    def test_generation_record_urls_use_project_endpoint_and_keep_fragment(self):
        result = main.view({'recordUrl': '03-test%5C记录.md#生成记录-001', 'sourceUrl': 'https://example.com/source'}, '示例项目')
        self.assertEqual(result['recordUrl'], '/api/projects/%E7%A4%BA%E4%BE%8B%E9%A1%B9%E7%9B%AE/files/03-test/记录.md#生成记录-001')
        self.assertEqual(result['sourceUrl'], 'https://example.com/source')


if __name__ == '__main__':
    unittest.main()
