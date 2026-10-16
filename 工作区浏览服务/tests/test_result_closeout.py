"""Temporary projects and fake remotes: collection -> receipt -> ACK -> review page."""
import asyncio
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from backend import main
from backend.services import comfy_tasks as t
from backend.services.desktop_channel import DesktopChannel
from backend.services.projects import ProjectStore
from backend.services.result_registration import closeout, register, REPORT
from backend.services.result_summary import summary
from tests import test_comfy_tasks as base, test_submission_lifecycle as lifecycle


class CloseoutTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = lifecycle.LifecycleTests.asyncSetUp
    asyncTearDown = lifecycle.LifecycleTests.asyncTearDown
    video = lifecycle.LifecycleTests.video

    def setup_video(self):
        self.video()
        identity = 'EP001-C001-P001-R001-一采'
        candidate = self.project / '09-剧集制作/EP001/其他资料/候选视频' / (identity + '.mp4')
        self.data.segment_plan.targets[0].path = str(candidate)
        base.TaskTests.seed(self, status='running')
        self.store.generation_context.prepare_generation_context(self.data.project, self.record,
            self.data.workflow, self.data.task_type, {'planned/ref.png': {'file': str(self.project / 'reference.png')}}, fixed_checked=True)
        draft = self.project / '09-剧集制作/EP001/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md'
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text('# 分段工作稿\n## 2. 执行记录\n### R001-一采\n- 原文：保留。\n## 3. 人工审阅\n', 'utf-8')
        index = self.project / '09-剧集制作/EP001/03-分镜脚本/EP001-分镜索引.md'
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text('| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n| EP001-C001 | EP001-C001-P001 | 3 |\n', 'utf-8')
        screenplay = self.project / '09-剧集制作/EP001/02-剧集剧本/EP001-本集剧本.md'
        screenplay.parent.mkdir(parents=True, exist_ok=True)
        screenplay.write_text('## 1. 故事剧本正文\n### EP001-C001\n测试场次。\n', 'utf-8')
        self.terminal = {'state': 'success', 'files': [], 'history': {'outputs': {'403': {'text': [
            'Segment 1/1: 一采 mp4 saved → E:/Comfy/output/minimax_seg_export/run/seg_0000_pre.mp4']}}}}
        self.projects = ProjectStore(self.project.parent)
        self.store.projects = self.projects
        return candidate, draft

    def download(self, remote, args):
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'isolated media')
        return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'remote': {name: getattr(args, name) for name in ('filename', 'subfolder', 'type')}}

    async def collect_and_notice(self, automatic=False):
        """Legacy fixtures exercise explicit repair; automatic=True exercises new delivery."""
        with patch.object(t.client, 'download', side_effect=self.download) as download:
            await self.store.finish_collection('task', self.terminal)
        download.assert_called_once()
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        legacy = nullcontext() if automatic else patch.object(self.store, 'prepare_report', AsyncMock(return_value={
            'tasks': [summary(self.store, 'task')], 'results': [], 'user_message_ready': False}))
        with legacy, patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[idle, {}])), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        return self.store.rows['task']['state']['notices'][0]['batch_id']

    async def test_http_ack_register_and_real_parser_review_page(self):
        candidate, draft = self.setup_video()
        batch = await self.collect_and_notice()
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/ack/{batch_id}', main.agent_notice_ack, methods=['POST'])
        app.add_api_route('/register/{batch_id}', main.agent_register_results, methods=['POST'])
        headers = {'x-nora-task-token': self.store.token}
        with patch.object(main, 'store', self.projects), patch.object(t.client, 'submit') as submit, \
                patch.object(t.client, 'status') as remote, patch.object(t.client, 'download') as download:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=headers) as http:
                ack = await http.post('/ack/' + batch, json={'thread_id': self.data.thread_id})
                self.assertEqual(ack.status_code, 200, ack.text)
                self.assertEqual(ack.json()['tasks'][0]['outputs'][0]['identity'], candidate.stem)
                result = await http.post('/register/' + batch, json={'thread_id': self.data.thread_id})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertTrue(result.json()['user_message_ready'], result.text)
                self.assertIn('registered_at', result.json()['results'][0])
                self.assertIn('verified_at', result.json()['results'][0]['browser'])
                before = draft.read_bytes()
                again = await http.post('/register/' + batch, json={'thread_id': self.data.thread_id})
                self.assertTrue(again.json()['results'][0]['reused'])
                self.assertEqual(draft.read_bytes(), before)
            submit.assert_not_called(); remote.assert_not_called(); download.assert_not_called()
        text = draft.read_text('utf-8')
        self.assertIn('- 原文：保留。', text)
        self.assertIn('- 决定：待审核', text)
        self.assertNotIn('- 决定：批准采用', text)

    async def test_ack_is_idempotent_and_rejects_other_thread(self):
        self.setup_video()
        batch = await self.collect_and_notice()
        self.store.acknowledge(batch, self.data.thread_id)
        changes = self.store.db.total_changes
        result = self.store.acknowledge(batch, self.data.thread_id)
        self.assertTrue(result['reused'])
        self.assertEqual(self.store.db.total_changes, changes)
        with self.assertRaises(ValueError): self.store.acknowledge(batch, 'different-source')

    async def test_registration_resume_preserves_existing_user_decision(self):
        candidate, draft = self.setup_video()
        batch = await self.collect_and_notice()
        decision = '\n### 审阅-R001-一采-001\n- 被审具体输出：' + candidate.name + '\n- 决定：修改后再审\n- 用户反馈：保留原话。\n'
        draft.write_text(draft.read_text('utf-8') + decision, 'utf-8')
        result = register(self.store, 'task')
        self.assertEqual(result['status'], 'registered')
        self.assertIn(decision, draft.read_text('utf-8'))
        self.assertNotIn('- 决定：待审核', draft.read_text('utf-8'))
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertEqual(register(self.store, 'task'), result)
        self.store.acknowledge(batch, self.data.thread_id)

    async def test_browser_failure_returns_source_report_and_can_resume(self):
        _, draft = self.setup_video()
        batch = await self.collect_and_notice()
        self.projects.get(self.project.name)
        with patch.object(self.projects, 'snapshot', side_effect=OSError('browser unavailable')):
            result = await closeout(self.store, self.projects, batch, self.data.thread_id)
        self.assertFalse(result['user_message_ready'])
        self.assertEqual(self.store.rows['task']['state']['closeout']['status'], 'browser_pending')
        before = draft.read_bytes()
        result = await closeout(self.store, self.projects, batch, self.data.thread_id)
        self.assertTrue(result['user_message_ready'], result)
        self.assertEqual(draft.read_bytes(), before)

    async def test_file_published_without_receipt_is_never_overwritten(self):
        candidate, _ = self.setup_video()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b'original unconfirmed bytes')
        # Use real download's existing-file guard without any network call.
        with patch.object(t.client.Client, 'open', side_effect=AssertionError('no network')):
            await self.store.finish_collection('task', self.terminal)
        self.assertEqual(candidate.read_bytes(), b'original unconfirmed bytes')
        self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
        self.assertEqual(self.store.rows['task']['state']['collection_retry_stop'], 'requires_attention')

    async def test_malformed_saved_result_finishes_with_one_problem_notice(self):
        self.setup_video()
        (self.record / self.data.history_name).write_text('{broken', 'utf-8')
        with patch.object(self.store, 'queue_notice') as notice, patch.object(t.client, 'status') as remote:
            await self.store.collect_saved('task')
        self.assertEqual(self.store.rows['task']['state']['status'], 'collection_failed')
        notice.assert_called_once(); remote.assert_not_called()

    async def test_final_report_reused_on_retry_and_success_metadata_not_read_twice(self):
        self.setup_video()
        await self.collect_and_notice()
        from backend.services import comfy_segments as segments
        with patch.object(segments, 'saved_files', wraps=segments.saved_files) as stamps, \
                patch.object(t.client, 'download') as download:
            # A retry with the same terminal object reuses the parsed report and one proof per success.
            await self.store.finish_collection('task', self.terminal)
        self.assertEqual(stamps.call_count, 1)
        download.assert_not_called()

    async def test_registration_interruption_resume_and_concurrent_edit_protection(self):
        _, draft = self.setup_video()
        await self.collect_and_notice()
        original_replace = Path.replace
        def interrupt(path, target):
            if str(path.name).startswith('.nora-result-'):
                raise OSError('simulated interrupted write')
            return original_replace(path, target)
        with patch.object(Path, 'replace', interrupt):
            with self.assertRaises(OSError): register(self.store, 'task')
        report_file = self.record / REPORT
        self.assertEqual(json.loads(report_file.read_text('utf-8'))['status'], 'registering')
        self.assertNotIn('- 决定：待审核', draft.read_text('utf-8'))
        draft.write_text(draft.read_text('utf-8') + '\n用户并发修改。', 'utf-8')
        with self.assertRaisesRegex(ValueError, '登记期间源资料已被修改'):
            register(self.store, 'task')
        self.assertIn('用户并发修改。', draft.read_text('utf-8'))

    async def test_registration_after_written_draft_reuses_journal_and_no_duplicate_review(self):
        _, draft = self.setup_video()
        await self.collect_and_notice()
        from backend.services import result_registration as registration
        write = registration.write_json
        def interrupted(path, value):
            if value.get('status') == 'registered': raise OSError('report write interrupted')
            return write(path, value)
        with patch.object(registration, 'write_json', interrupted):
            with self.assertRaises(OSError): register(self.store, 'task')
        before = draft.read_bytes()
        result = register(self.store, 'task')
        self.assertEqual(result['status'], 'registered')
        self.assertEqual(draft.read_bytes(), before)
        self.assertEqual(draft.read_text('utf-8').count('### 审阅-R001-一采-001'), 1)

    async def test_business_updates_after_closeout_are_not_ignored_or_repeated(self):
        self.setup_video()
        batch = await self.collect_and_notice()
        await closeout(self.store, self.projects, batch, self.data.thread_id)
        progress = self.project / '项目进度.md'
        progress.write_text('| EP001 | 生成中 |\n', 'utf-8')
        changes = [{'path': '项目进度.md', 'old': '| EP001 | 生成中 |', 'new': '| EP001 | 待审核 |'}]
        with patch.object(self.projects, 'scan', wraps=self.projects.scan) as scan:
            result = await closeout(self.store, self.projects, batch, self.data.thread_id, changes)
            self.assertTrue(result['user_message_ready'], result)
            scan.assert_called_once()
        self.assertIn('待审核', progress.read_text('utf-8'))
        before = progress.read_bytes()
        with patch.object(self.projects, 'scan') as scan:
            result = await closeout(self.store, self.projects, batch, self.data.thread_id, changes)
            scan.assert_not_called()
        self.assertTrue(result['results'][0]['reused'])
        self.assertEqual(before, progress.read_bytes())
        outside = [{'path': '项目进度.md', 'old': 'EP002', 'new': 'wrong'}]
        result = await closeout(self.store, self.projects, batch, self.data.thread_id, outside)
        self.assertFalse(result['user_message_ready'])
        self.assertEqual(result['results'][0]['status'], 'registration_failed')
        self.assertEqual(before, progress.read_bytes())

    async def test_business_update_interruption_resumes_without_resending_plan(self):
        self.setup_video()
        batch = await self.collect_and_notice()
        progress = self.project / '项目进度.md'
        progress.write_text('EP001 生成中', 'utf-8')
        changes = [{'path': '项目进度.md', 'old': 'EP001 生成中', 'new': 'EP001 待审核'}]
        from backend.services import result_registration as registration
        original = registration.write_json
        def interrupted(path, value):
            if value.get('record_updates', {}).get('status') == 'completed': raise OSError('interrupt journal commit')
            return original(path, value)
        with patch.object(registration, 'write_json', interrupted):
            result = await closeout(self.store, self.projects, batch, self.data.thread_id, changes)
        self.assertFalse(result['user_message_ready'])
        self.assertEqual(progress.read_text('utf-8'), 'EP001 待审核')
        result = await closeout(self.store, self.projects, batch, self.data.thread_id)
        self.assertTrue(result['user_message_ready'], result)
        self.assertEqual(progress.read_text('utf-8'), 'EP001 待审核')

    async def test_missing_receipt_and_duplicate_stage_cannot_be_registered(self):
        _, draft = self.setup_video()
        await self.collect_and_notice()
        receipt = self.record / self.data.segment_plan.targets[0].response_name
        saved = receipt.read_bytes()
        receipt.unlink()
        with self.assertRaisesRegex(ValueError, '成果或取回凭据缺失'):
            register(self.store, 'task')
        receipt.write_bytes(saved)
        draft.write_text(draft.read_text('utf-8') + '\n### R001-一采\n重复章节。\n', 'utf-8')
        with self.assertRaisesRegex(ValueError, '缺少本轮执行章节'):
            register(self.store, 'task')

    async def test_busy_poll_coalesces_once_and_records_only_transitions(self):
        self.setup_video()
        busy = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'running'}}})}]}
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        with patch.object(self.store, 'desktop_call', AsyncMock(side_effect=[busy,busy,idle,{}])), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()) as sleep, \
                patch.object(self.store, 'record', wraps=self.store.record) as record:
            self.store.queue_notice('task', 'terminal', 'terminal', 'isolated')
            await self.store.notifiers['task']
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2,15,15])
        self.assertEqual(sum(call.args[2]=='waiting_idle' for call in record.call_args_list), 1)

    async def test_ack_racing_send_preserves_ack_and_waiter_wakes_without_poll(self):
        self.setup_video()
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        async def adapter(data, operation, prompt=''):
            if operation == 'read': return idle
            batch = self.store.db.execute('SELECT id FROM notification_batches').fetchone()[0]
            self.store.acknowledge(batch, data.thread_id)
            return {}
        with patch.object(self.store, 'desktop_call', adapter), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()), \
                patch.object(self.store, 'record', wraps=self.store.record) as record:
            self.store.queue_notice('task', 'terminal', 'terminal', 'isolated')
            await self.store.notifiers['task']
        self.assertEqual(self.store.rows['task']['state']['notification'], 'acknowledged')
        self.assertEqual(sum(call.args[2]=='acknowledged' for call in record.call_args_list), 1)
        self.assertEqual(sum(call.args[2]=='delivery_confirmed' for call in record.call_args_list), 1)
        batch = self.store.db.execute('SELECT id FROM notification_batches').fetchone()[0]
        self.store.db.execute("UPDATE notification_batches SET state='delivery_unknown' WHERE id=?", (batch,))
        waiter = asyncio.create_task(self.store.wait_ack(batch))
        await asyncio.sleep(0)
        self.store.acknowledge(batch, self.data.thread_id)
        await asyncio.wait_for(waiter, .2)
        self.assertNotIn(batch, self.store._ack_events)

    async def test_direct_summary_does_not_build_global_public_or_read_video(self):
        self.setup_video()
        await self.collect_and_notice()
        with patch.object(self.store, 'public', side_effect=AssertionError('global queue forbidden')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('media read forbidden')):
            result = summary(self.store, 'task')
        self.assertEqual(len(result['outputs']),1)
        self.assertNotIn('private-pipe', json.dumps(result))

    async def test_image_summary_keeps_original_review_workflow(self):
        base.TaskTests.seed(self, status='completed')
        self.assertEqual(summary(self.store, 'task')['next_action'], 'image-review-workflow')
        self.store.save('task', collected=1)
        self.assertEqual(register(self.store, 'task')['status'], 'image-review-workflow')

    async def test_same_project_batch_syncs_once_and_reuses_both_registrations(self):
        _, first = self.setup_video()
        batch = await self.collect_and_notice()
        # A second already-completed task in the same genuine-source test batch.
        import copy
        second = copy.deepcopy(self.store.rows['task'])
        second['state']['id'] = 'second'
        second['state']['prompt_id'] = 'second-remote'
        second['state']['segments']['0']['identity'] = 'EP001-C001-P002-R001-一采'
        old_candidate = Path(second['state']['segments']['0']['path'])
        new_candidate = old_candidate.with_name('EP001-C001-P002-R001-一采.mp4')
        new_candidate.write_bytes(b'second isolated media')
        second['state']['segments']['0']['path'] = str(new_candidate)
        second['input'].record_dir = str(self.project / '执行附件/second')
        second_record = Path(second['input'].record_dir)
        second_record.mkdir(parents=True)
        receipt = second_record / 'second.json'
        receipt.write_text('{}','utf-8')
        second['state']['segments']['0']['receipt'] = str(receipt)
        second['state']['collected'] = second['state']['expected'] = 1
        mapping = json.loads((self.record / '输入映射.json').read_text('utf-8-sig'))
        mapping['generation_contexts'][0]['identity'] = new_candidate.stem
        (second_record / '输入映射.json').write_text(json.dumps(mapping), 'utf-8')
        draft = first.with_name('EP001-C001-P002-视频制作-工作稿.md')
        draft.write_text(first.read_text('utf-8'), 'utf-8')
        index = self.project / '09-剧集制作/EP001/03-分镜脚本/EP001-分镜索引.md'
        index.write_text(index.read_text('utf-8') + '| EP001-C001 | EP001-C001-P002 | 3 |\n', 'utf-8')
        self.store.rows['second'] = second
        self.store.save('second')
        self.store.db.execute('UPDATE notification_batches SET task_ids=? WHERE id=?', (json.dumps(['task','second']),batch))
        self.store.db.commit()
        with patch.object(self.projects, 'snapshot', wraps=self.projects.snapshot) as scan, \
                patch.object(self.projects, 'section', wraps=self.projects.section) as section:
            result = await closeout(self.store, self.projects, batch, self.data.thread_id)
        self.assertTrue(result['user_message_ready'], result)
        scan.assert_called_once()
        section.assert_called_once()
        self.assertEqual(len(result['results']),2)
        self.assertIn('- 决定：待审核', draft.read_text('utf-8'))

    async def test_real_agent_cli_ack_to_registration_without_remote_calls(self):
        import os, sys
        from tests.test_queue_recovery import serving
        self.setup_video()
        batch = await self.collect_and_notice()
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/api/internal/comfy/notifications/{batch_id}/ack', main.agent_notice_ack, methods=['POST'])
        app.add_api_route('/api/internal/comfy/notifications/{batch_id}/register-results', main.agent_register_results, methods=['POST'])
        cli = self.root / '.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
        cli.parent.mkdir(parents=True)
        shutil.copyfile(t.SKILL / 'scripts/browser_tasks.py', cli)
        async with serving(app) as url:
            config = self.root / '工作区浏览服务/runtime/task-service.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'url':url,'token':self.store.token}), 'utf-8')
            with patch.object(main, 'store', self.projects), patch.object(t.client,'submit') as submit, \
                    patch.object(t.client,'status') as remote, patch.object(t.client,'download') as download:
                for action in ('ack','register-results'):
                    process = await asyncio.create_subprocess_exec(sys.executable,'-X','utf8',str(cli), action,
                        '--notification-id', batch, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        env={**os.environ,'CODEX_THREAD_ID':self.data.thread_id})
                    stdout, stderr = await asyncio.wait_for(process.communicate(),15)
                    self.assertEqual(process.returncode,0,stderr.decode('utf-8'))
                    result=json.loads(stdout)
                self.assertTrue(result['user_message_ready'],result)
                submit.assert_not_called();remote.assert_not_called();download.assert_not_called()

    async def test_new_notice_arriving_during_channel_close_is_not_lost(self):
        self.setup_video()
        idle = {'content': [{'type': 'text', 'text': json.dumps({'thread': {'status': {'type': 'idle'}}})}]}
        closing = 0
        async def close_channel():
            nonlocal closing
            closing += 1
            if closing == 1:
                self.store.queue_notice('task','new-outcome','terminal','new isolated outcome')
        with patch('backend.services.desktop_channel.DesktopChannel') as factory, \
                patch.object(self.store,'desktop_call',AsyncMock(side_effect=[idle,{},idle,{}])) as adapter, \
                patch('backend.services.task_notifications.asyncio.sleep',AsyncMock()):
            factory.return_value.close = AsyncMock(side_effect=close_channel)
            self.store.queue_notice('task','old-outcome','terminal','old isolated outcome')
            old = self.store.notifiers['task']
            await old
            new = self.store.notifiers['task']
            self.assertIsNot(new,old)
            await new
        self.assertFalse(self.store.notification_pending(self.data.thread_id))
        self.assertEqual(sum(call.args[1]=='send' for call in adapter.call_args_list),2)

    async def test_local_terminal_evidence_error_does_not_reconnect_remote(self):
        self.setup_video()
        (self.record / self.data.history_name).write_text('{broken','utf-8')
        socket=AsyncMock()
        with patch.object(t.client,'status') as remote, patch.object(self.store,'notify',AsyncMock()), \
                patch.object(t.asyncio,'sleep',AsyncMock()) as sleep:
            await self.store.watch('task',socket=socket)
        self.assertEqual(self.store.rows['task']['state']['status'],'needs_attention')
        self.assertEqual(self.store.rows['task']['state']['failure_stage'],'collection')
        remote.assert_not_called();sleep.assert_not_called()
        socket.close.assert_awaited_once()


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_node_protocol_reuses_one_initialize_and_preserves_thread(self):
        import tempfile
        from types import SimpleNamespace
        node = shutil.which('node')
        if not node: self.skipTest('Node not installed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'trace.jsonl'
            fake = root / 'fake.mjs'
            fake.write_text('''import {createInterface} from 'node:readline';
import {appendFileSync} from 'node:fs';
for await (const line of createInterface({input:process.stdin})) {
 const m=JSON.parse(line); appendFileSync(TRACE,JSON.stringify(m)+'\\n');
 if (!m.id) continue;
 const result=m.method==='tools/call'?{content:[],isError:false}:{};
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+'\\n');
}'''.replace('TRACE', json.dumps(str(trace))), 'utf-8')
            data = SimpleNamespace(thread_id='isolated-thread', desktop=SimpleNamespace(node=node,
                server=str(fake), pipe='fake-pipe', caller_thread='isolated-caller'))
            channel = DesktopChannel()
            try:
                await channel.call(data, 'read')
                process = channel.process
                await channel.call(data, 'send', 'isolated notification')
                self.assertIs(channel.process, process)
            finally: await channel.close()
            rows = [json.loads(line) for line in trace.read_text('utf-8').splitlines()]
            self.assertEqual(sum(row['method']=='initialize' for row in rows), 1)
            self.assertEqual(sum(row['method']=='tools/list' for row in rows), 1)
            calls = [row for row in rows if row['method']=='tools/call']
            self.assertEqual([row['params']['name'] for row in calls], ['read_thread','send_message_to_thread'])
            self.assertTrue(all(row['params']['arguments']['threadId']=='isolated-thread' for row in calls))
            self.assertTrue(all(row['params']['_meta']['openai/threadId']=='isolated-caller' for row in calls))

    async def test_one_shot_compatibility_and_closed_channel_recovery(self):
        import tempfile
        from types import SimpleNamespace
        node = shutil.which('node')
        if not node: self.skipTest('Node not installed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'fake.mjs'
            fake.write_text("""import {createInterface} from 'node:readline';
for await (const line of createInterface({input:process.stdin})) {
 const m=JSON.parse(line); if (!m.id) continue;
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:{content:[]}})+'\\n');
}""",'utf-8')
            bridge = Path(t.__file__).resolve().parents[2] / 'scripts/codex_task_bridge.mjs'
            process=await asyncio.create_subprocess_exec(node,str(bridge),stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            raw=json.dumps({'server':str(fake),'caller':'isolated-caller','threadId':'isolated-thread','operation':'read'}).encode()
            stdout,stderr=await asyncio.wait_for(process.communicate(raw),10)
            self.assertEqual(process.returncode,0,stderr.decode())
            self.assertEqual(json.loads(stdout),{'content':[]})
            fake.write_text('process.exit(1);','utf-8')
            data=SimpleNamespace(thread_id='isolated-thread',desktop=SimpleNamespace(node=node,
                server=str(fake),pipe='fake-pipe',caller_thread='isolated-caller'))
            channel=DesktopChannel()
            try:
                with self.assertRaises((OSError,ValueError)):
                    await asyncio.wait_for(channel.call(data,'read'),5)
                self.assertIsNone(channel.process)
            finally: await channel.close()
