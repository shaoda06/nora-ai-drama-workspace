"""Legacy supplements share only file states actually read in the current call."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from backend.services import comfy_tasks as t, execution_checks as checks
from tests import test_comfy_tasks as base, test_submission_lifecycle as lifecycle


class LegacySourceTests(unittest.IsolatedAsyncioTestCase):
    video = lifecycle.LifecycleTests.video
    respond = lifecycle.LifecycleTests.respond

    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.script = self.video()
        self.source = Path(self.data.uploads[0]['file'])
        self.added = self.project / 'new-context.txt'
        self.added.write_bytes(b'new context')
        await self.store.prepare_only(self.data)
        self.previous = checks.read_report(self.data)
        self.previous.pop('context_sources')
        checks.write_report(self.data, self.previous)

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)

    def count_reads(self, calls):
        original = Path.stat
        def stat(path, *args, **kwargs):
            # Separate explicit state reads from pathlib's incidental resolve probes.
            if sys._getframe(1).f_globals.get('__name__') == 'backend.services.execution_checks':
                calls[path] = calls.get(path, 0) + 1
            return original(path, *args, **kwargs)
        return patch.object(Path, 'stat', stat)

    def supplement(self):
        original = checks.context_checks
        def context(*args, **kwargs):
            return original(*args, **kwargs) + [str(self.source), str(self.source), str(self.added)]
        return patch.object(checks, 'context_checks', side_effect=context)

    def preserved(self, report):
        for field in ('segments', 'checked_at', 'prepared_input'):
            self.assertEqual(report[field], self.previous[field])

    async def test_explicit_preparation_reads_existing_and_new_sources_once(self):
        calls = {}
        with self.count_reads(calls), self.supplement(), \
                patch.object(checks, 'fixed_checks', side_effect=AssertionError('reuse covered checks')):
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])
        for path in (self.source, self.script, self.added):
            self.assertEqual(calls[path], 1)
        report = checks.read_report(self.data)
        self.preserved(report)
        self.assertEqual(report['context_checked_during'], 'preparation')
        self.assertIn('new-context.txt', report['sources'])

    async def test_execution_supplement_shares_reads_even_without_output_cache(self):
        calls = {}
        with self.count_reads(calls), self.supplement(), \
                patch.object(checks, 'fixed_checks', side_effect=AssertionError('reuse covered checks')):
            checked = checks.check_prepared(self.store, self.data, legacy=True)
        for path in (self.source, self.script, self.added):
            self.assertEqual(calls[path], 1)
        self.preserved(checked)
        self.assertEqual(checked['context_checked_during'], 'execution')

    async def test_execution_returns_actual_current_states_to_upload_baseline(self):
        calls, states = {}, {self.source: (-1, -1)}
        with self.count_reads(calls), self.supplement():
            checked = checks.check_prepared(self.store, self.data, legacy=True, file_stamps=states)
        self.assertEqual(calls[self.source], 1)
        for path in (self.source, self.added):
            self.assertEqual(list(states[path]), checked['sources'][path.relative_to(self.project).as_posix()])
        self.assertNotIn('observed', checks.read_report(self.data))

    async def test_next_execution_rereads_states_and_rejects_changes(self):
        with self.supplement():
            checks.check_prepared(self.store, self.data, legacy=True)
        self.added.write_bytes(b'changed after the previous call')
        calls = {}
        with self.count_reads(calls), patch.object(checks, 'context_checks', side_effect=AssertionError('already covered')):
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                checks.check_prepared(self.store, self.data, legacy=True)
        self.assertEqual(calls[self.added], 1)

    async def test_changed_original_source_stops_before_supplement(self):
        self.source.write_bytes(b'changed before supplement')
        with patch.object(checks, 'context_checks', side_effect=AssertionError('change must stop first')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                checks.check_prepared(self.store, self.data, legacy=True)
            upload.assert_not_called()
            submit.assert_not_called()

    async def test_missing_added_file_fails_both_supplement_entrypoints(self):
        missing = self.project / 'missing-new-context.txt'
        for execution in (False, True):
            with self.subTest(execution=execution):
                checks.write_report(self.data, copy.deepcopy(self.previous))
                with patch.object(checks, 'context_checks', return_value=[str(self.source), str(missing)]), \
                        patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
                    with self.assertRaises((ValueError, OSError)):
                        if execution:
                            checks.check_prepared(self.store, self.data, legacy=True)
                        else:
                            await self.store.prepare_only(self.data)
                    upload.assert_not_called()
                    submit.assert_not_called()
                self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_full_repreparation_after_change_takes_fresh_postcheck_states(self):
        self.source.write_bytes(b'changed before explicit reprepare')
        original = checks.fixed_checks
        def fixed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.source.write_bytes(b'changed again during the full fixed checks')
            return result
        calls = {}
        with self.count_reads(calls), patch.object(checks, 'fixed_checks', side_effect=fixed) as full:
            result = await self.store.prepare_only(self.data)
        self.assertFalse(result.get('reused', False))
        full.assert_called_once()
        self.assertEqual(calls[self.source], 2)  # Old comparison and fresh full-preparation result.
        stamp = self.source.stat()
        self.assertEqual(checks.read_report(self.data)['sources']['reference.png'], [stamp.st_size, stamp.st_mtime_ns])

    async def test_skipped_bound_api_gets_real_state_when_added_by_supplement(self):
        api = self.record / 'task.api.json'
        api.write_text(api.read_text('utf-8') + '\n', 'utf-8')
        calls, states = {}, {}
        original = checks.context_checks
        def context(*args, **kwargs):
            return original(*args, **kwargs) + [str(api)]
        with self.count_reads(calls), patch.object(checks, 'context_checks', side_effect=context):
            checked = checks.check_prepared(self.store, self.data, legacy=True, bound=True, file_stamps=states)
        self.assertEqual(calls[api], 1)
        stamp = api.stat()
        self.assertEqual(states[api], (stamp.st_size, stamp.st_mtime_ns))
        self.assertNotEqual(checked['sources'][api.relative_to(self.project).as_posix()],
                            self.previous['sources'][api.relative_to(self.project).as_posix()])

    async def test_change_during_supplement_still_fails_upload_change_check(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        base.TaskTests.legacy_registration(self, key)
        original = checks.context_checks
        def context(*args, **kwargs):
            result = original(*args, **kwargs)
            self.source.write_bytes(b'changed after original states were read')
            return result
        with patch.object(checks, 'context_checks', side_effect=context), \
                patch.object(t.client.Client, 'json', side_effect=self.respond), \
                patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '上传开始时'):
                await self.store.prepare(key)
            submit.assert_not_called()
