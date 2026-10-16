"""Recovery shares current observations, while checking both saved baselines."""
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, execution_checks as checks
from backend.services.director_uploads import pairs
from tests import test_comfy_tasks as base, test_submission_lifecycle as lifecycle


class RecoveryFileStateTests(unittest.IsolatedAsyncioTestCase):
    video = lifecycle.LifecycleTests.video
    respond = lifecycle.LifecycleTests.respond

    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.session = patch.object(self.store, 'read_session_name', AsyncMock())
        self.session.start()

    async def asyncTearDown(self):
        self.session.stop()
        await base.TaskTests.asyncTearDown(self)

    def count_source_stats(self, paths, calls):
        paths = {paths} if isinstance(paths, Path) else set(paths)
        original = Path.stat
        def stat(path, *args, **kwargs):
            caller = sys._getframe(1).f_globals.get('__name__')
            if path in paths and caller in ('backend.services.execution_checks', 'backend.services.local_queue'):
                (calls[path] if isinstance(calls, dict) else calls).append(path)
            return original(path, *args, **kwargs)
        return patch.object(Path, 'stat', stat)

    def image_pair(self):
        seed = 9223372036854775807
        canvas = {'nodes': [dict(id=1, type='SaveImage', inputs=[], outputs=[],
                                widgets_values_named={'seed': seed}, widgets_values=[seed])], 'links': []}
        self.data.workflow = pairs.Canvas(canvas).api(1)
        api = self.record / 'task.api.json'
        drawing = self.record / 'task.workflow.json'
        api.write_text(json.dumps(self.data.workflow), 'utf-8')
        drawing.write_text(json.dumps(canvas), 'utf-8')
        return api, drawing

    async def prepared(self):
        files = self.image_pair()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        await self.store.prepare(key)
        return files, key

    async def restart(self):
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.queue_notifications = False

    async def test_reschedule_reads_api_and_canvas_once_without_rechecking_pair(self):
        files, key = await self.prepared()
        calls = {path: [] for path in files}
        before = checks.read_report(self.data)
        with self.count_source_stats(files, calls), \
                patch.object(checks, 'fixed_checks', side_effect=AssertionError('fixed checks repeated')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            await self.store.prepare(key)
        self.assertEqual([len(calls[path]) for path in files], [1, 1])
        self.assertEqual(checks.read_report(self.data), before)
        upload.assert_not_called()
        post.assert_not_called()

    async def test_restart_reads_once_for_baselines_and_fresh_at_end(self):
        files, key = await self.prepared()
        await self.restart()
        calls = {path: [] for path in files}
        with self.count_source_stats(files, calls), \
                patch.object(checks, 'fixed_checks', side_effect=AssertionError('fixed checks repeated')):
            await self.store.prepare(key)
        self.assertEqual([len(calls[path]) for path in files], [2, 2])

    async def changed_file_stops(self, index):
        files, key = await self.prepared()
        path = files[index]
        path.write_bytes(path.read_bytes() + b' changed')
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()
            post.assert_not_called()

    async def test_later_invocation_observes_api_change(self):
        await self.changed_file_stops(0)

    async def test_later_invocation_observes_canvas_change(self):
        await self.changed_file_stops(1)

    async def test_cached_phase_baseline_is_still_compared_when_report_matches(self):
        files, key = await self.prepared()
        phase = self.store.rows[key]['_prepared_run']['files']
        phase[str(files[0])] = (0, 0)
        with self.assertRaisesRegex(ValueError, '准备资料已变化'):
            await self.store.prepare(key)

    async def test_durable_phase_baseline_is_still_compared_when_report_matches(self):
        files, key = await self.prepared()
        name = files[1].relative_to(self.project).as_posix()
        self.store.rows[key]['state']['prepared_files'][name] = [0, 0]
        self.store.save(key)
        await self.restart()
        with self.assertRaisesRegex(ValueError, '已保存执行资料发生变化'):
            await self.store.prepare(key)

    async def test_bound_video_files_get_current_phase_observation_and_dynamic_cache_check(self):
        self.video()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
        self.assertTrue(self.store.rows[key]['state']['uploads_bound'])
        files = [self.record / 'task.api.json', self.record / 'task.workflow.json']
        calls = {path: [] for path in files}
        with self.count_source_stats(files, calls), \
                patch.object(t.client.Client, 'json', side_effect=self.respond) as remote:
            await self.store.prepare(key)
        self.assertEqual([len(calls[path]) for path in files], [1, 1])
        self.assertEqual([call.args[0] for call in remote.call_args_list],
                         ['/minimax/director/first_pass_cache_status'])
        files[0].write_bytes(files[0].read_bytes() + b' changed')
        with patch.object(t.client.Client, 'json') as remote:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            remote.assert_not_called()

    async def test_phase_only_file_gets_one_read_and_missing_file_stops_recovery(self):
        _, key = await self.prepared()
        path = self.record / 'saved-extra.json'
        path.write_bytes(b'phase only')
        stamp = path.stat()
        self.store.rows[key]['_prepared_run']['files'][str(path)] = (stamp.st_size, stamp.st_mtime_ns)
        calls = []
        with self.count_source_stats(path, calls):
            await self.store.prepare(key)
        self.assertEqual(len(calls), 1)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            await self.store.prepare(key)

    async def overlapping_source(self):
        files = self.image_pair()
        self.data.uploads = [dict(file=str(files[0]), node='1', input='seed', subfolder='task',
                                  **{'response-name': 'upload.json'})]
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
        await self.restart()
        return files, key

    async def test_recovered_upload_reuses_phase_observation_and_preserves_final_read(self):
        files, key = await self.overlapping_source()
        calls = []
        with self.count_source_stats(files[0], calls), patch.object(t.client, 'upload') as upload:
            await self.store.prepare(key)
        self.assertEqual(len(calls), 2)  # Opening observation and fresh final read.
        upload.assert_not_called()

    async def test_restart_final_check_still_rejects_changed_upload_source(self):
        files, key = await self.overlapping_source()
        async def after_recovery(*args):
            files[0].write_bytes(files[0].read_bytes() + b' changed at end')
        with patch.object(self.store, 'check_target_cache', side_effect=after_recovery):
            with self.assertRaisesRegex(ValueError, '上传／核验时'):
                await self.store.prepare(key)
        self.assertNotIn('_prepared_run', self.store.rows[key])
