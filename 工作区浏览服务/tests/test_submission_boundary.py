"""One structure check per submission path; only mocked remote generation endpoints."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t
from backend.services import execution_checks as checks
from tests import test_comfy_tasks as base


class SubmissionBoundaryTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await base.TaskTests.asyncTearDown(self)

    async def test_backend_checks_structure_once_from_preparation_through_transport(self):
        with patch.object(t.client, 'validate_workflow', wraps=t.client.validate_workflow) as check, \
                patch.object(checks, 'fixed_checks', wraps=checks.fixed_checks) as fixed, \
                patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(t.client.Client, 'json', return_value={'prompt_id': 'mock-id'}) as remote, \
                patch.object(self.store, 'watch', AsyncMock()):
            await self.store.prepare_only(self.data)
            check.assert_called_once()
            with patch.object(checks, 'read_report', side_effect=AssertionError('入队不读取报告')):
                key = (await self.store.enqueue(self.data))['local_task_id']
            check.assert_called_once()
            fixed.assert_called_once()
            workflow = await self.store.prepare(key)
            result = await self.store.submit(self.data, key=key, workflow=workflow)
            await asyncio.sleep(0)
            check.assert_called_once()
            fixed.assert_called_once()
            remote.assert_called_once()
            self.assertEqual(remote.call_args.args[0], '/prompt')
            self.assertEqual(result['prompt_id'], 'mock-id')

    async def test_invalid_structure_stops_during_preparation(self):
        self.data.workflow['1']['inputs'] = []
        with patch.object(t.client.Client, 'json') as remote:
            with self.assertRaises(t.client.ClientError) as error:
                await self.store.prepare_only(self.data)
            self.assertEqual(error.exception.code, 'invalid_workflow')
            remote.assert_not_called()
        self.assertFalse(self.store.rows)
        self.assertFalse(json.loads((self.record / '执行检查报告.json').read_text('utf-8'))['ok'])

    async def test_existing_response_is_guarded_only_in_transport_and_pauses_unsent_task(self):
        await self.store.prepare_only(self.data)
        evidence = self.record / self.data.response_name
        evidence.write_bytes(b'original remote response')
        key = (await self.store.enqueue(self.data))['local_task_id']
        with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(t.client, 'submit', wraps=t.client.submit) as transport, \
                patch.object(t.client.Client, 'json') as remote:
            with self.assertRaises(t.client.ClientError) as blocked:
                await self.store.submit(self.data, key=key)
            transport.assert_called_once()
            remote.assert_not_called()
            self.assertEqual(blocked.exception.details['submission_state'], 'not_sent')
        state = self.store.rows[key]['state']
        self.assertEqual(state['status'], 'paused')
        self.assertEqual(state['error_details']['submission_state'], 'not_sent')
        self.assertNotIn('dispatch_attempt', state)
        self.assertEqual(evidence.read_bytes(), b'original remote response')
        self.assertFalse((self.record / self.data.attempt_name).exists())
        events = json.loads((self.record / '后台过程记录.json').read_text('utf-8'))
        self.assertEqual([event['result'] for event in events if event['stage'] == 'submit'], ['started', 'blocked'])

    async def test_blocked_retry_preserves_unknown_task_and_original_error(self):
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        details = {'submission_state': 'unknown', 'response': {'file': 'remote/value'}}
        self.store.save(key, status='submission_unknown', phase='submit', failure_stage='submit',
                        dispatch_attempt=1, error='original timeout', error_details=details)
        (self.record / self.data.attempt_name).write_bytes(b'original attempt')
        previous = self.store.rows[key]['state'].copy()
        with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), \
                patch.object(t.client.Client, 'json') as remote:
            with self.assertRaises(t.client.ClientError) as blocked:
                await self.store.submit(self.data, key=key)
            self.assertEqual(blocked.exception.details['submission_state'], 'not_sent')
            remote.assert_not_called()
        actual = self.store.rows[key]['state']
        self.assertEqual({k: v for k, v in actual.items() if k != 'updated_at'},
                         {k: v for k, v in previous.items() if k != 'updated_at'})

    async def test_accepted_id_uses_existing_task_state_without_transport(self):
        key = (await self.store.enqueue(self.data))['local_task_id']
        self.store.save(key, prompt_id='existing-id', status='queued')
        with patch.object(t, 'connect', AsyncMock()) as connect, patch.object(t.client, 'submit') as transport:
            with self.assertRaisesRegex(ValueError, '已有远端ID'):
                await self.store.submit(self.data, key=key)
            connect.assert_not_awaited()
            transport.assert_not_called()
        self.assertEqual(self.store.rows[key]['state']['status'], 'queued')

    async def test_connection_failure_does_not_replace_existing_unknown_result(self):
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        self.store.save(key, status='submission_unknown', error='original timeout', error_details={'original': True})
        previous = self.store.rows[key]['state'].copy()
        with patch.object(t, 'connect', AsyncMock(side_effect=OSError('connection unavailable'))), \
                patch.object(t.client, 'submit') as transport:
            with self.assertRaisesRegex(OSError, 'connection unavailable'):
                await self.store.submit(self.data, key=key)
            transport.assert_not_called()
        self.assertEqual(self.store.rows[key]['state'], previous)
