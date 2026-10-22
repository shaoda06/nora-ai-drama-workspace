"""New registration requirements and persisted legacy recovery; no real jobs."""
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, execution_checks as checks, comfy_segments as segments
from tests import test_comfy_tasks as base, test_submission_lifecycle as lifecycle


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    video = lifecycle.LifecycleTests.video
    respond = lifecycle.LifecycleTests.respond
    node = lifecycle.LifecycleTests.node

    async def asyncSetUp(self):
        await lifecycle.LifecycleTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await lifecycle.LifecycleTests.asyncTearDown(self)

    async def test_h3_stage_checked_once_for_native_plan(self):
        self.video()
        with patch.object(segments, 'validate_h3_stage', wraps=segments.validate_h3_stage) as stage:
            await self.store.prepare_only(self.data)
            stage.assert_called_once_with('video-first-pass')
            key = (await self.store.enqueue(self.data))['local_task_id']
            with patch.object(t.client.Client, 'json', side_effect=self.respond):
                await self.store.prepare(key)
                await self.store.prepare(key)
            stage.assert_called_once()

    async def test_h3_stage_checked_once_without_plan_and_invalid_stage_keeps_error(self):
        self.data.workflow['1']['class_type'] = 'MiniMaxH3ReferenceToVideo'
        with patch.object(segments, 'validate_h3_stage', wraps=segments.validate_h3_stage) as stage:
            with self.assertRaises(t.client.ClientError) as error:
                await self.store.prepare_only(self.data)
        self.assertEqual(error.exception.code, 'invalid_task_type')
        stage.assert_called_once_with('image')

    async def test_targets_checked_in_preparation_not_registration_or_execution(self):
        self.video()
        with patch.object(checks, 'check_new_targets', wraps=checks.check_new_targets) as targets:
            await self.store.prepare_only(self.data)
            targets.assert_called_once()
            key = (await self.store.enqueue(self.data))['local_task_id']
            with patch.object(t.client.Client, 'json', side_effect=self.respond):
                await self.store.prepare(key)
            targets.assert_called_once()

    async def test_completed_candidate_invalidates_cached_preparation_and_blocks_execution(self):
        self.video()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        adopted = self.project / '09-剧集制作/EP001/06-阶段采用视频/01-一采/C001-场次/EP001-C001-P001-R001-一采.mp4'
        adopted.parent.mkdir(parents=True)
        adopted.write_bytes(b'completed adopted output')
        with self.assertRaisesRegex(ValueError, '使用新R'):
            await self.store.prepare(key)
        with self.assertRaisesRegex(ValueError, '使用新R'):
            checks.prepare_report(self.store, self.data)
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_missing_targets_fail_preparation_before_any_network(self):
        self.video()
        self.data.segment_plan.targets = []
        with patch.object(t.client.Client, 'json') as network:
            with self.assertRaisesRegex(ValueError, '显式'):
                await self.store.prepare_only(self.data)
            network.assert_not_called()
        self.assertFalse(checks.read_report(self.data)['ok'])
        self.assertFalse(self.store.rows)

    async def test_old_success_report_adds_only_new_target_check_once(self):
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('new_task_ready')
        checks.write_report(self.data, report)
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('old fixed checks are covered')), \
                patch.object(checks, 'check_new_targets', wraps=checks.check_new_targets) as targets:
            await self.store.prepare_only(self.data)
            await self.store.prepare_only(self.data)
            targets.assert_called_once()
        self.assertTrue(checks.read_report(self.data)['new_task_ready'])

    async def test_old_report_with_missing_targets_cannot_upgrade_as_ready(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        self.data.segment_plan.targets = []
        report['prepared_input'] = checks.basis(self.store, self.data)
        report.pop('new_task_ready')
        checks.write_report(self.data, report)
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('do not repeat old checks')):
            with self.assertRaisesRegex(ValueError, '显式'):
                await self.store.prepare_only(self.data)
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_new_job_without_report_pauses_without_supplement_or_upload(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        self.node()
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('new jobs must not supplement')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit, \
                patch.object(self.store, 'queue_notice'):
            await self.store.dispatch_once()
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertIn('--prepare-only', self.store.rows[key]['state']['error'])
        upload.assert_not_called()
        submit.assert_not_called()
        self.assertIsNone(checks.read_report(self.data))

    async def test_new_job_stays_new_after_restart_and_can_be_explicitly_prepared(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.node()
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('restart must not grant legacy permission')), \
                patch.object(self.store, 'queue_notice'):
            await self.store.dispatch_once()
        self.assertTrue(self.store.rows[key]['state']['preparation_required'])
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        result = await self.store.prepare_only(self.data)
        self.assertEqual(result['local_task_id'], key)
        await self.store.prepare(key)
        self.assertEqual(self.store.rows[key]['state']['status'], 'preparing')

    async def test_legacy_job_without_report_supplements_once_even_after_restart(self):
        base.TaskTests.seed(self, status='local_queued')
        self.store.rows['task']['state'].update(prompt_id=None, queue_order=1)
        self.store.save('task')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(checks, 'fixed_checks', wraps=checks.fixed_checks) as fixed:
            await self.store.prepare('task')
            await self.store.prepare('task')
            fixed.assert_called_once()
        report = checks.read_report(self.data)
        self.assertEqual(report['checked_during'], 'execution')
        self.assertFalse(report.get('new_task_ready', False))

    async def test_new_job_cannot_supplement_incomplete_legacy_report(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('context_sources')
        checks.write_report(self.data, report)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(checks, 'context_checks', side_effect=AssertionError('supplement only in preparation')), \
                patch.object(t.client, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, '资料关联'):
                await self.store.prepare(key)
            upload.assert_not_called()

    async def test_new_direct_submit_cannot_bypass_preparation(self):
        with patch.object(t, 'connect') as connect, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '新任务必须'):
                await self.store.submit(self.data)
        connect.assert_not_called()
        submit.assert_not_called()
        self.assertFalse(self.store.rows)

    async def test_prepared_direct_submit_compares_report_once(self):
        await self.store.prepare_only(self.data)
        with patch.object(checks, 'check_prepared', wraps=checks.check_prepared) as report, \
                patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(t.client.Client, 'json', return_value={'prompt_id': 'mock-id'}), \
                patch.object(self.store, 'watch', AsyncMock()):
            await self.store.submit(self.data)
            report.assert_called_once()

    async def test_old_ready_marker_is_not_assumed_for_new_registration(self):
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('new_task_ready')
        checks.write_report(self.data, report)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(checks, 'check_new_targets', side_effect=AssertionError('prepare explicitly')):
            with self.assertRaisesRegex(ValueError, '完整登记要求'):
                await self.store.prepare(key)

    async def test_new_existing_key_direct_submit_cannot_skip_preparation(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t, 'connect') as connect, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '新任务必须'):
                await self.store.submit(self.data, key=key)
        connect.assert_not_called()
        submit.assert_not_called()
