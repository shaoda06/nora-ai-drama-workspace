"""Cover approval, real dimensions and Imagegen registration; no remote calls."""
import json
from pathlib import Path
import tempfile
import unittest
from backend.parsers.project import build_data
from backend.parsers.covers import DIRECTORY, INDEX, RECORD
from tests.test_image_closeout import png
from tests import test_imagegen_results as native_tests
from backend.services import imagegen_results as native


class CoverParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.put(INDEX, '| 封面名称 | 适用范围 | 版式 | 目标比例 | 目标尺寸 | 成品文件 | 采用原图 | 采用版本 | 审阅记录 | 处理记录 |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| 通用竖版 | 系列通用 | 竖版 | 3:4 | 12×16 | [成品](正式封面/竖版.png) | [原图](其他资料/工作稿/素材/原图.png) | v04 | [批准](其他资料/工作稿/封面制作-工作稿.md#审阅-生成记录-006-002) | [处理](其他资料/工作稿/封面制作-工作稿.md#生成记录-006) |')
        self.put(RECORD, '## 2. 逐次生成记录\n### 生成记录-006\n- 候选文件入口：[原图](素材/原图.png)\n- 用户决定及具体候选、批准依据：批准采用；用户明确选定\n## 4. 审阅区\n### 审阅-生成记录-006-002\n#### 4. 用户确认\n- 决定：批准采用\n- 对应具体候选：[原图](素材/原图.png)\n')
        self.put(DIRECTORY + '/正式封面/竖版.png', png(12, 16))
        self.put(DIRECTORY + '/其他资料/工作稿/素材/原图.png', png(11, 17))

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)

    def covers(self):
        return build_data(self.root, load_scope=DIRECTORY)['catalogues'][DIRECTORY]

    def test_adopted_source_stays_in_details_not_history(self):
        data = self.covers()
        self.assertTrue(data['items'][0]['ready'])
        self.assertEqual(data['items'][0]['media']['ratio'], '3:4')
        self.assertEqual(data['items'][0]['original']['ratio'], '11:17')
        self.assertEqual(data['candidates'], [])
        self.assertEqual(data['items'][0]['original']['key'], DIRECTORY + '/其他资料/工作稿/素材/原图.png')

    def test_other_candidate_is_kept_even_with_same_approved_status(self):
        path = self.root / RECORD
        path.write_text(path.read_text().replace('## 4. 审阅区',
            '### 生成记录-007\n- 候选文件入口：[另一张](素材/另一张.png)\n'
            '- 用户决定及具体候选、批准依据：批准采用；旧批准仍保留\n## 4. 审阅区'))
        self.put(DIRECTORY + '/其他资料/工作稿/素材/另一张.png', png(11, 17))
        self.assertEqual([item['generation'] for item in self.covers()['candidates']], ['生成记录-007'])

    def test_source_returns_to_history_when_no_longer_current(self):
        self.assertEqual(self.covers()['candidates'], [])
        self.put(INDEX, '')
        self.assertEqual([item['generation'] for item in self.covers()['candidates']], ['生成记录-006'])

    def test_missing_original_does_not_hide_the_formal_cover(self):
        (self.root / DIRECTORY / '其他资料/工作稿/素材/原图.png').unlink()
        data = self.covers()
        self.assertTrue(data['items'][0]['ready'])
        self.assertIsNone(data['items'][0]['original'])
        self.assertEqual(data['candidates'], [])

    def test_set_and_platforms_are_read_from_explicit_columns(self):
        path = self.root / INDEX
        text = path.read_text().replace('| 封面名称 |', '| 套组名称 | 适用平台 | 目标格式 | 规格依据 | 封面名称 |', 1)
        text = text.replace('| --- |', '| --- | --- | --- | --- | --- |', 1)
        text = text.replace('| 通用竖版 |', '| 系列通用 | 快手、小红书 | PNG | 用户指定规格 | 通用竖版 |', 1)
        path.write_text(text)
        item = self.covers()['items'][0]
        self.assertEqual(item['setName'], '系列通用')
        self.assertEqual(item['platforms'], ['快手', '小红书'])
        self.assertEqual(item['specBasis'], '用户指定规格')
        self.assertEqual(item['targetFormat'], 'PNG')
        self.assertTrue(item['ready'])

    def test_legacy_index_does_not_infer_set_or_platform(self):
        path = self.root / INDEX
        path.write_text('- 适用平台：抖音\n' + path.read_text())
        item = self.covers()['items'][0]
        self.assertEqual(item['setName'], '')
        self.assertEqual(item['platforms'], [])
        self.assertEqual(item['specBasis'], '')
        self.assertTrue(item['ready'])

    def test_candidate_platforms_use_the_generation_record(self):
        self.put(INDEX, '')
        path = self.root / RECORD
        path.write_text(path.read_text().replace('### 生成记录-006\n', '### 生成记录-006\n- 套组名称：系列通用\n- 适用平台：抖音、小红书\n', 1))
        candidate = self.covers()['candidates'][0]
        self.assertEqual(candidate['setName'], '系列通用')
        self.assertEqual(candidate['platforms'], ['抖音', '小红书'])

    def test_legacy_candidate_keeps_an_unassigned_platform(self):
        self.put(INDEX, '')
        self.assertEqual(self.covers()['candidates'][0]['platforms'], [])

    def test_failed_attempt_does_not_claim_later_successful_file(self):
        self.put(INDEX, '')
        path = self.root / RECORD
        path.write_text(path.read_text().replace('## 4. 审阅区', '### 生成记录-007\n- 真实执行状态：failed；未自动重试\n- 候选文件入口：尚未生成；计划：[同名原图](素材/原图.png)\n## 4. 审阅区'))
        self.assertEqual(len(self.covers()['candidates']), 1)

    def test_file_does_not_imply_approval(self):
        path = self.root / RECORD
        path.write_text(path.read_text().replace('决定：批准采用', '决定：待确认'))
        self.assertFalse(self.covers()['items'][0]['approved'])
        self.assertEqual(len(self.covers()['candidates']), 1)

    def test_approval_must_point_to_the_selected_source(self):
        path = self.root / RECORD
        path.write_text(path.read_text().replace('对应具体候选：[原图](素材/原图.png)', '对应具体候选：[另图](素材/另图.png)'))
        self.assertFalse(self.covers()['items'][0]['approved'])

    def test_wrong_actual_dimensions_remain_pending(self):
        self.put(DIRECTORY + '/正式封面/竖版.png', png(11, 17))
        item = self.covers()['items'][0]
        self.assertTrue(item['approved'])
        self.assertEqual(item['status'], '待规格处理')
        self.assertEqual(len(self.covers()['candidates']), 1)

    def test_target_ratio_is_also_checked(self):
        path = self.root / INDEX
        path.write_text(path.read_text().replace('| 3:4 |', '| 4:3 |'))
        self.assertFalse(self.covers()['items'][0]['ready'])


class NativeCoverTests(unittest.TestCase):
    setUp = native_tests.NativeImageTests.setUp
    tearDown = native_tests.NativeImageTests.tearDown
    prepare = native_tests.NativeImageTests.prepare

    def test_six_references_are_rejected_before_reading_or_creating_records(self):
        self.spec['references'] = [{} for _ in range(6)]
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, '最多接收5张'):
            native.prepare(self.project, self.request)
        self.assertFalse((self.project / self.spec['draft']).exists())

    def test_free_prompt_cover_visible_without_adoption_index(self):
        self.spec.update(kind='封面', object='通用', image_type='竖版封面', draft=RECORD,
                         prompt='自由编写的完整画面与文案。', ratio='3:4', formal_size=[1080, 1440],
                         formal=DIRECTORY + '/正式封面/通用-竖版封面.png',
                         output=DIRECTORY + '/其他资料/工作稿/素材/通用-竖版封面-候选-v01.png')
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
        self.prepare()
        result = native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertTrue(result['user_message_ready'])
        data = self.projects.section(self.project.name, DIRECTORY)['catalogues'][DIRECTORY]
        self.assertEqual(len(data['candidates']), 1)
        self.assertEqual(data['items'], [])
        self.assertIn('自由编写的完整画面与文案。', (self.project / RECORD).read_text())


class QwenCoverTests(unittest.TestCase):
    def test_backup_uses_cover_record_and_free_prompt(self):
        from backend.services import submission_plans as plans
        from backend.services.imagegen_results import SKILL
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            documents = plans.Documents(root)
            spec = dict(task_type='image', object='通用', title='备用封面', kind='封面',
                        image_type='横版封面', draft=RECORD, authorization='用户选择备用千问',
                        supplementary=True, size=[1536, 1152],
                        formal=DIRECTORY + '/正式封面/通用-横版封面.png',
                        prompt=dict(rewritten_prompt='自由描述画面、标题和排版。', wh_ratio='4:3', ratio_follow=''))
            task = plans.build_image(root, SKILL, spec, documents, '2026-10-22')
            self.assertEqual(task['image_plan']['kind'], '封面')
            self.assertIn('自由描述画面、标题和排版。', documents.read(RECORD))
            self.assertEqual(task['workflow']['514']['inputs']['width'], 1536)
