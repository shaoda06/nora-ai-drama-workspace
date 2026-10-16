"""Background change discovery must preserve source and path checks."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.services.projects import ProjectStore


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
