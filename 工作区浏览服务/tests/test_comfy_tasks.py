"""Task lifecycle and trust boundaries; temporary projects and simulated remote media only."""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import socket as sockets
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from tests.http_case import HttpTestCase
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from starlette.websockets import WebSocketDisconnect
import uvicorn
from backend import main
from backend.services import comfy_tasks as t


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'projects/测试项目'
        self.project.mkdir(parents=True)
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': ['http://comfy.invalid:8188']}))
        self.record = self.project / '执行附件/任务001'
        self.record.mkdir(parents=True)
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.store.queue_notifications = False
        self.data = t.TaskInput(project=str(self.project), title='测试图', task_type='image',
            url='http://comfy.invalid:8188', workflow={'1': {'class_type': 'SaveImage', 'inputs': {'seed': 9223372036854775807}}},
            record_dir=str(self.record), attempt_name='提交尝试.json', request_name='请求.json', response_name='提交响应.json',
            outputs=[dict(node_id='1', output_key='images', index=0, path=str(self.project / '候选/result.png'), response_name='取回响应.json')],
            thread_id='authorized-target', desktop=dict(node='node', server='server.mjs', pipe='private-pipe', caller_thread='real-caller'))

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    def seed(self, status='queued', notification='waiting'):
        self.store.rows['task'] = {'input': self.data, 'state': {
            'id': 'task', 'project': self.project.name, 'title': '测试图', 'task_type': 'image',
            'prompt_id': 'real-id', 'client_id': 'listener-id', 'status': status, 'notification': notification,
            'created_at': t.client.now(), 'collected': 0, 'expected': 1}}
        self.store.save('task')

    def legacy_registration(self, key):
        """Fixture for registrations persisted before preparation became mandatory."""
        self.store.rows[key]['state'].pop('preparation_required', None)
        self.store.save(key)

    async def test_websocket_opens_before_post_and_same_client_id(self):
        await self.store.prepare_only(self.data)
        order = []
        socket = AsyncMock()
        async def connected(url, **kwargs):
            order.append(('ws', url))
            return socket
        def submit(remote, args, workflow, client_id):
            order.append(('post', client_id))
            self.assertEqual(workflow['1']['inputs']['seed'], 9223372036854775807)
            return {'prompt_id': 'new-id', 'client_id': client_id, 'submission_state': 'accepted'}
        with patch.object(t, 'connect', connected), patch.object(t.client, 'submit', submit), patch.object(self.store, 'watch', AsyncMock()):
            result = await self.store.submit(self.data)
            self.assertIn('clientId=' + order[1][1], order[0][1])
            self.assertEqual(result['monitor'], 'browser')
            self.assertEqual(self.store.rows[result['monitor_id']]['state']['prompt_id'], 'new-id')

    async def test_post_timeout_is_recorded_and_never_retried_on_restart(self):
        await self.store.prepare_only(self.data)
        with patch.object(t, 'connect', AsyncMock(return_value=AsyncMock())), patch.object(t.client, 'submit', side_effect=t.client.ClientError('submission_unknown', 'timeout')) as post:
            with self.assertRaises(t.client.ClientError):
                await self.store.submit(self.data)
            await self.store.start()
            self.assertEqual(post.call_count, 1)
            self.assertEqual(next(iter(self.store.rows.values()))['state']['status'], 'submission_unknown')

    async def test_restart_recovers_existing_id_without_post(self):
        self.seed()
        with patch.object(self.store, 'watch', AsyncMock()) as watch, patch.object(t.client, 'submit') as post:
            await self.store.start()
            await asyncio.sleep(0)
            watch.assert_awaited_once_with('task')
            post.assert_not_called()

    async def test_new_task_cannot_submit_to_backup(self):
        backup = 'http://backup.invalid:8188'
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [self.data.url, backup]}))
        self.data.url = backup
        with patch.object(t, 'connect', AsyncMock()) as connect, patch.object(t.client, 'submit') as post:
            with self.assertRaisesRegex(ValueError, '主节点'):
                await self.store.submit(self.data)
            connect.assert_not_awaited()
            post.assert_not_called()
        self.assertEqual(self.store.rows, {})

    async def test_second_project_reuses_workspace_primary_without_project_configuration(self):
        project = self.root / 'projects/另一个项目'
        project.mkdir()
        data = self.data.model_copy(deep=True)
        data.project = str(project)
        data.record_dir = str(project / '执行附件/新任务')
        data.outputs[0].path = str(project / '候选/result.png')
        self.assertEqual(self.store.validate_registration(data), project.resolve())
        self.assertFalse((project / 'comfyui-config.json').exists())

    async def test_restart_preserves_old_backup_task_address_without_resubmitting(self):
        primary = self.data.url
        backup = 'http://backup.invalid:8188'
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [primary, backup]}))
        self.data.url = backup
        self.seed()
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'watch', AsyncMock()) as watch, patch.object(t.client, 'submit') as post:
            await self.store.start()
            await asyncio.sleep(0)
            watch.assert_awaited_once_with('task')
            post.assert_not_called()
        self.assertEqual(self.store.client_for(self.store.rows['task']['input']).url, backup)

    async def test_removed_endpoint_keeps_history_visible_and_is_not_a_transfer_target(self):
        old_url = self.data.url
        self.seed(status='completed')
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-nodes': [{'url': 'https://new.invalid'}]}))
        snapshot = self.store.public(include_history=False)
        self.assertEqual([node['url'] for node in snapshot['remote_nodes']], ['https://new.invalid', old_url])
        self.assertEqual(snapshot['remote_nodes'][1]['connection'], 'unconfigured')
        self.assertEqual(snapshot['local_counts'][old_url]['history'], 1)
        self.assertEqual(self.store.rows['task']['input'].url, old_url)
        self.assertEqual(self.store.remote_urls(), ['https://new.invalid'])

    async def test_restart_recovers_saved_submit_response_and_preserves_unknown_delivery(self):
        self.seed()
        self.store.save('task', prompt_id=None, status='submitting')
        (self.record / self.data.response_name).write_text(json.dumps({'prompt_id': 'recovered-id'}))
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'watch', AsyncMock()) as watch, patch.object(t.client, 'submit') as post:
            await self.store.start()
            await asyncio.sleep(0)
            self.assertEqual(self.store.rows['task']['state']['prompt_id'], 'recovered-id')
            watch.assert_awaited_once_with('task')
            post.assert_not_called()
        self.store.save('task', status='completed', notification='sending')
        with patch.object(self.store, 'notify', AsyncMock()) as notify:
            await self.store.start()
            self.assertEqual(self.store.rows['task']['state']['notification'], 'delivery_unknown')
            notify.assert_not_awaited()

    async def test_success_collects_exact_output_and_preserves_history(self):
        self.seed()
        identity = {'filename': 'real.png', 'subfolder': 'task', 'type': 'output'}
        result = {'state': 'success', 'history': {'status': {'completed': True}}, 'files': [
            {'node_id': '1', 'output_key': 'images', 'index': 0, 'file': identity}]}
        def download(remote, args):
            target = Path(args.output)
            target.parent.mkdir()
            target.write_bytes(b'media')
            return {'path': str(target), 'remote': identity, 'bytes': 5}
        with patch.object(t.client, 'status', return_value=result), patch.object(t.client, 'download', download):
            self.assertTrue(await self.store.reconcile('task'))
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
        self.assertEqual(json.loads((self.record / '执行结果.json').read_text('utf-8'))['data']['history'], result['history'])
        self.assertTrue((self.record / '取回响应.json').is_file())
        self.assertEqual(self.store.rows['task']['state']['saved_outputs'], [self.data.outputs[0].path])

    async def test_missing_output_is_not_reported_as_downloaded(self):
        self.seed()
        old_file = Path(self.data.outputs[0].path)
        old_file.parent.mkdir()
        old_file.write_bytes(b'previous execution')
        with patch.object(t.client, 'status', return_value={'state': 'success', 'history': {}, 'files': []}):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
        self.assertEqual(self.store.rows['task']['state']['collected'], 0)
        self.assertIn('已保存成果：[]', self.store.notification_text('task'))
        self.assertEqual(old_file.read_bytes(), b'previous execution')

    async def test_start_timestamp_is_remote_event_time_and_survives_restart(self):
        self.seed()
        self.store.record_start('task', {'timestamp': 1791567518669})
        expected = '2026-10-09T17:38:38.669000+00:00'
        self.assertEqual(self.store.rows['task']['state']['started_at'], expected)
        self.store.record_start('task', {'timestamp': 1791567618669})
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(self.store.rows['task']['state']['started_at'], expected)

    async def test_history_recovers_only_matching_start_and_queue_does_not_invent_one(self):
        self.seed()
        with patch.object(t.client, 'status', return_value={'state': 'running', 'history': None, 'queue': {}}):
            await self.store.reconcile('task')
        self.assertIsNone(self.store.rows['task']['state'].get('started_at'))
        result = {'state': 'failed', 'history': {'status': {'messages': [
            ['execution_start', {'prompt_id': 'other-task', 'timestamp': 1}],
            ['execution_start', {'prompt_id': 'real-id', 'timestamp': 1791567518669}]]}}, 'files': []}
        with patch.object(t.client, 'status', return_value=result), patch.object(self.store, 'notify', AsyncMock()):
            await self.store.reconcile('task')
        self.assertEqual(self.store.rows['task']['state']['started_at'], '2026-10-09T17:38:38.669000+00:00')

    async def test_source_session_title_uses_registered_thread_without_messaging(self):
        self.seed()
        result = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'title': '制作会话'}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value=result)) as desktop:
            await self.store.read_session_name('task')
        desktop.assert_awaited_once_with(self.data, 'read')
        self.assertEqual(self.store.public()['tasks'][0]['source_session_name'], '制作会话')

    async def test_failed_task_is_not_downloaded(self):
        self.seed()
        with patch.object(t.client, 'status', return_value={'state': 'failed', 'history': {}, 'files': []}), patch.object(t.client, 'download') as download:
            await self.store.reconcile('task')
            download.assert_not_called()
        self.assertEqual(self.store.rows['task']['state']['status'], 'failed')

    async def test_duplicate_notification_and_unknown_delivery_do_not_resend(self):
        self.seed('completed')
        read = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[read, OSError('response lost')])) as bridge:
            await self.store.notify('task')
            await self.store.notify('task')
            self.assertEqual(bridge.await_count, 2)
        self.assertEqual(self.store.rows['task']['state']['notification'], 'delivery_unknown')

    async def test_cli_queue_notifies_without_private_pipe_read_and_records_receipt(self):
        self.seed('completed')
        self.store.queue_notifications = True
        self.data.desktop.cli = '/codex/app/cli'
        result = t.subprocess.CompletedProcess([], 0, 'Queued message queue-id', '')
        with patch.object(t.subprocess, 'run', return_value=result) as run, patch.object(t.asyncio, 'sleep', AsyncMock()):
            await self.store.notify('task')
            await self.store.notify('task')
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[:5], ['/codex/app/cli', 'queue', '--thread', 'authorized-target', '--message'])
        self.assertIn('本地任务ID：task', args[5])
        self.assertEqual(self.store.rows['task']['state']['notification'], 'sent')
        event = json.loads(self.store.db.execute('SELECT event FROM task_events ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertEqual(event['receipt'], 'Queued message queue-id')
        batch = self.store.rows['task']['state']['notices'][0]['batch_id']
        self.store.acknowledge(batch, self.data.thread_id)
        self.assertEqual(self.store.rows['task']['state']['notification'], 'acknowledged')

    async def test_cli_queue_failure_keeps_reason_and_does_not_resend(self):
        self.seed('completed')
        self.store.queue_notifications = True
        self.data.desktop.cli = '/codex/app/cli'
        result = t.subprocess.CompletedProcess([], 1, '', 'queue unavailable')
        with patch.object(t.subprocess, 'run', return_value=result) as run, patch.object(t.asyncio, 'sleep', AsyncMock()):
            await self.store.notify('task')
            await self.store.notify('task')
        run.assert_called_once()
        self.assertEqual(self.store.rows['task']['state']['notification'], 'delivery_unknown')
        event = json.loads(self.store.db.execute('SELECT event FROM task_events ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertIn('queue unavailable', event['error'])

    async def test_legacy_task_uses_service_cli_without_changing_stored_context(self):
        self.store.queue_notifications = True
        result = t.subprocess.CompletedProcess([], 0, 'Queued message legacy-id', '')
        with patch.dict(t.os.environ, {'CODEX_CLI_PATH': '/codex/service/cli'}), patch.object(t.subprocess, 'run', return_value=result) as run:
            await self.store.desktop_call(self.data, 'send', '完成通知')
        self.assertEqual(run.call_args.args[0], ['/codex/service/cli', 'queue', '--thread', 'authorized-target', '--message', '完成通知'])
        self.assertIsNone(self.data.desktop.cli)

    async def test_busy_thread_waits_before_one_send(self):
        self.seed('completed')
        def read(status):
            return {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': status}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[read('active'), read('idle'), {'isError': False}])) as bridge, patch.object(t.asyncio, 'sleep', AsyncMock()):
            await self.store.notify('task')
            self.assertEqual([call.args[1] for call in bridge.await_args_list], ['read', 'read', 'send'])
        self.assertEqual(self.store.rows['task']['state']['notification'], 'sent')

    async def test_desktop_adapter_keeps_node_pipe_and_busy_check_with_optional_cli(self):
        for cli in (None, '/must-not-run/codex'):
            with self.subTest(cli=cli):
                self.seed('completed')
                self.data.desktop.cli = cli
                responses = [
                    {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': status}}})}]}
                    for status in ('active', 'idle')]
                responses.append({'content': [], 'isError': False})
                completed = [t.subprocess.CompletedProcess([], 0, json.dumps(result), '') for result in responses]
                with patch.object(t.subprocess, 'run', side_effect=completed) as run, patch.object(t.asyncio, 'sleep', AsyncMock()):
                    await self.store.notify('task')
                    await self.store.notify('task')
                self.assertEqual(run.call_count, 3)
                payloads = [json.loads(call.kwargs['input']) for call in run.call_args_list]
                self.assertEqual([payload['operation'] for payload in payloads], ['read', 'read', 'send'])
                for call, payload in zip(run.call_args_list, payloads):
                    self.assertEqual(call.args[0][0], 'node')
                    self.assertTrue(call.args[0][1].endswith('codex_task_bridge.mjs'))
                    self.assertEqual(call.kwargs['env']['CODEX_APP_TOOLS_PIPE_PATH'], 'private-pipe')
                    self.assertEqual(payload['caller'], 'real-caller')
                    self.assertEqual(payload['threadId'], 'authorized-target')
                self.assertEqual(self.store.rows['task']['state']['notification'], 'sent')
                batch = self.store.rows['task']['state']['notices'][0]['batch_id']
                self.store.acknowledge(batch, self.data.thread_id)
                self.assertEqual(self.store.rows['task']['state']['notification'], 'acknowledged')

    async def test_desktop_adapter_tool_error_is_not_recorded_as_sent(self):
        result = t.subprocess.CompletedProcess([], 0, json.dumps({'isError': True, 'content': []}), '')
        with patch.object(t.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(OSError, 'Codex拒绝本次会话操作'):
                await self.store.desktop_call(self.data, 'send', '完成通知')

    async def test_pending_failure_is_superseded_by_success(self):
        self.seed('collection_failed')
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[idle, {}])) as call, patch.object(t.asyncio, 'sleep', AsyncMock()):
            self.store.queue_notice('task', 'issue', 'attention', '旧取回失败')
            self.store.save('task', status='completed', error=None, collection_attempt=2)
            self.store.queue_notice('task', 'terminal', 'terminal', '现在成功')
            await self.store.notifiers['task']
            sent = call.await_args_list[-1].args[2]
            self.assertIn('completed', sent)
            self.assertNotIn('旧取回失败', sent)
            self.assertEqual(sum(item.args[1] == 'send' for item in call.await_args_list), 1)
        self.assertEqual([item['delivery'] for item in self.store.rows['task']['state']['notices']], ['superseded', 'sent'])

    async def test_same_source_tasks_merge_and_acknowledge_unknown_delivery(self):
        self.seed('completed')
        self.store.rows['second'] = {'input': self.data.model_copy(update={'record_dir': str(self.record / 'second')}),
                                     'state': {**self.store.rows['task']['state'], 'id': 'second'}}
        self.store.save('second')
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[idle, OSError('reply lost')])) as call, patch.object(t.asyncio, 'sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            self.store.queue_notice('second', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
            await self.store.notifiers['second']
            self.assertEqual(sum(item.args[1] == 'send' for item in call.await_args_list), 1)
            self.assertIn('本地任务ID：task', call.await_args_list[-1].args[2])
            self.assertIn('本地任务ID：second', call.await_args_list[-1].args[2])
            batch = self.store.rows['task']['state']['notices'][0]['batch_id']
            self.assertEqual(self.store.rows['second']['state']['notification'], 'delivery_unknown')
            with self.assertRaises(ValueError):
                self.store.acknowledge(batch, 'another-thread')
            self.store.acknowledge(batch, self.data.thread_id)
            self.assertEqual(self.store.rows['second']['state']['notification'], 'acknowledged')
            await self.store.notify('task')
            self.assertEqual(call.await_count, 2)

    async def test_progress_and_short_disconnect_do_not_enqueue_attention(self):
        self.seed('running')
        self.store.save('task', progress={'value': 1, 'max': 9}, connection='reconnecting')
        self.assertNotIn('notices', self.store.rows['task']['state'])

    async def test_paths_and_remote_endpoint_are_checked(self):
        self.data.outputs[0].path = str(self.root / 'escape.png')
        with self.assertRaises(ValueError):
            await self.store.enqueue(self.data)
        self.data.outputs[0].path = str(self.project / 'ok.png')
        self.data.url = 'http://other.invalid'
        with self.assertRaises(ValueError):
            self.store.validate_registration(self.data)

    async def test_public_snapshot_has_no_desktop_connection(self):
        self.seed()
        raw = json.dumps(self.store.public())
        self.assertNotIn('private-pipe', raw)
        self.assertNotIn('real-caller', raw)
        self.assertNotIn('server.mjs', raw)

    async def test_public_nodes_follow_config_order_and_task_remote(self):
        urls = ['http://comfy.invalid:8188', 'http://comfy.invalid:8189',
                'http://comfy.invalid:8190', 'http://comfy.invalid:8191']
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': urls}))
        second_project = self.root / 'projects/另一项目'
        second_project.mkdir()
        (second_project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': urls}))
        self.data.url = urls[1] + '/'
        self.seed()
        self.store.save('task', node='H3')
        snapshot = self.store.public()
        self.assertEqual([{'url': node['url'], 'name': node['name']} for node in snapshot['remote_nodes']], [
            {'url': url, 'name': name} for url, name in zip(urls, ['默认节点', '备用1', '备用2', '备用3'])])
        self.assertTrue(all(node['running_count'] is None and node['updated_at'] is None
                            for node in snapshot['remote_nodes']))
        self.assertEqual(snapshot['tasks'][0]['remote_url'], urls[1])
        self.assertEqual(snapshot['tasks'][0]['node'], 'H3')

    async def test_public_nodes_include_idle_legacy_config(self):
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-url': self.data.url + '/'}))
        snapshot = self.store.public()
        self.assertEqual(snapshot['tasks'], [])
        self.assertEqual(snapshot['remote_nodes'][0], {
            'url': self.data.url, 'name': '默认节点', 'connection': 'connecting',
            'queue': [], 'running_count': None, 'queued_count': None,
            'updated_at': None, 'error': None, 'queue_error': None})

    async def test_foreign_events_are_ignored_and_terminal_event_wakes_once(self):
        self.seed()
        socket = AsyncMock()
        socket.recv.side_effect = [
            b'preview',
            json.dumps({'type': 'execution_start', 'data': {'prompt_id': 'other-user'}}),
            json.dumps({'type': 'progress', 'data': {'prompt_id': 'other-user', 'value': 99, 'max': 100}}),
            json.dumps({'type': 'execution_start', 'data': {'prompt_id': 'real-id'}}),
            json.dumps({'type': 'executing', 'data': {'prompt_id': 'real-id', 'node': '1'}}),
            json.dumps({'type': 'progress', 'data': {'prompt_id': 'real-id', 'value': 3, 'max': 20}}),
            json.dumps({'type': 'execution_success', 'data': {'prompt_id': 'real-id'}})]
        async def reconcile(key):
            if self.store.rows[key]['state'].get('progress'):
                self.assertEqual(self.store.rows[key]['state']['progress'], {'value': 3, 'max': 20})
                self.assertEqual(self.store.rows[key]['state']['started_at'], '2026-10-09T08:30:00+00:00')
                self.assertNotEqual(self.store.rows[key]['state']['started_at'], self.store.rows[key]['state']['created_at'])
                self.store.save(key, status='completed')
                return True
            return False
        with patch.object(self.store, 'reconcile', reconcile), patch.object(self.store, 'notify', AsyncMock()) as notify, patch.object(t.client, 'now', return_value='2026-10-09T08:30:00+00:00'):
            await self.store.watch('task', socket)
            notify.assert_awaited_once_with('task')
            socket.close.assert_awaited_once()

    async def test_disconnect_reconciles_existing_id_without_post(self):
        self.seed()
        original, restored = AsyncMock(), AsyncMock()
        original.recv.side_effect = OSError('connection lost')
        async def reconcile(key):
            if self.store.rows[key]['state']['connection'] == 'connected' and original.close.await_count:
                self.store.save(key, status='completed')
                return True
            return False
        with patch.object(t, 'connect', AsyncMock(return_value=restored)), patch.object(t.asyncio, 'sleep', AsyncMock()), \
                patch.object(self.store, 'reconcile', reconcile), patch.object(self.store, 'notify', AsyncMock()), \
                patch.object(t.client, 'submit') as post:
            await self.store.watch('task', original)
            post.assert_not_called()
            original.close.assert_awaited_once()
            restored.close.assert_awaited_once()


    async def test_real_websocket_http_submit_history_and_download(self):
        remote = FastAPI()
        saved = {'socket': None, 'posts': 0, 'completed': False}
        @remote.websocket('/ws')
        async def ws(websocket: WebSocket):
            await websocket.accept()
            saved['socket'] = websocket
            saved['client_id'] = websocket.query_params['clientId']
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                return
        @remote.post('/prompt')
        async def prompt(request: Request):
            payload = await request.json()
            self.assertEqual(payload['client_id'], saved['client_id'])
            self.assertEqual(payload['prompt']['1']['inputs']['seed'], 9223372036854775807)
            saved['posts'] += 1
            async def finish():
                await asyncio.sleep(.1)
                saved['completed'] = True
                await saved['socket'].send_json({'type': 'execution_success', 'data': {'prompt_id': 'wire-id'}})
            asyncio.create_task(finish())
            return {'prompt_id': 'wire-id'}
        @remote.get('/queue')
        def queue():
            return {'queue_pending': [[0, 'wire-id']] if saved['posts'] and not saved['completed'] else [], 'queue_running': []}
        @remote.get('/history/wire-id')
        def history():
            return {'wire-id': {'status': {'completed': True, 'status_str': 'success'}, 'outputs': {
                '1': {'images': [{'filename': 'wire.png', 'subfolder': '', 'type': 'output'}]}}}} if saved['completed'] else {}
        @remote.get('/view')
        def view(filename: str):
            self.assertEqual(filename, 'wire.png')
            return Response(b'wire-media', media_type='image/png')
        listener = sockets.socket()
        listener.bind(('127.0.0.1', 0))
        url = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(remote, log_level='error', lifespan='off'))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            await asyncio.sleep(.01)
        self.data.url = url
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls': [url]}))
        try:
            with patch.object(self.store, 'notify', AsyncMock()) as notify:
                await self.store.prepare_only(self.data)
                result = await self.store.enqueue(self.data)
                self.store.remote_queues.states[url] = {'connection': 'connected', 'queue': [],
                    'running_count': 0, 'queued_count': 0, 'updated_at': t.client.now(), 'queue_error': None}
                await self.store.dispatch_once()
                await asyncio.wait_for(self.store.workers[result['monitor_id']], 5)
                self.assertEqual(saved['posts'], 1)
                self.assertEqual(Path(self.data.outputs[0].path).read_bytes(), b'wire-media')
                self.assertEqual(self.store.rows[result['monitor_id']]['state']['status'], 'completed')
                notify.assert_awaited_once()
        finally:
            server.should_exit = True
            await serving
            listener.close()


class ApiBoundaryTests(HttpTestCase):
    def test_queue_writes_require_same_origin_and_agent_receipts_require_token(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'projects/test'
            project.mkdir(parents=True)
            (Path(folder) / 'comfyui-config.json').write_text(json.dumps({'remote-urls': ['http://comfy.invalid:8188']}))
            store = t.TaskStore(Path(folder), Path(folder))
            main.app.state.comfy_tasks = store
            api = TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234))
            try:
                self.assertEqual(api.post('/api/comfy/drag', json={}).status_code, 403)
                self.assertEqual(api.post('/api/comfy/drag', json={}, headers={'origin': 'http://evil.invalid'}).status_code, 403)
                result = api.post('/api/comfy/drag', json={}, headers={'origin': 'http://127.0.0.1'})
                self.assertEqual(result.status_code, 200)
                token = result.json()['token']
                with patch.object(store, 'reorder') as reorder:
                    self.assertEqual(api.put('/api/comfy/order', json={'token': token, 'ids': []},
                        headers={'origin': 'http://127.0.0.1'}).status_code, 200)
                    reorder.assert_called_once_with([], token)
                self.assertEqual(api.post('/api/internal/comfy/tasks/missing/retry-collection', json={}).status_code, 403)
                self.assertEqual(api.get('/api/internal/comfy/tasks/missing', headers={'x-nora-task-token': store.token}).status_code, 404)
            finally:
                api.close()
                store.db.close()
    def test_browser_cannot_submit_even_from_loopback(self):
        with tempfile.TemporaryDirectory() as folder:
            store = t.TaskStore(Path(folder), Path(folder))
            main.app.state.comfy_tasks = store
            data = dict(project=folder, title='invalid', task_type='image', url='http://remote.invalid', workflow={},
                record_dir=folder, attempt_name='a', request_name='b', response_name='c', outputs=[], thread_id='t',
                desktop=dict(node='node', server='server', pipe='secret', caller_thread='t'))
            # No lifespan here: never touch the real runtime in this boundary test.
            main.app.state.comfy_tasks = store
            api = TestClient(main.app, client=('127.0.0.1', 1234))
            try:
                self.assertEqual(api.post('/api/internal/comfy/submit', json=data).status_code, 403)
                self.assertEqual(api.post('/api/internal/comfy/submit', json=data,
                    headers={'origin': 'http://localhost', 'x-nora-task-token': store.token}).status_code, 403)
                snapshot = api.get('/api/comfy/tasks').json()
                self.assertEqual(snapshot, {'tasks': [], 'remote_nodes': [], 'local_tasks': []})
                self.assertEqual(api.delete('/api/comfy/tasks').status_code, 405)
            finally:
                api.close()
                store.db.close()
