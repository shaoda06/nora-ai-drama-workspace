"""Prompt tests only use temporary libraries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.services.prompts import PromptLibrary, PromptError, revision
from backend.routes.prompts import create_router
from tests.http_case import HttpTestCase


class PromptFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '提示词管理'
        self.lib = PromptLibrary(self.root)

    def create(self, title='人物', body='第一行\n\n**第二行**\n', category=''):
        return self.lib.save(category, title, body)

    def test_empty_nested_and_move(self):
        self.assertEqual(self.lib.snapshot(), {'categories': [], 'prompts': []})
        self.assertFalse(self.root.exists())
        doc = self.create()
        self.lib.create_category('', '人物设计')
        self.lib.create_category('人物设计', '古装')
        moved = self.lib.save('人物设计/古装', '新版', doc['body'], doc['path'], doc['revision'])
        self.assertFalse((self.root / '人物.md').exists())
        self.assertEqual(self.lib.read(moved['path'])['body'], doc['body'])
        self.assertEqual(len(self.lib.snapshot()['categories']), 2)

    def test_crlf_and_failed_recycle(self):
        doc = self.create(body='第一行\r\n第二行\r\n')
        self.assertEqual(self.lib.read(doc['path'])['body'], '第一行\r\n第二行\r\n')
        with patch('backend.services.prompts.os.link', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.lib.discard(doc['path'], doc['revision'])
        self.assertTrue((self.root / doc['path']).exists())
        self.assertEqual(self.lib.trash_list(), [])

    def test_search_and_external_files(self):
        self.create('根提示词', '主角的表情')
        self.lib.create_category('', '人物')
        self.lib.create_category('人物', '古装')
        external = self.root / '人物/古装/外部.md'
        external.write_text('**主角**\n雨夜', encoding='utf-8')
        self.assertEqual(len(self.lib.search('主角')), 2)
        self.assertEqual(len(self.lib.search('主角', '人物')), 1)
        self.assertEqual(self.lib.search('外部')[0]['title'], '外部')
        external.rename(external.with_name('移动.md'))
        self.assertIn('人物/古装/移动.md', [p['path'] for p in self.lib.snapshot()['prompts']])

    def test_external_uppercase_extension(self):
        self.root.mkdir()
        (self.root / '外部.MD').write_text('原文', encoding='utf-8')
        doc = self.lib.read('外部.MD')
        saved = self.lib.save('', doc['title'], '改写', doc['path'], doc['revision'])
        self.assertEqual(saved['path'], '外部.MD')
        self.assertEqual(self.lib.read('外部.MD')['body'], '改写')

    def test_conflict_preserves_external_content(self):
        doc = self.create()
        (self.root / doc['path']).write_text('外部新正文', encoding='utf-8')
        for action in [lambda: self.lib.save('', '人物', '网页旧稿', doc['path'], doc['revision']),
                       lambda: self.lib.save('', '移动', '网页旧稿', doc['path'], doc['revision']),
                       lambda: self.lib.discard(doc['path'], doc['revision'])]:
            with self.assertRaises(PromptError) as raised:
                action()
            self.assertEqual(raised.exception.status, 409)
        self.assertEqual((self.root / doc['path']).read_text(), '外部新正文')

    def test_collisions_and_names(self):
        doc = self.create('Same')
        for title in ['Same', 'same', '', '../逃出', '.trash', 'CON', 'com1.txt', 'a/b', 'a\\b', 'a:', ' 空格', 'a.']:
            with self.subTest(title=title), self.assertRaises(PromptError):
                self.create(title)
        self.lib.create_category('', '其他')
        self.create('Same', category='其他')
        self.assertEqual(self.lib.read(doc['path'])['body'], doc['body'])

    def test_categories_and_nonempty_delete(self):
        original = self.lib.create_category('', '原分类')
        self.lib.update_category('原分类', '', '新分类', original['revision'])
        self.lib.create_category('新分类', '子分类')
        stamp = revision(self.root / '新分类')
        with self.assertRaises(PromptError):
            self.lib.update_category('新分类', '新分类/子分类', '新分类', stamp)
        with self.assertRaises(PromptError):
            self.lib.delete_category('新分类', stamp)
        with self.assertRaises(PromptError):
            self.lib.delete_category('', '')
        self.lib.delete_category('新分类/子分类', revision(self.root / '新分类/子分类'))
        (self.root / '新分类/其他.txt').write_text('保留')
        with self.assertRaises(PromptError):
            self.lib.delete_category('新分类', revision(self.root / '新分类'))
        self.assertTrue((self.root / '新分类/其他.txt').exists())

    def test_trash_restore_rebuild_conflict_purge(self):
        self.lib.create_category('', '人物')
        doc = self.create(category='人物')
        record = self.lib.discard(doc['path'], doc['revision'])
        self.assertEqual(self.lib.snapshot()['prompts'], [])
        trashed = self.lib.trash_read(record['id'])
        self.assertEqual(trashed['body'], doc['body'])
        self.lib.delete_category('人物', revision(self.root / '人物'))
        restored = self.lib.restore(record['id'], '人物', '人物', trashed['revision'])
        self.assertEqual(restored['body'], doc['body'])
        record = self.lib.discard(restored['path'], restored['revision'])
        trashed = self.lib.trash_read(record['id'])
        self.create(category='人物', body='不能覆盖')
        with self.assertRaises(PromptError):
            self.lib.restore(record['id'], '人物', '人物', trashed['revision'])
        self.assertEqual(self.lib.read('人物/人物.md')['body'], '不能覆盖')
        self.lib.purge(record['id'], trashed['revision'])
        self.assertEqual(self.lib.trash_list(), [])

    def test_links_and_traversal(self):
        self.create()
        external = Path(self.temp.name) / 'outside.md'
        external.write_text('private')
        (self.root / 'linked.md').symlink_to(external)
        (self.root / 'linked-dir').symlink_to(Path(self.temp.name), target_is_directory=True)
        for path in ['../outside.md', '/outside.md', 'linked.md', 'linked-dir/outside.md', '.trash/a/content.md']:
            with self.subTest(path=path), self.assertRaises(PromptError):
                self.lib.read(path)
        self.assertEqual(len(self.lib.snapshot()['prompts']), 1)
        (self.root / '.trash').symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(PromptError):
            self.lib.trash_list()
        self.assertEqual(external.read_text(), 'private')

    def test_atomic_failure(self):
        doc = self.create()
        with patch('backend.services.prompts.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.lib.save('', doc['title'], 'new', doc['path'], doc['revision'])
        self.assertEqual(self.lib.read(doc['path'])['body'], doc['body'])
        self.assertEqual([p.name for p in self.root.iterdir()], ['人物.md'])

    def test_create_race(self):
        self.root.mkdir()
        from os import link
        def raced_link(source, target):
            Path(target).write_text('外部抢先创建')
            return link(source, target)
        with patch('backend.services.prompts.os.link', side_effect=raced_link):
            with self.assertRaises(FileExistsError):
                self.create()
        self.assertEqual((self.root / '人物.md').read_text(), '外部抢先创建')


class PromptHttp(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from backend.main import queue_write
        self.app = FastAPI()
        self.app.include_router(create_router(PromptLibrary(Path(self.temp.name) / '提示词管理'), queue_write))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8782')
        self.headers = {'origin': 'http://127.0.0.1:8782'}

    def test_api_and_origin(self):
        data = {'title': '中文标题', 'body': '多行\n正文'}
        self.assertEqual(self.client.post('/api/prompts/document', json=data).status_code, 403)
        self.assertEqual(self.client.post('/api/prompts/document', json=data, headers={'origin': 'https://other.test'}).status_code, 403)
        response = self.client.post('/api/prompts/document', json=data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        doc = response.json()
        self.assertEqual(self.client.get('/api/prompts/document', params={'path': doc['path']}).json()['body'], data['body'])
        self.assertEqual(len(self.client.get('/api/prompts/search', params={'q': '正文'}).json()), 1)
        response = self.client.request('DELETE', '/api/prompts/document', json={'path': doc['path'], 'revision': doc['revision']}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.client.get('/api/prompts/trash').json()), 1)

    def test_preview(self):
        result = self.client.post('/api/prompts/preview', headers=self.headers, json={'body': '<script>alert(1)</script>\n\n**加粗**\n\n[x](javascript:alert(1))'})
        self.assertEqual(result.status_code, 200)
        html = result.json()['html']
        self.assertNotIn('<script>', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('<strong>加粗</strong>', html)
