"""Preparation owns upload/name checks; runtime owns actual execution evidence."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, execution_checks as checks
from tests import test_comfy_tasks as base


class PreparedInputChecksTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)

    async def test_formats_and_planned_names_checked_once_through_actual_upload_and_submit(self):
        source = self.project / 'prepared-source.png'
        source.write_bytes(b'image')
        self.data.uploads = [{'file': str(source), 'node': '1', 'input': 'seed', 'subfolder': 'planned-folder',
                              'response-name': 'prepared-upload.json'}]
        def respond(route, *args):
            if route == '/upload/image':
                return {'name': 'remote-name.png', 'subfolder': 'actual-folder', 'type': 'input'}
            self.assertEqual(route, '/prompt')
            return {'prompt_id': 'mock-id'}
        with patch.object(checks, 'fixed_input_checks', wraps=checks.fixed_input_checks) as fixed, \
                patch.object(t.client, 'remote_path', wraps=t.client.remote_path) as names, \
                patch.object(t.client.Client, 'json', side_effect=respond) as remote, \
                patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(self.store, 'watch', AsyncMock()):
            await self.store.prepare_only(self.data)
            first_names = [call.args for call in names.call_args_list]
            fixed.assert_called_once()
            # Explicit unchanged preparation reuses its report too.
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])
            self.assertEqual([call.args for call in names.call_args_list], first_names)
            with patch.object(checks, 'read_report', side_effect=AssertionError('入队不读取报告')):
                key = (await self.store.enqueue(self.data))['local_task_id']
            self.assertEqual([call.args for call in names.call_args_list], first_names)
            workflow = await self.store.prepare(key)
            await self.store.submit(self.data, key=key, workflow=workflow)
            await asyncio.sleep(0)
            fixed.assert_called_once()
            # Only real upload response names are new information at runtime.
            self.assertEqual([call.args for call in names.call_args_list[len(first_names):]],
                             [('remote-name.png',), ('actual-folder',)])
            self.assertEqual([call.args[0] for call in remote.call_args_list], ['/upload/image', '/prompt'])

    async def test_malformed_upload_is_registered_without_name_or_format_checks_then_stops(self):
        self.data.uploads = [{'file': 42, 'response-name': '../unsafe.json'}]
        with patch.object(checks, 'fixed_input_checks', side_effect=AssertionError('入队不查格式')), \
                patch.object(t.client, 'remote_path', side_effect=AssertionError('入队不查文件名')):
            key = (await self.store.enqueue(self.data))['local_task_id']
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(checks, 'fixed_input_checks', side_effect=AssertionError('开工不补查格式')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '新任务必须先通过准备检查'):
                await self.store.prepare(key)
            upload.assert_not_called()
            submit.assert_not_called()
        self.assertFalse((self.project.parent / 'unsafe.json').exists())

    async def test_changed_name_fails_comparison_without_rerunning_fixed_checks(self):
        await self.store.prepare_only(self.data)
        self.data.response_name = '../changed.json'
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(checks, 'fixed_input_checks', side_effect=AssertionError('不自动重查修改资料')), \
                patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '准备资料已变化'):
                await self.store.prepare(key)
            upload.assert_not_called()
            submit.assert_not_called()

    async def test_registration_ignores_custom_evidence_but_submission_preserves_it(self):
        original = self.record / self.data.history_name
        original.write_bytes(b'old execution result')
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        workflow = await self.store.prepare(key)
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaises(t.client.ClientError) as error:
                await self.store.submit(self.data, key=key, workflow=workflow)
            self.assertEqual(error.exception.code, 'execution_guard')
            self.assertEqual(error.exception.details['submission_state'], 'not_sent')
            upload.assert_not_called()
            submit.assert_not_called()
        self.assertEqual(original.read_bytes(), b'old execution result')
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')

    async def test_download_receipt_is_preserved_and_does_not_block_registration(self):
        receipt = self.record / self.data.outputs[0].response_name
        receipt.write_bytes(b'original download receipt')
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        workflow = await self.store.prepare(key)
        with patch.object(t.client, 'submit') as submit:
            with self.assertRaises(t.client.ClientError) as error:
                await self.store.submit(self.data, key=key, workflow=workflow)
            self.assertEqual(error.exception.code, 'execution_guard')
            submit.assert_not_called()
        self.assertEqual(receipt.read_bytes(), b'original download receipt')

    async def test_report_path_occupied_by_other_evidence_is_not_overwritten(self):
        evidence = self.record / '执行检查报告.json'
        evidence.write_bytes(b'{"prompt_id":"existing-id"}')
        with self.assertRaisesRegex(ValueError, '已有其他资料'):
            await self.store.prepare_only(self.data)
        self.assertEqual(evidence.read_bytes(), b'{"prompt_id":"existing-id"}')

    async def test_registration_blocks_unowned_backend_records_but_reuses_same_id(self):
        backend_record = self.record / '后台任务状态.json'
        backend_record.write_bytes(b'old backend identity')
        with self.assertRaises(t.client.ClientError) as error:
            await self.store.enqueue(self.data)
        self.assertEqual(error.exception.code, 'registration_guard')
        self.assertEqual(backend_record.read_bytes(), b'old backend identity')
        backend_record.unlink()
        key = (await self.store.enqueue(self.data))['local_task_id']
        self.assertEqual((await self.store.enqueue(self.data))['local_task_id'], key)

    async def test_existing_upload_receipt_is_recovered_after_report_match(self):
        import hashlib
        source = self.project / 'reference.png'
        source.write_bytes(b'uploaded')
        self.data.uploads = [{'file': str(source), 'node': '1', 'input': 'seed', 'subfolder': 'task',
                              'response-name': 'uploaded.json'}]
        receipt = {'ok': True, 'url': self.data.url, 'data': {'input_path': 'task/reference.png',
                   'sha256': hashlib.sha256(b'uploaded').hexdigest(),
                   'remote': {'name': 'reference.png', 'subfolder': 'task', 'type': 'input'}}}
        saved = self.record / 'uploaded.json'
        saved.write_text(json.dumps(receipt), 'utf-8')
        before = saved.read_bytes()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t.client, 'upload') as upload:
            workflow = await self.store.prepare(key)
            upload.assert_not_called()
        self.assertEqual(workflow['1']['inputs']['seed'], 'task/reference.png')
        self.assertEqual(saved.read_bytes(), before)
