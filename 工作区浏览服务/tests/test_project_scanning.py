"""Background change discovery must preserve source and path checks."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend.services.projects import ProjectStore
from backend.parsers.project import SourceChangedError, build_data
from backend.services.revision_notes import NoteChange, RevisionNotes


class ProjectScanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        self.source = self.project / '00-项目定位/项目基本定位.md'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('# 定位\n## 正文\n原内容。', encoding='utf-8')
        self.store = ProjectStore(self.root)
        self.addCleanup(self.wait_for_scan)

    def wait_for_scan(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            entry = self.store.entries.get('示例项目')
            if entry is None or not entry['scanning']:
                return
            time.sleep(.002)
        self.fail('background scan did not finish')

    def test_first_status_scans_once_and_reuses_that_check(self):
        with patch.object(self.store, 'snapshot', wraps=self.store.snapshot) as scan:
            first = self.store.status('示例项目')
            second = self.store.status('示例项目')
            self.assertEqual(scan.call_count, 1)
        self.assertFalse(first['checking'])
        self.assertEqual(first, second)

    def test_slow_section_keeps_status_and_other_sections_available_and_deduplicates(self):
        entry = self.store.get('示例项目')
        started, release = threading.Event(), threading.Event()

        def read(*args, **kwargs):
            if kwargs.get('load_scope') == '00-项目定位':
                started.set()
                release.wait(5)
            return build_data(*args, **kwargs)

        with patch('backend.services.projects.build_data', side_effect=read) as parse, ThreadPoolExecutor(4) as pool:
            first = pool.submit(self.store.section, '示例项目', '00-项目定位')
            try:
                self.assertTrue(started.wait(1))
                self.assertTrue(entry['lock'].acquire(blocking=False))
                entry['lock'].release()
                self.assertEqual(pool.submit(self.store.status, '示例项目').result(1)['revision'], 1)
                other = pool.submit(self.store.section, '示例项目', '01-主旨与简介').result(1)
                self.assertIn('story', other)
                duplicate = pool.submit(self.store.section, '示例项目', '00-项目定位')
                self.assertFalse(first.done())
            finally:
                release.set()
            self.assertIs(first.result(2), duplicate.result(2))
            calls = [c for c in parse.call_args_list if c.kwargs.get('load_scope') == '00-项目定位']
            self.assertEqual(len(calls), 1)

    def test_source_change_during_section_read_never_publishes_old_data(self):
        entry = self.store.get('示例项目')
        started, release = threading.Event(), threading.Event()

        def read(*args, **kwargs):
            result = build_data(*args, **kwargs)
            if kwargs.get('load_scope') == '00-项目定位':
                started.set()
                release.wait(5)
            return result

        with patch('backend.services.projects.build_data', side_effect=read), ThreadPoolExecutor(1) as pool:
            pending = pool.submit(self.store.section, '示例项目', '00-项目定位')
            try:
                self.assertTrue(started.wait(1))
                self.source.write_text('# 定位\n## 正文\n并发修改后的内容。', encoding='utf-8')
                self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
                self.assertEqual(entry['revision'], 2)
            finally:
                release.set()
            with self.assertRaises(SourceChangedError):
                pending.result(2)
        self.assertNotIn('00-项目定位', entry['sections'])
        self.assertIn('并发修改后的内容', self.store.section('示例项目', '00-项目定位')['positionHtml'])

    def test_initial_project_read_does_not_hold_state_or_other_project_locks(self):
        other = self.root / '另一个项目'
        other.mkdir()
        started, release = threading.Event(), threading.Event()
        original = self.store.snapshot

        def snapshot(path):
            if path == self.project:
                started.set()
                release.wait(5)
            return original(path)

        with patch.object(self.store, 'snapshot', side_effect=snapshot) as scan, ThreadPoolExecutor(3) as pool:
            first = pool.submit(self.store.get, '示例项目')
            try:
                self.assertTrue(started.wait(1))
                entry = self.store.entries['示例项目']
                self.assertTrue(entry['lock'].acquire(blocking=False))
                entry['lock'].release()
                self.assertIsNotNone(pool.submit(self.store.get, '另一个项目').result(1)['data'])
                duplicate = pool.submit(self.store.get, '示例项目')
            finally:
                release.set()
            self.assertIs(first.result(2), duplicate.result(2))
            self.assertEqual([c.args[0] for c in scan.call_args_list].count(self.project), 1)

    def test_slow_scan_does_not_hold_project_lock_or_duplicate_work(self):
        entry = self.store.get('示例项目')
        before = entry['revision']
        entry['checked'] = 0
        started, release = threading.Event(), threading.Event()
        original = self.store.snapshot

        def slow_scan(path):
            started.set()
            release.wait(5)
            return original(path)

        with patch.object(self.store, 'snapshot', side_effect=slow_scan) as scan:
            try:
                first = self.store.status('示例项目')
                self.assertTrue(started.wait(1))
                self.assertTrue(first['checking'])
                self.assertFalse(first['updating'])
                self.assertTrue(entry['lock'].acquire(blocking=False))
                entry['lock'].release()
                self.assertIn('原内容', self.store.section('示例项目', '00-项目定位')['positionHtml'])
                for _ in range(8):
                    self.assertTrue(self.store.status('示例项目')['checking'])
                self.assertEqual(scan.call_count, 1)
                # A slow scan may outlast the throttle interval; completing it
                # must not immediately schedule another scan on the follow-up.
                entry['checked'] = 0
                self.source.write_text('# 定位\n## 正文\n扫描中更新。', encoding='utf-8')
            finally:
                release.set()
                self.wait_for_scan()
        self.assertEqual(entry['revision'], before + 1)
        self.assertIn('扫描中更新', self.store.section('示例项目', '00-项目定位')['positionHtml'])
        self.assertFalse(self.store.status('示例项目')['checking'])

    def test_unchanged_scan_keeps_revision_and_never_reports_sync(self):
        entry = self.store.get('示例项目')
        data, revision = entry['data'], entry['revision']
        entry['checked'] = 0
        self.store.status('示例项目')
        self.wait_for_scan()
        self.assertIs(entry['data'], data)
        self.assertEqual(entry['revision'], revision)
        self.assertFalse(entry['updating'])
        self.assertIsNone(entry['error'])

    def test_review_note_creation_edit_clear_and_removal_do_not_refresh_project(self):
        episode = self.project / '09-剧集制作/EP001'
        episode.mkdir(parents=True)
        entry = self.store.get('示例项目')
        data, snapshot, revision = entry['data'], entry['snapshot'], entry['revision']
        notes = RevisionNotes()
        target = episode / '其他资料/工作稿/EP001-C001-视频修改意见.json'
        expected = ''
        for text in ('动作需要调整。', '动作需要调整。\n再加一条意见。', ''):
            notes.save(self.project, 'EP001', 'C001', NoteChange(
                segment='P001', stage='一采', run='R001', text=text, fileRevision='123-456', expectedText=expected))
            expected = text
            self.assertEqual(notes.read(self.project, 'EP001', 'C001').notes['P001/一采/R001'].text, text)
            self.assertEqual(self.store.snapshot(self.project), snapshot)
            entry['checked'] = 0
            self.store.status('示例项目')
            self.wait_for_scan()
            self.assertIs(entry['data'], data)
            self.assertEqual(entry['revision'], revision)
            self.assertFalse(entry['updating'])
        target.unlink()
        self.assertEqual(self.store.snapshot(self.project), snapshot)

    def test_review_notes_exemption_does_not_hide_real_episode_changes(self):
        folder = self.project / '09-剧集制作/EP001/其他资料/工作稿'
        folder.mkdir(parents=True)
        baseline = self.store.snapshot(self.project)
        for name in ('EP001-C001-场次分镜-工作稿.md', '输入映射.json', 'EP002-C001-视频修改意见.json',
                     'EP001-C001-视频修改意见-备份.json', 'EP001-C001-视频修改意见.md'):
            with self.subTest(name=name):
                source = folder / name
                source.write_text('新内容', encoding='utf-8')
                self.assertNotEqual(self.store.snapshot(self.project), baseline)
                source.unlink()

    def test_scan_error_preserves_snapshot_and_retry_recovers(self):
        entry = self.store.get('示例项目')
        data, snapshot = entry['data'], entry['snapshot']
        entry['checked'] = 0
        with self.assertLogs('backend.services.projects', level='ERROR'), patch.object(
                self.store, 'snapshot', side_effect=PermissionError('目录暂时不可读')):
            self.store.status('示例项目')
            self.wait_for_scan()
        self.assertIs(entry['data'], data)
        self.assertIs(entry['snapshot'], snapshot)
        self.assertEqual(entry['error_kind'], 'read_failed')
        self.assertIn('目录暂时不可读', entry['error'])
        self.assertGreater(entry['retry_at_time'], time.time() * 1000)
        retry_at = entry['retry_at_time']
        entry['checked'] = 0
        with self.assertLogs('backend.services.projects', level='ERROR'), patch.object(
                self.store, 'snapshot', side_effect=PermissionError('目录暂时不可读')):
            self.store.status('示例项目')
            self.wait_for_scan()
        self.assertEqual(entry['retry_at_time'], retry_at)
        entry['retry_at'] = 0
        self.store.status('示例项目')
        self.wait_for_scan()
        self.assertIsNone(entry['error'])
        self.assertEqual(entry['retry_at_time'], 0)
        self.assertFalse(entry['updating'])

    def test_new_source_change_retries_without_waiting_for_error_deadline(self):
        entry = self.store.get('示例项目')
        with self.assertLogs('backend.services.projects', level='ERROR'), patch(
                'backend.services.projects.build_data', side_effect=ValueError('原资料不可读')):
            self.store.refresh('示例项目', entry, entry['snapshot'])
        self.source.write_text('# 定位\n## 正文\n已修正。', encoding='utf-8')
        entry['checked'] = 0
        self.store.status('示例项目')
        self.wait_for_scan()
        self.assertIsNone(entry['error'])
        self.assertIn('已修正', entry['data']['positionHtml'])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction boundary')
    def test_junctions_keep_inside_sources_and_exclude_outside_sources(self):
        inside, outside = self.project / '素材', self.root / '外部'
        for directory in [inside, outside]:
            directory.mkdir()
            (directory / '资料.txt').write_text('保留', encoding='utf-8')
        for label, target in [('内部联接', inside), ('外部联接', outside)]:
            link = self.project / label
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.addCleanup(os.rmdir, link)
        snapshot = self.store.snapshot(self.project)
        self.assertIn('内部联接/资料.txt', snapshot)
        self.assertFalse(any(key.startswith('外部联接/') for key in snapshot))
        self.assertEqual((outside / '资料.txt').read_text('utf-8'), '保留')

    def test_symbolic_links_preserve_file_and_directory_boundaries(self):
        outside = self.root / '外部.txt'
        outside.write_text('外部', encoding='utf-8')
        try:
            (self.project / '内部文件.txt').symlink_to(self.source)
        except OSError as error:
            self.skipTest('symbolic links unavailable: ' + str(error))
        (self.project / '外部文件.txt').symlink_to(outside)
        (self.project / '目录链接').symlink_to(self.source.parent, target_is_directory=True)
        snapshot = self.store.snapshot(self.project)
        self.assertIn('内部文件.txt', snapshot)
        self.assertNotIn('外部文件.txt', snapshot)
        self.assertFalse(any(key.startswith('目录链接/') for key in snapshot))
