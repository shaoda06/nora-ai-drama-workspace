"""Prepared execution reuse and tool ownership; all files/endpoints are isolated."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from backend import main
from backend.services import execution_checks as checks
from backend.services import comfy_tasks as t
from tests import test_comfy_tasks as base


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)

    async def test_prepare_writes_report_without_queue_upload_post_or_content_changes(self):
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            result = await self.store.prepare_only(self.data)
        self.assertTrue(result['prepared'])
        self.assertFalse(self.store.rows)
        self.assertTrue(checks.read_report(self.data)['ok'])
        upload.assert_not_called()
        post.assert_not_called()
        self.assertFalse((self.record / '输入映射.json').exists())

    async def test_prepared_input_reused_without_pair_or_network_recheck(self):
        await self.store.prepare_only(self.data)
        with patch.object(t.client.Client, 'json') as network, \
                patch('backend.services.director_uploads.check_pair') as pair, \
                patch.object(checks, 'fixed_checks', side_effect=AssertionError('固定检查不得重复')), \
                patch.object(t.client, 'validate_workflow', side_effect=AssertionError('结构检查不得重复')), \
                patch.object(checks, 'check_prepared', wraps=checks.check_prepared) as compare:
            key = (await self.store.enqueue(self.data))['local_task_id']
            compare.assert_not_called()
            await self.store.prepare(key)
            compare.assert_called_once()
        network.assert_not_called()
        pair.assert_not_called()
        events = json.loads((self.record / '后台过程记录.json').read_text('utf-8'))
        event = next(event for event in events if event['stage'] == 'preparation')
        self.assertEqual(event['result'], 'reused')
        from backend.services.task_details import task_detail
        detail = await task_detail(self.store, key)
        self.assertTrue(any(record['name'] == '准备检查报告' for record in detail['records']))

    async def test_unprepared_task_gets_fixed_checks_once_at_execution(self):
        with patch.object(checks, 'fixed_checks', wraps=checks.fixed_checks) as fixed:
            key = (await self.store.enqueue(self.data))['local_task_id']
            fixed.assert_not_called()
            await self.store.prepare(key)
            fixed.assert_called_once()
            self.assertEqual(checks.read_report(self.data)['checked_during'], 'execution')
            await self.store.prepare(key)
            fixed.assert_called_once()

    async def test_unprepared_invalid_binding_stops_before_upload_and_post(self):
        source = self.project / 'source.png'
        source.write_bytes(b'reference')
        self.data.uploads = [{'file': str(source), 'node': 'missing-node', 'input': 'seed', 'subfolder': '', 'response-name': 'upload.json'}]
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '上传映射必须绑定已有输入'):
                await self.store.prepare(key)
            upload.assert_not_called()
            post.assert_not_called()
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_output_identity_is_checked_in_preparation_not_enqueue(self):
        self.data.outputs[0].node_id = 'missing-node'
        with self.assertRaisesRegex(ValueError, '预期输出节点不在工作流中'):
            await self.store.prepare_only(self.data)
        self.assertFalse(self.store.rows)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('失败报告不能被自动重做')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '准备资料已变化或检查未通过'):
                await self.store.prepare(key)
            upload.assert_not_called()
            post.assert_not_called()

    async def test_h3_stage_type_is_checked_once_by_preparation_tool(self):
        self.data.workflow['1']['class_type'] = 'MiniMaxH3ReferenceToVideo'
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaises(t.client.ClientError) as error:
                await self.store.prepare(key)
            self.assertEqual(error.exception.code, 'invalid_task_type')
            upload.assert_not_called()
            post.assert_not_called()

    async def test_changed_workflow_is_registered_but_stops_before_upload_or_post(self):
        await self.store.prepare_only(self.data)
        self.data.workflow['1']['inputs']['seed'] = 4
        with patch.object(checks, 'read_report', side_effect=AssertionError('入队不读取准备报告')):
            key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()
            post.assert_not_called()
        self.assertEqual(checks.read_report(self.data)['prepared_input']['workflow']['1']['inputs']['seed'], 9223372036854775807)

    async def test_explicit_preparation_replaces_changed_preparation_result(self):
        await self.store.prepare_only(self.data)
        self.data.workflow['1']['inputs']['seed'] = 4
        await self.store.prepare_only(self.data)  # Explicit preparation can replace its old check result.
        self.assertEqual(checks.read_report(self.data)['prepared_input']['workflow']['1']['inputs']['seed'], 4)

    async def test_source_changed_before_enqueue_is_checked_only_when_execution_starts(self):
        source = self.project / 'source.png'
        source.write_bytes(b'old')
        self.data.uploads = [{'file': str(source), 'node': '1', 'input': 'seed', 'subfolder': 'task', 'response-name': 'upload.json'}]
        await self.store.prepare_only(self.data)
        source.write_bytes(b'changed')
        with patch.object(checks, 'read_report', side_effect=AssertionError('入队不读取准备报告')):
            key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()
            post.assert_not_called()

    async def test_file_change_while_waiting_stops_before_upload(self):
        source = self.project / 'source.png'
        source.write_bytes(b'old')
        self.data.uploads = [{'file': str(source), 'node': '1', 'input': 'seed', 'subfolder': 'task', 'response-name': 'upload.json'}]
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        source.write_bytes(b'changed')
        with patch.object(t.client, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()

    async def test_runtime_file_failure_is_written_as_failed_report(self):
        self.data.uploads = [{'file': str(self.project / 'missing.png'), 'node': '1', 'input': 'seed', 'subfolder': '', 'response-name': 'upload.json'}]
        with self.assertRaises(OSError):
            await self.store.prepare_only(self.data)
        self.assertFalse(checks.read_report(self.data)['ok'])
        self.assertFalse(self.store.rows)

    async def test_prepare_does_not_query_remote_capabilities_or_touch_inventory(self):
        with patch.object(t.client.Client, 'json') as query:
            await self.store.prepare_only(self.data)
            query.assert_not_called()
        self.assertFalse((self.root / 'runtime/comfy-capabilities.json').exists())

    async def test_remote_rejection_details_are_kept_and_never_retried(self):
        detail = {'node_errors': {'1': {'errors': [{'message': 'remote model missing'}]}},
                  'http_status': 400, 'response': {'file': 'models/remote-relative-model.bin'}}
        error = t.client.ClientError('submission_rejected', 'remote refused', **detail)
        def refuse(*args, **kwargs):
            (self.record / self.data.attempt_name).write_text('real attempt evidence')
            raise error
        actual_submit = t.client.submit
        with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), patch.object(t.client, 'submit', side_effect=refuse) as post:
            with self.assertRaises(t.client.ClientError):
                await self.store.submit(self.data)
            key = next(iter(self.store.rows))
            self.assertEqual(self.store.rows[key]['state']['error_details'], detail)
            event = next(event for event in json.loads((self.record / '后台过程记录.json').read_text('utf-8'))
                         if event['stage'] == 'submit' and event['result'] == 'rejected')
            self.assertEqual(event['error_details'], detail)
            with patch.object(t.client, 'submit', wraps=actual_submit), patch.object(t.client.Client, 'json') as network:
                with self.assertRaises(t.client.ClientError) as blocked:
                    await self.store.submit(self.data, key=key)
                self.assertEqual(blocked.exception.details['submission_state'], 'not_sent')
                network.assert_not_called()
            self.assertEqual(self.store.rows[key]['state']['status'], 'rejected')
            self.assertEqual(self.store.rows[key]['state']['error_details'], detail)
            post.assert_called_once()
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/tasks/{key}', main.agent_task_status)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1') as http:
            response = await http.get('/tasks/' + key, headers={'x-nora-task-token': self.store.token})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['error_details'], detail)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(self.store.rows[key]['state']['error_details'], detail)

    async def test_prepare_endpoint_requires_internal_token_and_never_enqueues(self):
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/prepare', main.comfy_prepare, methods=['POST'])
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1') as http:
            self.assertEqual((await http.post('/prepare', json=self.data.model_dump())).status_code, 403)
            response = await http.post('/prepare', json=self.data.model_dump(), headers={'x-nora-task-token': self.store.token})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.store.rows)

    async def test_remote_runtime_error_is_returned_without_rewriting(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        details = {'node_id': '1', 'exception_type': 'FileNotFoundError', 'exception_message': 'remote weight missing', 'traceback': ['remote traceback']}
        with patch.object(t.client, 'submit') as post:
            await self.store.finish_collection(key, {'state': 'failed', 'history': {'status': {'messages': [['execution_error', details]]}}})
            post.assert_not_called()
        self.assertEqual(self.store.rows[key]['state']['error_details'], details)

    async def test_same_endpoint_first_pass_cache_is_checked_by_tool(self):
        workflow = json.loads((t.SKILL / 'references/comfyui-workflow/Minimax-H3-导演台-视频生成-标准版.api.json').read_text('utf-8'))
        self.data.workflow = workflow
        # Register a normal test queue item, then provide the director test fixture.
        image = self.data.model_copy(deep=True)
        image.workflow = {'1': {'class_type': 'SaveImage', 'inputs': {}}}
        key = (await self.store.enqueue(image))['local_task_id']
        self.store.rows[key]['input'].workflow = workflow
        self.store.rows[key]['input'].task_type = 'video-first-pass'
        with patch.object(t.client.Client, 'json', return_value={'can_confirm_refine': True}) as query, \
                patch('backend.services.execution_checks.fixed_checks', return_value={'pair': {}, 'segments': []}), \
                patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '进入二采'):
                await self.store.prepare(key)
            query.assert_called_once()
            self.assertEqual(query.call_args.args[0], '/minimax/director/first_pass_cache_status')
            post.assert_not_called()

    async def test_upload_responses_reach_scoped_binding_save_and_both_media_states(self):
        from backend.services.director_uploads import save_uploaded_workflow
        source = self.project / 'source.png'
        source.write_bytes(b'reference')
        key = (await self.store.enqueue(self.data))['local_task_id']
        workflow = json.loads((t.SKILL / 'references/comfyui-workflow/Minimax-H3-导演台-视频生成-标准版.api.json').read_text('utf-8'))
        timeline = json.loads(workflow['502']['inputs']['timeline_data'])
        media = {'imageFile': 'planned.png', 'fileName': 'planned.png', 'subfolder': '', 'type': 'input', 'index': 0}
        timeline['global']['refs'] = [media.copy()]
        timeline['batchWorkspaces']['r2v']['globalCommon']['refs'] = [media.copy()]
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        self.data.workflow, self.data.task_type = workflow, 'video-first-pass'
        self.data.uploads = [{'file': str(source), 'node': '502', 'input': 'timeline_data', 'subfolder': 'planned',
                              'response-name': 'upload.json', 'json-path': ['global', 'refs', 0, 'imageFile']}]
        (self.record / '输入映射.json').write_text(json.dumps({'uploads': []}), 'utf-8')
        uploaded = {'input_path': 'actual/renamed.png', 'sha256': 'mock-transport-digest',
                    'remote': {'name': 'renamed.png', 'subfolder': 'actual', 'type': 'input'}}
        cache = {'can_confirm_refine': False, 'segments': [
            {'index': index, 'final_matches': True} for index in range(len(timeline['segments']))]}
        with patch.object(t.client, 'upload', return_value=uploaded) as upload, \
                patch('backend.services.execution_checks.fixed_checks', return_value={'pair': {}, 'segments': []}), \
                patch.object(t.client.Client, 'json', return_value=cache), \
                patch('backend.services.director_uploads.save_uploaded_workflow', wraps=save_uploaded_workflow) as save, \
                patch.object(self.store.generation_context, 'prepare_generation_context'), \
                patch.object(t.client, 'submit') as post:
            actual = await self.store.prepare(key)
            upload.assert_called_once()
            save.assert_called_once()
            self.assertEqual(save.call_args.args[-1], [(self.data.uploads[0], uploaded)])
            post.assert_not_called()
        bound = json.loads(actual['502']['inputs']['timeline_data'])
        expected = {'imageFile': 'actual/renamed.png', 'fileName': 'renamed.png', 'subfolder': 'actual', 'type': 'input', 'index': 0}
        self.assertEqual(bound['global']['refs'][0], expected)
        self.assertEqual(bound['batchWorkspaces']['r2v']['globalCommon']['refs'][0], expected)


class LocalFormatTests(unittest.TestCase):
    def test_h3_length_input_labels_counts_and_audio_duration(self):
        group = {'durationSec': 5, 'prompt': '<Picture 1>', 'refs': []}
        common = {'commonEnabled': True, 'prompt': '', 'refs': [{'index': 0, 'imageFile': 'scene.png'}]}
        def workflow():
            return {'1': {'class_type': 'MiniMaxH3Director', 'inputs': {'timeline_data': json.dumps({'global': common, 'segments': [group]})}}}
        self.assertEqual(checks.director_checks(workflow())[0]['counts']['Picture'], 1)
        group['prompt'] = 'x' * 7001
        with self.assertRaisesRegex(ValueError, '7000'):
            checks.director_checks(workflow())
        group['prompt'] = '<Picture 2>'
        with self.assertRaisesRegex(ValueError, '标签'):
            checks.director_checks(workflow())
        group['prompt'] = '<Picture 1>'
        group['refAudios'] = [{'index': 0, 'audioFile': 'voice.wav'}]
        with self.assertRaisesRegex(ValueError, '时长'):
            checks.director_checks(workflow())
        group['refAudios'][0]['durationSec'] = 3
        self.assertEqual(checks.director_checks(workflow())[0]['reference_seconds']['Audio'], 3)


if __name__ == '__main__':
    unittest.main()
