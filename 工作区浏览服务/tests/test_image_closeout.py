"""Temporary projects/PNGs, no remote generation or real conversation notices."""
import hashlib
import json
import re
import struct
import unittest
from unittest.mock import AsyncMock, patch
import zlib
from backend.services import comfy_tasks as tasks, image_closeout as image, result_registration as registration
from backend.services.projects import ProjectStore
from tests import test_comfy_tasks as base


def png(w=4, h=3):
    def chunk(k, b):
        return struct.pack('>I', len(b)) + k + b + struct.pack('>I', zlib.crc32(k + b))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x66\x88\xaa' * w) * h)) + chunk(b'IEND', b'')


class ImageCloseoutTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.TaskTests.asyncSetUp
    asyncTearDown = base.TaskTests.asyncTearDown

    async def test_repair_after_progress_edit_before_journal_keeps_original_task(self):
        from copy import deepcopy
        import asyncio, os, shutil, sys
        from fastapi import FastAPI
        from backend import main
        from tests.test_queue_recovery import serving
        self.setup_image()
        progress = self.project / '项目进度.md'
        row = '| 人物参考图 | 会话 | 进行中 | 尚未生成 | - 无 | - 无 |'
        progress.write_text(row)
        updates = [dict(path='项目进度.md', old=row, new=row.replace('尚未生成', '{{outputs}}；{{specs}}'))]
        self.data.image_plan['record_updates'] = updates
        image.validate_plan(self.data)
        original = deepcopy(self.data.image_plan)
        current = row.replace('尚未生成', '用户补充备注')
        progress.write_text(current)
        with self.assertRaises(ValueError):
            registration.register(self.store, 'task')
        self.assertFalse((self.record / registration.REPORT).exists())
        repair = dict(reason='原授权内同步并保留用户备注', expected_updates=updates,
                      updates=[dict(path='项目进度.md', old=current, new=current.replace('用户补充备注', '用户补充备注；已保存'))])
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/api/internal/comfy/notifications/{batch_id}/register-results', main.agent_register_results, methods=['POST'])
        cli = self.root / '.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
        cli.parent.mkdir(parents=True)
        shutil.copyfile(tasks.SKILL / 'scripts/browser_tasks.py', cli)
        repair_file = self.record / '登记修复请求.json'
        repair_file.write_text(json.dumps({'task': repair}, ensure_ascii=False))
        async with serving(app) as url:
            config = self.root / '工作区浏览服务/runtime/task-service.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps(dict(url=url, token=self.store.token)))
            with patch.object(registration, 'batch_tasks', return_value=(['task'], None)), \
                    patch.object(main, 'store', self.store.projects):
                process = await asyncio.create_subprocess_exec(sys.executable, '-B', str(cli),
                    'register-results', '--notification-id', 'batch', '--image-repairs', str(repair_file),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, 'CODEX_THREAD_ID': self.data.thread_id})
                stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
                self.assertEqual(process.returncode, 0, stderr.decode())
                result = json.loads(stdout)
        self.assertTrue(result['user_message_ready'], result)
        self.assertIn('用户补充备注；已保存', progress.read_text())
        self.assertEqual(self.data.image_plan, original)

    def test_invalid_associated_updates_stop_before_registration(self):
        self.setup_image()
        for update in (dict(path='03-人物资料/人物索引.md', old='没有的原文', new='新文字'),
                       dict(path='03-人物资料/人物索引.md', old='CH001', new='{{unsupported}}')):
            with self.subTest(update=update):
                self.data.image_plan['record_updates'] = [update]
                with self.assertRaises(ValueError):
                    image.validate_plan(self.data)

    async def test_repair_existing_journal_is_audited_and_idempotent(self):
        self.setup_image()
        path = '03-人物资料/人物索引.md'
        old = (self.project / path).read_text()
        updates = [dict(path=path, old=old, new=old.replace('主角', '主角；{{specs}}'))]
        self.data.image_plan['record_updates'] = updates
        with patch.object(image, 'apply', side_effect=ValueError('登记中断')):
            with self.assertRaisesRegex(ValueError, '登记中断'):
                registration.register(self.store, 'task')
        current = old.replace('主角', '主角（用户备注）')
        (self.project / path).write_text(current)
        repair = dict(reason='保留备注接续登记', expected_updates=updates,
                      updates=[dict(path=path, old='主角（用户备注）', new='主角（用户备注）；已保存')])
        with patch.object(registration, 'batch_tasks', return_value=(['task'], None)):
            for _ in range(2):
                result = await registration.closeout(self.store, self.store.projects, 'batch', self.data.thread_id,
                                                      image_repairs={'task': repair})
                self.assertTrue(result['user_message_ready'])
        self.assertEqual((self.project / path).read_text().count('；已保存'), 1)
        self.assertEqual(len(list(self.record.glob('*登记修复前-*.json'))), 1)
        self.assertEqual(self.draft.read_text().count('### 审阅-生成记录-001-001'), 1)

    def test_record_repair_rejects_new_targets_stale_requests_and_approval_changes(self):
        self.setup_image()
        old = self.draft.read_text()
        confirmation = '#### 4. 用户确认\n\n- 结论：批准采用\n- 批准的具体候选：原图\n'
        self.draft.write_text(old + '\n' + confirmation)
        updates = [dict(path=self.rel(self.draft), old='原图', new='原图；关联补齐')]
        report_file = self.record / '独立修复报告.json'
        for expected, new in (([], updates),
                              (updates, [dict(path='项目进度.md', old='旧', new='新')]),
                              (updates, [dict(path=self.rel(self.draft), old='批准采用', new='待确认')])):
            with self.subTest(expected=expected, updates=new):
                with self.assertRaises(ValueError):
                    image.repair_record_updates(self.project, [self.rel(self.draft)], updates,
                        dict(reason='测试保护', expected_updates=expected, updates=new), report_file)
        self.assertIn(confirmation, self.draft.read_text())
        self.assertFalse(list(self.record.glob('*登记修复前-*.json')))

    def setup_image(self, kind='人物', scope='03-人物资料'):
        self.draft = self.project / scope / '其他资料/工作稿/CH001-参考图-工作稿.md'
        self.draft.parent.mkdir(parents=True)
        template = (tasks.SKILL / 'references/模板' / image.TEMPLATES[kind]).read_text('utf-8-sig')
        text = re.search(r'````markdown\n(.*?)\n````', template, re.S)[1]
        text = text[:text.index('### 审阅-生成记录-001-001')]
        self.draft.write_text(image.fields(text, {'用户采用状态': '未送审', '图片类型': '服装参考图', '人物状态': '大学', '服装状态': '日常'}))
        if kind == '人物':
            folder = self.project / scope / 'CH001-男主'
            folder.mkdir()
            (folder / 'CH001-男主-人物资料卡.md').write_text('# 人物资料卡\n\n## 3. 外貌与基础造型\n### 3.1 大学\n')
            (self.project / scope / '人物索引.md').write_text('| 人物编号 | 姓名 | 人物定位 | 资料卡入口 |\n| --- | --- | --- | --- |\n| CH001 | 男主 | 主角 | [资料卡](CH001-男主/CH001-男主-人物资料卡.md) |\n')
        out = self.draft.parent / '素材/CH001-服装参考图-候选-v01.png'
        self.data.outputs[0].path = str(out)
        self.data.image_plan = dict(draft=self.rel(self.draft), kind=kind, generation='生成记录-001', review='审阅-生成记录-001-001', images=[dict(path=self.rel(out), width=4, height=3)])
        base.TaskTests.seed(self, status='completed')
        self.store.save('task', collected=1)
        self.request()
        self.output(out, png())
        self.store.projects = ProjectStore(self.project.parent)
        return out

    def rel(self, path):
        return path.relative_to(self.project).as_posix()

    def request(self):
        (self.record / self.data.request_name).write_text(json.dumps({'prompt': self.data.workflow, 'client_id': 'listener-id'}))

    def output(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        remote = dict(filename='result.png', subfolder='batch', type='output')
        receipt = self.record / self.data.outputs[0].response_name
        receipt.write_text(json.dumps({'data': dict(path=self.rel(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), remote=remote)}))
        self.store.save('task', result_items=[dict(path=str(path), receipt=str(receipt), bytes=len(raw), remote=remote)])
        return receipt

    async def test_image_ready_before_notice_and_report_only_reads_snapshot(self):
        out = self.setup_image()
        async def sent(data, operation, prompt=''):
            if operation == 'send':
                self.assertIn('- 用户采用状态：待确认', self.draft.read_text())
                saved = json.loads(self.store.db.execute('SELECT report FROM notification_reports').fetchone()[0])
                self.assertTrue(saved['user_message_ready'], saved)
                self.assertEqual(saved['tasks'][0]['next_action'], 'display-image')
            return {}
        with patch.object(self.store, 'desktop_call', side_effect=sent), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        batch = self.store.rows['task']['state']['notices'][0]['batch_id']
        before = self.draft.read_bytes()
        with patch.object(registration, 'register', side_effect=AssertionError('no registration')), patch.object(ProjectStore, 'snapshot', side_effect=AssertionError('no scan')):
            self.assertTrue(self.store.read_report(batch, self.data.thread_id)['user_message_ready'])
            self.assertTrue(self.store.read_report(batch, self.data.thread_id)['reused'])
        self.assertEqual(before, self.draft.read_bytes())
        self.assertIn(out.name, before.decode())
        self.assertEqual(self.store.projects.section(self.project.name, '03-人物资料')['people'][0]['pendingCount'], 1)

    async def test_invalid_png_dimensions_or_receipt_do_not_write_records(self):
        out = self.setup_image()
        before = self.draft.read_bytes()
        for raw in (png(5, 3), png()[:-4], b'not png'):
            self.output(out, raw)
            with self.assertRaises(ValueError):
                registration.register(self.store, 'task')
            self.assertEqual(before, self.draft.read_bytes())
        receipt = self.output(out, png())
        proof = json.loads(receipt.read_text())
        proof['data']['remote']['filename'] = 'wrong.png'
        receipt.write_text(json.dumps(proof))
        with self.assertRaisesRegex(ValueError, '凭据不符'):
            registration.register(self.store, 'task')

    async def test_repaired_closeout_refreshes_old_notice_and_report_after_restart(self):
        self.setup_image()
        index = self.project / '03-人物资料/人物索引.md'
        original = index.read_text()
        index.unlink()
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        batch = self.store.rows['task']['state']['notices'][0]['batch_id']
        stale = self.store.db.execute('SELECT report FROM notification_reports WHERE batch_id=?', (batch,)).fetchone()[0]
        self.assertEqual(json.loads(stale)['results'][0]['status'], 'browser_pending')
        self.assertFalse(self.store.read_report(batch, self.data.thread_id)['user_message_ready'])
        index.write_text(original)
        with patch.object(self.store, 'desktop_call', AsyncMock()) as send:
            repaired = await registration.closeout(self.store, self.store.projects, batch, self.data.thread_id)
            self.assertTrue(repaired['user_message_ready'])
            saved = json.loads(self.store.db.execute('SELECT report FROM notification_reports WHERE batch_id=?', (batch,)).fetchone()[0])
            self.assertTrue(saved['user_message_ready'])
            send.assert_not_awaited()
        # Existing installations already have stale snapshots alongside repaired tasks.
        self.store.db.execute('UPDATE notification_reports SET report=? WHERE batch_id=?', (stale, batch))
        self.store.db.commit()
        await self.store.close()
        self.store = tasks.TaskStore(self.root / 'runtime', self.root)
        with patch.object(registration, 'register', side_effect=AssertionError('no registration')), \
                patch.object(ProjectStore, 'snapshot', side_effect=AssertionError('no scan')), \
                patch.object(tasks.client, 'status', side_effect=AssertionError('no remote')):
            changes = self.store.db.total_changes
            with self.assertRaises(ValueError):
                self.store.read_report(batch, 'another-thread')
            self.assertEqual(self.store.db.total_changes, changes)
            current = self.store.read_report(batch, self.data.thread_id)
            self.assertTrue(current['user_message_ready'])
            self.assertEqual(current['results'][0]['status'], 'completed')
            self.assertEqual(current['delivery']['image_count'], 1)
            changes = self.store.db.total_changes
            self.assertEqual(self.store.read_report(batch, self.data.thread_id), current)
            self.assertEqual(self.store.db.total_changes, changes)

    async def test_queued_notice_contains_identity_not_expiring_status(self):
        self.setup_image()
        self.store.save('task', closeout={'status': 'browser_pending', 'error': '网页缺少本批图片'},
                        closeout_retry_stop='exhausted')
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})) as send, \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        prompt = next(c.args[2] for c in send.call_args_list if c.args[1] == 'send')
        self.assertIn('本地任务ID：task', prompt)
        self.assertIn('最新', prompt)
        self.assertNotIn('browser_pending', prompt)
        self.assertNotIn('网页缺少本批图片', prompt)
        self.assertNotIn('当前状态：', prompt)

    async def test_browser_retry_does_not_repeat_png_or_record_work(self):
        self.setup_image()
        original, calls = registration.verify, []
        def flaky(*args):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError('temporarily unavailable')
            return original(*args)
        with patch.object(registration, 'verify', side_effect=flaky), patch.object(image, 'png', wraps=image.png) as checked, patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            report = await self.store.prepare_report(['task'])
            self.assertTrue(report['user_message_ready'], report)
            self.assertEqual(checked.call_count, 1)
        self.assertEqual(self.draft.read_text().count('### 审阅-生成记录-001-001'), 1)

    def setup_upscale(self):
        source = self.setup_image()
        registration.register(self.store, 'task')
        text = self.draft.read_text()
        review = image.section(text, '审阅-生成记录-001-001')[0]
        approved = image.fields(review, {'结论': '批准采用', '批准的具体候选': image.link(self.draft, source), '决定原因': '用户说就用这版', '确认时间与依据': '真实批准依据'})
        self.draft.write_text(image.fields(text.replace(review, approved), {'用户采用状态': '批准采用'}))
        self.data = self.data.model_copy(deep=True)
        self.record = self.record / '超分-001'
        self.record.mkdir()
        self.data.record_dir = str(self.record)
        out = source.with_name('CH001-服装参考图-候选-v01-超分-001.png')
        self.data.task_type = 'image-upscale'
        self.data.workflow = {'2': {'class_type': 'LoadImage', 'inputs': {'image': 'uploaded/source.png'}}, '1': {'class_type': 'RTXVideoSuperResolution', 'inputs': {'images': ['2', 0], 'resize_type': 'scale by multiplier', 'resize_type.scale': 2}}, '3': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0]}}}
        self.data.uploads = [dict(file=str(source), node='2', input='image', **{'response-name': 'upload.json'})]
        (self.record / 'upload.json').write_text(json.dumps({'data': dict(input_path='uploaded/source.png', sha256=hashlib.sha256(source.read_bytes()).hexdigest())}))
        self.data.outputs[0].path, self.data.outputs[0].node_id = str(out), '3'
        plan = self.data.image_plan
        plan['images'] = [dict(path=self.rel(out), width=8, height=6)]
        formal = self.project / '03-人物资料/CH001-男主/参考图/CH001-日常-服装参考图.png'
        header = '| 图片类型 | 人物状态 | 服装状态 | 正式文件 | 采用的候选版本 | 适用范围 | 审阅记录 |\n| --- | --- | --- | --- | --- | --- | --- |'
        plan['upscale'] = dict(number='超分-001', source=self.rel(source), approval=plan['draft'] + '#' + plan['review'], formal=self.rel(formal), record_updates=[dict(path=plan['draft'], old=header, new=header + '\n| 服装参考图 | 大学 | 日常 | {{file}} | v01／超分001 | 首集 | [批准](#审阅-生成记录-001-001) |')])
        base.TaskTests.seed(self, status='completed')
        self.store.save('task', collected=1)
        self.request()
        self.output(out, png(8, 6))
        return source, formal

    async def test_approved_upscale_publishes_and_keeps_original_decision(self):
        source, formal = self.setup_upscale()
        result = await self.store.prepare_report(['task'])
        self.assertTrue(result['user_message_ready'], result)
        self.assertEqual(formal.read_bytes(), png(8, 6))
        self.assertEqual(source.read_bytes(), png())
        text = self.draft.read_text()
        self.assertIn('用户说就用这版', text)
        self.assertIn('- 结论：批准采用', text)
        self.assertIn('- 用户采用状态：已采用', text)
        self.assertEqual(text.count('### 审阅-生成记录-001-001'), 1)
        self.assertEqual(result['tasks'][0]['closeout']['display_outputs'][0]['display_path'], self.rel(formal))

    async def test_approved_upscale_notifies_only_when_closeout_fails(self):
        source, formal = self.setup_upscale()
        with patch.object(self.store, 'desktop_call', AsyncMock()) as send, \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '超分完成')
            await self.store.notifiers['task']
            send.assert_not_awaited()
        self.assertEqual(formal.read_bytes(), png(8, 6))
        self.assertEqual(source.read_bytes(), png())
        self.assertEqual(self.store.rows['task']['state']['closeout']['status'], 'completed')
        self.assertEqual(self.store.rows['task']['state']['notification'], 'not_required')
        text = self.draft.read_text()
        self.assertIn('用户说就用这版', text)
        self.assertIn('- 结论：批准采用', text)
        self.assertIn('- 用户采用状态：已采用', text)
        self.assertEqual(text.count('### 审阅-生成记录-001-001'), 1)

    async def test_upscale_error_report_recovers_to_typed_formal_output_without_sending(self):
        source, formal = self.setup_upscale()
        with patch.object(registration, 'verify', side_effect=ValueError('网页尚未收录')), \
                patch.object(self.store, 'desktop_call', AsyncMock(return_value={})), \
                patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '超分完成')
            await self.store.notifiers['task']
        batch = self.store.rows['task']['state']['notices'][0]['batch_id']
        self.assertFalse(self.store.read_report(batch, self.data.thread_id)['user_message_ready'])
        before = self.draft.read_bytes()
        with patch.object(self.store, 'desktop_call', AsyncMock()) as send:
            fixed = await registration.closeout(self.store, self.store.projects, batch, self.data.thread_id)
            self.assertTrue(fixed['user_message_ready'])
            send.assert_not_awaited()
        await self.store.close()
        self.store = tasks.TaskStore(self.root / 'runtime', self.root)
        with patch.object(registration, 'register', side_effect=AssertionError('no registration')), \
                patch.object(ProjectStore, 'snapshot', side_effect=AssertionError('no scan')), \
                patch.object(image, 'png', side_effect=AssertionError('no decode')):
            result = self.store.read_report(batch, self.data.thread_id)
            self.assertTrue(result['user_message_ready'])
            entry = result['delivery']['tasks'][0]
            self.assertEqual(entry['task_type'], 'image-upscale')
            self.assertEqual(entry['images'][0]['file'], str(formal))
            self.assertEqual((entry['images'][0]['width'], entry['images'][0]['height']), (8, 6))
        self.assertEqual(before, self.draft.read_bytes())
        self.assertEqual(source.read_bytes(), png())
        self.assertEqual(formal.read_bytes(), png(8, 6))

    async def test_unapproved_upscale_never_publishes(self):
        _, formal = self.setup_upscale()
        self.draft.write_text(self.draft.read_text().replace('- 结论：批准采用', '- 结论：待确认'))
        result = await self.store.prepare_report(['task'])
        self.assertFalse(result['user_message_ready'])
        self.assertFalse(formal.exists())

    async def test_target_dimensions_plan_must_match_workflow(self):
        _, formal = self.setup_upscale()
        self.data.workflow['1']['inputs'].update({'resize_type': 'target dimensions',
            'resize_type.width': 9, 'resize_type.height': 6})
        self.request()
        with self.assertRaisesRegex(ValueError, 'RTX指定尺寸与成果计划不符'):
            image.validate_plan(self.data)
        self.assertFalse(formal.exists())

    async def test_target_dimensions_rejects_wrong_actual_pixels(self):
        _, formal = self.setup_upscale()
        self.data.workflow['1']['inputs'].update({'resize_type': 'target dimensions',
            'resize_type.width': 11, 'resize_type.height': 8})
        self.data.image_plan['images'][0].update(width=11, height=8)
        self.request()
        result = await self.store.prepare_report(['task'])
        self.assertFalse(result['user_message_ready'])
        self.assertFalse(formal.exists())

    async def test_target_dimensions_keeps_source_approval_required(self):
        _, formal = self.setup_upscale()
        self.data.workflow['1']['inputs'].update({'resize_type': 'target dimensions',
            'resize_type.width': 8, 'resize_type.height': 6})
        self.draft.write_text(self.draft.read_text().replace('- 结论：批准采用', '- 结论：待确认'))
        with self.assertRaisesRegex(ValueError, '没有明确批准'):
            image.validate_plan(self.data)
        self.assertFalse(formal.exists())

    async def test_changed_evidence_stops_interrupted_resume(self):
        out = self.setup_image()
        with patch.object(image, 'apply', side_effect=OSError('temporary write failure')), self.assertRaises(OSError):
            registration.register(self.store, 'task')
        out.write_bytes(png(5, 3))
        with self.assertRaisesRegex(ValueError, '证据发生变化'):
            registration.register(self.store, 'task')

    async def test_episode_template_and_legacy_missing_plan(self):
        self.setup_image(kind='剧集素材', scope='09-剧集制作/EP001')
        self.assertEqual(registration.register(self.store, 'task')['status'], 'registered')
        self.assertIn('- 决定：待确认', self.draft.read_text())
        (self.record / registration.REPORT).unlink()
        self.data.image_plan = None
        result = await self.store.prepare_report(['task'])
        self.assertFalse(result['user_message_ready'])
        self.assertIn('image_plan', result['results'][0]['error'])

    async def test_other_asset_templates_keep_their_own_fixed_fields(self):
        for kind in ('场景', '道具'):
            with self.subTest(kind=kind):
                template = (tasks.SKILL / 'references/模板' / image.TEMPLATES[kind]).read_text('utf-8-sig')
                generation = '- 图片类型：服装参考图\n'
                text = image.review_text(tasks.SKILL, dict(kind=kind, review='审阅-生成记录-003-001', generation='生成记录-003'), generation, '[候选](a.png)', '4×3、PNG、可解码', '[凭据](a.json)', 'now')
                self.assertIn('- 结论：待确认', text)
                self.assertNotIn('通过／异常', text)
                self.assertNotIn('````', text)

    async def test_interrupted_write_resumes_without_duplicate_review(self):
        self.setup_image()
        replace = image.Path.replace
        calls = []
        def fail_once(path, target):
            if target == self.draft and not calls:
                calls.append(1)
                raise OSError('temporary write failure')
            return replace(path, target)
        with patch.object(image.Path, 'replace', fail_once), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()), patch.object(image, 'png', wraps=image.png) as checked:
            result = await self.store.prepare_report(['task'])
            self.assertTrue(result['user_message_ready'], result)
            self.assertEqual(checked.call_count, 1)
        self.assertEqual(self.draft.read_text().count('### 审阅-生成记录-001-001'), 1)

    async def test_formal_replacement_archives_previous_bytes_and_conflicting_archive_stops(self):
        _, formal = self.setup_upscale()
        formal.parent.mkdir(parents=True, exist_ok=True)
        formal.write_bytes(b'previous approved original')
        archive = formal.parent / '历史/old.png'
        self.data.image_plan['upscale']['archive'] = self.rel(archive)
        result = await self.store.prepare_report(['task'])
        self.assertTrue(result['user_message_ready'], result)
        self.assertEqual(archive.read_bytes(), b'previous approved original')
        self.assertEqual(formal.read_bytes(), png(8, 6))

    async def test_source_upload_mismatch_never_publishes(self):
        _, formal = self.setup_upscale()
        upload = self.record / 'upload.json'
        text = json.loads(upload.read_text())
        text['data']['sha256'] = 'different'
        upload.write_text(json.dumps(text))
        with self.assertRaisesRegex(ValueError, '上传与批准原图不符'):
            registration.register(self.store, 'task')
        self.assertFalse(formal.exists())

    async def test_explicit_legacy_association_repair_is_scoped_and_durable(self):
        self.setup_image()
        plan = self.data.image_plan
        self.data.image_plan = None
        batch = 'legacy-batch'
        self.store.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)', (batch, self.data.thread_id, json.dumps(['task']), 'notice', 'sent'))
        self.store.db.commit()
        result = await registration.closeout(self.store, self.store.projects, batch, self.data.thread_id, image_plans={'task': plan})
        self.assertTrue(result['user_message_ready'], result)
        self.assertEqual(self.store.rows['task']['state']['image_closeout_plan'], plan)
        with self.assertRaisesRegex(ValueError, '属于本通知'):
            await registration.closeout(self.store, self.store.projects, batch, self.data.thread_id, image_plans={'another-task': plan})

    async def test_record_updates_render_links_relative_to_each_document(self):
        self.setup_image()
        progress = self.project / '项目进度.md'
        row = '| 人物参考图 | 会话 | 进行中 | 未生成 | - 无 | - 无 |'
        progress.write_text(row)
        self.data.image_plan['record_updates'] = [dict(path='项目进度.md', old=row,
            new='| 人物参考图 | 会话 | 待确认 | {{outputs}}；{{specs}} | - 审核本轮候选 | - 无 |')]
        image.validate_plan(self.data)
        registration.register(self.store, 'task')
        self.assertIn('](03-人物资料/其他资料/工作稿/素材/', progress.read_text())
        self.assertNotIn('{{', progress.read_text())

    async def test_image_progress_updates_cannot_append_history(self):
        self.setup_image()
        progress = self.project / '项目进度.md'
        row = '| 人物参考图 | 会话 | 进行中 | 当前成果 | - 无 | - 无 |'
        progress.write_text(row)
        self.data.image_plan['record_updates'] = [dict(path='项目进度.md', old=row,
            new=row + '\n\n### 图片已取回\n完成流水')]
        before = self.draft.read_bytes()
        with self.assertRaisesRegex(ValueError, '不得追加历史记录'):
            image.validate_plan(self.data)
        with self.assertRaisesRegex(ValueError, '不得追加历史记录'):
            registration.register(self.store, 'task')
        self.assertEqual(progress.read_text(), row)
        self.assertEqual(self.draft.read_bytes(), before)

    async def test_image_progress_updates_cannot_modify_an_unrelated_phase(self):
        self.setup_image()
        progress = self.project / '项目进度.md'
        row = '| 场景参考图 | 其他会话 | 待确认 | 其他成果 | - 场景问题 | - 无 |'
        progress.write_text(row)
        self.data.image_plan['record_updates'] = [dict(path='项目进度.md', old=row,
            new=row.replace('场景问题', '误清'))]
        with self.assertRaisesRegex(ValueError, '对应阶段行'):
            image.validate_plan(self.data)
        with self.assertRaisesRegex(ValueError, '对应阶段行'):
            registration.register(self.store, 'task')
        self.assertEqual(progress.read_text(), row)

    async def test_interrupt_after_document_publish_does_not_duplicate_appended_review(self):
        self.setup_image()
        original = image.write_json
        calls = []
        def failure(path, report):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('interrupted after publish')
            return original(path, report)
        with patch.object(image, 'write_json', side_effect=failure), self.assertRaises(OSError):
            registration.register(self.store, 'task')
        self.assertEqual(self.draft.read_text().count('### 审阅-生成记录-001-001'), 1)
        registration.register(self.store, 'task')
        self.assertEqual(self.draft.read_text().count('### 审阅-生成记录-001-001'), 1)

    async def test_user_edit_during_closeout_is_preserved(self):
        self.setup_image()
        original = image.apply
        def edit_first(*args):
            self.draft.write_text(self.draft.read_text().replace('- 人物状态：大学', '- 人物状态：用户刚修改的状态'))
            return original(*args)
        with patch.object(image, 'apply', side_effect=edit_first), self.assertRaisesRegex(ValueError, '源文字变化'):
            registration.register(self.store, 'task')
        self.assertIn('用户刚修改的状态', self.draft.read_text())
        self.assertNotIn('### 审阅-生成记录-001-001', self.draft.read_text())

    async def test_collection_then_notice_finishes_all_image_work(self):
        out = self.setup_image()
        out.unlink()
        (self.record / self.data.outputs[0].response_name).unlink()
        self.store.save('task', status='running', collected=0, result_items=[])
        remote = dict(filename='result.png', subfolder='batch', type='output')
        terminal = dict(state='success', files=[dict(node_id='1', output_key='images', index=0, file=remote)], history={})
        def downloaded(client, args):
            out.write_bytes(png())
            return dict(path=str(out), bytes=len(png()), sha256=hashlib.sha256(png()).hexdigest(), remote=remote)
        with patch.object(tasks.client, 'download', side_effect=downloaded) as download:
            await self.store.finish_collection('task', terminal)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
        result = await self.store.prepare_report(['task'])
        self.assertTrue(result['user_message_ready'], result)
        self.assertIn('- 结论：待确认', self.draft.read_text())

    async def test_two_images_same_project_only_sync_once(self):
        from copy import deepcopy
        self.setup_image()
        second = self.draft.with_name('CH002-参考图-工作稿.md')
        second.write_text(self.draft.read_text())
        data = self.data.model_copy(deep=True)
        data.image_plan['draft'] = self.rel(second)
        data.record_dir = str(self.record / 'second')
        image.Path(data.record_dir).mkdir()
        out = self.draft.parent / '素材/CH002-候选-v01.png'
        data.outputs[0].path = str(out)
        data.image_plan['images'][0]['path'] = self.rel(out)
        state = deepcopy(self.store.rows['task']['state'])
        state['id'] = 'second'
        item = deepcopy(state['result_items'][0])
        item['path'] = str(out)
        item['receipt'] = str(image.Path(data.record_dir) / data.outputs[0].response_name)
        out.write_bytes(png())
        proof = json.loads((self.record / self.data.outputs[0].response_name).read_text())
        proof['data']['path'] = self.rel(out)
        image.Path(item['receipt']).write_text(json.dumps(proof))
        image.Path(data.record_dir, data.request_name).write_text(json.dumps({'prompt': data.workflow, 'client_id': 'listener-id'}))
        state['result_items'] = [item]
        self.store.rows['second'] = dict(input=data, state=state)
        self.store.save('second')
        folder = self.project / '03-人物资料/CH002-女主'
        folder.mkdir()
        (folder / 'CH002-女主-人物资料卡.md').write_text('# 人物资料卡\n')
        index = self.project / '03-人物资料/人物索引.md'
        index.write_text(index.read_text() + '| CH002 | 女主 | 主角 | [资料卡](CH002-女主/CH002-女主-人物资料卡.md) |\n')
        original = registration.verify
        with patch.object(registration, 'verify', wraps=original) as verify, patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            result = await self.store.prepare_report(['task', 'second'])
        self.assertEqual(verify.call_count, 1)
        self.assertTrue(result['user_message_ready'], result)

    async def test_loose_file_without_asset_registry_is_not_a_ready_review_entry(self):
        self.setup_image()
        (self.project / '03-人物资料/人物索引.md').unlink()
        with patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            result = await self.store.prepare_report(['task'])
        self.assertFalse(result['user_message_ready'])
        self.assertEqual(result['results'][0]['status'], 'browser_pending')

    async def test_episode_images_are_verified_only_against_their_own_episode(self):
        from unittest.mock import Mock
        self.setup_image(kind='剧集素材', scope='09-剧集制作/EP001')
        items = [dict(image=True, draft=f'09-剧集制作/{ep}/其他资料/工作稿/{ep}-专用素材制作-工作稿.md', path=f'09-剧集制作/{ep}/其他资料/工作稿/素材/{ep}-首帧.png') for ep in ('EP001', 'EP002')]
        projects = Mock()
        projects.status.return_value = dict(updating=False, checking=False, error=None, revision=1, updated='now')
        projects.section.side_effect = lambda name, scope, episode: {'groups': [{'files': [{'key': item['path']} for item in items if episode in item['path']]}]}
        result = registration.verify(projects, self.store, 'task', {'items': items})
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(projects.section.call_count, 2)

    async def test_image_cli_report_is_ready_for_display_without_more_agent_file_work(self):
        import asyncio
        import os
        from pathlib import Path
        import shutil
        import sys
        from fastapi import FastAPI
        from backend import main
        from tests.test_queue_recovery import serving
        out = self.setup_image()
        with patch.object(self.store, 'desktop_call', AsyncMock(return_value={})), patch('backend.services.task_notifications.asyncio.sleep', AsyncMock()):
            self.store.queue_notice('task', 'terminal', 'terminal', '完成')
            await self.store.notifiers['task']
        batch = self.store.rows['task']['state']['notices'][0]['batch_id']
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/api/internal/comfy/notifications/{batch_id}/report', main.agent_result_report, methods=['POST'])
        cli = self.root / '.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
        cli.parent.mkdir(parents=True)
        shutil.copyfile(tasks.SKILL / 'scripts/browser_tasks.py', cli)
        async with serving(app) as url:
            config = self.root / '工作区浏览服务/runtime/task-service.json'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(json.dumps({'url': url, 'token': self.store.token}))
            with patch.object(registration, 'register', side_effect=AssertionError('report must not register')), patch.object(image, 'png', side_effect=AssertionError('report must not decode')):
                reports = []
                for extra in ([], ['--details']):
                    process = await asyncio.create_subprocess_exec(sys.executable, '-B', str(cli), 'report', '--notification-id', batch, *extra,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        env={**os.environ, 'CODEX_THREAD_ID': self.data.thread_id})
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
                    self.assertEqual(process.returncode, 0, stderr.decode())
                    reports.append(json.loads(stdout))
        brief, full = reports
        self.assertNotIn('tasks', brief)
        self.assertIn('tasks', full)
        self.assertTrue(brief['user_message_ready'])
        self.assertEqual(brief['delivery']['image_count'], 1)
        entry = brief['delivery']['tasks'][0]
        self.assertEqual(entry['task_type'], 'image')
        self.assertEqual(entry['images'][0]['file'], str(out))
        self.assertEqual(entry['images'][0]['width'], 4)
        self.assertEqual(entry['review_url'], url + full['tasks'][0]['review_path'])
        self.assertEqual(full['status'], 'acknowledged')

    async def test_actual_input_binding_and_request_links_are_written_without_agent_edits(self):
        from copy import deepcopy
        self.setup_image()
        text = self.draft.read_text().replace('#### 3. 提示词与执行参数', '- 输入1：用户指定参考；用途：衣装\n\n#### 3. 提示词与执行参数', 1)
        self.draft.write_text(text)
        source = self.project / 'source.png'
        source.write_bytes(png())
        self.data.uploads = [dict(file=str(source), node='1', input='seed', **{'response-name':'upload.json'})]
        receipt = self.record / 'upload.json'
        receipt.write_text(json.dumps({'data':dict(input_path='actual/source.png', sha256=hashlib.sha256(source.read_bytes()).hexdigest())}))
        workflow = deepcopy(self.data.workflow)
        workflow['1']['inputs']['seed'] = 'actual/source.png'
        (self.record/self.data.request_name).write_text(json.dumps(dict(prompt=workflow, client_id='listener-id')))
        report = registration.register(self.store, 'task')
        current = self.draft.read_text()
        self.assertIn('实际上传：actual/source.png；槽位：1.seed', current)
        self.assertIn('[上传凭据]', current)
        self.assertNotIn('- 请求响应与执行结果入口：\n', current)
        self.assertEqual(len([item for item in report['checks'] if item['path']==self.rel(receipt)]), 1)
        receipt.write_text(receipt.read_text()+' ')
        with self.assertRaisesRegex(ValueError, '已核验证据发生变化'):
            registration.register(self.store, 'task')
