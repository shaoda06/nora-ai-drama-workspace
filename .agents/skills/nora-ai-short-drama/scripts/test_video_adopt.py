"""Offline approval/movement regression tests; no real project or network writes."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import video_adopt as tool


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.extra = self.root / '09-剧集制作/EP001/其他资料'
        self.summary = self.extra / '工作稿/EP001-生成说明-工作稿.md'
        self.progress = self.root / '项目进度.md'
        self.put(self.summary, '# 生成说明\n- 当前状态：待审核\n')
        self.put(self.progress, '# 项目进度\n| EP001 | 制作中 |\n')
        self.plan = {'approval_text': '这两段通过了', 'items': [], 'record_updates': [
            {'path': str(self.summary), 'old': '- 当前状态：待审核', 'new': '- 当前状态：本批批准采用'},
            {'path': str(self.progress), 'old': '| EP001 | 制作中 |', 'new': '| EP001 | 本批已采用，其他任务继续 |'}]}

    def put(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def write_json(self, path, value):
        self.put(path, json.dumps(value, ensure_ascii=False))

    def item(self, part='P001', revision='R001', stage='一采', mapping=None):
        unit = getattr(self, 'unit', 'EP001')
        identity = f'{unit}-C001-{part}-{revision}-{stage}'
        draft = self.extra / f'工作稿/{unit}-C001-{part}-视频制作-工作稿.md'
        if not draft.exists():
            self.put(draft, '# 分段工作稿\n- 最近更新：原时间\n- 当前状态及待办：待审核\n\n'
                     '## 1. 当前选定结果\n\n'
                     '| 处理阶段 | 当前选定文件 | R编号 | 来源任务 | 人工批准依据 |\n'
                     '| --- | --- | --- | --- | --- |\n'
                     '| 一采 | 未选定 | — | — | — |\n| 二采 | 未选定 | — | — | — |\n'
                     '| 后处理 | 未选定 | — | — | — |\n\n'
                     '## 2. 修订版各阶段与采用记录\n')
        text = draft.read_text(encoding='utf-8')
        block = f'### {revision}-{stage}\n- 处理阶段：{stage}\n- 用户决定：待审核\n- 原提交事实：不得改写\n\n'
        if '## 4. 审阅区' in text:
            text = text.replace('## 4. 审阅区', block + '## 4. 审阅区')
        else:
            text += block + '## 4. 审阅区\n\n## 其他补充\n保留。\n'
        self.put(draft, text)
        mapping = mapping or self.extra / f'执行附件/{identity}/输入映射.json'
        mapped = tool.load(mapping) if mapping.exists() else {'prompt_id': 'real-prompt', 'status': 'success', 'generation_contexts': [], 'outputs': []}
        source = self.extra / '候选视频' / (identity + '.mp4')
        source.parent.mkdir(parents=True, exist_ok=True)
        content = identity.encode('utf-8')
        source.write_bytes(content)
        receipt = mapping.parent / (part + '-下载响应.json')
        remote = {'filename': part + '.mp4', 'subfolder': 'actual', 'type': 'output'}
        data = {'path': str(source), 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(), 'remote': remote}
        self.write_json(receipt, {'ok': True, 'data': data})
        mapped['generation_contexts'].append({'identity': identity})
        mapped['outputs'].append({'identity': identity, **data})
        self.write_json(mapping, mapped)
        item = {'identity': identity, 'mapping': str(mapping), 'receipt': str(receipt)}
        self.plan['items'].append(item)
        target = self.extra.parent / f'06-阶段采用视频/{tool.STAGES[stage]}/C001-场次/{identity}.mp4'
        return item, draft, source, target

    def run_plan(self, apply=True):
        path = self.extra / '执行附件/采用请求.json'
        self.write_json(path, self.plan)
        return tool.adoption(argparse.Namespace(project=str(self.root), plan=str(path), apply=apply))

    def test_shared_units_adopt_each_stage_without_touching_numbered_episode(self):
        numbered_summary = self.summary
        original = numbered_summary.read_bytes()
        for unit in ('片头', '片尾'):
            self.unit = unit
            self.extra = self.root / '09-剧集制作' / unit / '其他资料'
            self.summary = self.extra / '工作稿' / (unit + '-生成说明-工作稿.md')
            self.put(self.summary, '# 生成说明\n- 当前状态：待审核\n')
            for stage in tool.STAGES:
                self.plan = {'approval_text': '本条具体候选通过采用', 'items': [], 'record_updates': [
                    {'path': str(self.summary), 'old': '- 当前状态：待审核', 'new': '- 当前状态：待审核'},
                    {'path': str(self.progress), 'old': '| EP001 | 制作中 |', 'new': '| EP001 | 制作中 |'}]}
                _, draft, source, target = self.item(stage=stage)
                content = source.read_bytes()
                result = self.run_plan()
                self.assertEqual(result['items'][0]['state'], 'adopt')
                self.assertEqual(target.read_bytes(), content)
                self.assertFalse(source.exists())
                self.assertIn('- 决定：批准采用', draft.read_text())
        self.assertEqual(numbered_summary.read_bytes(), original)

    def test_each_stage_and_repeat_do_not_change_revision_or_bytes(self):
        for stage in tool.STAGES:
            with self.subTest(stage=stage):
                self.plan['items'] = []
                item, draft, source, target = self.item(stage=stage)
                content = source.read_bytes()
                result = self.run_plan()
                self.assertEqual(result['items'][0]['state'], 'adopt')
                self.assertFalse(source.exists())
                self.assertEqual(target.read_bytes(), content)
                text = draft.read_text(encoding='utf-8')
                self.assertIn('- 决定：批准采用', text)
                self.assertIn('- 原提交事实：不得改写', text)
                self.assertIn('#审阅-r001-' + stage + '-采用-001', text)
                self.assertTrue(text.index('### 审阅-') < text.index('## 其他补充'))
                snapshot = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                self.assertEqual(self.run_plan()['items'][0]['state'], 'already_adopted')
                self.assertEqual(snapshot, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_backend_state_and_receipt_bind_actual_execution_without_backfilling_inputs(self):
        item, draft, source, target = self.item()
        mapping = Path(item['mapping'])
        mapped = tool.load(mapping)
        output = mapped.pop('outputs')[0]
        prompt = mapped.pop('prompt_id')
        self.write_json(mapping, mapped)
        self.write_json(mapping.parent / '提交响应.json', {'prompt_id': prompt})
        self.write_json(mapping.parent / '后台任务状态.json', {
            'record_dir': str(mapping.parent), 'prompt_id': prompt,
            'remote_url': 'https://example.test',
            'segments': {'0': {**output, 'receipt': item['receipt']}}})
        receipt_path = Path(item['receipt'])
        receipt = tool.load(receipt_path)
        receipt.update(identity=item['identity'], prompt_id='wrong-prompt')
        self.write_json(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, '任务ID或分段身份'):
            self.run_plan()
        self.assertTrue(source.exists())
        receipt['prompt_id'] = prompt
        self.write_json(receipt_path, receipt)
        self.assertEqual(self.run_plan()['items'][0]['state'], 'adopt')
        saved = tool.load(mapping)
        self.assertNotIn('prompt_id', saved)
        self.assertNotIn('outputs', saved)
        self.assertEqual(saved['generation_contexts'], mapped['generation_contexts'])
        self.assertEqual(saved['adoptions'][0]['prompt_id'], prompt)
        self.assertTrue(target.is_file())
        self.assertEqual(self.run_plan()['items'][0]['state'], 'already_adopted')

    def test_backend_postprocess_selector_and_download_receipt_bind_output(self):
        item, draft, source, target = self.item(stage='后处理')
        mapping = Path(item['mapping'])
        mapped = tool.load(mapping)
        output = mapped.pop('outputs')[0]
        prompt = mapped.pop('prompt_id')
        self.write_json(mapping, mapped)
        self.write_json(mapping.parent / '提交响应.json', {'prompt_id': prompt})
        selector = {'node_id': '16', 'output_key': 'gifs', 'index': 0,
                    'path': output['path'], 'response_name': Path(item['receipt']).name}
        self.write_json(mapping.parent / '后台任务状态.json', {
            'record_dir': str(mapping.parent), 'prompt_id': prompt,
            'remote_url': 'https://example.test', 'outputs': [selector]})
        terminal = {'data': {'prompt_id': 'wrong-prompt', 'state': 'success',
            'files': [{'node_id': '16', 'output_key': 'gifs', 'index': 0, 'file': output['remote']}]}}
        self.write_json(mapping.parent / '执行结果.json', terminal)
        with self.assertRaisesRegex(ValueError, '执行结果.*任务ID'):
            self.run_plan()
        terminal['data']['prompt_id'] = prompt
        self.write_json(mapping.parent / '执行结果.json', terminal)
        wrong = tool.load(Path(item['receipt']))
        wrong['data']['remote']['filename'] = 'wrong.mp4'
        self.write_json(Path(item['receipt']), wrong)
        with self.assertRaisesRegex(ValueError, '远端文件'):
            self.run_plan()
        wrong['data']['remote'] = output['remote']
        self.write_json(Path(item['receipt']), wrong)
        self.assertEqual(self.run_plan()['items'][0]['state'], 'adopt')
        self.assertEqual(target.read_bytes(), item['identity'].encode())
        saved = tool.load(mapping)
        self.assertNotIn('prompt_id', saved)
        self.assertNotIn('outputs', saved)
        self.assertEqual(saved['generation_contexts'], mapped['generation_contexts'])
        self.assertEqual(self.run_plan()['items'][0]['state'], 'already_adopted')

    def test_existing_storyboard_summary_adoption_and_repeat(self):
        self.item(stage='后处理')
        existing = self.summary.with_name('EP001-分镜索引-工作稿.md')
        self.summary.rename(existing)
        self.plan['summary'] = str(existing)
        self.plan['record_updates'][0]['path'] = str(existing)
        self.assertEqual(self.run_plan()['items'][0]['state'], 'adopt')
        self.assertIn('本批批准采用', existing.read_text(encoding='utf-8'))
        self.assertFalse(self.summary.exists())
        self.assertEqual(self.run_plan()['items'][0]['state'], 'already_adopted')

    def test_summary_cannot_target_another_episode_or_segment(self):
        self.item()
        for name in ['EP002-分镜索引-工作稿.md', 'EP001-C001-P001-视频制作-工作稿.md']:
            with self.subTest(name=name):
                self.plan['summary'] = str(self.summary.with_name(name))
                with self.assertRaisesRegex(ValueError, 'summary 须为本集'):
                    self.run_plan()

    def test_shared_mapping_partial_approval(self):
        first, draft, source, target = self.item()
        second, _, second_source, second_target = self.item('P002', mapping=Path(first['mapping']))
        self.plan['items'] = [first]
        result = self.run_plan()
        mapped = tool.load(Path(first['mapping']))
        self.assertEqual([x['identity'] for x in mapped['adoptions']], [first['identity']])
        self.assertEqual(mapped['status'], 'success')
        self.assertTrue(second_source.exists())
        self.assertFalse(second_target.exists())
        self.assertEqual(result['selected_approved_counts']['一采'], 1)

    def test_template_scope_unknown_time_and_movement_origin(self):
        item, draft, source, target = self.item()
        item['approval_scope'] = '接受本段现有画面；音频缺陷保留'
        item['review_entry'] = '[网页审核](http://localhost/review)'
        movement = ('#### 位置变化及替代关系\n\n'
                    '| 原位置 | 新位置 | 时间 | 用户决定／移动依据 | 替代关系及需同步的下游入口 |\n'
                    '| --- | --- | --- | --- | --- |\n')
        self.put(draft, draft.read_text(encoding='utf-8').replace('## 4. 审阅区',
                 '- 取回核对状态：未取回\n\n' + movement + '\n## 4. 审阅区'))
        self.run_plan()
        text = draft.read_text(encoding='utf-8')
        self.assertIn('- 批准或要求修改的范围：' + item['approval_scope'], text)
        self.assertIn('实际决定时间未记录；登记时间：', text)
        self.assertIn('| 反馈时间／依据 |', text)
        self.assertIn('- 受影响的分段、场次或整集版本及处理决定：', text)
        self.assertIn('- 其他补充：采用登记时间：', text)
        self.assertIn(item['review_entry'], text)
        self.assertNotIn('- 取回核对状态：未取回', text)
        self.assertEqual(text.count('#### 位置变化及替代关系'), 1)
        self.assertIn('| ' + tool.link(draft, source) + ' | [文件](' + tool.link(draft, target) + ')', text)
        self.assertEqual(tool.load(Path(item['mapping']))['adoptions'][0]['approval_scope'], item['approval_scope'])

    def test_actual_decision_time_is_preserved(self):
        _, draft, _, _ = self.item()
        self.plan['approval_time'] = '2026-10-09T12:10:00+08:00'
        self.run_plan()
        self.assertIn('- 决定时间与依据：2026-10-09T12:10:00+08:00；', draft.read_text(encoding='utf-8'))

    def test_actual_non_mp4_extension_is_preserved(self):
        item, draft, source, target = self.item()
        actual = source.with_suffix('.mov')
        source.rename(actual)
        item['source'] = str(actual)
        result = self.run_plan()
        self.assertTrue(target.with_suffix('.mov').exists())
        self.assertFalse(target.exists())
        self.assertEqual(result['selected_approved_counts']['一采'], 1)
        self.assertIn(actual.name, draft.read_text(encoding='utf-8'))
        self.assertEqual(self.run_plan()['items'][0]['state'], 'already_adopted')

    def test_existing_approval_after_directory_move_only_updates_mapping(self):
        item, draft, _, target = self.item()
        self.run_plan()
        text = draft.read_bytes()
        mapping = Path(item['mapping'])
        mapped = tool.load(mapping)
        recorded = mapped['adoptions'][0]['recorded_at']
        mapped['adoptions'][0]['selected_path'] = str(self.extra / '旧采用目录' / target.name)
        self.write_json(mapping, mapped)
        self.plan['record_updates'] = []
        result = self.run_plan()
        self.assertEqual(result['items'][0]['state'], 'already_adopted')
        self.assertEqual(result['moves'], [])
        self.assertEqual(draft.read_bytes(), text)
        adopted = tool.load(mapping)['adoptions'][0]
        self.assertEqual(adopted['selected_path'], str(target))
        self.assertEqual(adopted['recorded_at'], recorded)

    def local_item(self):
        item, draft, source, target = self.item(revision='R002')
        mapping = Path(item['mapping'])
        mapped = tool.load(mapping)
        origin = 'EP001-C001-P001-R001-一采'
        del mapped['prompt_id']
        mapped['generation_contexts'][0]['source'] = origin
        mapped['local_edit'] = {'tool': 'ffmpeg', 'source': origin,
                                'source_file': '09-剧集制作/EP001/其他资料/候选视频/' + origin + '.mp4',
                                'parameters': ['-an']}
        mapped['output'] = mapped.pop('outputs')[0]
        del mapped['output']['sha256']
        del mapped['output']['remote']
        self.write_json(mapping, mapped)
        item['receipt'] = str(mapping)
        return item, draft, source, target

    def test_local_edit_without_comfy_prompt_or_hash_uses_real_record(self):
        item, draft, source, target = self.local_item()
        self.run_plan()
        self.assertFalse(source.exists())
        self.assertTrue(target.exists())
        text = draft.read_text(encoding='utf-8')
        self.assertIn('[本地修改记录]', text)
        self.assertNotIn('prompt None', text)
        self.assertNotIn('sha256', tool.load(Path(item['mapping']))['output'])
        self.assertEqual(self.run_plan()['items'][0]['state'], 'already_adopted')

    def test_local_edit_mismatched_source_and_output_stop_before_move(self):
        item, _, source, target = self.local_item()
        mapping = Path(item['mapping'])
        mapped = tool.load(mapping)
        mapped['local_edit']['source'] = '错误来源'
        self.write_json(mapping, mapped)
        with self.assertRaisesRegex(ValueError, '来源与生成资料关联'):
            self.run_plan()
        mapped['local_edit']['source'] = mapped['generation_contexts'][0]['source']
        mapped['output']['path'] = str(source.with_name('other.mp4'))
        self.write_json(mapping, mapped)
        with self.assertRaisesRegex(ValueError, '凭据与批准文件'):
            self.run_plan()
        self.assertFalse(target.exists())
        self.assertTrue(source.exists())

    def test_preflight_missing_later_file_leaves_first_untouched(self):
        _, draft, source, target = self.item()
        _, _, second, _ = self.item('P002')
        second.unlink()
        before = draft.read_bytes()
        with self.assertRaisesRegex(ValueError, '文件缺失'):
            self.run_plan()
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())
        self.assertEqual(draft.read_bytes(), before)

    def test_same_length_changed_bytes_cannot_inherit_approval(self):
        _, _, source, target = self.item()
        source.write_bytes(b'x' * source.stat().st_size)
        with self.assertRaisesRegex(ValueError, '字节'):
            self.run_plan()
        self.assertFalse(target.exists())

    def test_dry_run_and_missing_progress_update(self):
        _, draft, source, target = self.item()
        self.plan['record_updates'] = []
        before = draft.read_bytes()
        preview = self.run_plan(False)
        self.assertEqual(len(preview['required_record_updates']), 2)
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())
        self.assertEqual(draft.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, '项目进度'):
            self.run_plan()

    def test_changed_progress_text_fails_before_move(self):
        _, _, source, target = self.item()
        self.put(self.progress, '其他会话已改动')
        with self.assertRaisesRegex(ValueError, '原文已变化'):
            self.run_plan()
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_duplicate_old_record_does_not_pass_because_new_text_exists(self):
        _, _, source, target = self.item()
        update = self.plan['record_updates'][1]
        self.put(self.progress, update['old'] + '\n' + update['old'] + '\n' + update['new'])
        with self.assertRaisesRegex(ValueError, '匹配不唯一'):
            self.run_plan()
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_replace_returns_old_candidate_keeps_approval_history(self):
        _, draft, _, old_target = self.item()
        self.run_plan()
        self.plan['items'] = []
        _, _, source, target = self.item(revision='R002')
        self.run_plan()
        self.assertFalse(old_target.exists())
        self.assertTrue((self.extra / '候选视频' / old_target.name).exists())
        self.assertTrue(target.exists())
        text = draft.read_text(encoding='utf-8')
        self.assertEqual(text.count('- 决定：批准采用'), 2)
        self.assertIn('审阅-R001-一采-采用-001', text)
        self.assertIn('审阅-R002-一采-采用-001', text)

    def test_replace_upstream_with_selected_downstream_requires_disposition(self):
        self.item()
        self.run_plan()
        self.plan['items'] = []
        self.item(stage='二采')
        self.run_plan()
        self.plan['items'] = []
        _, _, source, target = self.item(revision='R002')
        with self.assertRaisesRegex(ValueError, '影响已选定二采'):
            self.run_plan()
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_retry_child_updates_parent_pointer_preserves_unknown_history(self):
        item, _, _, _ = self.item(mapping=self.extra / '执行附件/task/执行-001/输入映射.json')
        parent = self.extra / '执行附件/task/输入映射.json'
        self.write_json(parent, {'prompt_id': 'old-prompt', 'status': 'unknown', 'current_execution': {
            'mapping': item['mapping'], 'prompt_id': 'real-prompt'}})
        item['related_mappings'] = [str(parent)]
        self.run_plan()
        mapped = tool.load(parent)
        self.assertEqual(mapped['status'], 'unknown')
        self.assertEqual(mapped['prompt_id'], 'old-prompt')
        self.assertEqual(mapped['current_execution']['adoption']['identity'], item['identity'])

    def test_boundary_identity_receipt_destination_and_duplicates(self):
        item, _, source, target = self.item()
        for mutation, message in [({'identity': 'EP001-C001-P999-R001-一采'}, '未关联'),
                                  ({'mapping': str(self.root.parent / 'outside.json')}, '越出项目')]:
            with self.subTest(message=message):
                old = item.copy()
                item.update(mutation)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_plan()
                item.clear(); item.update(old)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'conflict')
        with self.assertRaisesRegex(ValueError, '长度'):
            self.run_plan()
        target.unlink()
        self.plan['items'].append(item)
        with self.assertRaisesRegex(ValueError, '重复'):
            self.run_plan()
        self.assertTrue(source.exists())

    def test_legacy_heading_explicitly_selected(self):
        item, draft, _, _ = self.item(stage='后处理')
        text = draft.read_text(encoding='utf-8').replace('### R001-后处理', '### R001后处理故障接续-001')
        self.put(draft, text)
        item['execution_heading'] = 'R001后处理故障接续-001'
        self.run_plan()
        self.assertIn('- 用户决定：见[本阶段人工审核决定]', draft.read_text(encoding='utf-8'))

    def test_existing_approval_punctuation_and_normalized_path_are_idempotent(self):
        item, draft, _, target = self.item()
        self.run_plan()
        self.put(draft, draft.read_text(encoding='utf-8').replace('- 决定：批准采用\n', '- 决定：批准采用。\n'))
        mapping = Path(item['mapping'])
        mapped = tool.load(mapping)
        mapped['adoptions'][0]['selected_path'] = str(target).replace('\\', '\\\\').replace('/工作稿/', '//工作稿//')
        self.write_json(mapping, mapped)
        self.plan['record_updates'] = []
        self.assertEqual(self.run_plan(False)['items'][0]['state'], 'already_adopted')
        self.put(draft, draft.read_text(encoding='utf-8').replace('- 决定：批准采用。', '- 决定：通过并采用P001 R001一采；依据为用户反馈。'))
        self.assertEqual(self.run_plan(False)['items'][0]['state'], 'already_adopted')

    def test_interrupted_record_write_can_finish_without_removing_video(self):
        _, draft, source, target = self.item()
        with patch.object(tool.os, 'replace', side_effect=OSError('simulated disk write error')):
            with self.assertRaisesRegex(OSError, 'disk write'):
                self.run_plan()
        self.assertFalse(source.exists())
        self.assertTrue(target.exists())
        self.run_plan()
        self.assertIn('- 决定：批准采用', draft.read_text(encoding='utf-8'))
        self.assertFalse(list(self.root.rglob('*.tmp')))

    def test_browser_reads_fixed_review_without_duplicate_decision_summary(self):
        parser_path = Path(__file__).resolve().parents[4] / '工作区浏览服务/backend/parsers/project.py'
        if not parser_path.exists():
            self.skipTest('独立技能安装不包含工作区浏览服务')
        sys.path.insert(0, str(parser_path.parents[2]))
        self.addCleanup(lambda: sys.path.remove(str(parser_path.parents[2])))
        portal = importlib.import_module('backend.parsers.project')
        for stage in tool.STAGES:
            self.plan['items'] = []
            self.item(stage=stage)
            self.run_plan()
        episode = self.extra.parent
        self.put(episode / '02-剧集剧本/EP001-本集剧本.md', '# 剧本\n## 1. 故事剧本正文\n### EP001-C001\n办公室。')
        self.put(episode / '03-分镜脚本/EP001-C001-场次分镜.md', '# 分镜\n## 1. 镜头正文\n### EP001-C001-P001\n镜头。')
        self.put(episode / '03-分镜脚本/EP001-分镜索引.md', '# 索引\n| 分段 | 场次 | 分段计划时长（秒） |\n| --- | --- | --- |\n| EP001-C001-P001 | EP001-C001 | 3 |')
        data = portal.build_data(self.root, web_episode_navigation=True)
        videos = data['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos']
        adopted = [v for v in videos if v.get('approved')]
        self.assertEqual({v['stage'] for v in adopted}, set(tool.STAGES))
        self.assertFalse(any('当前选定记录的批准依据' in warning for warning in data['warnings']))


if __name__ == '__main__':
    unittest.main()
