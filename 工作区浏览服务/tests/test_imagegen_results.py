"""Native image handoff and shared closeout; temporary projects, no generation calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_submission_plans import plans
from tests.test_image_closeout import png
from backend.services import imagegen_results as native, image_closeout as images
from backend.services.projects import ProjectStore


class NativeImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'projects/Imagegen测试'
        person = self.project / '03-人物资料/CH001-测试人物'
        person.mkdir(parents=True)
        (person / 'CH001-测试人物-人物资料卡.md').write_text('# 人物资料卡\n\n## 3. 外貌与基础造型\n### 3.1 成年\n')
        (person.parent / '人物索引.md').write_text('| 人物编号 | 姓名 | 人物定位 | 资料卡入口 |\n| --- | --- | --- | --- |\n| CH001 | 测试人物 | 主角 | [资料卡](CH001-测试人物/CH001-测试人物-人物资料卡.md) |\n')
        self.request = self.project / '03-人物资料/其他资料/执行附件/测试批次/请求.json'
        self.request.parent.mkdir(parents=True)
        self.spec = dict(kind='人物', object='CH001', image_type='人物上半身正面肖像图', title='独立管线测试',
            draft='03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md', prompt='保持原文的测试提示词。',
            authorization='用户授权一次独立测试，不自动重试', ratio='1:1', formal_size=[2048, 2048],
            output='03-人物资料/其他资料/工作稿/素材/CH001-成年-人物上半身正面肖像图-候选-v01.png',
            fields={'人物状态': '成年'})
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
        self.projects = ProjectStore(self.project.parent)
        self.source = self.root / 'native.png'
        self.source.write_bytes(png(7, 5))

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self):
        self.job = native.prepare(self.project, self.request)
        self.result = self.project / self.job['record'] / '实际调用结果.json'
        self.result.parent.mkdir(parents=True, exist_ok=True)
        self.result.write_text(json.dumps(dict(source=str(self.source), actual_prompt=self.spec['prompt'])))
        return self.job

    def test_native_size_is_preserved_and_registered_in_actual_web_parser(self):
        self.prepare()
        result = native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertTrue(result['user_message_ready'])
        self.assertEqual(result['browser']['status'], 'verified')
        self.assertEqual(self.source.read_bytes(), (self.project / self.job['candidate']).read_bytes())
        self.assertEqual((result['items'][0]['width'], result['items'][0]['height']), (7, 5))
        text = (self.project / self.job['draft']).read_text()
        self.assertIn('- 用户采用状态：待确认', text)
        self.assertIn('- 结论：待确认', text)
        self.assertNotIn('- 结论：批准采用', text)
        self.assertIn('非ComfyUI任务', text)
        self.assertEqual(self.projects.section(self.project.name, '03-人物资料')['people'][0]['pendingCount'], 1)
        self.assertFalse(list(self.project.rglob('*.api.json')))
        self.assertFalse(list(self.project.rglob('后台任务状态.json')))

    def test_prepare_and_complete_reuse_without_new_generation_or_overwriting_feedback(self):
        self.prepare()
        self.assertEqual(native.prepare(self.project, self.request), self.job)
        first = native.complete(self.project, self.job['manifest'], self.result, self.projects)
        draft = self.project / self.job['draft']
        draft.write_text(draft.read_text().replace('尚无反馈', '用户的新反馈'))
        before = draft.read_bytes()
        with patch.object(images, 'apply_updates', side_effect=AssertionError('no repeated registration')), \
                patch.object(self.projects, 'get', side_effect=AssertionError('report already ready')):
            second = native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertEqual(first, second)
        self.assertEqual(draft.read_bytes(), before)
        self.assertEqual(draft.read_text().count('### 生成记录-001\n'), 1)

    def test_prompt_change_is_rejected_before_copying_output(self):
        self.prepare()
        self.result.write_text(json.dumps(dict(source=str(self.source), actual_prompt='改过的提示词')))
        with self.assertRaisesRegex(ValueError, '提示词与交接正文不符'):
            native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertFalse((self.project / self.job['candidate']).exists())

    def test_invalid_png_never_creates_review(self):
        self.prepare()
        self.source.write_bytes(b'not-an-image')
        with self.assertRaisesRegex(ValueError, '不是PNG'):
            native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertNotIn('### ' + self.job['review'], (self.project / self.job['draft']).read_text())

    def test_different_candidate_is_not_overwritten(self):
        self.prepare()
        candidate = self.project / self.job['candidate']
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(png(9, 6))
        with self.assertRaisesRegex(ValueError, '已有不同内容'):
            native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertEqual(candidate.read_bytes(), png(9, 6))

    def test_browser_failure_can_resume_without_repeating_registration(self):
        self.prepare()
        with patch.object(native, 'verify_image_entries', side_effect=ValueError('网页尚未同步')):
            with self.assertRaisesRegex(ValueError, '网页尚未同步'):
                native.complete(self.project, self.job['manifest'], self.result, self.projects)
        draft = self.project / self.job['draft']
        before = draft.read_bytes()
        with patch.object(images, 'apply_updates', side_effect=AssertionError('already registered')):
            self.assertTrue(native.complete(self.project, self.job['manifest'], self.result, self.projects)['user_message_ready'])
        self.assertEqual(before, draft.read_bytes())

    def test_concurrent_source_document_edit_is_preserved(self):
        self.prepare()
        original = images.apply_updates
        def interrupted(root, report, report_file):
            draft = root / self.job['draft']
            draft.write_text(draft.read_text().replace('- 用户采用状态：未送审', '- 用户采用状态：不采用'))
            return original(root, report, report_file)
        with patch.object(images, 'apply_updates', side_effect=interrupted), self.assertRaisesRegex(ValueError, '变化或不唯一'):
            native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertIn('- 用户采用状态：不采用', (self.project / self.job['draft']).read_text())

    def test_failed_generation_records_error_without_creating_candidate(self):
        self.prepare()
        result = native.fail(self.project, self.job['manifest'], 'tool error')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['user_message_ready'])
        self.assertFalse((self.project / self.job['candidate']).exists())
        text = (self.project / self.job['draft']).read_text()
        self.assertIn('tool error', text)
        self.assertNotIn('### ' + self.job['review'], text)

    def test_all_existing_templates_are_prepared_without_new_asset_categories(self):
        for kind, scope, who in [('场景', '04-场景资料', 'SC001'), ('道具', '05-道具资料', 'PR001'),
                                 ('剧集素材', '09-剧集制作/EP001', 'EP001')]:
            with self.subTest(kind=kind):
                spec = dict(self.spec, kind=kind, object=who,
                    draft=f'{scope}/其他资料/工作稿/{who}-参考图-工作稿.md',
                    output=f'{scope}/其他资料/工作稿/素材/{who}-候选-v01.png')
                request = self.request.with_name(who + '.json')
                request.write_text(json.dumps(spec, ensure_ascii=False))
                job = native.prepare(self.project, request)
                body = (self.project / job['draft']).read_text()
                self.assertIn('### 生成记录-001', body)
                self.assertIn(self.spec['prompt'], body)
                self.assertEqual(job['executor'], dict(model='gpt-6-luna', reasoning_effort='medium', fork_turns='none'))

    def test_approved_native_reference_does_not_require_a_qwen_seed(self):
        self.prepare()
        native.complete(self.project, self.job['manifest'], self.result, self.projects)
        draft = self.project / self.job['draft']
        text = draft.read_text()
        review = images.section(text, self.job['review'])[0]
        approved = images.fields(review, {'结论': '批准采用',
            '批准的具体候选': images.link(draft, self.project / self.job['candidate'])})
        draft.write_text(text.replace(review, approved))
        spec = dict(self.spec, output=self.spec['output'].replace('v01.png', 'v02.png'), references=[dict(
            file=self.job['candidate'], purpose='保持人物身份', approval=self.job['draft'] + '#' + self.job['review'])])
        request = self.request.with_name('第二次.json')
        request.write_text(json.dumps(spec, ensure_ascii=False))
        second = native.prepare(self.project, request)
        self.assertEqual(second['generation'], '生成记录-002')
        self.assertIn('用途：保持人物身份', draft.read_text())

    def test_episode_generation_and_review_both_remain_pending(self):
        self.spec.update(kind='剧集素材', object='EP001-C001-P001', image_type='剧集专用参考图',
            draft='09-剧集制作/EP001/其他资料/工作稿/EP001-专用素材制作-工作稿.md',
            output='09-剧集制作/EP001/其他资料/工作稿/素材/EP001-专用图-候选-v01.png')
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
        self.prepare()
        result = native.complete(self.project, self.job['manifest'], self.result, self.projects)
        self.assertTrue(result['user_message_ready'])
        body = (self.project / self.job['draft']).read_text()
        self.assertIn('- 用户决定及具体候选、批准依据：待确认；', body)
        self.assertIn('- 决定：待确认', body)

    def test_cli_prepares_completes_and_reads_ready_report(self):
        script = native.SKILL / 'scripts/imagegen_results.py'
        def call(*args):
            result = subprocess.run([sys.executable, '-B', str(script), *args, '--project', str(self.project)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        for scope in ('人物', '剧集素材'):
            with self.subTest(scope=scope):
                if scope == '剧集素材':
                    self.spec.update(kind='剧集素材', object='EP001-C001-P001', image_type='剧集专用参考图',
                        draft='09-剧集制作/EP001/其他资料/工作稿/EP001-专用素材制作-工作稿.md',
                        output='09-剧集制作/EP001/其他资料/工作稿/素材/EP001-专用图-候选-v01.png')
                    self.request = self.request.with_name('剧集请求.json')
                    self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
                job = call('prepare', '--request', str(self.request))
                self.assertTrue((self.project / job['generation_call_file']).is_file())
                self.assertTrue(job['result_store_key'].startswith('imagegen:'))
                result = subprocess.run(job['complete_command'] + ['--source', str(self.source)], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertTrue(report['user_message_ready'])
                self.assertEqual(call('report', '--manifest', job['manifest']), report)
                self.assertEqual(call('complete', '--manifest', job['manifest'], '--source', str(self.source),
                    '--actual-prompt-file', str(self.project / job['prompt_file'])), report)

    def test_cli_default_prompt_path_still_rejects_changed_text(self):
        self.prepare()
        (self.project / self.job['prompt_file']).write_text('被改过的正文')
        result = subprocess.run([sys.executable, '-B', str(native.SKILL / 'scripts/imagegen_results.py'),
            'complete', '--project', str(self.project), '--manifest', self.job['manifest'], '--source', str(self.source)],
            text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('实际提示词与交接不符', result.stderr)
        self.assertFalse((self.project / self.job['candidate']).exists())

    def test_generation_call_preserves_native_result_before_display(self):
        self.spec['prompt'] = '杯子写着"测试"。\n只改颜色，保留原图。'
        self.spec['references'] = []
        for name in ('参考 白杯.png', '参考 蓝杯.png'):
            file = self.project / name
            file.write_bytes(png())
            self.spec['references'].append(dict(file=name, purpose=name,
                user_reference=True, basis='用户指定的独立测试输入'))
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
        self.prepare()
        source = (self.project / self.job['generation_call_file']).read_text()
        expected = dict(prompt=self.spec['prompt'], referenced_image_paths=[
            str(self.project / ref['file']) for ref in self.spec['references']])
        # Imagegen returns image_url/output_hint, not MCP content blocks.
        for display_fails in (False, True):
            with self.subTest(display_fails=display_fails):
                harness = '''
const events = [], saved = {};
const output = {image_url: 'data:image/png;base64,dGVzdA==', output_hint: 'native result'};
const tools = {image_gen__imagegen: async args => {events.push(['call', args]); return output;}};
const store = (key, value) => {events.push(['store', key]); saved[key] = value;};
const generatedImage = value => {events.push(['display', value]); DISPLAY_FAILURE};
let failure = null;
try { GENERATION_CALL } catch (error) {failure = error.message;}
process.stdout.write(JSON.stringify({events, saved, output, failure}));
'''.replace('DISPLAY_FAILURE', "throw new Error('display interrupted')" if display_fails else '')
                harness = harness.replace('GENERATION_CALL', source)
                result = subprocess.run(['node', '--input-type=module', '-e', harness],
                    text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual([event[0] for event in data['events']], ['call', 'store', 'display'])
                self.assertEqual(data['events'][0][1], expected)
                self.assertEqual(data['saved'][self.job['result_store_key']], data['output'])
                self.assertEqual(data['events'][2][1], data['output'])
                self.assertEqual(data['failure'], 'display interrupted' if display_fails else None)
