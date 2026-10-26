"""Episode exports use temporary project data; no production notes are written."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.services.projects import ProjectStore
from backend.services.revision_notes import RevisionNotes
from tests.http_case import HttpTestCase
from tests import test_revision_notes as fixture


class EpisodeRevisionNotesTests(HttpTestCase):
    put = fixture.RevisionNotesTests.put
    round_manifest = fixture.RevisionNotesTests.round_manifest

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / '示例项目'
        for episode in ('EP001', 'EP002'):
            (self.project / '09-剧集制作' / episode).mkdir(parents=True)
        self.overrides = [patch.object(main, 'store', ProjectStore(self.root)), patch.object(main, 'revision_notes', RevisionNotes())]
        for override in self.overrides:
            override.start()
        self.client = TestClient(main.app, base_url='http://localhost:8782')
        self.url = '/api/projects/示例项目/revision-notes/EP001/C001'
        self.value = dict(segment='P001', stage='一采', run='R001', text='原文', fileRevision='fixture')

    def tearDown(self):
        self.client.close()
        for override in reversed(self.overrides):
            override.stop()
        self.temp.cleanup()

    @property
    def episode_url(self):
        return self.url.rsplit('/', 1)[0]

    def shared_rounds(self):
        directory = self.project / '09-剧集制作/EP001/其他资料/工作稿'
        directory.mkdir(parents=True, exist_ok=True)
        scene = {'storyboard': {'file': 'board.md', 'version': 'v1'}, 'segments': [
            {'id': 'P001', 'stage': '一采', 'run': 'R001', 'duration': 3}]}
        (directory / 'EP001-修改轮次.json').write_text(json.dumps({'episode': 'EP001', 'rounds': [
            {'number': number, 'created_at': f'2026-10-26T0{number}:00:00+08:00',
             'script': {'file': 'script.md', 'version': 'v1'}, 'scenes': {'C001': scene, 'C002': scene}}
            for number in (3, 4)]}), 'utf-8')

    def export(self, notes=None, rounds=None, headers=None, combination=None):
        return self.client.put(self.episode_url + '/export', json={'notes': notes or [], 'rounds': rounds or [], 'combination': combination},
                               headers=headers if headers is not None else {'Origin': 'http://localhost:8782'})

    def test_read_empty_is_read_only(self):
        response = self.client.get(self.episode_url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'episode': 'EP001', 'rounds': {}, 'scenes': {}, 'combinations': {}})
        self.assertFalse((self.project / '09-剧集制作/EP001/其他资料').exists())

    def test_episode_notes_do_not_invalidate_compiled_project_sources(self):
        from backend.parsers.project import live_revision_notes
        for name in ('EP001-视频修改意见.json', 'EP001-C001-视频修改意见.json'):
            self.assertTrue(live_revision_notes('09-剧集制作/EP001/其他资料/工作稿/' + name))
        self.assertFalse(live_revision_notes('09-剧集制作/EP001/其他资料/工作稿/EP002-视频修改意见.json'))

    def test_round_summary_shared_across_scenes_and_isolated_from_legacy(self):
        self.round_manifest()
        self.shared_rounds()
        legacy = {'notes': [], 'rounds': [{'number': 1, 'text': '历史整场意见', 'expectedText': ''}]}
        self.assertEqual(self.client.put(self.url + '/export', json=legacy,
                                        headers={'Origin': 'http://localhost:8782'}).status_code, 200)
        for scene in ('C001', 'C002'):
            self.assertEqual(self.put(self.value | {'roundNumber': 3, 'text': scene}, self.url.replace('C001', scene)).status_code, 200)
        summary = {'number': 3, 'text': '本轮整集不要字幕', 'expectedText': ''}
        response = self.export(rounds=[summary])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['rounds']['3']['text'], summary['text'])
        self.assertEqual(response.json()['scenes']['C001']['rounds']['1']['text'], '历史整场意见')
        self.assertEqual(response.json()['scenes']['C002']['rounds'], {})
        self.assertEqual(self.export(rounds=[summary | {'number': 4, 'text': '下一轮'}]).status_code, 200)
        saved = self.client.get(self.episode_url).json()
        self.assertEqual(saved['rounds']['3']['text'], summary['text'])
        self.assertEqual(saved['rounds']['4']['text'], '下一轮')
        other = self.client.get(self.episode_url.replace('EP001', 'EP002')).json()
        self.assertEqual(other['rounds'], {})

    def test_conflict_in_one_scene_prevents_other_scene_and_summary_changes(self):
        self.shared_rounds()
        for scene in ('C001', 'C002'):
            self.put(self.value | {'roundNumber': 3, 'text': scene}, self.url.replace('C001', scene))
        changes = [self.value | {'scene': scene, 'roundNumber': 3, 'text': '新意见', 'expectedText': scene} for scene in ('C001', 'C002')]
        changes[1]['expectedText'] = '过时文字'
        response = self.export(changes, [{'number': 3, 'text': '总体', 'expectedText': ''}])
        self.assertEqual(response.status_code, 409, response.text)
        saved = self.client.get(self.episode_url).json()
        self.assertEqual(saved['scenes']['C001']['notes']['round/3/P001/一采/R001']['text'], 'C001')
        self.assertEqual(saved['rounds'], {})
        changes[1]['expectedText'] = 'C002'
        response = self.export(changes, [{'number': 3, 'text': '总体', 'expectedText': ''}])
        self.assertEqual(response.status_code, 200, response.text)
        for scene in ('C001', 'C002'):
            self.assertEqual(response.json()['scenes'][scene]['notes']['round/3/P001/一采/R001']['text'], '新意见')

    def test_only_real_episode_rounds_accept_summary_and_origin_is_required(self):
        self.round_manifest()
        summary = {'number': 1, 'text': '不能把场次旧轮当整集轮', 'expectedText': ''}
        self.assertEqual(self.export(rounds=[summary]).status_code, 503)
        self.shared_rounds()
        self.assertEqual(self.export(rounds=[summary | {'number': 3}], headers={}).status_code, 403)
        self.assertEqual(self.export(rounds=[summary | {'number': 0}]).status_code, 422)
        self.assertEqual(self.export(rounds=[summary | {'number': 99}]).status_code, 503)
        self.assertEqual(self.export(rounds=[summary | {'number': 3, 'text': '字' * 20001}]).status_code, 422)

    def test_corrupt_summary_and_write_failure_never_clear_existing_text(self):
        self.shared_rounds()
        value = {'number': 3, 'text': '原文', 'expectedText': ''}
        self.assertEqual(self.export(rounds=[value]).status_code, 200)
        target = self.project / '09-剧集制作/EP001/其他资料/工作稿/EP001-视频修改意见.json'
        before = target.read_bytes()
        with patch('backend.services.revision_notes.os.replace', side_effect=OSError('磁盘不可写')):
            self.assertEqual(self.export(rounds=[value | {'text': '新文字', 'expectedText': '原文'}]).status_code, 503)
        self.assertEqual(target.read_bytes(), before)
        target.write_text('{broken', 'utf-8')
        self.assertEqual(self.client.get(self.episode_url).status_code, 503)
        self.assertEqual(self.export(rounds=[value]).status_code, 503)
        self.assertEqual(target.read_text('utf-8'), '{broken')

    def test_new_round_segment_notes_and_summary_use_one_atomic_file(self):
        self.shared_rounds()
        for scene in ('C001', 'C002'):
            self.assertEqual(self.put(self.value | {'roundNumber': 3}, self.url.replace('C001', scene)).status_code, 200)
        directory = self.project / '09-剧集制作/EP001/其他资料/工作稿'
        target = directory / 'EP001-视频修改意见.json'
        self.assertTrue(target.exists())
        self.assertEqual(list(directory.glob('EP001-C*-视频修改意见.json')), [])
        before = target.read_bytes()
        changes = [self.value | {'scene': scene, 'roundNumber': 3, 'text': '新文字', 'expectedText': '原文'} for scene in ('C001', 'C002')]
        with patch('backend.services.episode_revision_notes.os.replace', side_effect=OSError('磁盘不可写')):
            response = self.export(changes, [{'number': 3, 'text': '整集汇总', 'expectedText': ''}])
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(list(directory.glob('*.tmp')))
        self.assertEqual(self.export(changes, [{'number': 3, 'text': '整集汇总', 'expectedText': ''}]).status_code, 200)
        saved = json.loads(target.read_text())
        self.assertEqual(set(saved['notes']), {'C001', 'C002'})
        self.assertEqual(saved['notes']['C001']['round/3/P001/一采/R001']['fileRevision'], 'fixture')
        self.assertEqual(saved['rounds']['3']['text'], '整集汇总')

    def test_scene_history_export_does_not_fork_shared_round_notes_or_summary(self):
        self.shared_rounds()
        self.put(self.value | {'roundNumber': 3})
        headers = {'Origin': 'http://localhost:8782'}
        value = self.value | {'roundNumber': 3, 'text': '从历史入口整理', 'expectedText': '原文'}
        response = self.client.put(self.url + '/export', json={'notes': [value], 'rounds': []}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['notes']['round/3/P001/一采/R001']['text'], '从历史入口整理')
        self.assertEqual(self.client.get(self.episode_url).json()['scenes']['C001']['notes']['round/3/P001/一采/R001']['text'], '从历史入口整理')
        response = self.client.put(self.url + '/export', json={'notes': [], 'rounds': [{'number': 3, 'text': '不能单场保存', 'expectedText': ''}]}, headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get(self.episode_url).json()['rounds'], {})

    def test_legacy_combination_accepts_one_episode_summary_without_migrating_notes(self):
        self.round_manifest()
        directory = self.project / '09-剧集制作/EP001/其他资料/工作稿'
        manifest = json.loads((directory / 'EP001-C001-场次修改轮次.json').read_text())
        manifest['scene'] = 'C002'
        manifest['rounds'] = [manifest['rounds'][0] | {'number': 7}]
        (directory / 'EP001-C002-场次修改轮次.json').write_text(json.dumps(manifest))
        for scene, number in [('C001', 2), ('C002', 7)]:
            self.assertEqual(self.put(self.value | {'roundNumber': number, 'text': scene}, self.url.replace('C001', scene)).status_code, 200)
        originals = {path: path.read_bytes() for path in directory.glob('*.json')}
        value = {'scenes': {'C002': 7, 'C001': 2}, 'text': '本轮整集节奏再快一点', 'expectedText': ''}
        response = self.export(combination=value)
        self.assertEqual(response.status_code, 200, response.text)
        key = 'C001:2|C002:7'
        self.assertEqual(response.json()['combinations'][key]['text'], value['text'])
        self.assertEqual(response.json()['rounds'], {})
        self.assertEqual(self.client.get(self.episode_url).json()['combinations'][key]['scenes'], value['scenes'])
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse((directory / 'EP001-修改轮次.json').exists())
        self.assertEqual(self.export(combination=value | {'text': '过时覆盖'}).status_code, 409)
        self.assertEqual(self.export(combination=value | {'scenes': {'C001': 99}}).status_code, 503)
        self.assertEqual(self.export(combination=value | {'scenes': {}}).status_code, 422)
        other = value | {'scenes': {'C001': 1, 'C002': 7}, 'text': '另一组合意见'}
        self.assertEqual(self.export(combination=other).status_code, 200)
        self.assertEqual(len(self.client.get(self.episode_url).json()['combinations']), 2)
        target = directory / 'EP001-视频修改意见.json'
        before = target.read_bytes()
        with patch('backend.services.episode_revision_notes.os.replace', side_effect=OSError('磁盘不可写')):
            self.assertEqual(self.export(combination=value | {'text': '未保存', 'expectedText': value['text']}).status_code, 503)
        self.assertEqual(target.read_bytes(), before)
