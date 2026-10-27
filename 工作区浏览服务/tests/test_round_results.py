"""Original submission scopes in temporary projects; no renderer, network or real tasks."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from backend.services import comfy_tasks as t
from backend.services.round_results import submission_result, round_results
from tests import test_notification_handoffs as handoffs


class RoundResultsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = handoffs.NotificationHandoffTests.asyncSetUp
    asyncTearDown = handoffs.NotificationHandoffTests.asyncTearDown
    task = handoffs.NotificationHandoffTests.task
    notice = handoffs.NotificationHandoffTests.notice
    reports = handoffs.NotificationHandoffTests.reports

    def scope(self, counts=(1,) * 12, retained=0):
        self.plan = self.project / '执行附件/整轮/任务清单.json'
        self.plan.parent.mkdir(parents=True)
        specs, prepared, scenes = [], [], {}
        for i, count in enumerate(counts):
            key = str(i)
            data = self.task(key, status='running', kind='video-first-pass')
            data.submission_plan = str(self.plan)
            scene = f'C{i // 3 + 1:03d}' if len(counts) == 12 else 'C001'
            segments = [dict(segment=f'EP003-{scene}-P{i * 5 + n + 1:03d}', round='R001') for n in range(count)]
            mapping = dict(scene='EP003-' + scene, scene_modification_round=19,
                           segments=segments, selected_indices=list(range(count)))
            (Path(data.record_dir) / '输入映射.json').write_text(json.dumps(mapping))
            scenes.setdefault(scene, {'segments': []})['segments'].extend(
                dict(id=s['segment'].split('-')[2], run='R001', stage='一采') for s in segments)
            specs.append(dict(task_type=data.task_type, record_dir=Path(data.record_dir).relative_to(self.project).as_posix()))
            prepared.append(dict(task_type=data.task_type, record_dir=data.record_dir))
            self.store.save(key)
        for i in range(retained):
            scenes['C001']['segments'].append(dict(id=f'P{900+i}', run='R002', stage='一采'))
        self.manifest = self.project / '09-剧集制作/EP003/其他资料/工作稿/EP003-修改轮次.json'
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(json.dumps({'rounds': [{'number': 19, 'scenes': scenes}]}))
        self.source = dict(business_scope=dict(episode='EP003', episode_round=19, expected_video_count=sum(counts)), tasks=specs)
        self.plan.write_text(json.dumps(self.source))
        self.journal = self.plan.with_name('任务清单-装配结果.json')
        self.journal.write_text(json.dumps(dict(source=self.source, tasks=prepared, thread_id='isolated-thread', accepted=[])))

    def complete(self, key, *, browser=True):
        row = self.store.rows[key]
        mapping = json.loads((Path(row['input'].record_dir) / '输入映射.json').read_text())
        outputs = [dict(identity=s['segment'] + '-R001-一采', path='候选/' + s['segment'] + '.mp4',
                        draft='工作稿/' + s['segment'] + '.md', receipt='凭据.json', bytes=10)
                   for s in mapping['segments']]
        self.store.save(key, status='completed', collected=len(outputs), expected=len(outputs), result_items=outputs,
                        closeout=dict(status='completed' if browser else 'browser_pending', video_outputs=outputs))

    async def test_twelve_segments_four_scenes_partial_notifications_and_restart(self):
        self.scope()
        self.complete('0')
        await self.notice('0')
        batch, _ = self.reports()[0]
        first = self.store.read_report(batch, 'isolated-thread')
        scope = first['rounds'][0]
        self.assertEqual((scope['expected_tasks'], scope['expected_video_count'], scope['completed_video_count']), (12, 12, 1))
        self.assertFalse(scope['review_ready'])
        self.assertEqual(len(scope['missing_identities']), 11)
        for i in range(1, 12):
            self.complete(str(i))
        latest = self.store.read_report(batch, 'isolated-thread')
        self.assertEqual(latest['rounds'][0]['completed_video_count'], 12)
        self.assertEqual(latest['rounds'][0]['delivery']['video_count'], 12)
        self.assertTrue(latest['rounds'][0]['review_ready'])
        self.assertTrue(latest['rounds'][0]['received'])
        self.assertIsNone(latest['rounds'][0]['delivered_to_user'])
        self.assertEqual(set(latest['new_task_ids']), {str(i) for i in range(1, 12)})
        changes = self.store.db.total_changes
        self.assertFalse(self.store.read_report(batch, 'isolated-thread')['should_notify_user'])
        self.assertEqual(self.store.db.total_changes, changes)
        await self.store.close()
        self.store = t.TaskStore(self.root / 'runtime', self.root)
        self.assertFalse(self.store.read_report(batch, 'isolated-thread')['should_notify_user'])
        sender = AsyncMock()
        await self.notice('11', sender)
        sender.assert_not_awaited()

    async def test_five_segments_one_task_excludes_retained_ten(self):
        self.scope((5,), retained=10)
        self.complete('0')
        scope = submission_result(self.store, '0')
        self.assertEqual((scope['expected_tasks'], scope['expected_video_count']), (1, 5))
        self.assertEqual(len(scope['retained_identities']), 10)
        self.assertEqual(scope['completed_video_count'], 5)

    async def test_partial_submission_failure_cancel_stop_and_unknown(self):
        self.scope((1,) * 5)
        self.complete('0')
        self.store.save('1', status='failed', error='generation failed')
        self.store.save('2', status='cancelled')
        self.store.save('3', status='resolved')
        missing = self.store.rows.pop('4')
        scope = submission_result(self.store, '0')
        self.assertFalse(scope['terminal'])
        self.assertEqual(scope['registered_tasks'], 4)
        self.assertEqual(scope['tasks'][4]['status'], 'not_submitted')
        self.assertEqual(scope['failed_tasks'], ['1'])
        self.assertEqual(scope['cancelled_tasks'], ['2'])
        self.assertEqual(scope['stopped_tasks'], ['3'])
        self.store.rows['4'] = missing
        self.store.save('4', status='submission_unknown')
        self.assertFalse(submission_result(self.store, '0')['terminal'])
        self.store.save('4', status='cancelled')
        scope = submission_result(self.store, '0')
        self.assertEqual(scope['status'], 'terminal_partial')
        self.assertFalse(scope['review_ready'])

    async def test_browser_pending_and_collection_retry_are_not_ready(self):
        self.scope((1, 1))
        self.complete('0', browser=False)
        self.store.save('1', status='collection_failed', error='retry pending')
        scope = submission_result(self.store, '0')
        self.assertEqual(scope['collected_video_count'], 1)
        self.assertEqual(scope['completed_video_count'], 0)
        self.assertFalse(scope['terminal'])
        self.complete('0')
        self.complete('1')
        self.assertTrue(submission_result(self.store, '0')['review_ready'])

    async def test_old_round_remains_its_own_scope_and_other_thread_does_not_join(self):
        self.scope((1,))
        self.complete('0')
        manifest = json.loads(self.manifest.read_text())
        manifest['rounds'].append({**manifest['rounds'][0], 'number': 20})
        self.manifest.write_text(json.dumps(manifest))
        self.task('other', kind='video-first-pass')
        result = submission_result(self.store, '0')
        self.assertFalse(result['current_round'])
        self.assertEqual(result['expected_tasks'], 1)
        self.assertEqual(result['tasks'][0]['task_id'], '0')

    async def test_missing_or_changed_source_is_explicit_and_read_only(self):
        self.scope((1,))
        self.source['business_scope']['expected_video_count'] = 2
        self.plan.write_text(json.dumps(self.source))
        before = self.plan.read_bytes()
        result = round_results(self.store, ['0'])[0]
        self.assertEqual(result['status'], 'needs_attention')
        self.assertIn('不一致', result['reason'])
        self.assertFalse(result['review_ready'])
        self.assertEqual(self.plan.read_bytes(), before)
        self.plan.unlink()
        self.assertEqual(round_results(self.store, ['0'])[0]['status'], 'needs_attention')

    async def test_duplicate_identity_cannot_complete_a_round(self):
        self.scope((1, 1))
        first = Path(self.store.rows['0']['input'].record_dir) / '输入映射.json'
        second = Path(self.store.rows['1']['input'].record_dir) / '输入映射.json'
        second.write_bytes(first.read_bytes())
        self.assertIn('重复', round_results(self.store, ['0'])[0]['reason'])


if __name__ == '__main__':
    unittest.main()
