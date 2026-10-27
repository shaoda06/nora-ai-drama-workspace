"""Existing phase-row updates preserve other phases and reject history appends."""
import unittest

import project_progress as progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.original = ('# 项目进度\n'
                         '| EP001制作 | 会话 | 进行中 | 原成果 | - 当前问题 | - 当前动作 |\n'
                         '| EP002制作 | 另一会话 | 待确认 | 另一成果 | - 另一问题 | - 另一动作 |\n')

    def test_only_the_requested_phase_changes_and_items_remain_separate(self):
        updated = progress.update(self.original, 'EP001', status='进行中', outputs='[成果](成果.md)',
                                  pending=['问题甲', '问题乙'], next_steps=['处理甲', '处理乙'])
        progress.validate_update(self.original, updated, {'EP001'})
        self.assertEqual(progress.phase_row(self.original, 'EP002')[0][0],
                         progress.phase_row(updated, 'EP002')[0][0])
        self.assertEqual(progress.phase_row(updated, 'EP001')[1][4:],
                         ['- 问题甲<br>- 问题乙', '- 处理甲<br>- 处理乙'])

    def test_history_or_other_phase_edits_are_rejected(self):
        updated = progress.update(self.original, 'EP001', status='已完成', outputs='成果')
        for text in (updated + '\n### 定稿留档\n历史记录\n',
                     updated.replace('另一问题', '偷偷修改')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, '对应阶段行'):
                progress.validate_update(self.original, text, {'EP001'})

    def test_common_opening_and_ending_use_their_existing_phase_rows(self):
        for unit in ('片头', '片尾'):
            text = '| ' + unit + '制作 | 原会话 | 进行中 | 原成果 | - 无 | - 无 |\n'
            updated = progress.update(text, unit, status='已完成', outputs='当前成果')
            progress.validate_update(text, updated, {unit})
            self.assertEqual(progress.phase_row(updated, unit)[1][4:], ['- 无', '- 无'])

    def test_spaced_phase_labels_preserve_label_and_validation_scope(self):
        original = self.original.replace('EP001制作', 'EP001 制作')
        updated = progress.update(original, 'EP001', status='待确认', outputs='当前结果')
        progress.validate_update(original, updated, {'EP001'})
        self.assertEqual(progress.phase_row(updated, 'EP001')[1][0], 'EP001 制作')
        with self.assertRaisesRegex(ValueError, '对应阶段行'):
            progress.validate_update(original, updated.replace('另一动作', '变化'), {'EP001'})

    def test_spaced_and_unspaced_duplicate_phase_is_ambiguous(self):
        text = self.original + '| EP001 制作 | 会话 | 进行中 | 原成果 | - 无 | - 无 |\n'
        with self.assertRaisesRegex(ValueError, '唯一'):
            progress.update(text, 'EP001', status='待确认', outputs='结果')


if __name__ == '__main__':
    unittest.main()
