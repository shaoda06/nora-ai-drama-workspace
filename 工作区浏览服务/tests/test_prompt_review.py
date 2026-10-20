"""Content checks block faulty/stale preparation before any remote operation."""
import copy
import json
import unittest
from unittest.mock import patch

from backend.services import comfy_tasks as tasks, execution_checks as checks
from tests import test_submission_lifecycle as lifecycle
from tests.prompt_review_fixture import ENGLISH, CHINESE
from h3_prompt_checks import audit, text_findings, group_mode, bind_review

FL_ENGLISH = '''How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 4.46-second mark of the target video.

integrated_multimodal_description: [Shot 1] The woman extends her raised leg once and reaches the contact pose. No subtitles appear throughout the entire video.

overall_soundscape: Wind and one impact.

non_diegetic_music: N/A'''
FL_CHINESE = '''参考图对应——图片1（镜头1）对应0.00秒；图片2（镜头1）对应4.46秒。

integrated_multimodal_description: [Shot 1] 女子抬起的腿向前伸出一次，落到接触姿势。全片没有字幕。

overall_soundscape: 风声和一次命中声。

non_diegetic_music: N/A'''


class TextChecks(unittest.TestCase):
    def test_fl2v_uses_base_sections_and_checks_the_supplied_pair(self):
        self.assertEqual(text_findings(FL_ENGLISH, FL_CHINESE, {}, mode='fl2v', images={0, 1}, duration=4.46), [])
        for slots in ({0}, {1}, set(), {0, 1, 2}):
            with self.subTest(slots=slots):
                self.assertIn('keyframe_alignment', [x['code'] for x in text_findings(FL_ENGLISH, mode='fl2v', images=slots)])

    def test_3d_style_matches_chinese_dimensions_without_changing_real_numbers(self):
        english = FL_ENGLISH.replace('The woman extends', 'Refined 3D rendering. The woman extends')
        chinese = FL_CHINESE.replace('女子抬起', '精致三维渲染。女子抬起')
        self.assertEqual(text_findings(english, chinese, mode='fl2v'), [])

    def test_wrong_mode_wrong_end_time_and_translation_still_fail(self):
        self.assertIn('sections', [x['code'] for x in text_findings(FL_ENGLISH, mode='r2v')])
        self.assertIn('keyframe_timing', [x['code'] for x in text_findings(FL_ENGLISH, mode='fl2v', duration=5)])
        self.assertIn('translation_numbers', [x['code'] for x in text_findings(
            FL_ENGLISH, FL_CHINESE.replace('4.46', '4.47'), mode='fl2v')])
        self.assertIn('translation_tags', [x['code'] for x in text_findings(
            FL_ENGLISH, FL_CHINESE.replace('[Shot 1]', '[Shot 2]'), mode='fl2v')])

    def test_base_modes_do_not_borrow_ref2va_subject_requirements(self):
        base = FL_ENGLISH[FL_ENGLISH.index('integrated_multimodal_description:'):]
        self.assertEqual(text_findings(base, mode='t2v'), [])
        first = 'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n' + base
        self.assertEqual(text_findings(first, mode='i2v', images={0}), [])
        self.assertIn('keyframe_alignment', [x['code'] for x in text_findings(first, mode='i2v', images=set())])
        last = 'How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 4.46-second mark of the target video.\n\n' + base
        self.assertEqual(text_findings(last, mode='fl2v', images={1}, duration=4.46), [])

    def test_per_segment_mode_overrides_director_in_a_mixed_canvas(self):
        timeline = {'global': {'taskType': 'r2v'}, 'segments': [{'taskType': 'fl2v — 首尾帧'}, {'taskType': 'r2v'}]}
        workflow = {'502': {'inputs': {'task_type': 'r2v', 'timeline_data': json.dumps(timeline)}}}
        self.assertEqual(group_mode(workflow, '502', 0)[0], 'fl2v')
        self.assertEqual(group_mode(workflow, '502', 1)[0], 'r2v')
        timeline['segments'][0]['taskType'] = 'not-a-mode'
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        with self.assertRaisesRegex(ValueError, '无法识别'):
            group_mode(workflow, '502', 0)

    def test_numeric_style_and_chinese_adjacency_use_the_same_tokens(self):
        english = ENGLISH.replace('detailed_description:', 'detailed_description:\nUse 3D animation for 0.7 seconds.')
        chinese = CHINESE.replace('detailed_description:', 'detailed_description:\n采用3D动画，保持0.7秒。')
        self.assertEqual(text_findings(english, chinese), [])
        codes = {x['code'] for x in text_findings(english, chinese.replace('0.7秒', '0.8秒'))}
        self.assertIn('translation_numbers', codes)

    def test_specific_english_faults_are_blocked_not_just_bad_translation(self):
        broken = ENGLISH.replace('<Subject 1>陈甲', '<Subject 1> is Chen Jia', 1)
        broken = broken.replace('stands screen right', 'stands screen right. The man moves')
        broken = broken.replace('No subtitles or title cards appear throughout the entire video.', '')
        codes = {x['code'] for x in text_findings(broken, CHINESE)}
        self.assertTrue({'subject_name', 'subject_reference', 'role_alias', 'subtitle_rule'} <= codes)

    def test_summary_translation_fails_even_when_english_is_valid(self):
        self.assertEqual(text_findings(ENGLISH, CHINESE, {'1': '陈甲'}), [])
        codes = {x['code'] for x in text_findings(ENGLISH, CHINESE.replace('<Subject 1>陈甲', '陈甲'))}
        self.assertIn('translation_tags', codes)

    def test_three_quarter_view_is_not_itself_a_forbidden_word(self):
        self.assertFalse(text_findings(ENGLISH.replace('stands screen right', 'appears in three-quarter view'), CHINESE))

    def test_partial_subtitle_ban_cannot_borrow_full_duration_from_another_sentence(self):
        text = ENGLISH.replace('No subtitles or title cards appear throughout the entire video.',
                               'Keep the face consistent throughout the entire video. No subtitles in the first second.')
        self.assertIn('subtitle_rule', [x['code'] for x in text_findings(text)])

    def test_dialogue_role_words_are_not_treated_as_action_aliases(self):
        self.assertFalse(text_findings(ENGLISH.replace(
            'stands screen right', 'says <d>The man outside is my uncle.</d> and stands screen right')))


# Define a separate class so unittest does not rerun inherited lifecycle tests.
class ContentPreparationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = lifecycle.LifecycleTests.asyncSetUp
    asyncTearDown = lifecycle.LifecycleTests.asyncTearDown
    video = lifecycle.LifecycleTests.video
    node = lifecycle.LifecycleTests.node

    def mapping(self):
        return json.loads((self.record / '输入映射.json').read_text('utf-8'))

    def save_mapping(self, mapping):
        (self.record / '输入映射.json').write_text(json.dumps(mapping, ensure_ascii=False), 'utf-8')

    async def test_fl2v_review_accepts_no_subjects_and_rejects_missing_end_frame(self):
        self.video()
        workflow, mapping = copy.deepcopy(self.data.workflow), self.mapping()
        timeline = json.loads(workflow['502']['inputs']['timeline_data'])
        timeline['global'].update(commonEnabled=False)
        timeline['segments'][0].update(taskType='fl2v', prompt=FL_ENGLISH, durationSec=4.46,
            refs=[{'index': 0, 'imageFile': 'start.png'}, {'index': 1, 'imageFile': 'end.png'}])
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        review = mapping['content_review']['groups'][0]
        (self.project / review['chinese']['file']).write_text(FL_CHINESE)
        review.pop('input_sha256'); review['chinese'].pop('sha256'); review['subjects'] = {}
        for check in review['checks'].values():
            check['prompt_quote'] = 'The woman extends her raised leg once'
            check['chinese_quote'] = '女子抬起的腿向前伸出一次'
            for source in check['sources']:
                source.pop('sha256')
        mapping['content_review'] = bind_review(self.project, workflow, {'groups': [review]})
        self.assertTrue(audit(self.project, workflow, mapping)['ok'])
        timeline['segments'][0]['refs'].pop()
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        issues = audit(self.project, workflow, mapping)['groups'][0]['issues']
        self.assertIn('keyframe_alignment', [x['code'] for x in issues])

    async def test_missing_review_and_failed_claim_stop_without_queue_or_network(self):
        self.video()
        mapping = self.mapping()
        mapping['content_review'] = '已检查通过'
        self.save_mapping(mapping)
        with patch.object(tasks.client, 'upload') as upload, patch.object(tasks.client, 'submit') as submit:
            with self.assertRaisesRegex(ValueError, 'review_missing'):
                await self.store.prepare_only(self.data)
        upload.assert_not_called(); submit.assert_not_called()
        self.assertFalse(self.store.rows)
        self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_valid_review_prepares_and_reuses_then_chinese_change_blocks(self):
        self.video()
        await self.store.prepare_only(self.data)
        self.assertTrue(checks.read_report(self.data)['content_checks']['ok'])
        with patch('h3_prompt_checks.audit', side_effect=AssertionError('unchanged review is reused')):
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])
        chinese = self.record / 'review-document.md'
        chinese.write_text(chinese.read_text('utf-8').replace('画面右侧', '画面左侧'), 'utf-8')
        with self.assertRaisesRegex(ValueError, '准备资料已变化'):
            checks.check_prepared(self.store, self.data)
        with self.assertRaisesRegex(ValueError, 'translation_stale'):
            await self.store.prepare_only(self.data)

    async def test_changed_prompt_or_reference_invalidates_review(self):
        self.video()
        mapping = self.mapping()
        for field, value in [('prompt', ENGLISH.replace('screen right', 'screen left')), ('durationSec', 4)]:
            workflow = copy.deepcopy(self.data.workflow)
            timeline = json.loads(workflow['502']['inputs']['timeline_data'])
            timeline['segments'][0][field] = value
            workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
            report = audit(self.project, workflow, mapping)
            self.assertIn('review_stale', [i['code'] for i in report['groups'][0]['issues']])
        workflow = copy.deepcopy(self.data.workflow)
        timeline = json.loads(workflow['502']['inputs']['timeline_data'])
        timeline['global']['refs'][0]['imageFile'] = 'different.png'
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        self.assertIn('review_stale', [i['code'] for i in audit(self.project, workflow, mapping)['groups'][0]['issues']])

    async def test_common_text_and_selected_scope_are_checked(self):
        self.video()
        workflow, mapping = copy.deepcopy(self.data.workflow), self.mapping()
        timeline = json.loads(workflow['502']['inputs']['timeline_data'])
        timeline['global']['prompt'] = 'The man moves.'
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        report = audit(self.project, workflow, mapping)
        self.assertFalse(report['ok'])
        self.assertIn('sections', [i['code'] for i in report['groups'][0]['issues']])
        # An unselected group has no content verdict and cannot borrow the selected one's.
        timeline['global']['prompt'] = ''
        timeline['segments'].append(copy.deepcopy(timeline['segments'][0]))
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        self.assertTrue(audit(self.project, workflow, mapping)['ok'])
        timeline['runSelection'] = [0, 1]
        workflow['502']['inputs']['timeline_data'] = json.dumps(timeline)
        self.assertFalse(audit(self.project, workflow, mapping)['ok'])

    async def test_source_change_and_false_evidence_cannot_pass(self):
        self.video()
        mapping = self.mapping()
        group = mapping['content_review']['groups'][0]
        group['checks']['space_action']['prompt_quote'] = 'nonexistent sentence'
        group['checks']['translation']['status'] = 'pending'
        (self.project / 'review-source.md').write_text('Different source', 'utf-8')
        report = audit(self.project, self.data.workflow, mapping)
        codes = {i['code'] for i in report['groups'][0]['issues']}
        self.assertTrue({'review_evidence', 'review_source_stale', 'review_incomplete'} <= codes)

    async def test_old_report_cannot_authorize_new_job_but_old_registration_can_resume(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('content_checks')
        report['sources'].pop('review-source.md')
        document = self.record / 'review-document.md'
        report['sources'].pop(document.relative_to(self.project).as_posix())
        # Older context checks did not read the document used by the content review.
        report['context_sources'] = [name for name in report['context_sources'] if name != str(document)]
        checks.write_report(self.data, report)
        with self.assertRaisesRegex(ValueError, '内容核对'):
            checks.check_prepared(self.store, self.data)
        self.assertTrue(checks.check_prepared(self.store, self.data, require_content_review=False)['ok'])
        with patch.object(checks, 'fixed_checks', side_effect=AssertionError('reuse covered technical checks')):
            await self.store.prepare_only(self.data)
        self.assertTrue(checks.read_report(self.data)['content_checks']['ok'])

    async def test_new_job_missing_review_pauses_before_upload_and_post(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        report.pop('content_checks'); checks.write_report(self.data, report)
        key = (await self.store.enqueue(self.data))['local_task_id']
        await self.store.close()
        self.store = tasks.TaskStore(self.root / 'runtime', self.root)
        self.node()
        with patch.object(tasks.client, 'upload') as upload, patch.object(tasks.client, 'submit') as submit, patch.object(self.store, 'queue_notice'):
            await self.store.dispatch_once()
        self.assertEqual(self.store.rows[key]['state']['status'], 'paused')
        self.assertTrue(self.store.rows[key]['state']['content_review_required'])
        upload.assert_not_called(); submit.assert_not_called()

    async def test_malformed_review_returns_failure_and_never_a_ready_report(self):
        self.video()
        mapping = self.mapping()
        mapping['content_review']['groups'][0]['checks'] = True
        self.save_mapping(mapping)
        with self.assertRaisesRegex(ValueError, 'review_schema'):
            await self.store.prepare_only(self.data)
        self.assertFalse(checks.read_report(self.data)['ok'])
