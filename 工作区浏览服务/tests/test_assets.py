"""Asset CRUD tests use an isolated library, never project or production data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from io import BytesIO
import tempfile
import unittest
from PIL import Image

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import main
from backend.routes.assets import create_router
from backend.services.assets import AssetError, AssetLibrary, MAX_IMAGE_BYTES
from tests.http_case import HttpTestCase


buffer = BytesIO()
Image.new('RGB', (16, 24), '#96b7a5').save(buffer, format='PNG')
PNG = buffer.getvalue()


class Assets(HttpTestCase):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.library = AssetLibrary(Path(temp.name) / '资产管理')
        app = FastAPI()
        app.include_router(create_router(self.library, main.queue_write))
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.addCleanup(self.client.close)
        self.headers = {'Origin': 'http://127.0.0.1'}

    def create(self, kind='person', category=''):
        response = self.client.post('/api/assets', headers=self.headers, json={
            'kind': kind, 'category': category, 'name': '独立资产', 'profile': {'description': '中文\n两行资料'}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def upload(self, item, slot='album', filename='原图.png', data=PNG):
        return self.client.post(f"/api/assets/{item['id']}/images", headers=self.headers,
                                data={'revision': item['revision'], 'slot': slot}, files={'file': (filename, data, 'image/png')})

    def test_empty_read_has_no_disk_side_effect(self):
        self.assertEqual(self.client.get('/api/assets').json(), [])
        self.assertFalse(self.library.root.exists())

    def test_card_edit_persistence_and_kind_boundary(self):
        item = self.create()
        saved = self.client.put('/api/assets/' + item['id'], headers=self.headers, json={
            'kind': 'person', 'name': '新姓名', 'profile': {'age': '20岁', 'description': '保留文字'}, 'revision': item['revision']})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = AssetLibrary(self.library.root).read(item['id'])
        self.assertEqual(reopened['name'], '新姓名')
        self.assertEqual(reopened['profile']['age'], '20岁')
        changed_kind = self.client.put('/api/assets/' + item['id'], headers=self.headers, json={
            'kind': 'prop', 'name': '错误类型', 'revision': reopened['revision']})
        self.assertEqual(changed_kind.status_code, 422)

    def test_original_images_replace_and_delete(self):
        item = self.create()
        first = self.upload(item, 'portrait').json()
        original = first['images'][0]
        path = f"/api/assets/{item['id']}/images/{original['id']}"
        response = self.client.get(path + '?download=true')
        self.assertEqual(response.content, PNG)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertIn('attachment;', response.headers['content-disposition'])
        second = self.upload(first, 'portrait', '../中文新图.png').json()
        self.assertEqual(len(second['images']), 1)
        self.assertEqual(second['images'][0]['name'], '中文新图.png')
        self.assertEqual(self.client.get(path).status_code, 404)
        third = self.upload(second, 'views').json()
        fourth = self.upload(third).json()
        fifth = self.upload(fourth, filename='第二张.png').json()
        self.assertEqual(len(fifth['images']), 4)
        picture = fifth['images'][-1]
        deleted = self.client.delete(f"/api/assets/{item['id']}/images/{picture['id']}?revision={fifth['revision']}", headers=self.headers)
        self.assertEqual(len(deleted.json()['images']), 3)
        self.assertEqual(self.client.get(f"/api/assets/{item['id']}/images/{picture['id']}").status_code, 404)

    def test_categories_and_required_name(self):
        for category in ['帽子', '服装', '鞋子', '配饰']:
            self.assertEqual(self.create('clothing', category)['category'], category)
        self.create('prop')
        for payload in [{'kind': 'clothing', 'name': '未选分类'}, {'kind': 'person', 'name': '  '},
                        {'kind': 'person', 'name': '人物', 'category': '帽子'}, {'kind': 'unknown', 'name': '未知'}]:
            self.assertEqual(self.client.post('/api/assets', json=payload, headers=self.headers).status_code, 422)

    def test_supported_raster_formats_are_preserved(self):
        item = self.create()
        for format, mime in [('PNG', 'image/png'), ('JPEG', 'image/jpeg'), ('GIF', 'image/gif'), ('WEBP', 'image/webp')]:
            data = BytesIO()
            Image.new('RGB', (12, 18), 'green').save(data, format=format)
            response = self.upload(item, data=data.getvalue())
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()
            picture = item['images'][-1]
            original = self.client.get(f"/api/assets/{item['id']}/images/{picture['id']}")
            self.assertEqual(original.headers['content-type'], mime)
            self.assertEqual(original.content, data.getvalue())

    def test_upload_validation_and_cross_asset_access(self):
        item = self.create('prop')
        self.assertEqual(self.upload(item, 'portrait').status_code, 422)
        self.assertEqual(self.upload(item, data=b'<svg><script>alert(1)</script></svg>').status_code, 422)
        self.assertEqual(self.upload(item, data=b'').status_code, 422)
        self.assertEqual(self.upload(item, data=PNG[:40]).status_code, 422)
        self.assertEqual(self.upload(item, data=PNG + b'0' * MAX_IMAGE_BYTES).status_code, 413)
        image = self.upload(item).json()['images'][0]
        other = self.create()
        self.assertEqual(self.client.get(f"/api/assets/{other['id']}/images/{image['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/assets/{other['id']}/images/{image['id']}?revision=1", headers=self.headers).status_code, 404)

    def test_stale_edits_and_deletes_preserve_data(self):
        item = self.create()
        current = self.upload(item).json()
        self.assertEqual(self.upload(item, 'portrait').status_code, 409)
        self.assertEqual(self.client.put(f"/api/assets/{item['id']}", headers=self.headers, json={
            'kind': 'person', 'name': '旧页面修改', 'revision': item['revision']}).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/assets/{item['id']}?revision=1", headers=self.headers).status_code, 409)
        self.assertEqual(self.library.read(item['id']), current)

    def test_concurrent_writers_only_one_can_update(self):
        item = self.create()
        def update(name):
            try:
                return self.library.save({'kind': 'person', 'name': name, 'category': '', 'profile': {}}, item['id'], 1)['name']
            except AssetError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update, ['第一个', '第二个']))
        self.assertEqual(results.count(409), 1)
        self.assertEqual(self.library.read(item['id'])['revision'], 2)

    def test_access_controls_cover_mutations(self):
        item = self.create()
        image = self.upload(item).json()
        requests = [('POST', '/api/assets'), ('PUT', f"/api/assets/{item['id']}"),
                    ('DELETE', f"/api/assets/{item['id']}?revision=2"),
                    ('POST', f"/api/assets/{item['id']}/images"),
                    ('DELETE', f"/api/assets/{item['id']}/images/{image['images'][0]['id']}?revision=2")]
        for method, path in requests:
            for headers in [{}, {'Origin': 'https://other.example'}]:
                self.assertEqual(self.client.request(method, path, headers=headers).status_code, 403)
        self.assertEqual(self.library.read(item['id']), image)

    def test_asset_delete_cascades_images(self):
        item = self.upload(self.create()).json()
        deleted = self.client.delete(f"/api/assets/{item['id']}?revision={item['revision']}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get('/api/assets').json(), [])
        self.assertEqual(self.client.get('/api/assets/' + item['id']).status_code, 404)
        self.assertEqual(self.client.get(f"/api/assets/{item['id']}/images/{item['images'][0]['id']}").status_code, 404)


if __name__ == '__main__':
    unittest.main()
