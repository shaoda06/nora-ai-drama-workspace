from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.http_case import HttpTestCase
from backend import main
from backend.services.projects import ProjectStore
from backend.services.revision_notes import NoteInput, RevisionNotes


class RevisionNotesTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        for project in ('示例项目', '另一个项目'):
            for episode in ('EP001', 'EP002'):
                (self.root / project / '09-剧集制作' / episode).mkdir(parents=True)
        self.overrides = [patch.object(main, 'store', ProjectStore(self.root)), patch.object(main, 'revision_notes', RevisionNotes())]
        for override in self.overrides:
            override.start()
        self.client = TestClient(main.app, base_url='http://localhost:8782')
        self.url = '/api/projects/示例项目/revision-notes/EP001/C001'
        self.value = dict(segment='P001', stage='一采', run='R001', text='手指动作需要自然。\n保留原来的机位。', fileRevision='12345-100')

    def tearDown(self):
        self.client.close()
        for override in reversed(self.overrides):
            override.stop()
        self.temp.cleanup()

    def put(self, value=None, url=None):
        return self.client.put(url or self.url, json=value or self.value, headers={'Origin': 'http://localhost:8782'})

    def test_read_empty_does_not_create_files(self):
        self.assertEqual(self.client.get(self.url).json(), {'episode': 'EP001', 'scene': 'C001', 'notes': {}, 'rounds': {}})
        self.assertFalse((self.project / '09-剧集制作/EP001/其他资料').exists())

    def test_disk_persistence_unicode_and_independent_versions(self):
        first = self.put()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertRegex(first.json()['updatedAt'], r'[+-]\d{2}:\d{2}$')
        for change in ({'segment': 'P002'}, {'stage': '二采'}, {'run': 'R002'}):
            self.assertEqual(self.put(self.value | change).status_code, 200)
        target = self.project / '09-剧集制作/EP001/其他资料/工作稿/EP001-C001-视频修改意见.json'
        saved = json.loads(target.read_text('utf-8'))
        self.assertEqual(len(saved['notes']), 4)
        fresh = RevisionNotes().read(self.project, 'EP001', 'C001')
        self.assertEqual(fresh.notes['P001/一采/R001'].text, self.value['text'])
        self.assertEqual(fresh.notes['P001/一采/R001'].fileRevision, '12345-100')
        self.assertEqual(self.put(self.value | {'text': '', 'fileRevision': 'updated-200'}).status_code, 200)
        self.assertEqual(len(self.client.get(self.url).json()['notes']), 4)
        self.assertFalse(list(target.parent.glob('.revision-notes-*')))

    def test_project_episode_and_scene_are_isolated(self):
        self.put()
        for url in (self.url.replace('C001', 'C002'), self.url.replace('EP001', 'EP002'), self.url.replace('示例项目', '另一个项目')):
            self.assertEqual(self.client.get(url).json()['notes'], {})
            self.assertEqual(self.put(self.value | {'text': url}, url).status_code, 200)
        self.assertEqual(self.client.get(self.url).json()['notes']['P001/一采/R001']['text'], self.value['text'])

    def test_same_origin_local_write_boundary(self):
        self.assertEqual(self.client.put(self.url, json=self.value).status_code, 403)
        self.assertEqual(self.client.put(self.url, json=self.value, headers={'Origin': 'https://elsewhere.example'}).status_code, 403)
        with TestClient(main.app, base_url='http://8.8.8.8:8782') as remote:
            self.assertEqual(remote.put(self.url, json=self.value, headers={'Origin': 'http://8.8.8.8:8782'}).status_code, 403)
        stripped = self.client.put(self.url, json=self.value, headers={'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-origin', 'Referer': 'http://localhost:8782/'})
        self.assertEqual(stripped.status_code, 200, stripped.text)

    def test_input_validation_and_missing_project(self):
        for change in ({'segment': '../P001'}, {'run': 'R1'}, {'stage': '任意'}, {'text': 3}, {'text': '字' * 20001}, {'fileRevision': ''}, {'extra': True}):
            self.assertEqual(self.put(self.value | change).status_code, 422)
        self.assertEqual(self.client.get(self.url.replace('C001', 'no-scene')).status_code, 422)
        self.assertEqual(self.client.get(self.url.replace('EP001', 'EP003')).status_code, 404)
        self.assertEqual(self.put(url=self.url.replace('示例项目', '不存在')).status_code, 404)

    def test_corrupt_or_misidentified_file_never_overwritten(self):
        self.put()
        target = main.revision_notes.path(self.project, 'EP001', 'C001')
        for content in ('{broken', json.dumps({'episode': 'EP002', 'scene': 'C001', 'notes': {}})):
            target.write_text(content, 'utf-8')
            self.assertEqual(self.client.get(self.url).status_code, 503)
            self.assertEqual(self.put().status_code, 503)
            self.assertEqual(target.read_text('utf-8'), content)

    def test_failed_replace_keeps_original_and_reports_failure(self):
        self.put()
        target = main.revision_notes.path(self.project, 'EP001', 'C001')
        original = target.read_bytes()
        with patch('backend.services.revision_notes.os.replace', side_effect=OSError('磁盘不可写')):
            response = self.put(self.value | {'text': '新的意见'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('未保存', response.text)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(target.parent.glob('.revision-notes-*')))

    def test_concurrent_segment_saves_do_not_lose_entries(self):
        service = main.revision_notes
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda number: service.save(self.project, 'EP001', 'C001', NoteInput(**(self.value | {'segment': f'P{number:03}'}))), range(1, 17)))
        self.assertEqual(len(results), 16)
        self.assertEqual(len(service.read(self.project, 'EP001', 'C001').notes), 16)
        self.assertEqual(list(self.project.rglob('*.json')), [service.path(self.project, 'EP001', 'C001')])

    def round_manifest(self):
        path = self.project / '09-剧集制作/EP001/其他资料/工作稿/EP001-C001-场次修改轮次.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'episode': 'EP001', 'scene': 'C001', 'rounds': [
            {'number': number, 'script': {'file': 'script.md', 'version': 'v1'}, 'storyboard': {'file': 'board.md', 'version': 'v1'},
             'segments': [{'id': 'P001', 'stage': '一采', 'run': 'R001', 'duration': 3}]} for number in (1, 2)
        ]}), 'utf-8')

    def export_put(self, notes=None, rounds=None):
        return self.client.put(self.url + '/export', json={'notes': notes or [], 'rounds': rounds or []}, headers={'Origin': 'http://localhost:8782'})

    def test_export_batch_and_rounds_persist_without_changing_other_entries(self):
        self.round_manifest()
        self.put()
        self.put(self.value | {'segment': 'P002', 'text': '别动这一条'})
        self.put(self.value | {'fileRevision': 'new-file-mark'})
        change = self.value | {'text': '改好的分段意见', 'expectedText': self.value['text']}
        response = self.export_put([change], [{'number': 1, 'text': '整场不要字幕', 'expectedText': ''}])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['notes']['P001/一采/R001']['text'], change['text'])
        self.assertEqual(response.json()['notes']['P001/一采/R001']['fileRevision'], 'new-file-mark')
        self.assertEqual(response.json()['notes']['P002/一采/R001']['text'], '别动这一条')
        self.assertEqual(self.export_put(rounds=[{'number': 2, 'text': '第二轮总体', 'expectedText': ''}]).status_code, 200)
        self.put(self.value | {'segment': 'P003'})
        saved = RevisionNotes().read(self.project, 'EP001', 'C001')
        self.assertEqual(saved.rounds['1'].text, '整场不要字幕')
        self.assertEqual(saved.rounds['2'].text, '第二轮总体')
        self.assertEqual(self.export_put(rounds=[{'number': 1, 'text': '', 'expectedText': '整场不要字幕'}]).status_code, 200)
        self.assertEqual(RevisionNotes().read(self.project, 'EP001', 'C001').rounds['2'].text, '第二轮总体')

    def test_export_conflict_and_failed_write_are_atomic(self):
        self.round_manifest()
        self.put()
        change = self.value | {'text': '新文字', 'expectedText': self.value['text']}
        self.assertEqual(self.export_put([change], [{'number': 1, 'text': '整体', 'expectedText': '过时的内容'}]).status_code, 409)
        self.assertEqual(self.client.get(self.url).json()['notes']['P001/一采/R001']['text'], self.value['text'])
        self.put(self.value | {'text': '其他页面的新文字'})
        self.assertEqual(self.export_put([change]).status_code, 409)
        change['expectedText'] = '其他页面的新文字'
        target = main.revision_notes.path(self.project, 'EP001', 'C001')
        original = target.read_bytes()
        with patch('backend.services.revision_notes.os.replace', side_effect=OSError('磁盘不可写')):
            self.assertEqual(self.export_put([change], [{'number': 1, 'text': '整体', 'expectedText': ''}]).status_code, 503)
        self.assertEqual(target.read_bytes(), original)

    def test_legacy_file_and_export_write_boundary(self):
        self.put()
        target = main.revision_notes.path(self.project, 'EP001', 'C001')
        legacy = json.loads(target.read_text('utf-8'))
        legacy.pop('rounds')
        target.write_text(json.dumps(legacy), 'utf-8')
        self.assertEqual(self.client.get(self.url).json()['rounds'], {})
        payload = {'notes': [], 'rounds': []}
        self.assertEqual(self.client.put(self.url + '/export', json=payload).status_code, 403)
        self.round_manifest()
        self.assertEqual(self.export_put(rounds=[{'number': 0, 'text': '', 'expectedText': ''}]).status_code, 422)
        self.assertEqual(self.export_put(rounds=[{'number': 9, 'text': '', 'expectedText': ''}]).status_code, 503)


if __name__ == '__main__':
    unittest.main()
