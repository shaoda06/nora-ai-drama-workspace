"""Whole dispatch paths with temporary projects and simulated remote endpoints only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, execution_checks as checks, comfy_segments as segments
from backend.services.director_uploads import pairs
from tests import test_comfy_tasks as base
from tests.prompt_review_fixture import ENGLISH, attach_review
from workflow_paths import workflow_file


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.session = patch.object(self.store, 'read_session_name', AsyncMock())
        self.session.start()

    async def asyncTearDown(self):
        self.session.stop()
        await base.TaskTests.asyncTearDown(self)

    def node(self, running=0):
        self.store.remote_queues.states[self.data.url] = dict(connection='connected', queue_error=None,
            updated_at=t.client.now(), running_count=running, queued_count=0)

    def upload(self):
        source = self.project / 'reference.png'
        source.write_bytes(b'isolated picture')
        self.data.uploads = [dict(file=str(source), node='1', input='seed', subfolder='task', **{'response-name': 'upload.json'})]
        return source

    def video(self):
        self.data.task_type = 'video-first-pass'
        self.record = self.project / '执行附件/EP001-C001-P001-R001-一采'
        self.record.mkdir()
        self.data.record_dir = str(self.record)
        source = self.project / 'reference.png'
        source.write_bytes(b'isolated picture')
        canvas = json.loads((workflow_file('Minimax-H3-导演台-视频生成-标准版', 'workflow')).read_text('utf-8'))
        node = next(node for node in canvas['nodes'] if node['id'] == 502)
        inputs = node['widgets_values_named']
        timeline = json.loads(inputs['timeline_data'])
        common = timeline['global']
        common.update(prompt='', commonEnabled=True, taskType='r2v', refs=[{'index': 0, 'imageFile': 'planned/ref.png'}],
                      refVideos=[], refAudios=[], referenceVideo=None)
        group = timeline['segments'][0]
        group.update(prompt=ENGLISH, durationSec=3, refs=[], refVideos=[], refAudios=[], referenceVideo=None)
        timeline.update(segments=[group], runSelectEnabled=True, runSelection=[0], editMode='segment')
        timeline['output']['exportMode'] = 'segments'
        timeline['batchWorkspaces']['r2v'].update(globalCommon=common.copy(), segments=[group.copy()])
        inputs.update(timeline_data=json.dumps(timeline, ensure_ascii=False), global_prompt='')
        node['widgets_values'] = list(inputs.values())
        workflow = pairs.Canvas(canvas).api(403)
        self.data.workflow = workflow
        self.data.outputs = []
        self.data.segment_plan = segments.SegmentPlan(director_node='502', report_node='403', output_root='E:/Comfy/output',
            targets=[segments.SegmentTarget(index=0, path=str(self.project / '候选/video.mp4'), response_name='segment.json')])
        (self.record / 'task.workflow.json').write_text(json.dumps(canvas), 'utf-8')
        (self.record / 'task.api.json').write_text(json.dumps(workflow), 'utf-8')
        script = self.project / 'storyboard.md'
        script.write_text('- 文档版本：v1\n镜头正文。', 'utf-8')
        (self.project / 'screenplay.md').write_text('- 文档版本：v1\n剧本正文。', 'utf-8')
        mapping = dict(scene='EP001-C001', scene_storyboard_version='v1', selected_indices=[0], storyboard_file='storyboard.md',
            screenplay_version='v1', scene_modification_round=1,
            uploads=[], segments=[dict(segment='EP001-C001-P001', round='R001', duration_seconds=3, local_execution_dir=str(self.record))])
        manifest = self.project / '09-剧集制作/EP001/其他资料/工作稿/EP001-C001-场次修改轮次.json'
        manifest.parent.mkdir(parents=True, exist_ok=True)
        self.scene_rounds_file = manifest
        manifest.write_text(json.dumps({'episode': 'EP001', 'scene': 'C001', 'rounds': [{
            'number': 1, 'script': {'file': 'screenplay.md', 'version': 'v1'},
            'storyboard': {'file': 'storyboard.md', 'version': 'v1'},
            'segments': [{'id': 'P001', 'stage': '一采', 'run': 'R001', 'duration': 3}]}]}), 'utf-8')
        attach_review(self.project, self.record, workflow, mapping)
        (self.record / '输入映射.json').write_text(json.dumps(mapping), 'utf-8')
        self.data.uploads = [dict(file=str(source), node='502', input='timeline_data', subfolder='task',
            **{'response-name': 'upload.json', 'json-path': ['global', 'refs', 0, 'imageFile']})]
        return script

    async def test_new_video_requires_round_before_any_upload_or_submission(self):
        self.video()
        path = self.record / '输入映射.json'
        mapping = json.loads(path.read_text('utf-8')); mapping.pop('scene_modification_round')
        path.write_text(json.dumps(mapping), 'utf-8')
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, 'scene_modification_round'):
                await self.store.prepare_only(self.data)
            upload.assert_not_called(); submit.assert_not_called()
        self.assertFalse(self.store.rows)

    async def test_preparation_pins_referenced_round_not_entire_round_history(self):
        self.video()
        original = json.loads(self.scene_rounds_file.read_text('utf-8'))
        original['rounds'][0]['segments'].append({'id': 'P002', 'stage': '一采', 'run': 'R009', 'duration': 3})
        self.scene_rounds_file.write_text(json.dumps(original), 'utf-8')
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        self.assertIn('scene_composition', report['prepared_input'])
        self.assertNotIn(self.scene_rounds_file.relative_to(self.project).as_posix(), report['sources'])
        self.assertIn('screenplay.md', report['sources'])
        data = json.loads(self.scene_rounds_file.read_text('utf-8'))
        data['rounds'].append({**data['rounds'][0], 'number': 2})
        self.scene_rounds_file.write_text(json.dumps(data), 'utf-8')
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('adding a round must not repeat fixed checks')):
            self.assertTrue(checks.check_prepared(self.store, self.data)['ok'])
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])
        data['rounds'][0]['segments'][1]['run'] = 'R010'
        self.scene_rounds_file.write_text(json.dumps(data), 'utf-8')
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                checks.check_prepared(self.store, self.data)
            upload.assert_not_called(); submit.assert_not_called()

    async def test_old_preparation_without_round_can_resume_but_cannot_ready_a_new_task(self):
        self.video()
        path = self.record / '输入映射.json'
        mapping = json.loads(path.read_text('utf-8')); mapping.pop('scene_modification_round')
        path.write_text(json.dumps(mapping), 'utf-8')
        before = path.read_bytes()
        checks.prepare_report(self.store, self.data, at_execution=True)
        report = checks.read_report(self.data)
        self.assertTrue(report['ok'])
        self.assertNotIn('scene_composition', report['prepared_input'])
        self.assertNotIn('new_task_ready', report)
        self.assertTrue(checks.check_prepared(self.store, self.data, legacy=True)['ok'])
        with self.assertRaisesRegex(ValueError, '新视频任务必须先关联场次修改轮次'):
            checks.check_prepared(self.store, self.data)
        self.assertEqual(path.read_bytes(), before)

    async def test_round_requirement_survives_restart_and_does_not_reclassify_older_prepared_jobs(self):
        self.video()
        await self.store.prepare_only(self.data)
        path = self.record / '输入映射.json'
        mapping = json.loads(path.read_text('utf-8')); mapping.pop('scene_modification_round')
        path.write_text(json.dumps(mapping), 'utf-8')
        report = checks.read_report(self.data)
        report['prepared_input']['mapping'].pop('scene_modification_round')
        report['prepared_input'].pop('scene_composition')
        checks.write_report(self.data, report)
        key = (await self.store.enqueue(self.data))['local_task_id']
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertTrue(self.store.rows[key]['state']['scene_round_required'])
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '新视频任务必须先关联场次修改轮次'):
                await self.store.prepare(key)
            upload.assert_not_called(); submit.assert_not_called()
        # A pre-existing prepared job has the original preparation marker, but no new round marker.
        self.store.rows[key]['state'].pop('scene_round_required')
        self.store.save(key)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertTrue(self.store.rows[key]['state']['preparation_required'])
        with patch.object(t.client.Client, 'json', side_effect=self.respond), patch.object(t.client, 'submit') as submit:
            await self.store.prepare(key)
            submit.assert_not_called()
        self.assertNotIn('scene_round_required', self.store.rows[key]['state'])

    def respond(self, route, *args, **kwargs):
        if route == '/upload/image':
            return {'name': 'renamed.png', 'subfolder': 'actual', 'type': 'input'}
        if route == '/minimax/director/first_pass_cache_status':
            return {'can_confirm_refine': False, 'selected_matched': 0, 'segments': [{'index': 0, 'final_matches': True}]}
        self.assertEqual(route, '/prompt')
        return {'prompt_id': 'isolated-id'}

    async def test_video_prepare_enqueue_busy_reschedule_submit_counts(self):
        self.video()
        async def refresh(url):
            self.node(running=1 if refreshes.pop(0) else 0)
        refreshes = [True, False]
        with patch.object(checks, 'fixed_checks', wraps=checks.fixed_checks) as fixed, \
                patch.object(self.store.generation_context, 'validate_segment_context', wraps=self.store.generation_context.validate_segment_context) as shared, \
                patch.object(self.store.generation_context, 'prepare_generation_context', wraps=self.store.generation_context.prepare_generation_context) as context, \
                patch.object(t.client, 'upload', wraps=t.client.upload) as upload, \
                patch('backend.services.local_queue.hashlib.file_digest', wraps=hashlib.file_digest) as digest, \
                patch.object(t.client.Client, 'json', side_effect=self.respond) as remote, \
                patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(self.store, 'watch', AsyncMock()), \
                patch.object(self.store.remote_queues, 'refresh', refresh):
            await self.store.prepare_only(self.data)
            with patch.object(self.store, 'resolve_input', wraps=self.store.resolve_input) as resolve:
                key = (await self.store.enqueue(self.data))['local_task_id']
                resolve.assert_called_once()
            self.node()
            await self.store.dispatch_once()
            self.assertEqual(self.store.rows[key]['state']['status'], 'local_queued')
            saved = {path: path.stat().st_mtime_ns for path in self.record.rglob('*') if path.is_file()
                     and path.name not in ('后台任务状态.json', '后台过程记录.json')}
            self.node()
            await self.store.dispatch_once()
            fixed.assert_called_once()
            upload.assert_called_once()
            digest.assert_not_called()
            self.assertEqual(context.call_count, 2)  # Fixed preparation + actual snapshot, never on rescheduling.
            shared.assert_called_once()  # Retrieval and input records consume the same validated facts.
            self.assertEqual([call.args[0] for call in remote.call_args_list].count('/prompt'), 1, self.store.rows[key]['state'])
            self.assertEqual([call.args[0] for call in remote.call_args_list].count('/minimax/director/first_pass_cache_status'), 2)
            for path, stamp in saved.items():
                self.assertEqual(path.stat().st_mtime_ns, stamp)

    async def test_binding_writes_prepared_field_without_reading_it_again(self):
        self.video()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        writes = []
        class PreparedSlot(dict):
            def __getitem__(self, key):
                if key == 'imageFile':
                    raise AssertionError('prepared field must not be checked again')
                return super().__getitem__(key)

            def __setitem__(self, key, value):
                writes.append((key, value))
                return super().__setitem__(key, value)

        original = t.client.strict_json
        def parse(raw):
            document = original(raw)
            if isinstance(document, dict) and 'batchWorkspaces' in document:
                document['global']['refs'][0] = PreparedSlot(document['global']['refs'][0])
            return document

        with patch.object(t.client, 'strict_json', side_effect=parse), \
                patch.object(t.client.Client, 'json', side_effect=self.respond), \
                patch.object(t.client, 'submit') as post:
            actual = await self.store.prepare(key)
            post.assert_not_called()
        bound = json.loads(actual['502']['inputs']['timeline_data'])
        self.assertIn(('imageFile', 'actual/renamed.png'), writes)
        self.assertEqual(bound['global']['refs'][0]['imageFile'], 'actual/renamed.png')
        self.assertEqual(bound['batchWorkspaces']['r2v']['globalCommon']['refs'][0]['imageFile'], 'actual/renamed.png')

    async def test_relative_source_resolved_once_before_fixed_checks(self):
        self.upload()
        self.data.uploads[0]['file'] = 'reference.png'
        original = t.paths.project_file
        with patch.object(t.paths, 'project_file', wraps=original) as resolve:
            self.store.resolve_input(self.data)
            with patch.object(Path, 'is_absolute', side_effect=AssertionError('resolved path must not be checked again')):
                checks.fixed_input_checks(self.store, self.data)
        source_calls = [call for call in resolve.call_args_list if call.args[1] == 'reference.png']
        self.assertEqual(len(source_calls), 1)
        self.assertEqual(self.data.uploads[0]['file'], str(self.project / 'reference.png'))

    async def test_invalid_video_version_fails_before_upload_and_is_reported(self):
        script = self.video()
        script.write_text('- 文档版本：v2\n', 'utf-8')
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '分镜版本'):
                await self.store.prepare_only(self.data)
            upload.assert_not_called()
            post.assert_not_called()
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_bad_mapping_is_saved_as_failed_preparation_report(self):
        (self.record / '输入映射.json').write_text('{', 'utf-8')
        with self.assertRaises(ValueError):
            await self.store.prepare_only(self.data)
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_legacy_report_reuses_existing_checks_and_only_supplements_missing_context(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report['prepared_input'].pop('title')
        report.pop('context_sources')
        checks.write_report(self.data, report)
        key = (await self.store.enqueue(self.data))['local_task_id']
        base.TaskTests.legacy_registration(self, key)
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('must not rerun old fixed checks')), \
                patch.object(self.store.generation_context, 'validate_segment_context', side_effect=AssertionError('old segment checks already passed')), \
                patch.object(checks, 'context_checks', wraps=checks.context_checks) as supplement, \
                patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
            await self.store.prepare(key)
            supplement.assert_called_once()
            self.assertTrue(supplement.call_args.kwargs['segment_plan_checked'])
        self.assertEqual(checks.read_report(self.data)['context_checked_during'], 'execution')

    async def test_legacy_missing_context_failure_pauses_without_upload(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('context_sources')
        report['prepared_input']['mapping'].pop('scene_storyboard_version')
        report['prepared_input']['mapping'].pop('scene_modification_round')
        report['prepared_input'].pop('scene_composition')
        mapping_file = self.record / '输入映射.json'
        mapping = json.loads(mapping_file.read_text('utf-8'))
        mapping.pop('scene_storyboard_version')
        mapping.pop('scene_modification_round')
        mapping_file.write_text(json.dumps(mapping), 'utf-8')
        checks.write_report(self.data, report)
        key = (await self.store.enqueue(self.data))['local_task_id']
        base.TaskTests.legacy_registration(self, key)
        self.node()
        with patch.object(t.client, 'upload') as upload, patch.object(self.store, 'queue_notice'):
            await self.store.dispatch_once()
            upload.assert_not_called()
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_explicit_unchanged_legacy_preparation_supplements_without_full_recheck(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report['prepared_input'].pop('title')
        report.pop('context_sources')
        checks.write_report(self.data, report)
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('no full recheck')), \
                patch.object(self.store.generation_context, 'validate_segment_context', side_effect=AssertionError('do not recheck segment plan')), \
                patch.object(checks, 'context_checks', wraps=checks.context_checks) as missing:
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])
            missing.assert_called_once()
            self.assertTrue(missing.call_args.kwargs['segment_plan_checked'])
        self.assertEqual(checks.read_report(self.data)['context_checked_during'], 'preparation')

    async def test_legacy_reuse_preserves_fixed_report_and_rejects_changed_input_before_supplement(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('context_sources')
        checks.write_report(self.data, report)
        with patch.object(self.store.generation_context, 'validate_segment_context', side_effect=AssertionError('already checked')):
            checked = checks.check_prepared(self.store, self.data, legacy=True)
        for name in ('segments', 'checked_at', 'prepared_input'):
            self.assertEqual(checked[name], report[name])
        # Change the registered input, not the source file: no supplement may use
        # a previously successful report for different data.
        checked.pop('context_sources')
        checks.write_report(self.data, checked)
        self.data.workflow['502']['inputs']['seed'] += 1
        with patch.object(checks, 'context_checks', side_effect=AssertionError('basis mismatch must stop first')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                checks.check_prepared(self.store, self.data, legacy=True)
            upload.assert_not_called()
            post.assert_not_called()

    async def test_legacy_changed_source_stops_before_missing_checks(self):
        script = self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('context_sources')
        checks.write_report(self.data, report)
        script.write_text('changed storyboard after preparation', 'utf-8')
        with patch.object(checks, 'context_checks', side_effect=AssertionError('source change must stop first')):
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                checks.check_prepared(self.store, self.data, legacy=True)

    async def test_legacy_without_segment_plan_does_not_assume_shared_checks_passed(self):
        self.video()
        canvas_path = self.record / 'task.workflow.json'
        canvas = json.loads(canvas_path.read_text('utf-8'))
        node = next(item for item in canvas['nodes'] if item['id'] == 502)
        inputs = node['widgets_values_named']
        timeline = json.loads(inputs['timeline_data'])
        timeline['output']['exportMode'] = 'full'
        inputs['timeline_data'] = json.dumps(timeline)
        node['widgets_values'] = list(inputs.values())
        self.data.workflow = pairs.Canvas(canvas).api(403)
        self.data.segment_plan = None
        self.data.outputs = [t.OutputTarget(node_id='403', output_key='text', index=0,
            path=str(self.project / '候选/report.txt'), response_name='report-download.json')]
        canvas_path.write_text(json.dumps(canvas), 'utf-8')
        (self.record / 'task.api.json').write_text(json.dumps(self.data.workflow), 'utf-8')
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('context_sources')
        checks.write_report(self.data, report)
        with patch.object(self.store.generation_context, 'validate_segment_context', wraps=self.store.generation_context.validate_segment_context) as shared:
            self.assertTrue(checks.check_prepared(self.store, self.data, legacy=True)['ok'])
            self.assertTrue(checks.check_prepared(self.store, self.data, legacy=True)['ok'])
            shared.assert_called_once()  # Missing coverage is checked once, never silently reused.

    async def test_legacy_missing_version_check_still_fails_without_upload(self):
        script = self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('context_sources')
        script.write_text('- 文档版本：v2\n旧报告没有覆盖的版本检查。', 'utf-8')
        # This is the file state the legacy fixed-only preparation saw.
        report['sources'] = checks.sources(self.data)
        checks.write_report(self.data, report)
        with patch.object(self.store.generation_context, 'validate_segment_context', side_effect=AssertionError('already checked')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '分镜版本'):
                checks.check_prepared(self.store, self.data, legacy=True)
            upload.assert_not_called()
            post.assert_not_called()
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_paused_job_reprepare_updates_original_id_without_generating(self):
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        updated = self.data.model_copy(deep=True)
        updated.workflow['1']['inputs']['seed'] = 7
        self.store.task_action(key, 'pause')
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            result = await self.store.prepare_only(updated)
            self.assertEqual(result['local_task_id'], key)
            self.assertEqual(self.store.rows[key]['input'].workflow['1']['inputs']['seed'], 7)
            self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
            self.store.task_action(key, 'resume')
            await self.store.prepare(key)
            upload.assert_not_called()
            post.assert_not_called()

    async def test_reprepare_failure_leaves_job_paused_and_original_input(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        updated = self.data.model_copy(deep=True)
        updated.workflow['1']['inputs'] = []
        with self.assertRaises(t.client.ClientError):
            await self.store.prepare_only(updated)
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertIsInstance(self.store.rows[key]['input'].workflow['1']['inputs'], dict)

    async def test_existing_submit_proof_prevents_reprepare_and_keeps_bytes(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        proof = self.record / self.data.attempt_name
        proof.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError, '已有提交'):
            await self.store.prepare_only(self.data)
        self.assertEqual(proof.read_bytes(), b'original')
        self.assertEqual(len(self.store.rows), 1)

    async def test_restart_verifies_each_upload_once_then_reschedules_without_hash(self):
        self.upload()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch('backend.services.local_queue.hashlib.file_digest', wraps=hashlib.file_digest) as digest, \
                patch.object(checks, 'fixed_checks', side_effect=AssertionError('must reuse fixed report')), \
                patch.object(t.client, 'upload') as upload:
            await self.store.prepare(key)
            await self.store.prepare(key)
            digest.assert_called_once()
            upload.assert_not_called()

    async def test_completed_upload_does_not_allow_changed_source_on_reschedule(self):
        source = self.upload()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
        source.write_bytes(b'changed')
        with patch.object(t.client, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()

    async def test_concurrent_queue_refreshes_share_one_request(self):
        self.node()
        observer = self.store.remote_queues
        calls = []
        def queue(*args):
            calls.append(args)
            return {'queue_running': [], 'queue_pending': []}
        with patch.object(t.client.Client, 'json', side_effect=queue):
            await asyncio.gather(observer.refresh(self.data.url), observer.refresh(self.data.url))
        self.assertEqual(len(calls), 1)

    async def test_concurrent_task_checks_share_remote_read(self):
        base.TaskTests.seed(self, status='running', notification='sent')
        with patch.object(t.client, 'status', return_value={'state': 'running', 'history': None}) as read:
            await asyncio.gather(self.store.reconcile('task'), self.store.reconcile('task'))
        read.assert_called_once()

    async def test_dispatch_does_not_wait_for_previous_download(self):
        base.TaskTests.seed(self, status='running', notification='sent')
        finished = asyncio.Event()
        async def collect(key, confirmed_result):
            self.assertIs(confirmed_result, result)
            await finished.wait()
        result = {'state': 'success', 'history': {}, 'files': []}
        with patch.object(t.client, 'status', return_value=result), patch.object(self.store, 'collect_saved', collect):
            self.assertTrue(await asyncio.wait_for(self.store.reconcile('task', background_collection=True), 2))
            self.assertEqual(self.store.rows['task']['state']['status'], 'collecting')
            self.assertFalse(self.store.workers['task'].done())
            with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                    patch.object(self.store, 'notify', AsyncMock()) as notify:
                await self.store.watch('task')
                notify.assert_not_awaited()
            finished.set()
            await self.store.workers['task']

    async def test_metadata_write_failure_is_not_sent_and_never_becomes_unknown(self):
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(t.client, 'write_new', side_effect=OSError('disk full')), \
                patch.object(t.client.Client, 'json') as remote:
            with self.assertRaises(t.client.ClientError) as error:
                await self.store.submit(self.data, key=key)
            self.assertEqual(error.exception.details['submission_state'], 'not_sent')
            self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
            remote.assert_not_called()

    async def test_state_and_event_flush_once(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(self.store, 'write_records', wraps=self.store.write_records) as write:
            self.store.record(key, 'test', 'saved', _changes={'phase': 'test'})
            write.assert_called_once()

    async def test_upload_binding_paths_fail_in_preparation_before_network(self):
        self.upload()
        self.data.workflow['1']['inputs']['seed'] = json.dumps({'refs': []})
        self.data.uploads[0]['json-path'] = ['refs', 4, 'file']
        with patch.object(t.client.Client, 'json') as network:
            with self.assertRaisesRegex(ValueError, 'JSON字段路径'):
                await self.store.prepare_only(self.data)
            network.assert_not_called()

    async def test_shared_json_field_is_bound_once_for_all_slots(self):
        self.upload()
        item = self.data.uploads[0]
        self.data.workflow['1']['inputs']['seed'] = json.dumps({'refs': ['planned'] * 8})
        self.data.uploads = [{**item, 'response-name': f'upload-{index}.json', 'json-path': ['refs', index]}
                             for index in range(8)]
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        original = t.client.strict_json
        calls = []
        def decode(raw):
            if raw.startswith(b'{"refs"'):
                calls.append(raw)
            return original(raw)
        with patch.object(t.client.Client, 'json', side_effect=self.respond), patch.object(t.client, 'strict_json', side_effect=decode):
            actual = await self.store.prepare(key)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(actual['1']['inputs']['seed'])['refs'], ['actual/renamed.png'] * 8)

    async def test_restart_video_reuses_files_but_detects_changed_frozen_prompt(self):
        self.video()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client.Client, 'json', side_effect=self.respond):
            await self.store.prepare(key)
        prompt = self.record / '模型提示词.txt'
        prompt.write_text('changed after freezing', 'utf-8')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(t.client, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, '执行资料发生变化'):
                await self.store.prepare(key)
            upload.assert_not_called()

    async def test_download_retry_reuses_verified_receipt_and_detects_changes(self):
        base.TaskTests.seed(self, status='running', notification='sent')
        result = {'state': 'success', 'history': {}, 'files': [dict(node_id='1', output_key='images', index=0,
                  file=dict(filename='image.png', subfolder='', type='output'))]}
        original = t.client.strict_json
        reads = []
        def decode(raw):
            reads.append(raw)
            return original(raw)
        def download(client, args):
            Path(args.output).parent.mkdir(exist_ok=True)
            Path(args.output).write_bytes(b'image')
            return dict(path=args.output, remote=result['files'][0]['file'], bytes=5)
        with patch.object(t.client, 'download', side_effect=download) as get:
            self.assertFalse(await self.store.collect('task', result))
            with patch.object(t.client, 'strict_json', side_effect=decode):
                self.assertFalse(await self.store.collect('task', result))
                self.assertFalse(reads)
                Path(self.data.outputs[0].path).write_bytes(b'changed bytes')
                self.assertTrue(await self.store.collect('task', result))
                self.assertEqual(len(reads), 1)
            get.assert_called_once()

    async def test_transport_queue_read_is_shared_between_different_readers(self):
        import io
        import threading
        entered, release = threading.Event(), threading.Event()
        calls = []
        def open_queue(*args):
            calls.append(args)
            entered.set()
            if not release.wait(2):
                raise AssertionError('queue test timed out')
            return io.BytesIO(b'{"queue_running": [], "queue_pending": []}')
        first = t.client.Client(self.data.url, 3)
        second = t.client.Client(self.data.url, 2)
        with patch.object(t.client.Client, 'open', side_effect=open_queue):
            one = asyncio.create_task(asyncio.to_thread(first.json, '/queue'))
            await asyncio.to_thread(entered.wait, 2)
            two = asyncio.create_task(asyncio.to_thread(second.json, '/queue'))
            # Hold the first transport open while the second caller joins it.
            await asyncio.sleep(.05)
            release.set()
            results = await asyncio.gather(one, two)
        self.assertEqual(len(calls), 1)
        self.assertEqual(results[0], results[1])
        self.assertFalse(t.client.QUEUE_READS)

    async def test_real_cli_http_queue_upload_submit_and_download_in_isolation(self):
        from fastapi import FastAPI, Request, WebSocket
        from fastapi.responses import Response
        from starlette.websockets import WebSocketDisconnect
        from tests.test_queue_recovery import serving
        from backend import main
        remote, api = FastAPI(), FastAPI()
        api.state.comfy_tasks = self.store
        for route in main.app.routes:
            if getattr(route, 'path', '') in ('/api/internal/comfy/prepare', '/api/internal/comfy/submit'):
                api.add_api_route(route.path, route.endpoint, methods=route.methods)
        calls = []
        @remote.get('/queue')
        def queue():
            return {'queue_running': [], 'queue_pending': []}
        @remote.post('/upload/image')
        async def upload(request: Request):
            self.assertIn(b'isolated picture', await request.body())
            calls.append('upload')
            return {'name': 'remote.png', 'subfolder': 'task', 'type': 'input'}
        @remote.post('/prompt')
        async def prompt(request: Request):
            payload = await request.json()
            self.assertEqual(payload['prompt']['1']['inputs']['seed'], 'task/remote.png')
            calls.append('prompt')
            return {'prompt_id': 'isolated-id'}
        @remote.get('/history/isolated-id')
        def history():
            return {'isolated-id': {'status': {'completed': True, 'status_str': 'success'},
                    'outputs': {'1': {'images': [{'filename': 'image.png', 'subfolder': '', 'type': 'output'}]}}}}
        @remote.get('/view')
        def view():
            calls.append('view')
            return Response(b'isolated-result')
        @remote.websocket('/ws')
        async def ws(socket: WebSocket):
            await socket.accept()
            try:
                await socket.receive_text()
            except WebSocketDisconnect:
                pass
        self.upload()
        workflow = self.record / 'input.json'
        workflow.write_text(json.dumps(self.data.workflow), 'utf-8')
        uploads = self.record / 'uploads.json'
        uploads.write_text(json.dumps(self.data.uploads), 'utf-8')
        outputs = self.record / 'outputs.json'
        outputs.write_text(json.dumps([out.model_dump() for out in self.data.outputs]), 'utf-8')
        image_draft = self.project / 'image-draft.md'
        image_draft.write_text('# 工作稿\n### 生成记录-001\n- 执行状态：等待\n- 输出候选文件：未取得\n'
            '- 实际尺寸、格式及数量：待核对\n- 文件核对结论：待核对\n- 审阅记录入口：尚无\n## 4. 审阅区\n', 'utf-8')
        image_plan = self.record / 'image-plan.json'
        image_plan.write_text(json.dumps(dict(draft='image-draft.md', kind='人物', generation='生成记录-001',
            review='审阅-生成记录-001-001', images=[dict(path=self.data.outputs[0].path, width=4, height=3)])), 'utf-8')
        adapter = self.root / 'codex/plugins/cache/openai-bundled/codex-app-tools/test/server.mjs'
        adapter.parent.mkdir(parents=True)
        adapter.write_text('// Metadata only; never executed by this test.', 'utf-8')
        async with serving(remote) as remote_url, serving(api) as api_url:
            (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [remote_url]}), 'utf-8')
            self.data.url = remote_url
            service = self.root / '工作区浏览服务/runtime/task-service.json'
            service.parent.mkdir(parents=True)
            service.write_text(json.dumps({'url': api_url, 'token': self.store.token}), 'utf-8')
            command = [sys.executable, '-X', 'utf8', '-B', str(t.SKILL / 'scripts/comfyui_dispatch.py'),
                       '--project', str(self.project), '--task-type', 'image', '--workflow', str(workflow),
                       '--uploads', str(uploads), '--output-plan', str(outputs), '--record-dir', str(self.record),
                       '--image-plan', str(image_plan),
                       '--task-title', '隔离测试']
            async def cli(*extra):
                process = await asyncio.create_subprocess_exec(*command, *extra,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, 'CODEX_THREAD_ID': self.data.thread_id,
                         'CODEX_APP_TOOLS_PIPE_PATH': 'isolated-unused-pipe', 'CODEX_HOME': str(self.root / 'codex')})
                out, err = await asyncio.wait_for(process.communicate(), 15)
                self.assertEqual(process.returncode, 0, err.decode('utf-8') + out.decode('utf-8'))
                return json.loads(out)['data']
            with patch.object(checks, 'fixed_checks', wraps=checks.fixed_checks) as fixed, \
                    patch.object(self.store, 'queue_notice'), patch.object(self.store, 'notify', AsyncMock()):
                self.assertTrue((await cli('--prepare-only'))['prepared'])
                key = (await cli())['local_task_id']
                self.node()
                await self.store.dispatch_once()
                await asyncio.wait_for(self.store.workers[key], 10)
                fixed.assert_called_once()
            self.assertEqual(self.store.rows[key]['state']['status'], 'completed')
            self.assertEqual(Path(self.data.outputs[0].path).read_bytes(), b'isolated-result')
            self.assertEqual(calls, ['upload', 'prompt', 'view'])
