"""Preparation-only reuse, with fresh IO boundaries and exclusive frozen writes."""
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import comfy_tasks as t, execution_checks as checks, director_uploads
from project_paths import PreparationPaths
import project_paths
from tests import test_comfy_tasks as base, test_submission_lifecycle as lifecycle
from tests import test_generation_context as contexts


class BindingReuseTests(unittest.IsolatedAsyncioTestCase):
    video = lifecycle.LifecycleTests.video
    respond = lifecycle.LifecycleTests.respond

    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.session = patch.object(self.store, 'read_session_name', AsyncMock())
        self.session.start()

    async def asyncTearDown(self):
        self.session.stop()
        await base.TaskTests.asyncTearDown(self)

    def counted_json(self, calls):
        class Reference(dict):
            def __getitem__(self, key):
                if key == 'imageFile' and sys._getframe(1).f_globals.get('__name__') == checks.__name__:
                    calls.append(sys._getframe(1).f_code.co_name)
                return super().__getitem__(key)
        def loads(raw):
            value = json.loads(raw)
            if isinstance(value, dict) and 'batchWorkspaces' in value:
                value['global']['refs'][0] = Reference(value['global']['refs'][0])
            return value
        return SimpleNamespace(loads=loads)

    async def test_fixed_check_passes_terminal_values_without_walking_paths_again(self):
        self.video()
        self.store.resolve_input(self.data)
        calls = []
        with patch.object(checks, 'json', self.counted_json(calls)):
            checks.fixed_checks(self.store, self.data)
        self.assertEqual(calls, ['fixed_checks'])

    async def test_context_only_supplement_still_resolves_its_missing_binding_once(self):
        self.video()
        self.store.resolve_input(self.data)
        calls = []
        with patch.object(checks, 'json', self.counted_json(calls)):
            result = checks.context_checks(self.store, self.data)
        self.assertEqual(calls, ['context_checks'])
        self.assertIn(str(self.project / 'reference.png'), result)

    async def test_invalid_binding_still_stops_preparation_without_upload_or_submit(self):
        self.video()
        self.data.uploads[0]['json-path'] = ['global', 'refs', 99, 'imageFile']
        with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, '素材JSON字段路径不匹配'):
                await self.store.prepare_only(self.data)
        self.assertFalse(checks.read_report(self.data)['ok'])
        upload.assert_not_called()
        submit.assert_not_called()

    async def test_actual_binding_and_freezing_share_only_the_current_save_scope(self):
        self.video()
        await self.store.prepare_only(self.data)
        key = (await self.store.enqueue(self.data))['local_task_id']
        scopes = []
        original = director_uploads.save_uploaded_workflow
        def save(*args, **kwargs):
            scopes.append(kwargs['path_scope'])
            return original(*args, **kwargs)
        writer = self.store.generation_context.prepare_generation_context
        def freeze(*args, **kwargs):
            scopes.append(kwargs['path_scope'])
            return writer(*args, **kwargs)
        with patch.object(director_uploads, 'save_uploaded_workflow', side_effect=save), \
                patch.object(self.store.generation_context, 'prepare_generation_context', side_effect=freeze), \
                patch.object(t.client.Client, 'json', side_effect=self.respond), \
                patch.object(t.client, 'submit') as submit:
            await self.store.prepare(key)
        self.assertEqual(len(scopes), 2)
        self.assertIs(scopes[0], scopes[1])
        submit.assert_not_called()


class FrozenReuseTests(unittest.TestCase):
    write = contexts.GenerationContextTests.write
    storyboard = contexts.GenerationContextTests.storyboard
    automatic_task = contexts.GenerationContextTests.automatic_task

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / '示例项目'
        self.episode = '09-剧集制作/EP001'
        self.root, self.workflow, self.mapping = self.automatic_task()
        self.writer = contexts.writer

    def freeze(self):
        return self.writer.prepare_generation_context(self.project, self.root, self.workflow, 'video-first-pass')

    def observed_stats(self, target, calls):
        original = Path.stat
        def stat(path, *args, **kwargs):
            if path == target and sys._getframe(1).f_globals.get('__name__') == self.writer.__name__:
                calls.append(path)
            return original(path, *args, **kwargs)
        return patch.object(Path, 'stat', stat)

    def test_shared_reference_has_one_observation_plus_fresh_save_checkpoint(self):
        target = self.root / '输入素材/公共.png'
        calls = []
        with self.observed_stats(target, calls):
            self.freeze()
        self.assertEqual(len(calls), 2)
        self.assertEqual(target.read_text('utf-8'), '提交时公共原图')

    def test_existing_prompt_and_shared_reference_are_not_rewritten_or_rechecked_per_slot(self):
        self.freeze()
        for target in (self.root / '模型提示词.txt', self.root / '输入素材/公共.png'):
            with self.subTest(target=target.name):
                before = target.stat().st_mtime_ns
                calls = []
                with self.observed_stats(target, calls):
                    self.freeze()
                self.assertEqual(len(calls), 2)
                self.assertEqual(target.stat().st_mtime_ns, before)

    def inject_on_local_reference(self, action):
        original = Path.read_bytes
        source = self.project / '图片/本组.png'
        def read(path):
            if path == source:
                action()
            return original(path)
        return patch.object(Path, 'read_bytes', read)

    def test_new_file_appearing_before_save_is_not_overwritten(self):
        target = self.root / '输入素材/公共.png'
        def introduce():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'concurrent file')
        with self.inject_on_local_reference(introduce):
            with self.assertRaisesRegex(ValueError, '保存前发生变化'):
                self.freeze()
        self.assertEqual(target.read_bytes(), b'concurrent file')

    def test_existing_frozen_file_changing_before_save_is_not_accepted(self):
        self.freeze()
        target = self.root / '输入素材/公共.png'
        with self.inject_on_local_reference(lambda: target.write_bytes(b'concurrent replacement')):
            with self.assertRaisesRegex(ValueError, '保存前发生变化'):
                self.freeze()
        self.assertEqual(target.read_bytes(), b'concurrent replacement')

    def test_exclusive_create_still_stops_a_race_after_the_final_check(self):
        target = self.root / '输入素材/公共.png'
        original = Path.open
        def open_file(path, mode='r', *args, **kwargs):
            if path == target and mode == 'xb':
                with original(path, 'wb') as stream:
                    stream.write(b'race winner')
            return original(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            with self.assertRaises(FileExistsError):
                self.freeze()
        self.assertEqual(target.read_bytes(), b'race winner')

    def test_same_destination_with_different_sources_still_conflicts(self):
        self.write('另一处/公共.png', 'different source')
        self.mapping['uploads'][1]['file'] = '另一处/公共.png'
        (self.root / '输入映射.json').write_text(json.dumps(self.mapping), 'utf-8')
        with self.assertRaisesRegex(ValueError, '不可覆盖'):
            self.freeze()
        self.assertNotIn('generation_contexts', json.loads((self.root / '输入映射.json').read_text('utf-8')))

    def test_mapping_is_read_once_and_unchanged_result_is_not_rewritten(self):
        uploaded = {'remote/common.png': {'input_path': 'remote/common.png', 'file': str(self.project / '图片/公共.png')}}
        target = self.root / '输入映射.json'
        original = Path.read_text
        calls = []
        def read(path, *args, **kwargs):
            if path == target:
                calls.append(path)
            return original(path, *args, **kwargs)
        for first in (True, False):
            before = target.stat().st_mtime_ns
            calls.clear()
            with patch.object(Path, 'read_text', read):
                director_uploads.save_uploaded_workflow(self.project, self.root, self.workflow, self.workflow, uploaded, [])
            self.assertEqual(len(calls), 1)
            if not first:
                self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertEqual(json.loads(target.read_text('utf-8'))['prompt_id'], '既有事实不得修改')

    def test_new_scope_rechecks_changed_inputs_and_rejects_outside_paths(self):
        self.freeze()
        self.write('图片/公共.png', 'changed since prior call')
        with self.assertRaisesRegex(ValueError, '不可覆盖'):
            self.freeze()
        self.mapping['uploads'][0]['file'] = '../outside.png'
        (self.root / '输入映射.json').write_text(json.dumps(self.mapping), 'utf-8')
        with self.assertRaisesRegex(ValueError, '越出项目'):
            self.freeze()

    def test_address_reuse_does_not_replace_io_scope_checks(self):
        source = self.project / '图片/公共.png'
        scope = PreparationPaths.from_resolved(self.project, [self.root, source])
        with patch.object(project_paths, '_project_file', wraps=project_paths._project_file) as resolve:
            for _ in range(3):
                self.assertEqual(scope.file(source), source)
                self.assertEqual(scope.file('图片/公共.png'), source)
                scope.convert({'file': str(source)}, relative=True)
            resolve.assert_not_called()
            scope.io_file(source)
            scope.io_file(source)
            self.assertEqual(resolve.call_count, 2)
            with self.assertRaisesRegex(ValueError, '越出项目'):
                scope.io_file('../outside.png')

    def test_junction_retargeting_cannot_use_a_cached_address_to_escape(self):
        if os.name != 'nt':
            self.skipTest('Windows junction boundary')
        inside = self.project / '图片'
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / '公共.png').write_bytes(b'outside')
        alias = self.project / 'alias'
        def link(target):
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(target)],
                           check=True, capture_output=True)
        link(inside)
        scope = PreparationPaths(self.project)
        self.assertEqual(scope.file(alias / '公共.png'), inside / '公共.png')
        alias.rmdir()  # Removes only this temporary junction, never its target.
        link(outside)
        with self.assertRaisesRegex(ValueError, '越出项目'):
            scope.io_file(alias / '公共.png')
        self.assertEqual((outside / '公共.png').read_bytes(), b'outside')
