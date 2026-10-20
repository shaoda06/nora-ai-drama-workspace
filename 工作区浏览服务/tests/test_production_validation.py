"""Production index preparation and closeout checks, using isolated source files only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.services import comfy_tasks as t, execution_checks as checks
from backend.services.result_registration import closeout
from tests import test_submission_lifecycle as lifecycle, test_result_closeout as delivery


class IndexPreparationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = lifecycle.LifecycleTests.asyncSetUp
    asyncTearDown = lifecycle.LifecycleTests.asyncTearDown
    video = lifecycle.LifecycleTests.video

    def index(self):
        return self.project / '09-剧集制作/EP001/03-分镜脚本/EP001-分镜索引.md'

    async def test_bad_index_identities_stop_before_any_upload_or_generation(self):
        self.video()
        for scene, part in [('EP001-C001', 'P001'), ('EP001-C001', 'EP002-C001-P001'),
                            ('EP001-C001', 'EP001-C002-P001'), ('EP001-C002', 'EP001-C002-P001')]:
            with self.subTest(scene=scene, part=part):
                self.index().write_text('| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                                        + f'| {scene} | {part} | 3 |\n', 'utf-8')
                with patch.object(t.client, 'upload') as upload, patch.object(t.client, 'submit') as submit:
                    with self.assertRaisesRegex(ValueError, '分镜索引.md.*不匹配'):
                        await self.store.prepare_only(self.data)
                    upload.assert_not_called(); submit.assert_not_called()
                self.assertFalse(self.store.rows)
                self.assertFalse(checks.read_report(self.data)['ok'])

    async def test_missing_or_empty_index_cannot_pass_preparation(self):
        self.video()
        self.index().unlink()
        with self.assertRaises(FileNotFoundError):
            await self.store.prepare_only(self.data)
        self.index().write_text('# 没有分段表\n', 'utf-8')
        with self.assertRaisesRegex(ValueError, '没有可读取的分段表'):
            await self.store.prepare_only(self.data)
        self.assertFalse(self.store.rows)

    async def test_valid_index_is_recorded_and_unchanged_preparation_is_reused(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        self.assertEqual(report['storyboard_index']['rows'], 1)
        self.assertIn(self.index().relative_to(self.project).as_posix(), report['sources'])
        with patch.object(checks, 'storyboard_index_checks', side_effect=AssertionError('must reuse')):
            self.assertTrue((await self.store.prepare_only(self.data))['reused'])

    async def test_index_change_invalidates_report_and_is_checked_again(self):
        self.video()
        await self.store.prepare_only(self.data)
        self.index().write_text(self.index().read_text().replace('EP001-C001-P001', 'P001'), 'utf-8')
        with self.assertRaisesRegex(ValueError, '准备资料已变化'):
            checks.check_prepared(self.store, self.data)
        with self.assertRaisesRegex(ValueError, '分镜索引.md.*不匹配'):
            await self.store.prepare_only(self.data)
        self.assertFalse(self.store.rows)

    async def test_old_preparation_report_does_not_skip_new_index_check(self):
        self.video()
        await self.store.prepare_only(self.data)
        report = checks.read_report(self.data)
        for source in report.pop('storyboard_index')['files']:
            report['sources'].pop(Path(source).relative_to(self.project).as_posix())
        checks.write_report(self.data, report)
        self.index().write_text(self.index().read_text().replace('EP001-C001-P001', 'P001'), 'utf-8')
        with self.assertRaisesRegex(ValueError, '分镜索引.md.*不匹配'):
            await self.store.prepare_only(self.data)

    async def test_removing_scene_from_script_invalidates_preparation(self):
        self.video()
        await self.store.prepare_only(self.data)
        script = self.project / '09-剧集制作/EP001/02-剧集剧本/EP001-本集剧本.md'
        script.write_text('## 1. 故事剧本正文\n### EP001-C002\n其他场次。\n', 'utf-8')
        with self.assertRaisesRegex(ValueError, '分镜索引.md.*不匹配'):
            await self.store.prepare_only(self.data)


class IndexCloseoutTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = lifecycle.LifecycleTests.asyncSetUp
    asyncTearDown = lifecycle.LifecycleTests.asyncTearDown
    video = lifecycle.LifecycleTests.video
    setup_video = delivery.CloseoutTests.setup_video
    download = delivery.CloseoutTests.download
    collect_and_notice = delivery.CloseoutTests.collect_and_notice

    async def test_index_errors_block_web_verification_even_when_video_is_listed(self):
        candidate, draft = self.setup_video()
        index = self.project / '09-剧集制作/EP001/03-分镜脚本/EP001-分镜索引.md'
        correct = index.read_text('utf-8')
        index.write_text(correct.replace('EP001-C001-P001', 'P001'), 'utf-8')
        batch = await self.collect_and_notice()
        with patch.object(t.client, 'submit') as submit, patch.object(t.client, 'download') as download:
            result = await closeout(self.store, self.projects, batch, self.data.thread_id)
            self.assertFalse(result['user_message_ready'])
            self.assertEqual(self.store.rows['task']['state']['closeout']['status'], 'browser_pending')
            self.assertIn('制作资料需要修正', str(result))
            self.assertIn('分镜索引.md', str(result))
            parsed = self.projects.section(self.project.name, '09-剧集制作', 'EP001', mode='playback')
            self.assertIn('分段“P001”', json.dumps(parsed, ensure_ascii=False))
            self.assertIn(candidate.name, json.dumps(parsed, ensure_ascii=False))
            self.assertEqual(candidate.read_bytes(), b'isolated media')
            before = draft.read_bytes()
            index.write_text(correct, 'utf-8')
            result = await closeout(self.store, self.projects, batch, self.data.thread_id)
            self.assertTrue(result['user_message_ready'], result)
            self.assertEqual(draft.read_bytes(), before)
            submit.assert_not_called(); download.assert_not_called()
