"""批准收尾端到端测试：临时项目、模拟原生导出和网页，无真实生成。"""
import argparse
import copy
import contextlib
import json
import io
import urllib.parse
from pathlib import Path
import unittest
from unittest.mock import patch

import video_approve as tool
import test_scene_finalize as fixtures

NativeClient = fixtures.NativeClient


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinalizeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.put(self.root / '项目进度.md',
                         '# 项目进度\n\n| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n'
                         '| --- | --- | --- | --- | --- | --- |\n'
                         '| EP001制作 | 会话 | 进行中 | 来源 | 待审核 | 后处理 |\n')
        self.browser_calls = []

    def setup_stage(self, stage='后处理', parts=('P001', 'P002')):
        self.fixture.put(self.fixture.ep / '03-分镜脚本/EP001-分镜索引.md', ''.join(
            '| EP001-C001 | [分镜](scene.md) | EP001-C001-' + p + ' | 其他 |\n' for p in parts))
        all_items = {}
        for current in (('一采',) if stage == '一采' else ('一采', '二采')):
            items = [self.fixture.item(p, current) for p in parts]
            self.fixture.plan.update(stage=current, items=items)
            if current != stage:
                self.fixture.run_plan()
            all_items[current] = copy.deepcopy(items)
        if stage == '后处理':
            items = [self.fixture.item(p, stage, c) for p, c in zip(parts, all_items['二采'])]
        else:
            items = all_items[stage]
        tasks = []
        for item in items:
            mapping = Path(item['mapping'])
            data = tool.adopt.load(mapping)
            receipt = tool.adopt.load(Path(item['receipt']))['data']
            data['outputs'] = [{'identity': item['identity'], **receipt, 'receipt': item['receipt']}]
            if stage == '后处理':
                data['source_video'] = str(self.fixture.ep / '06-阶段采用视频/02-二采/C001-场次' /
                                           (data['generation_contexts'][0]['source'] + '.mp4'))
            self.fixture.put(mapping, data)
            # Fixed submission artifacts use these names; receipts stay explicit.
            for old, new in (('实际.api.json', '任务.api.json'), ('实际.workflow.json', '任务.workflow.json')):
                self.fixture.put(mapping.parent / new, (mapping.parent / old).read_bytes())
            tasks.append({'record_dir': str(mapping.parent), 'task_type': {'一采': 'video-first-pass', '二采': 'video-second-pass', '后处理': 'video-postprocess'}[stage]})
            identity = item['identity']
            adopted = self.fixture.ep / '06-阶段采用视频' / tool.adopt.STAGES[stage] / 'C001-场次' / (identity + '.mp4')
            candidate = self.fixture.extra / '候选视频' / (identity + '.mp4')
            candidate.parent.mkdir(exist_ok=True)
            adopted.rename(candidate)
            draft = self.fixture.extra / '工作稿' / (identity.rsplit('-', 2)[0] + '-视频制作-工作稿.md')
            text = draft.read_text()
            for other in tool.adopt.STAGES:
                if '| ' + other + ' |' not in text:
                    text = text.replace('\n## 2.', '\n| ' + other + ' | 未选定 | — | — | — |\n\n## 2.', 1)
            row = tool.adopt.selected_row(text, stage)[2]
            self.fixture.put(draft, text.replace(row, '| ' + stage + ' | 未选定 | — | — | — |') + '\n### R001-' + stage + '\n- 处理阶段：' + stage + '\n- 用户决定：待审核\n\n## 4. 审阅区\n')
        submission = Path(items[0]['mapping']).parent / '任务清单.json'
        self.fixture.put(submission, {'tasks': tasks})
        source = submission.with_name('来源二采定稿请求.json')
        self.fixture.put(source, {'episode': 'EP001', 'scene': 'C001', 'stage': '二采', 'items': all_items.get('二采', [])})
        self.request = submission.with_name('批准收尾请求.json')
        self.plan = {'submission_plans': [str(submission)], 'identities': [i['identity'] for i in items],
                     'approval_text': '这两段都批准了。'}
        if stage == '后处理':
            self.plan['source_finalization'] = str(source)
        self.fixture.put(self.request, self.plan)
        NativeClient.calls = []
        return items

    def run_plan(self, apply=True, browser_error=None):
        self.fixture.put(self.request, self.plan)

        def verify(root, episode, stage, identities, complete, timeout):
            self.browser_calls.append((stage, identities, complete))
            if browser_error:
                raise ValueError(browser_error)
            for identity in identities:
                self.assertEqual(tool.selected(root, identity.rsplit('-', 2)[0], stage), identity)
            return {'state': 'verified', 'review_url': 'http://browser/#/projects/test'}

        with patch.object(tool.final.client, 'Client', NativeClient), patch.object(tool, 'browser_sync', side_effect=verify):
            return tool.approve(argparse.Namespace(project=str(self.root), plan=str(self.request), apply=apply, timeout=30))

    def test_whole_postprocess_approval_finishes_episode_and_repeat_never_exports_again(self):
        items = self.setup_stage(parts=tuple(f'P{i:03d}' for i in range(1, 13)))
        for item in items:
            path = Path(item['mapping'])
            mapping = tool.adopt.load(path)
            prompt = mapping.pop('prompt_id')
            mapping.pop('url')
            output = mapping.pop('outputs')[0]
            upload = mapping['uploads'][0]
            receipt = {'bytes': mapping.pop('source_bytes'), 'sha256': mapping.pop('source_sha256'),
                       'input_path': upload['input_path']}
            upload['input_path'] = 'planned/' + upload['input_path']
            self.fixture.put(path, mapping)
            self.fixture.put(path.parent / '后台过程记录.json', [{'stage': 'upload', 'result': 'success',
                'file': upload['file'], 'remote': receipt}])
            self.fixture.put(path.parent / '后台任务状态.json', {'record_dir': str(path.parent),
                'prompt_id': prompt, 'remote_url': 'http://example.invalid', 'outputs': [{
                'node_id': '16', 'output_key': 'gifs', 'index': 0, 'path': output['path'],
                'response_name': Path(item['receipt']).name}]})
            self.fixture.put(path.parent / '执行结果.json', {'data': {'prompt_id': prompt, 'state': 'success',
                'files': [{'node_id': '16', 'output_key': 'gifs', 'index': 0, 'file': output['remote']}]}})
        original = {Path(i['api']): Path(i['api']).read_bytes() for i in items}
        result = self.run_plan()
        self.assertEqual(result['state'], 'completed')
        self.assertTrue(result['episode_completed'])
        self.assertEqual(len(result['adoption']['items']), 12)
        self.assertEqual(result['episode_missing'], [])
        self.assertEqual([c[0] for c in NativeClient.calls].count('export'), 1)
        self.assertIn('| 已完成 |', (self.root / '项目进度.md').read_text())
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.run_plan()['state'], 'completed')
        self.assertEqual([c[0] for c in NativeClient.calls].count('export'), 1)

    def test_partial_approval_does_not_approve_other_file_or_export(self):
        self.setup_stage()
        self.plan['identities'] = self.plan['identities'][:1]
        result = self.run_plan()
        self.assertEqual(result['state'], 'adopted_partial')
        self.assertFalse(result['episode_completed'])
        self.assertIsNone(tool.selected(self.root, 'EP001-C001-P002', '后处理'))
        self.assertEqual(NativeClient.calls, [])

    def test_preview_does_not_move_write_export_or_query_browser(self):
        self.setup_stage()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.run_plan(apply=False)['state'], 'ready')
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(NativeClient.calls, [])
        self.assertEqual(self.browser_calls, [])

    def test_browser_failure_preserves_approval_and_archive_and_recovers_without_export(self):
        self.setup_stage()
        failed = self.run_plan(browser_error='模拟网页失败')
        self.assertEqual(failed['state'], 'browser_pending')
        report = tool.adopt.load(self.request.with_name('批准收尾请求-结果.json'))
        self.assertEqual(report['state'], 'browser_pending')
        self.assertEqual(tool.selected(self.root, 'EP001-C001-P001', '后处理'), self.plan['identities'][0])
        recovered = self.run_plan()
        self.assertEqual(recovered['state'], 'completed')
        self.assertEqual(recovered['previous_failures'][0]['error'], '模拟网页失败')
        self.assertEqual([c[0] for c in NativeClient.calls].count('export'), 1)

    def test_empty_approval_stops_before_moving(self):
        self.setup_stage()
        self.plan['approval_text'] = ''
        failed = self.run_plan()
        self.assertEqual(failed['state'], 'needs_attention')
        self.assertIn('批准原话', failed['error'])
        self.assertIsNone(tool.selected(self.root, 'EP001-C001-P001', '后处理'))
        self.assertEqual(NativeClient.calls, [])

    def test_finalization_failure_keeps_adoption_and_does_not_finish_episode(self):
        self.setup_stage()
        NativeClient.corrupt = True
        self.assertEqual(self.run_plan()['state'], 'needs_attention')
        report = tool.adopt.load(self.request.with_name('批准收尾请求-结果.json'))
        self.assertEqual(report['phase'], 'finalization')
        self.assertEqual(report['state'], 'needs_attention')
        self.assertEqual(tool.selected(self.root, 'EP001-C001-P001', '后处理'), self.plan['identities'][0])
        self.assertNotIn('| 已完成 |', (self.root / '项目进度.md').read_text())
        self.assertEqual(self.browser_calls, [])

    def test_last_partial_approval_finalizes_existing_approved_combination(self):
        self.setup_stage()
        all_ids = self.plan['identities'][:]
        self.plan['identities'] = all_ids[:1]
        self.assertEqual(self.run_plan()['state'], 'adopted_partial')
        self.plan['identities'] = all_ids[1:]
        self.plan['approval_text'] = '第二段也批准了。'
        self.request = self.fixture.extra / '执行附件' / all_ids[1] / '批准收尾请求.json'
        result = self.run_plan()
        self.assertTrue(result['episode_completed'])
        self.assertEqual([c[0] for c in NativeClient.calls].count('export'), 1)

    def test_browser_verification_uses_existing_endpoints_and_exact_scene_revision(self):
        self.setup_stage()
        workspace = self.root.parent.parent
        config = workspace / '工作区浏览服务/runtime/task-service.json'
        self.fixture.put(config, {'url': 'http://browser.invalid'})
        catalogue = {'children': [{'name': 'EP001', 'productionComplete': True}]}
        playback = {'segments': {'C001': [{'id': 'P001', 'videos': [
            {'stage': '后处理', 'run': 'R001', 'approved': True}]}]}}
        called = []

        class Opener:
            def open(inner, url, timeout):
                path = urllib.parse.urlsplit(url).path
                called.append(path)
                if path == '/api/service':
                    value = {'workspace': str(workspace), 'ready': True}
                elif path.endswith('/status'):
                    value = {'updating': False, 'error': None}
                elif '/episodes/' in path:
                    value = playback
                elif '/sections/' in path:
                    value = catalogue
                else:
                    raise AssertionError('Unexpected endpoint ' + path)
                return io.BytesIO(json.dumps(value).encode())

        with patch.object(tool.urllib.request, 'build_opener', return_value=Opener()):
            result = tool.browser_sync(self.root, 'EP001', '后处理', self.plan['identities'][:1], True, 30)
            self.assertEqual(result['state'], 'verified')
            playback['segments'] = {'C002': playback['segments']['C001']}
            with self.assertRaisesRegex(ValueError, '具体采用版本'):
                tool.browser_sync(self.root, 'EP001', '后处理', self.plan['identities'][:1], False, 30)
        self.assertTrue(any('/episodes/EP001' in p for p in called))

    def test_existing_authorized_configuration_batches_are_preserved(self):
        self.setup_stage()
        source = Path(self.plan['source_finalization'])
        origin = tool.adopt.load(source)
        origin.update(configuration_batches=[
            {'name': '原配置甲', 'parts': ['EP001-C001-P001']},
            {'name': '原配置乙', 'parts': ['EP001-C001-P002']}],
            configuration_batch_authorization='用户明确允许这两份原配置分别留档，参数不变。')
        self.fixture.put(source, origin)
        result = self.run_plan()
        self.assertEqual(result['state'], 'completed')
        self.assertTrue(result['episode_completed'])
        self.assertEqual(len(result['finalization']['batches']), 2)
        self.assertEqual([c[0] for c in NativeClient.calls].count('export'), 2)

    def test_cli_returns_compact_result_and_saves_full_report(self):
        self.setup_stage()
        output = io.StringIO()
        with patch.object(tool.final.client, 'Client', NativeClient), \
                patch.object(tool, 'browser_sync', return_value={'state': 'verified', 'review_url': 'http://browser/project'}), \
                patch.object(tool.sys, 'argv', ['video_approve.py', '--project', str(self.root), '--plan', str(self.request), '--apply']), \
                contextlib.redirect_stdout(output):
            self.assertEqual(tool.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['identity_count'], 2)
        self.assertNotIn('adoption', result)
        self.assertEqual(len(tool.adopt.load(Path(result['report_file']))['adoption']['items']), 2)

    def test_first_pass_does_not_mark_episode_complete_or_generate_second_pass(self):
        self.setup_stage('一采')
        result = self.run_plan()
        self.assertEqual(result['state'], 'completed')
        self.assertFalse(result['episode_completed'])
        self.assertIn('| 进行中 |', (self.root / '项目进度.md').read_text())
        self.assertEqual([c[0] for c in NativeClient.calls].count('export'), 1)


if __name__ == '__main__':
    unittest.main()
