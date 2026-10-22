import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import sync_current_documents as sync


class SyncCurrentDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.draft = self.project / '其他资料/工作稿/提示词.md'
        self.target = self.project / '05-视频提示词/提示词.md'
        self.draft.parent.mkdir(parents=True)
        self.target.parent.mkdir(parents=True)
        self.archive = '其他资料/历史版本/同步-001'
        self.plan = [{'draft': '其他资料/工作稿/提示词.md', 'target': '05-视频提示词/提示词.md'}]

    def write_draft(self, body):
        self.draft.write_bytes(('# 工作稿\n\n## 1. 当前内容\n\n' + body + '\n## 2. 讨论与修改\n旧讨论\n').encode('utf-8'))

    def test_publish_nested_sections_preserves_payload_and_review_links(self):
        self.write_draft('### 正文\n- 确认状态：待审核\n#### 2. 正文第二节\n'
                         '[图](../../图片/参考.png) [本镜](#镜头一) [审批](#审阅-001)\n'
                         '##### 镜头一\n```text\n## 2. 这不是讨论区\n### 模型原文\n[模型文字](原样)\n```')
        before = b'old formal\r\n'
        self.target.write_bytes(before)
        result = sync.sync_documents(self.project, self.plan, self.archive)
        content = self.target.read_text(encoding='utf-8')
        self.assertIn('## 2. 正文第二节', content)
        self.assertIn('## 2. 这不是讨论区\n### 模型原文\n[模型文字](原样)', content)
        self.assertIn('[图](../图片/参考.png)', content)
        self.assertIn('[本镜](#镜头一)', content)
        self.assertIn('[审批](../其他资料/工作稿/提示词.md#审阅-001)', content)
        self.assertIn('确认状态：待审核', content)
        self.assertNotIn('旧讨论', content)
        self.assertEqual((self.project / result['archives'][0]).read_bytes(), before)
        self.assertNotIn(b'\r', self.target.read_bytes())

    def test_crlf_and_tilde_fences_preserve_model_content(self):
        self.draft.write_bytes('## 1. 当前内容\r\n### 提示词\r\n~~~text\r\n## 2. 保留\r\n<a>中文</a>\r\n~~~\r\n## 2. 讨论\r\n不发布'.encode('utf-8'))
        sync.sync_documents(self.project, self.plan, self.archive)
        self.assertEqual(self.target.read_bytes().decode('utf-8'), '# 提示词\n~~~text\n## 2. 保留\n<a>中文</a>\n~~~\n')

    def test_repeat_leaves_mtime_and_archives_unchanged(self):
        self.write_draft('### 标题\n当前正文')
        sync.sync_documents(self.project, self.plan, self.archive)
        before = self.target.stat().st_mtime_ns
        again = sync.sync_documents(self.project, self.plan, self.archive)
        self.assertEqual(again['written'], [])
        self.assertEqual(again['archives'], [])
        self.assertEqual(self.target.stat().st_mtime_ns, before)

    def test_preflight_failure_does_not_partially_publish(self):
        self.write_draft('### 当前\n新正文')
        self.target.write_bytes(b'keep')
        other = self.project / '其他资料/工作稿/坏稿.md'
        other.write_text('没有当前章节', encoding='utf-8')
        plan = self.plan + [{'draft': str(other), 'target': '05-视频提示词/另一个.md'}]
        with self.assertRaisesRegex(ValueError, '当前内容'):
            sync.sync_documents(self.project, plan, self.archive)
        self.assertEqual(self.target.read_bytes(), b'keep')
        self.assertFalse((self.project / self.archive).exists())

    def test_unclosed_fence_does_not_publish_truncated_content(self):
        self.write_draft('### 正文\n```text\n## 2. 仍是代码，尚未闭合')
        with self.assertRaisesRegex(ValueError, '围栏未闭合'):
            sync.sync_documents(self.project, self.plan, self.archive)
        self.assertFalse(self.target.exists())

    def test_existing_archive_cannot_be_overwritten(self):
        self.write_draft('### 新正文')
        self.target.write_bytes(b'old')
        backup = self.project / self.archive / self.plan[0]['target']
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b'history')
        with self.assertRaisesRegex(ValueError, '归档位置已占用'):
            sync.sync_documents(self.project, self.plan, self.archive)
        self.assertEqual(backup.read_bytes(), b'history')
        self.assertEqual(self.target.read_bytes(), b'old')

    def test_duplicate_sources_are_read_once_and_writes_are_explicit(self):
        self.write_draft('### 标题\n内容')
        plan = self.plan + [{'draft': self.plan[0]['draft'], 'target': '05-视频提示词/第二份.md'}]
        reads = []
        original = Path.read_bytes
        def read(path):
            reads.append(path)
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            result = sync.sync_documents(self.project, plan, self.archive)
        self.assertEqual(reads.count(self.draft.resolve()), 1)
        self.assertEqual(len(result['written']), 2)

    def test_outside_path_and_duplicate_targets_are_rejected(self):
        self.write_draft('### 正文')
        with self.assertRaisesRegex(ValueError, '目标重复'):
            sync.sync_documents(self.project, self.plan * 2, self.archive)
        with self.assertRaisesRegex(ValueError, '越出项目'):
            sync.sync_documents(self.project, [{'draft': self.plan[0]['draft'], 'target': '../outside.md'}], self.archive)
        self.assertFalse(self.target.exists())

    def test_cli_uses_project_relative_plan_paths(self):
        self.write_draft('### 正文\n资料内容')
        planfile = self.project / 'plan.json'
        planfile.write_text(json.dumps(self.plan), encoding='utf-8')
        run = subprocess.run([sys.executable, '-X', 'utf8', str(Path(sync.__file__)), '--project', str(self.project),
                              '--plan', str(planfile), '--archive-dir', self.archive],
                             capture_output=True, text=True, encoding='utf-8', check=True)
        self.assertTrue(json.loads(run.stdout)['ok'])
        self.assertEqual(self.target.read_text(encoding='utf-8'), '# 正文\n资料内容\n')

    def storyboard_plan(self, segment='EP002-C001-P001', scene='EP002-C001'):
        base = '09-剧集制作/EP002'
        script = self.project / base / '02-剧集剧本/EP002-本集剧本.md'
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('# EP002\n\n## 1. 故事剧本正文\n\n### EP002-C001\n对白\n', encoding='utf-8')
        draft = self.project / base / '其他资料/工作稿/EP002-分镜索引-工作稿.md'
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text('## 1. 当前内容\n\n### EP002-分镜索引\n\n'
                         '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                         f'| {scene} | {segment} | 14 |\n', encoding='utf-8')
        target = self.project / base / '03-分镜脚本/EP002-分镜索引.md'
        return script, draft, target, [{'draft': str(draft), 'target': str(target)}]

    def test_invalid_index_blocks_entire_batch_before_any_write(self):
        self.write_draft('### 提示词\n新正文')
        self.target.write_bytes(b'keep formal')
        for segment, scene in [('P001', 'EP002-C001'),
                               ('EP001-C001-P001', 'EP002-C001'),
                               ('EP002-C002-P001', 'EP002-C001'),
                               ('EP002-C002-P001', 'EP002-C002')]:
            with self.subTest(segment=segment, scene=scene):
                _, _, target, plan = self.storyboard_plan(segment, scene)
                with self.assertRaisesRegex(ValueError, 'EP002-分镜索引.md.*分段'):
                    sync.sync_documents(self.project, self.plan + plan, self.archive)
                self.assertEqual(self.target.read_bytes(), b'keep formal')
                self.assertFalse(target.exists())
                self.assertFalse((self.project / self.archive).exists())

    def test_index_checks_use_same_batch_script_instead_of_old_formal(self):
        script, draft, target, plan = self.storyboard_plan()
        script.write_text('## 1. 故事剧本正文\n### EP002-C009\n旧场次\n', encoding='utf-8')
        script_draft = draft.with_name('EP002-本集剧本-工作稿.md')
        script_draft.write_text('## 1. 当前内容\n### EP002\n#### 1. 故事剧本正文\n'
                                '##### EP002-C001\n新场次\n', encoding='utf-8')
        result = sync.sync_documents(self.project, plan + [{'draft': str(script_draft), 'target': str(script)}], self.archive)
        self.assertIn('EP002-C001-P001', target.read_text(encoding='utf-8'))
        self.assertEqual(len(result['written']), 2)

    def test_storyboard_only_publish_checks_existing_formal_index(self):
        _, draft, target, _ = self.storyboard_plan('P001')
        target.parent.mkdir(parents=True)
        target.write_text(''.join(draft.read_text(encoding='utf-8').splitlines(keepends=True)[2:]), encoding='utf-8')
        scene_draft = draft.with_name('EP002-C001-场次分镜-工作稿.md')
        scene_draft.write_text('## 1. 当前内容\n### 场次分镜\n镜头\n', encoding='utf-8')
        scene_target = target.with_name('EP002-C001-场次分镜.md')
        plan = [{'draft': str(scene_draft), 'target': str(scene_target)}]
        with self.assertRaisesRegex(ValueError, '分段'):
            sync.sync_documents(self.project, plan, self.archive)
        self.assertFalse(scene_target.exists())

    def test_empty_index_and_missing_script_scenes_are_rejected(self):
        script, draft, target, plan = self.storyboard_plan()
        script.write_text('# 没有场次正文\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'EP002-本集剧本.md.*场次'):
            sync.sync_documents(self.project, plan, self.archive)
        script.write_text('## 1. 故事剧本正文\n### EP002-C001\n对白\n', encoding='utf-8')
        draft.write_text('## 1. 当前内容\n### EP002-分镜索引\n尚无分段\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'EP002-分镜索引.md.*分段表'):
            sync.sync_documents(self.project, plan, self.archive)
        self.assertFalse(target.exists())


    def test_shared_design_and_index_publish_together(self):
        for name in ('片头', '片尾'):
            base = self.project / '09-剧集制作' / name
            work = base / '其他资料/工作稿'
            work.mkdir(parents=True)
            script_draft = work / (name + '-本集剧本-工作稿.md')
            script_draft.write_text(f'## 1. 当前内容\n### {name}内容稿\n#### 3. 动画内容\n##### {name}-C001\n飞机飞走。\n', encoding='utf-8')
            index_draft = work / (name + '-分镜索引-工作稿.md')
            index_draft.write_text('## 1. 当前内容\n### 分镜索引\n| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                                   f'| {name}-C001 | {name}-C001-P001 | 3 |\n', encoding='utf-8')
            script_target = base / '02-剧集剧本' / (name + '-本集剧本.md')
            index_target = base / '03-分镜脚本' / (name + '-分镜索引.md')
            result = sync.sync_documents(self.project, [{'draft': str(script_draft), 'target': str(script_target)},
                {'draft': str(index_draft), 'target': str(index_target)}], self.archive)
            self.assertEqual(len(result['written']), 2)
            self.assertIn('## 3. 动画内容', script_target.read_text(encoding='utf-8'))
            self.assertIn(name + '-C001-P001 | 3', index_target.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
