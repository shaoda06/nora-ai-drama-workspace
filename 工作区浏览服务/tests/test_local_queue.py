"""Local queue actions, restart and race handling without real ComfyUI jobs."""
import asyncio
import json
import hashlib
from pathlib import Path
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from tests import test_comfy_tasks as base
from backend.services import comfy_tasks as t


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.title_patch = patch.object(self.store, 'read_session_name', AsyncMock())
        self.title_patch.start()

    async def asyncTearDown(self):
        self.title_patch.stop()
        await base.TaskTests.asyncTearDown(self)

    async def add(self, name):
        data = self.data.model_copy(deep=True)
        data.record_dir = str(self.record.parent / name)
        data.title = name
        data.outputs[0].path = str(self.project / '候选' / (name + '.png'))
        result = await self.store.enqueue(data)
        return result['local_task_id']

    def node(self, running=0, queued=0):
        self.store.remote_queues.states[self.data.url] = {
            'connection': 'connected', 'queue': [], 'running_count': running, 'queued_count': queued,
            'updated_at': t.client.now(), 'error': None, 'queue_error': None}

    async def test_enqueue_has_uuid_and_no_upload_or_remote_post(self):
        with patch.object(t.client, 'submit') as submit, patch.object(t.client, 'upload') as upload:
            key = await self.add('第一项')
            self.assertEqual(uuid.UUID(key).version, 4)
            submit.assert_not_called()
            upload.assert_not_called()
        self.assertEqual(self.store.public()['local_tasks'][0]['queue_position'], 1)
        self.assertTrue((Path(self.store.rows[key]['input'].record_dir) / '后台过程记录.json').is_file())

    async def test_same_enqueue_recovers_id_but_changed_payload_is_rejected(self):
        key = await self.add('第一项')
        duplicate = await self.store.enqueue(self.store.rows[key]['input'])
        self.assertEqual(duplicate['local_task_id'], key)
        reconnected = self.store.rows[key]['input'].model_copy(deep=True)
        reconnected.desktop.pipe = 'fresh-pipe'
        self.assertEqual((await self.store.enqueue(reconnected))['local_task_id'], key)
        self.assertEqual(self.store.rows[key]['input'].desktop.pipe, 'fresh-pipe')
        changed = self.store.rows[key]['input'].model_copy(update={'title': '另一任务'})
        with self.assertRaises(ValueError):
            await self.store.enqueue(changed)

    async def test_pause_insert_resume_cancel_and_order_survive_restart(self):
        one, two = await self.add('一'), await self.add('二')
        self.store.task_action(one, 'pause')
        self.assertEqual(self.store.ordered(), [two])
        self.store.task_action(one, 'insert')
        self.assertEqual(self.store.ordered(), [one, two])
        self.store.task_action(one, 'pause')
        self.store.task_action(one, 'resume')
        self.assertEqual(self.store.ordered(), [two, one])
        self.store.task_action(two, 'cancel')
        self.assertEqual(next(item for item in self.store.public()['local_tasks'] if item['id'] == two)['category'], 'history')
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(self.store, 'watch', AsyncMock()) as watch:
            await self.store.start()
            self.assertEqual(self.store.ordered(), [one])
            self.assertEqual(self.store.rows[two]['state']['status'], 'cancelled')
            watch.assert_not_awaited()

    async def test_drag_stops_dispatch_and_atomically_saves_full_order(self):
        one, two = await self.add('一'), await self.add('二')
        self.node()
        token = self.store.drag()['token']
        with patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            submit.assert_not_awaited()
        self.store.reorder([two, one], token)
        self.assertEqual(self.store.ordered(), [two, one])
        with self.assertRaises(ValueError):
            self.store.reorder([two], token)
        self.store.drag(token, release=True)
        self.assertFalse(self.store.active_drag())
        self.store.drag_leases['expired'] = {'url': self.data.url, 'expires': 0}
        self.assertFalse(self.store.active_drag())

    async def test_normal_waits_but_paused_immediate_ignores_remote_busy(self):
        key = await self.add('一')
        self.node(running=1, queued=3)
        with patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            submit.assert_not_awaited()
        self.store.task_action(key, 'pause')
        self.store.task_action(key, 'immediate')
        with patch.object(self.store, 'submit', AsyncMock()) as submit, patch.object(self.store.remote_queues, 'refresh', AsyncMock()):
            await self.store.dispatch_once()
            submit.assert_awaited_once()
            self.assertEqual(submit.await_args.kwargs['key'], key)
        with self.assertRaises(ValueError):
            self.store.task_action(key, 'cancel')

    async def test_competing_remote_submit_before_final_check_keeps_task_local(self):
        key = await self.add('一')
        self.node()
        async def refresh(url):
            self.node(running=1)
        with patch.object(self.store.remote_queues, 'refresh', refresh), patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            submit.assert_not_awaited()
        self.assertEqual(self.store.rows[key]['state']['status'], 'local_queued')

    async def test_missing_material_pauses_with_record_without_blocking_next(self):
        key = await self.add('坏任务')
        self.store.rows[key]['input'].uploads = [{'file': str(self.project / 'missing.png'), 'node': '1',
            'input': 'seed', 'subfolder': '', 'response-name': 'upload.json'}]
        await self.add('好任务')
        self.node()
        with patch.object(self.store, 'notify', AsyncMock()), patch.object(self.store.remote_queues, 'refresh', AsyncMock()), patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
            await self.store.dispatch_once()
            submit.assert_awaited_once()
        events = json.loads((Path(self.store.rows[key]['input'].record_dir) / '后台过程记录.json').read_text('utf-8'))
        self.assertIn('missing.png', events[-2]['message'] if 'message' in events[-2] else str(events))

    async def test_retry_collection_uses_saved_terminal_result_never_posts(self):
        key = await self.add('一')
        row = self.store.rows[key]
        self.store.save(key, status='collection_failed', prompt_id='original')
        result = {'state': 'success', 'history': {}, 'files': []}
        (Path(row['input'].record_dir) / row['input'].history_name).write_text(json.dumps({'data': result}))
        with patch.object(self.store, 'finish_collection', AsyncMock()) as collect, patch.object(t.client, 'submit') as submit, patch.object(self.store, 'notify', AsyncMock()):
            await self.store.retry_collection(key)
            with self.assertRaises(ValueError):
                await self.store.retry_collection(key)
            await self.store.workers[key]
            collect.assert_awaited_once_with(key, result)
            submit.assert_not_called()

    async def test_unknown_old_task_does_not_block_independent_new_task(self):
        old = await self.add('旧任务')
        new = await self.add('新任务')
        self.store.save(old, status='running', prompt_id='lost')
        self.node()
        with patch.object(t.client, 'status', return_value={'state': 'unknown', 'history': None, 'queue': {}}), \
                patch.object(self.store, 'notify', AsyncMock()), patch.object(self.store.remote_queues, 'refresh', AsyncMock()), \
                patch.object(self.store, 'submit', AsyncMock()) as submit:
            await self.store.dispatch_once()
            self.assertEqual(self.store.rows[old]['state']['status'], 'needs_attention')
            self.assertEqual(submit.await_args.kwargs['key'], new)

    async def test_blank_title_and_changed_primary_are_rejected(self):
        self.data.title = '  '
        with self.assertRaises(ValueError):
            await self.store.enqueue(self.data)
        self.data.title = '合法'
        key = await self.add('一')
        (self.project / 'comfyui-config.json').write_text(json.dumps({'remote-urls': ['http://different.invalid']}))
        with self.assertRaises(ValueError):
            await self.store.prepare(key)

    async def test_pause_or_insert_clears_force_submission(self):
        key = await self.add('一')
        self.store.task_action(key, 'immediate')
        self.store.task_action(key, 'pause')
        self.store.task_action(key, 'resume')
        self.assertFalse(self.store.rows[key]['state']['immediate'])
        self.store.task_action(key, 'immediate')
        self.store.task_action(key, 'insert')
        self.assertFalse(self.store.rows[key]['state']['immediate'])

    async def test_upload_replaces_json_field_with_actual_name_without_changing_original(self):
        key = await self.add('一')
        data = self.store.rows[key]['input']
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        data.workflow['1']['inputs']['timeline_data'] = json.dumps({'global': {'refs': [{'imageFile': 'planned.png'}]}})
        data.uploads = [{'file': str(source), 'node': '1', 'input': 'timeline_data', 'subfolder': 'task',
            'response-name': 'upload.json', 'json-path': ['global', 'refs', 0, 'imageFile']}]
        uploaded = {'input_path': 'task/renamed.png', 'sha256': hashlib.sha256(b'picture').hexdigest(),
                    'remote': {'name': 'renamed.png', 'subfolder': 'task', 'type': 'input'}}
        with patch.object(t.client, 'upload', return_value=uploaded) as upload:
            workflow = await self.store.prepare(key)
            await self.store.prepare(key)
            upload.assert_called_once()
        self.assertEqual(json.loads(workflow['1']['inputs']['timeline_data'])['global']['refs'][0]['imageFile'], 'task/renamed.png')
        self.assertIn('planned.png', data.workflow['1']['inputs']['timeline_data'])
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '素材已不同'):
            await self.store.prepare(key)

    async def test_director_upload_updates_root_editor_and_actual_file_metadata(self):
        key = await self.add('导演台')
        data = self.store.rows[key]['input']
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        media = {'imageFile': 'planned.png', 'fileName': 'planned.png', 'subfolder': 'planned', 'type': 'input', 'index': 0}
        data.workflow['1']['class_type'] = 'MiniMaxH3Director'
        data.workflow['1']['inputs']['timeline_data'] = json.dumps({
            'global': {'refs': [media]}, 'segments': [{'refs': [media]}],
            'batchWorkspaces': {'r2v': {'globalCommon': {'refs': [media]}, 'segments': [{'refs': [media]}]}}})
        data.uploads = [{'file': str(source), 'node': '1', 'input': 'timeline_data', 'subfolder': 'task',
                         'response-name': f'upload-{scope}.json', 'json-path': path}
                        for scope, path in [('common', ['global', 'refs', 0, 'imageFile']),
                                            ('common-editor', ['batchWorkspaces', 'r2v', 'globalCommon', 'refs', 0, 'imageFile']),
                                            ('segment', ['segments', 0, 'refs', 0, 'imageFile']),
                                            ('segment-editor', ['batchWorkspaces', 'r2v', 'segments', 0, 'refs', 0, 'imageFile'])]]
        uploaded = {'input_path': 'actual/renamed.png', 'sha256': hashlib.sha256(b'picture').hexdigest(),
                    'remote': {'name': 'renamed.png', 'subfolder': 'actual', 'type': 'input'}}
        with patch.object(t.client, 'upload', return_value=uploaded) as upload:
            workflow = await self.store.prepare(key)
            await self.store.prepare(key)
            upload.assert_called_once()
        timeline = json.loads(workflow['1']['inputs']['timeline_data'])
        editor = timeline['batchWorkspaces']['r2v']
        for root, mirrored in [(timeline['global'], editor['globalCommon']), (timeline['segments'][0], editor['segments'][0])]:
            self.assertEqual(root['refs'], mirrored['refs'])
            self.assertEqual(root['refs'][0], {**media, 'imageFile': 'actual/renamed.png',
                                               'fileName': 'renamed.png', 'subfolder': 'actual'})
        self.assertIn('planned.png', data.workflow['1']['inputs']['timeline_data'])

    def bind_uploads(self, key, sources, folders=None):
        data = self.store.rows[key]['input']
        data.uploads = []
        for index, source in enumerate(sources):
            name = f'reference_{index}'
            data.workflow['1']['inputs'][name] = 'planned'
            data.uploads.append({'file': str(source), 'node': '1', 'input': name,
                                 'subfolder': folders[index] if folders else 'task',
                                 'response-name': f'upload-{index}.json'})
        return data

    @staticmethod
    def uploaded_file(remote, args):
        source = Path(args.file)
        return {'input_path': args.subfolder + '/' + source.name,
                'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'remote': {'name': source.name, 'subfolder': args.subfolder, 'type': 'input'}}

    async def test_53_bindings_upload_11_files_and_retain_every_receipt(self):
        key = await self.add('多段共用素材')
        sources = []
        for index, count in enumerate([4, 8, 6, 8, 1, 6, 5, 6, 4, 4, 1]):
            source = self.project / f'asset-{index}.png'
            source.write_bytes(f'asset {index}'.encode())
            sources.extend([source] * count)
        data = self.bind_uploads(key, sources)
        with patch.object(t.client, 'upload', side_effect=self.uploaded_file) as upload:
            workflow = await self.store.prepare(key)
            self.assertEqual(upload.call_count, 11)
            await self.store.prepare(key)
            self.assertEqual(upload.call_count, 11)
        receipts = []
        for item in data.uploads:
            receipt = json.loads((Path(data.record_dir) / item['response-name']).read_text('utf8'))
            receipts.append(receipt)
            self.assertEqual(workflow['1']['inputs'][item['input']], receipt['data']['input_path'])
            self.assertEqual(receipt['data']['sha256'], hashlib.sha256(Path(item['file']).read_bytes()).hexdigest())
            self.assertEqual(data.workflow['1']['inputs'][item['input']], 'planned')
        self.assertEqual(len(receipts), 53)
        self.assertEqual(sum('reused_from' in receipt for receipt in receipts), 42)

    async def test_restart_after_partial_receipt_write_reuses_completed_upload(self):
        key = await self.add('恢复上传')
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        data = self.bind_uploads(key, [source, source])
        record = Path(data.record_dir)
        original_write = t.client.write_new
        def fail_second_receipt(path, value):
            if Path(path).name == 'upload-1.json':
                raise OSError('simulated interrupted receipt write')
            return original_write(path, value)
        with patch.object(t.client, 'upload', side_effect=self.uploaded_file) as upload, \
                patch.object(t.client, 'write_new', side_effect=fail_second_receipt):
            with self.assertRaises(OSError):
                await self.store.prepare(key)
            upload.assert_called_once()
        self.assertTrue((record / 'upload-0.json').exists())
        self.assertFalse((record / 'upload-1.json').exists())
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        with patch.object(t.client, 'upload') as upload:
            workflow = await self.store.prepare(key)
            upload.assert_not_called()
        self.assertEqual(workflow['1']['inputs']['reference_0'], workflow['1']['inputs']['reference_1'])
        self.assertTrue((record / 'upload-1.json').is_file())

    async def test_receipt_on_later_binding_can_recover_earlier_missing_receipt(self):
        key = await self.add('后方凭据恢复')
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        data = self.bind_uploads(key, [source, source])
        from argparse import Namespace
        uploaded = self.uploaded_file(None, Namespace(file=str(source), subfolder='task'))
        receipt = Path(data.record_dir) / 'upload-1.json'
        t.client.write_new(receipt, {'ok': True, 'url': data.url, 'data': uploaded})
        original_bytes = receipt.read_bytes()
        with patch.object(t.client, 'upload') as upload:
            workflow = await self.store.prepare(key)
            upload.assert_not_called()
        recovered = json.loads((Path(data.record_dir) / 'upload-0.json').read_text('utf8'))
        self.assertEqual(recovered['reused_from'], 'upload-1.json')
        self.assertEqual(receipt.read_bytes(), original_bytes)
        self.assertEqual(workflow['1']['inputs']['reference_0'], uploaded['input_path'])

    async def test_different_files_or_target_directories_do_not_share_upload(self):
        key = await self.add('不同素材与目录')
        one, two = self.project / 'one.png', self.project / 'two.png'
        one.write_bytes(b'same content')
        two.write_bytes(b'same content')
        self.bind_uploads(key, [one, two, one], ['task', 'task', 'other'])
        with patch.object(t.client, 'upload', side_effect=self.uploaded_file) as upload:
            workflow = await self.store.prepare(key)
            self.assertEqual(upload.call_count, 3)
        self.assertEqual(workflow['1']['inputs']['reference_0'], 'task/one.png')
        self.assertEqual(workflow['1']['inputs']['reference_1'], 'task/two.png')
        self.assertEqual(workflow['1']['inputs']['reference_2'], 'other/one.png')

    async def test_reuse_cache_does_not_cross_tasks(self):
        one, two = await self.add('任务一'), await self.add('任务二')
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        for key in (one, two):
            self.bind_uploads(key, [source, source])
        with patch.object(t.client, 'upload', side_effect=self.uploaded_file) as upload:
            await self.store.prepare(one)
            await self.store.prepare(two)
            self.assertEqual(upload.call_count, 2)

    async def test_receipt_from_another_endpoint_is_not_reused(self):
        key = await self.add('其他执行端')
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        data = self.bind_uploads(key, [source, source])
        from argparse import Namespace
        uploaded = self.uploaded_file(None, Namespace(file=str(source), subfolder='task'))
        t.client.write_new(Path(data.record_dir) / 'upload-1.json',
                           {'ok': True, 'url': 'http://another.invalid:8188', 'data': uploaded})
        with patch.object(t.client, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, '上传凭据不完整'):
                await self.store.prepare(key)
            upload.assert_not_called()

    async def test_source_change_after_first_upload_stops_reuse(self):
        key = await self.add('上传中素材变化')
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        data = self.bind_uploads(key, [source, source])
        def upload_and_change(remote, args):
            uploaded = self.uploaded_file(remote, args)
            source.write_bytes(b'changed')
            return uploaded
        with patch.object(t.client, 'upload', side_effect=upload_and_change) as upload:
            with self.assertRaisesRegex(ValueError, '素材已不同'):
                await self.store.prepare(key)
            upload.assert_called_once()
        self.assertFalse((Path(data.record_dir) / 'upload-1.json').exists())

    async def test_upload_error_does_not_create_reusable_receipt(self):
        key = await self.add('上传失败')
        source = self.project / 'reference.png'
        source.write_bytes(b'picture')
        data = self.bind_uploads(key, [source, source])
        with patch.object(t.client, 'upload', side_effect=OSError('upload failed')) as upload:
            with self.assertRaises(OSError):
                await self.store.prepare(key)
            upload.assert_called_once()
        self.assertFalse(list(Path(data.record_dir).glob('upload-*.json')))

    async def test_invalid_upload_or_reserved_receipt_names_fail_at_boundary(self):
        self.data.uploads = [{'file': 'broken'}]
        with self.assertRaisesRegex(ValueError, '上传映射'):
            await self.store.enqueue(self.data)
        self.data.uploads = []
        self.data.response_name = '后台任务状态.json'
        with self.assertRaisesRegex(ValueError, '不能重复'):
            await self.store.enqueue(self.data)
