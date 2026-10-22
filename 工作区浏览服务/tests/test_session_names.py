"""Only initialize + metadata read; no model turn, resume, queue or real task."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.services import session_names as names


class SessionNameTests(unittest.IsolatedAsyncioTestCase):
    def process(self, response):
        process = Mock()
        process.stdin.drain = AsyncMock()
        process.wait = AsyncMock(return_value=0)
        process.stdout = asyncio.StreamReader()
        for message in ({'id': 1, 'result': {}}, {'method': 'server/status', 'params': {}}, response):
            process.stdout.feed_data((json.dumps(message) + '\n').encode())
        process.stdout.feed_eof()
        self.launch = self.enterContext(patch.object(names.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)))
        return process

    async def test_protocol_reads_exact_thread_name_without_turns_or_resume(self):
        process = self.process({'id': 2, 'result': {'thread': {'id': 'target-thread', 'name': '  制作会话  '}}})
        self.assertEqual(await names.read_thread_name('codex-cli', 'target-thread'), '制作会话')
        self.assertEqual(self.launch.call_args.args, ('codex-cli', 'app-server', '--listen', 'stdio://'))
        sent = [json.loads(call.args[0]) for call in process.stdin.write.call_args_list]
        self.assertEqual([message['method'] for message in sent], ['initialize', 'initialized', 'thread/read'])
        self.assertEqual(sent[-1]['params'], {'threadId': 'target-thread', 'includeTurns': False})
        process.stdin.close.assert_called_once()
        process.wait.assert_awaited_once()

    async def test_wrong_thread_id_is_not_accepted(self):
        self.process({'id': 2, 'result': {'thread': {'id': 'other-thread', 'name': '不能串名'}}})
        with self.assertRaisesRegex(ValueError, '编号不匹配'):
            await names.read_thread_name('codex-cli', 'target-thread')

    async def test_unnamed_thread_is_not_replaced_with_preview_or_project(self):
        process = self.process({'id': 2, 'result': {'thread': {'id': 'target-thread', 'name': None, 'preview': '不是标题'}}})
        with self.assertRaisesRegex(ValueError, '尚未命名'):
            await names.read_thread_name('codex-cli', 'target-thread')
        process.stdin.close.assert_called_once()

    async def test_rpc_error_preserves_diagnostic_and_closes_child(self):
        process = self.process({'id': 2, 'error': {'code': -32000, 'message': 'thread not found'}})
        with self.assertRaisesRegex(OSError, 'thread not found'):
            await names.read_thread_name('codex-cli', 'target-thread')
        process.stdin.close.assert_called_once()

    async def test_timeout_and_cancellation_clean_up_only_the_reader(self):
        process = self.process({'method': 'server/status'})
        process.stdout = asyncio.StreamReader()
        original_timeout = asyncio.timeout
        with patch.object(names.asyncio, 'timeout', side_effect=lambda _: original_timeout(.01)):
            with self.assertRaises(TimeoutError):
                await names.read_thread_name('codex-cli', 'target-thread')
        process.stdin.close.assert_called_once()
        process.stdin.close.reset_mock()
        reader = asyncio.create_task(names.read_thread_name('codex-cli', 'target-thread'))
        await asyncio.sleep(0)
        reader.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await reader
        process.stdin.close.assert_called_once()

    async def test_unresponsive_child_is_killed_after_reader_closes(self):
        process = self.process({'id': 2, 'result': {'thread': {'id': 'target-thread', 'name': '制作会话'}}})
        process.wait.side_effect = [TimeoutError, 0]
        self.assertEqual(await names.read_thread_name('codex-cli', 'target-thread'), '制作会话')
        process.kill.assert_called_once()


if __name__ == '__main__':
    unittest.main()
