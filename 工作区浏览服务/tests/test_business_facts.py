"""Current factual projections preserve approvals, prose and concurrent edits."""
import json
import unittest

from tests import test_round_results as rounds
from backend.services.result_registration import business_updates, apply_record_updates


class BusinessFactsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = rounds.RoundResultsTests.asyncSetUp
    asyncTearDown = rounds.RoundResultsTests.asyncTearDown
    task = rounds.RoundResultsTests.task
    scope = rounds.RoundResultsTests.scope
    complete = rounds.RoundResultsTests.complete

    def fixture(self, counts=(5,)):
        self.scope(counts, retained=10)
        self.complete('0')
        self.progress = self.project / '项目进度.md'
        self.progress.write_text('| EP003制作 | 制作会话 | 检查通过待入队 | 已采用十段 | 保留原批准 | 不自动进入二采 |\n')
        self.draft = self.manifest.with_name('EP003-生成说明-工作稿.md')
        self.draft.write_text('# 生成说明工作稿\n\n- 当前状态及待办：保留已通过十段；本批结果另审。\n\n## 1. 当前内容\n人工创作意见不改。\n\n## 2. 讨论\n历史：准备中，未提交。\n')
        self.formal = self.project / '09-剧集制作/EP003/05-视频提示词/EP003-生成说明.md'
        self.formal.parent.mkdir()
        self.formal.write_text('# 生成说明\n\n- 确认依据：原批准\n\n## 1. 内容\n已确认创作内容不改。\n')
        self.report = {'items': [{'episode': 'EP003'}] * counts[0]}

    def apply(self, updates, outcome):
        report = {'business_sync': outcome}
        apply_record_updates(self.store, '0', updates, {'EP003'}, report)

    async def test_five_returns_one_fact_source_and_no_generic_agent_work(self):
        self.fixture()
        before = self.draft.read_text()
        formal_before = self.formal.read_text()
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.assertFalse(outcome['needs_attention'])
        self.assertEqual(outcome['actions'], [])
        self.apply(updates, outcome)
        self.assertIn('本批已取回5段／本次清单预期5段', self.draft.read_text())
        self.assertIn('当前执行事实入口', self.formal.read_text())
        self.assertNotIn('已取回5段', self.formal.read_text())
        self.assertNotIn('已取回5段', self.progress.read_text())
        self.assertIn('当前执行事实', self.progress.read_text())
        self.assertIn('保留原批准 | 不自动进入二采', self.progress.read_text())
        self.assertEqual(self.draft.read_text().split('## 1.')[1], before.split('## 1.')[1])
        self.assertEqual(self.formal.read_text().split('## 1.')[1], formal_before.split('## 1.')[1])
        content = [p.read_bytes() for p in (self.progress, self.draft, self.formal)]
        repeated, outcome = business_updates(self.store, [('0', self.report)])
        self.assertEqual(len(repeated), 1)  # unchanged progress identity; no repeated document edits
        self.assertEqual(repeated[0]['old'], repeated[0]['new'])
        self.assertEqual(content, [p.read_bytes() for p in (self.progress, self.draft, self.formal)])

    async def test_mixed_todos_return_exact_fields_without_overwriting_or_full_review(self):
        self.fixture()
        self.draft.write_text(self.draft.read_text().replace('保留已通过十段；本批结果另审。', '等待用户反馈；本轮待取回，旧批准保留。'))
        self.progress.write_text(self.progress.read_text().replace('不自动进入二采', '待取回；二采须另授权'))
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.assertTrue(outcome['needs_attention'])
        self.assertEqual({a['field'] for a in outcome['actions']}, {'下一步', '当前状态及待办'})
        self.apply(updates, outcome)
        self.assertIn('等待用户反馈；本轮待取回，旧批准保留。', self.draft.read_text())
        self.assertIn('待取回；二采须另授权', self.progress.read_text())
        self.assertFalse(any(a['path'] == self.formal.relative_to(self.project).as_posix() for a in outcome['actions']))

    async def test_partial_notices_accumulate_current_source_count(self):
        self.fixture((1, 1))
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.apply(updates, outcome)
        self.assertIn('本批已取回1段／本次清单预期2段', self.draft.read_text())
        self.complete('1')
        updates, outcome = business_updates(self.store, [('1', self.report)])
        self.apply(updates, outcome)
        self.assertIn('本批已取回2段／本次清单预期2段', self.draft.read_text())
        self.assertEqual(self.draft.read_text().count('- 当前执行事实：'), 1)

    async def test_late_old_round_and_completed_production_are_preserved(self):
        self.fixture()
        original = [p.read_bytes() for p in (self.progress, self.draft, self.formal)]
        manifest = json.loads(self.manifest.read_text())
        manifest['rounds'].append({**manifest['rounds'][0], 'number': 20})
        self.manifest.write_text(json.dumps(manifest))
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.assertEqual(updates, [])
        self.assertEqual(outcome['status'], 'not_current')
        self.assertEqual(original, [p.read_bytes() for p in (self.progress, self.draft, self.formal)])
        manifest['rounds'].pop()
        self.manifest.write_text(json.dumps(manifest))
        self.progress.write_text(self.progress.read_text().replace('检查通过待入队', '已完成'))
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.assertEqual(updates, [])
        self.assertFalse(outcome['needs_attention'])

    async def test_changed_doc_and_round_between_prepare_apply_stop_without_overwrite(self):
        self.fixture()
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.draft.write_text(self.draft.read_text().replace('人工创作意见不改。', '用户并行修改'))
        original = self.progress.read_bytes()
        with self.assertRaisesRegex(ValueError, '原文不唯一或已变化'):
            self.apply(updates, outcome)
        self.assertEqual(original, self.progress.read_bytes())
        self.assertIn('用户并行修改', self.draft.read_text())
        updates, outcome = business_updates(self.store, [('0', self.report)])
        manifest = json.loads(self.manifest.read_text())
        manifest['rounds'].append({**manifest['rounds'][0], 'number': 20})
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, '当前轮次已改变'):
            self.apply(updates, outcome)
        self.assertEqual(original, self.progress.read_bytes())

    async def test_inconsistent_source_returns_specific_action_and_writes_nothing(self):
        self.fixture()
        self.source['business_scope']['expected_video_count'] = 30
        self.plan.write_text(json.dumps(self.source))
        updates, outcome = business_updates(self.store, [('0', self.report)])
        self.assertEqual(updates, [])
        self.assertEqual(outcome['actions'][0]['field'], '原清单范围')

    async def test_formal_pointer_permission_does_not_allow_rewriting_approved_content(self):
        self.fixture()
        before = self.formal.read_text()
        updates = [dict(path=self.formal.relative_to(self.project).as_posix(), old=before,
                        new=before.replace('已确认创作内容不改。', '错误覆盖。'))]
        with self.assertRaisesRegex(ValueError, '不改创作正文或批准'):
            self.apply(updates, {'entries': []})
        self.assertEqual(self.formal.read_text(), before)


if __name__ == '__main__':
    unittest.main()
