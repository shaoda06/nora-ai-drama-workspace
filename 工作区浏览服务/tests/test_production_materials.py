"""Episode image status comes from bound review records, not file location."""
import unittest
from backend.parsers.production_materials import material_review_states


SOURCE = '09-剧集制作/EP001/其他资料/工作稿/EP001-专用素材制作-工作稿.md'
BASE = '09-剧集制作/EP001/'


class MaterialReviewTests(unittest.TestCase):
    def setUp(self):
        self.record = '''## 1. 当前正式资产
| 正式文件 | 采用候选版本 | 审阅记录 |
| --- | --- | --- |
| [正式](../../04-专用素材/图.png) | v02 | [批准](#审阅-生成记录-001-001) |
## 2. 逐次生成记录
### 生成记录-001
- 候选文件入口：[候选](素材/图-候选-v02.png)
- 超分输出文件及实际规格：[超分](素材/图-候选-v02-超分-001.png)
## 4. 审阅
### 审阅-生成记录-001-001
- 具体候选文件及版本：[候选](素材/图-候选-v02.png)
#### 4. 用户确认
- 决定：批准采用
- 对应具体候选：[候选](素材/图-候选-v02.png)
#### 5. 采用与后续影响
- 当前制作适用性：适用；本场使用
- 留存用途：正式参考
'''
        self.paths = ['04-专用素材/图.png', '其他资料/工作稿/素材/图-候选-v02.png', '其他资料/工作稿/素材/图-候选-v02-超分-001.png', '04-专用素材/未登记.png']

    def parse(self, record=None):
        return material_review_states([dict(kind='image', key=BASE + path, name=path.split('/')[-1]) for path in self.paths], self.record if record is None else record, SOURCE)

    def test_approval_and_processed_sources(self):
        items = self.parse()
        self.assertEqual([item['materialGroup'] for item in items], ['adopted', 'history', 'history', 'unknown'])
        self.assertEqual(items[2]['materialReview']['key'], SOURCE + '#审阅-生成记录-001-001')

    def test_old_approval_is_retained_but_not_current(self):
        items = self.parse(self.record.replace('适用；本场使用', '不适用；新版改为小角'))
        self.assertEqual([x['materialGroup'] for x in items[:3]], ['history'] * 3)
        self.assertIn('批准采用', items[0]['approvalHtml'])

    def test_pending_revision_and_rejection_are_distinct(self):
        for decision, group in [('待确认', 'pending'), ('修改后再审', 'revision'), ('不采用', 'history')]:
            with self.subTest(decision=decision):
                items = self.parse(self.record.replace('决定：批准采用', '决定：' + decision))
                self.assertEqual(items[1]['materialGroup'], group)

    def test_wrong_candidate_version_does_not_approve_formal(self):
        items = self.parse(self.record.replace('| v02 |', '| v01 |'))
        self.assertEqual(items[0]['materialGroup'], 'unknown')
        self.assertEqual(items[1]['materialGroup'], 'history')

    def test_unrelated_review_does_not_approve_or_bind_processing(self):
        text = self.record.replace('对应具体候选：[候选](素材/图-候选-v02.png)', '对应具体候选：[别图](素材/别图-候选-v02.png)')
        self.assertEqual([x['materialGroup'] for x in self.parse(text)], ['unknown'] * 4)

    def test_missing_applicability_and_prompt_fields_are_not_approval(self):
        items = self.parse(self.record.replace('当前制作适用性：适用；本场使用', '当前制作适用性：待核对；版本变化'))
        self.assertEqual(items[0]['materialGroup'], 'unknown')
        self.assertEqual(self.parse('```markdown\n' + self.record + '```')[0]['materialGroup'], 'unknown')

    def test_closed_candidate_keeps_historical_pending_review(self):
        text = self.record.replace('决定：批准采用', '决定：待确认').replace(
            '### 生成记录-001\n',
            '### 生成记录-001\n- 用户决定及具体候选、批准依据：已结束未采用；最终方案已选定，原意见保留\n')
        items = self.parse(text)
        self.assertEqual([x['materialGroup'] for x in items[:3]], ['history'] * 3)
        self.assertEqual(items[1]['materialStatus'], '已结束未采用')
        self.assertIn('待确认', items[1]['approvalHtml'])

    def test_replaced_candidate_retains_original_approval(self):
        text = self.record.replace('### 生成记录-001\n',
            '### 生成记录-001\n- 用户决定及具体候选、批准依据：已被替换／归档；改用新版\n')
        items = self.parse(text)
        self.assertEqual(items[1]['materialGroup'], 'history')
        self.assertEqual(items[1]['materialStatus'], '已被替换／归档')
        self.assertIn('批准采用', items[1]['approvalHtml'])

    def test_closing_one_generation_does_not_close_another_candidate(self):
        text = self.record.replace('决定：批准采用', '决定：待确认').replace(
            '### 生成记录-001\n',
            '### 生成记录-001\n- 用户决定及具体候选、批准依据：已结束未采用；不再比较\n')
        text += '''
### 生成记录-002
- 候选文件入口：[另一候选](素材/另一图-候选-v01.png)
### 审阅-生成记录-002-001
- 对应具体候选：[另一候选](素材/另一图-候选-v01.png)
- 决定：待确认
- 当前制作适用性：待核对
'''
        files = [dict(key=BASE + '其他资料/工作稿/素材/' + name)
                 for name in ['图-候选-v02.png', '另一图-候选-v01.png']]
        items = material_review_states(files, text, SOURCE)
        self.assertEqual([x['materialGroup'] for x in items], ['history', 'pending'])
