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


if __name__ == '__main__':
    unittest.main()
