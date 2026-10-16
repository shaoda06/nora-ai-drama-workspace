"""Record formatting reuses checked paths without relaxing input/file boundaries."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, task_details
from tests import test_comfy_tasks as base


class RecordPathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.session = patch.object(self.store, 'read_session_name', AsyncMock())
        self.session.start()
        self.source = self.project / 'reference.png'
        self.source.write_bytes(b'picture')
        self.data.uploads = [{'file': str(self.source), 'node': '1', 'input': 'seed',
                              'subfolder': 'task', 'response-name': 'upload.json'}]

    async def asyncTearDown(self):
        self.session.stop()
        await base.TaskTests.asyncTearDown(self)

    async def enqueue(self):
        self.data.start_paused = True
        return (await self.store.enqueue(self.data))['local_task_id']

    async def test_known_input_paths_need_no_resolve_for_repeated_record_and_persist(self):
        key = await self.enqueue()
        with patch.object(Path, 'resolve', side_effect=AssertionError('known record paths must be reused')):
            for _ in range(3):
                self.store.record(key, 'upload', 'started', file=str(self.source), path=self.data.outputs[0].path)
                self.store.save(key, saved_outputs=[self.data.outputs[0].path])
        events = json.loads((self.record / '后台过程记录.json').read_text('utf-8'))
        self.assertEqual([event['file'] for event in events if event['stage'] == 'upload'], ['reference.png'] * 3)
        state = json.loads(self.store.db.execute('SELECT state FROM tasks WHERE id=?', (key,)).fetchone()[0])
        self.assertEqual(state['saved_outputs'], ['候选/result.png'])
        self.assertNotIn('_record_paths', state)

    async def test_new_record_path_checked_once_then_reused_in_both_spellings(self):
        key = await self.enqueue()
        receipt = self.record / 'new-receipt.json'
        with patch.object(t.paths, '_project_file', wraps=t.paths._project_file) as resolve:
            self.store.record(key, 'upload', 'success', receipt=str(receipt))
            self.store.save(key, evidence=[str(receipt)])
            self.store.record(key, 'upload', 'reused', receipt='执行附件/任务001/new-receipt.json')
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.args[1], receipt.as_posix())

    async def test_new_escaping_record_path_stops_before_event_is_written(self):
        key = await self.enqueue()
        count = self.store.db.execute('SELECT COUNT(*) FROM task_events').fetchone()[0]
        with self.assertRaisesRegex(ValueError, '越出项目'):
            self.store.record(key, 'download', 'success', path='../outside.png')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM task_events').fetchone()[0], count)

    async def test_new_record_path_checks_resolved_target_not_only_spelling(self):
        key = await self.enqueue()
        link = self.project / 'junction/escape.png'
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return self.root / 'outside.png' if path == link else original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            with self.assertRaisesRegex(ValueError, '越出项目'):
                self.store.record(key, 'download', 'success', path='junction/escape.png')

    async def test_record_cache_cannot_bypass_new_request_scope_checks(self):
        await self.enqueue()
        changed = self.data.model_copy(deep=True)
        changed.outputs[0].path = '../outside.png'
        with self.assertRaisesRegex(ValueError, '越出项目'):
            await self.store.enqueue(changed)

    async def test_restart_rechecks_input_then_reuses_loaded_record_paths(self):
        key = await self.enqueue()
        self.store.save(key, saved_outputs=[self.data.outputs[0].path])
        await self.store.close()
        with patch.object(t.paths, 'project_file', wraps=t.paths.project_file) as resolve:
            self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertTrue(any(call.args[1] == 'reference.png' for call in resolve.call_args_list))
        with patch.object(Path, 'resolve', side_effect=AssertionError('loaded record paths must be reused')):
            self.store.record(key, 'restart', 'restored', file=str(self.source))
            self.store.save(key)

    async def test_explicit_repreparation_rebuilds_converter_from_new_checked_input(self):
        await self.store.prepare_only(self.data)
        key = await self.enqueue()
        previous = self.store.record_paths(key)
        replacement = self.project / 'replacement.png'
        replacement.write_bytes(b'replacement')
        changed = self.data.model_copy(deep=True)
        changed.uploads[0]['file'] = str(replacement)
        await self.store.prepare_only(changed)
        self.assertIsNot(self.store.record_paths(key), previous)
        with patch.object(Path, 'resolve', side_effect=AssertionError('new input is already checked')):
            self.store.record(key, 'upload', 'started', file=str(replacement))

    async def test_projects_do_not_share_conversion_cache(self):
        first = t.paths.RecordPaths(self.project)
        other = self.root / 'projects/另一项目'
        other.mkdir()
        second = t.paths.RecordPaths(other)
        with patch.object(t.paths, '_project_file', wraps=t.paths._project_file) as resolve:
            a = first.convert({'file': 'same.png'})
            b = second.convert({'file': 'same.png'})
            first.convert({'file': 'same.png'}, relative=True)
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(a['file'], str(self.project / 'same.png'))
        self.assertEqual(b['file'], str(other / 'same.png'))

    async def test_remote_details_and_legacy_record_paths_keep_their_meaning(self):
        key = await self.enqueue()
        document = {'file': 'E:/Comfy/output/remote.png',
                    'error_details': {'file': '../../opaque-remote-error'},
                    'path': 'C:/Old/projects/' + self.project.name + '/候选/old.png'}
        converted = self.store.record_paths(key).convert(document, relative=True)
        self.assertEqual(converted, {**document, 'path': '候选/old.png'})
        self.assertNotEqual(converted['path'], document['path'])
        self.assertEqual(document['path'], 'C:/Old/projects/' + self.project.name + '/候选/old.png')
        with patch.object(Path, 'resolve', side_effect=AssertionError('opaque errors are not local paths')):
            self.assertIs(t.paths.recorded_paths(self.project, document, field='error_details'), document)

    async def test_standalone_conversion_shares_paths_only_within_one_call(self):
        document = {'file': 'reference.png', 'nested': [{'file': 'reference.png'}]}
        with patch.object(t.paths, '_project_file', wraps=t.paths._project_file) as resolve:
            t.paths.recorded_paths(self.project, document, relative=True)
            self.assertEqual(resolve.call_count, 1)
            t.paths.recorded_paths(self.project, document, relative=True)
            self.assertEqual(resolve.call_count, 2)

    async def test_download_receipt_reuses_checked_output_path(self):
        key = await self.enqueue()
        self.store.save(key, prompt_id='isolated-id')
        remote = {'filename': 'actual.png', 'subfolder': '', 'type': 'output'}
        def download(client, args):
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b'media')
            return {'path': str(output), 'remote': remote, 'bytes': 5}
        result = {'files': [{'node_id': '1', 'output_key': 'images', 'index': 0, 'file': remote}]}
        with patch.object(t.client, 'download', side_effect=download), \
                patch.object(t.paths, 'relative_file', side_effect=AssertionError('no separate record resolution')):
            self.assertEqual(await self.store.collect(key, result), [])
        receipt = json.loads((self.record / self.data.outputs[0].response_name).read_text('utf-8'))
        self.assertEqual(receipt['data']['path'], '候选/result.png')

    async def test_event_read_reuses_checked_paths_while_file_checks_remain_separate(self):
        key = await self.enqueue()
        self.store.record(key, 'upload', 'started', file=str(self.source))
        with patch.object(task_details, 'task_files', return_value={'outputs': [], 'records': []}), \
                patch.object(Path, 'resolve', side_effect=AssertionError('event conversion must reuse paths')):
            for _ in range(2):
                detail = await task_details.task_detail(self.store, key)
        event = next(item for item in detail['events'] if item['stage'] == 'upload')
        self.assertEqual(event['file'], str(self.source))
