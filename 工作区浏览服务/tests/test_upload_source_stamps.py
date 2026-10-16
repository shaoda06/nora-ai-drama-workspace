"""Share this run's checked source states, retaining transfer and end-of-run checks."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, execution_checks as checks
from tests import test_comfy_tasks as base, test_submission_lifecycle as lifecycle


class UploadStampTests(unittest.IsolatedAsyncioTestCase):
    upload = lifecycle.LifecycleTests.upload
    respond = lifecycle.LifecycleTests.respond

    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)

    def count_source_stats(self, source, calls):
        original = Path.stat
        def stat(path, *args, **kwargs):
            # Count state-comparison reads, not pathlib's incidental resolve() probes.
            caller = sys._getframe(1).f_globals.get('__name__')
            if path == source and caller in ('backend.services.execution_checks', 'backend.services.local_queue'):
                calls.append(path)
            return original(path, *args, **kwargs)
        return patch.object(Path, 'stat', stat)

    async def prepared(self, *, duplicate=False):
        source = self.upload()
        if duplicate:
            self.data.workflow['1']['inputs']['second'] = 'planned'
            self.data.uploads.append({**self.data.uploads[0], 'input': 'second', 'response-name': 'upload-second.json'})
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        return source, key

    async def test_fresh_upload_reads_source_state_once_before_transfer(self):
        source, key = await self.prepared(duplicate=True)
        calls = []
        def respond(route, *args, **kwargs):
            self.assertEqual(route, '/upload/image')
            self.assertEqual(len(calls), 1)  # Report comparison is the only pre-upload stat.
            return self.respond(route, *args, **kwargs)
        before = checks.read_report(self.data)
        with self.count_source_stats(source, calls), patch.object(t.client.Client, 'json', side_effect=respond) as remote:
            await self.store.prepare(key)
        remote.assert_called_once()
        self.assertEqual(len(calls), 3)  # Comparison, after transfer, end of preparation.
        self.assertEqual(checks.read_report(self.data), before)  # No ephemeral states persisted into the report.

    async def test_legacy_first_check_also_supplies_upload_baseline(self):
        source = self.upload()
        key = (await self.store.enqueue(self.data))['local_task_id']
        base.TaskTests.legacy_registration(self, key)
        calls = []
        def respond(route, *args, **kwargs):
            self.assertEqual(len(calls), 1)
            return self.respond(route, *args, **kwargs)
        with self.count_source_stats(source, calls), patch.object(t.client.Client, 'json', side_effect=respond):
            await self.store.prepare(key)
        self.assertEqual(len(calls), 3)
        self.assertEqual(checks.read_report(self.data)['checked_during'], 'execution')

    async def test_restart_reuses_comparison_state_and_hashes_unique_source_once(self):
        source, key = await self.prepared(duplicate=True)
        with patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        calls = []
        with self.count_source_stats(source, calls), \
                patch('backend.services.local_queue.hashlib.file_digest', wraps=hashlib.file_digest) as digest, \
                patch.object(t.client, 'upload') as upload:
            await self.store.prepare(key)
        self.assertEqual(len(calls), 2)  # Comparison and end-of-run check, no duplicate baseline read.
        digest.assert_called_once()
        upload.assert_not_called()

    async def test_change_before_report_comparison_stops_before_upload(self):
        source, key = await self.prepared()
        source.write_bytes(b'changed before execution')
        with patch.object(t.client, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()

    async def test_source_not_read_by_report_comparison_gets_one_upload_baseline(self):
        source = self.upload()
        renamed = source.with_suffix('.api.json')
        source.rename(renamed)
        self.data.uploads[0]['file'] = str(renamed)
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        # Actual API paths are deliberately skipped after upload binding. Their
        # old report values must not be exposed as newly observed file states.
        self.store.rows[key]['state']['uploads_bound'] = True
        calls = []
        def respond(route, *args, **kwargs):
            self.assertEqual(len(calls), 1)
            return self.respond(route, *args, **kwargs)
        with self.count_source_stats(renamed, calls), patch.object(t.client.Client, 'json', side_effect=respond):
            await self.store.prepare(key)
        self.assertEqual(len(calls), 3)

    async def test_change_after_report_comparison_is_not_accepted_as_new_baseline(self):
        source, key = await self.prepared()
        original = checks.check_prepared
        def compare(*args, **kwargs):
            result = original(*args, **kwargs)
            source.write_bytes(b'changed between comparison and transfer')
            return result
        with patch.object(checks, 'check_prepared', side_effect=compare), \
                patch.object(t.client.Client, 'json', side_effect=self.respond):
            with self.assertRaisesRegex(ValueError, '上传开始时'):
                await self.store.prepare(key)
        self.assertNotIn('_prepared_run', self.store.rows[key])

    async def test_change_during_upload_still_stops(self):
        source, key = await self.prepared()
        def respond(route, *args, **kwargs):
            source.write_bytes(b'changed while remote upload was in progress')
            return self.respond(route, *args, **kwargs)
        with patch.object(t.client.Client, 'json', side_effect=respond):
            with self.assertRaisesRegex(ValueError, '上传开始时'):
                await self.store.prepare(key)
        self.assertNotIn('_prepared_run', self.store.rows[key])

    async def test_change_after_transfer_still_fails_final_check(self):
        source, key = await self.prepared()
        async def later(*args):
            source.write_bytes(b'changed after the post-transfer check')
        with patch.object(t.client.Client, 'json', side_effect=self.respond), \
                patch.object(self.store, 'check_target_cache', AsyncMock(side_effect=later)):
            with self.assertRaisesRegex(ValueError, '上传／核验时'):
                await self.store.prepare(key)
        self.assertNotIn('_prepared_run', self.store.rows[key])
