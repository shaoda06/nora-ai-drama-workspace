"""Exercise the fixed Imagegen CLI in temporary projects without generating images."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image


CLI = Path(__file__).with_name('imagegen_results.py')
sys.path.insert(0, str(CLI.resolve().parents[4] / '工作区浏览服务'))
from backend.parsers.project import build_data, status_markup


class CandidateNamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = self.root / '04-场景资料/其他资料/执行附件/请求.json'
        self.request.parent.mkdir(parents=True)
        self.spec = dict(kind='场景', object='SC001', image_type='场景参考图', title='办公室',
                         draft='04-场景资料/其他资料/工作稿/SC001-参考图-工作稿.md',
                         output='04-场景资料/其他资料/工作稿/素材/SC001-EP001-C001-V001-场景参考图-候选-v01.png',
                         formal='04-场景资料/SC001-办公室/参考图/SC001-EP001-C001-V001-场景参考图.png',
                         prompt='空办公室。', authorization='隔离测试，只准备不生成',
                         ratio='16:9', formal_size=[2752, 1536])

    def prepare(self):
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
        return subprocess.run([sys.executable, '-B', str(CLI), 'prepare', '--project', str(self.root),
                               '--request', str(self.request)], capture_output=True, text=True)

    def test_bad_suffixes_stop_before_record_or_handoff(self):
        standard = self.spec['output']
        for suffix in ('-imagegen', '-16x9', '-imagegen-16x9'):
            with self.subTest(suffix=suffix):
                self.spec['output'] = standard.removesuffix('.png') + suffix + '.png'
                result = self.prepare()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('新图片候选须', result.stderr)
                self.assertFalse((self.root / self.spec['draft']).exists())
                self.assertFalse(self.request.with_name('请求-Imagegen执行清单.json').exists())
                self.assertEqual(list(self.root.rglob('*.*')), [self.request])

    def test_wrong_directory_stops_before_handoff(self):
        self.spec['output'] = '04-场景资料/参考图/SC001-场景参考图-候选-v01.png'
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('新图片候选须', result.stderr)
        self.assertFalse((self.root / self.spec['draft']).exists())

    def test_well_formed_but_different_formal_name_stops_before_handoff(self):
        self.spec['output'] = self.spec['output'].replace('场景参考图-候选', '无人总览-候选')
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('对应正式图片名', result.stderr)
        self.assertFalse((self.root / self.spec['draft']).exists())

    def test_missing_formal_identity_stops_before_handoff(self):
        del self.spec['formal']
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('formal', result.stderr)
        self.assertFalse((self.root / self.spec['draft']).exists())

    def test_social_native_and_sized_names_are_checked_without_writes(self):
        self.spec.update(kind='社交媒体', formal='10-社交媒体资料/个人页资料/头像/平台-账号-头像.png',
                         draft='10-社交媒体资料/个人页资料/其他资料/工作稿/平台-账号-主页视觉-工作稿.md')
        for suffix in ['原生', '1080x1080', '原生-imagegen']:
            with self.subTest(suffix=suffix):
                self.spec['output'] = '10-社交媒体资料/个人页资料/其他资料/工作稿/素材/平台-账号-头像-候选-v01-' + suffix + '.png'
                self.request.write_text(json.dumps(self.spec, ensure_ascii=False))
                result = subprocess.run([sys.executable, '-B', str(CLI), 'check-name', '--project', str(self.root),
                                         '--request', str(self.request)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, suffix != '原生-imagegen')
                self.assertFalse((self.root / self.spec['draft']).exists())
                self.assertFalse((self.root / self.spec['output']).exists())

    def test_standard_candidate_is_used_verbatim_without_generation(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        job = json.loads(result.stdout)
        self.assertEqual(job['candidate'], self.spec['output'])
        self.assertTrue((self.root / self.spec['draft']).is_file())
        self.assertFalse((self.root / self.spec['output']).exists())

    def scene_index(self):
        folder = self.root / '04-场景资料/SC001-办公室'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'SC001-办公室-资料卡.md').write_text('# 办公室\n已确认的独立场景。\n')
        (folder.parent / '场景索引.md').write_text(
            '| 场景编号 | 名称 | 场景类型 | 资料卡入口 |\n| --- | --- | --- | --- |\n'
            '| SC001 | 办公室 | 室内 | [资料卡](SC001-办公室/SC001-办公室-资料卡.md) |\n')

    def test_scene_without_episode_preserves_identity_through_native_closeout(self):
        self.scene_index()
        for field in ('formal', 'output'):
            self.spec[field] = self.spec[field].replace('-EP001-C001', '')
        self.spec['fields'] = {'最初制作场次': '尚未划分，依据已确认场景设计'}
        prepared = self.prepare()
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        job = json.loads(prepared.stdout)
        source = self.root / '隔离像素.png'
        Image.new('RGB', (16, 9), 'white').save(source)
        completed = subprocess.run([sys.executable, '-B', str(CLI), 'complete', '--project', str(self.root),
            '--manifest', job['manifest'], '--source', str(source)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)['user_message_ready'])
        scene = build_data(self.root.resolve(), load_scope='04-场景资料')['scenes'][0]
        self.assertEqual(scene['candidates'][0]['media']['key'], self.spec['output'])
        self.assertEqual(scene['pendingCount'], 1)
        self.assertIn('尚未划分', scene['candidates'][0]['state'])
        self.assertFalse((self.root / self.spec['formal']).exists())

    def test_explicit_scene_views_with_or_without_episode_are_formal_and_auxiliary_stays_separate(self):
        self.scene_index()
        draft = self.root / self.spec['draft']
        draft.parent.mkdir(parents=True, exist_ok=True)
        previous_files = []
        for stem, scope, formal in (
                ('SC001-V001-场景参考图', '已确认的室内基础总览', True),
                ('SC001-EP001-C001-V001-场景参考图', '本场实际环境', True),
                ('SC001-EP001-C001-场景参考图', '历史实际环境', True),
                ('SC001-V001-场景参考图', '仅供空间结构参考', False)):
            with self.subTest(stem=stem, scope=scope):
                for previous in previous_files:
                    previous.unlink()
                image = self.root / '04-场景资料/SC001-办公室/参考图' / (stem + '.png')
                image.parent.mkdir(exist_ok=True)
                Image.new('RGB', (16, 9), 'white').save(image)
                candidate = draft.parent / '素材' / (stem + '-候选-v01.png')
                candidate.parent.mkdir(exist_ok=True)
                candidate.write_bytes(image.read_bytes())
                previous_files = [image, candidate]
                draft.write_text('# 场景记录\n## 1. 当前正式资产\n'
                    '| 正式文件 | 最初制作场次 | 场景状态与适用条件 | 采用的候选版本 | 审阅记录 |\n'
                    '| --- | --- | --- | --- | --- |\n'
                    f'| [正式图](../../SC001-办公室/参考图/{image.name}) | 尚未划分 | {scope} | '
                    '[生成记录-001](#生成记录-001)；v01 | [审阅](#审阅-生成记录-001-001) |\n'
                    '## 2. 逐次生成记录\n### 生成记录-001\n'
                    f'- 输出候选文件：[候选](素材/{candidate.name})\n- 用户采用状态：已采用\n'
                    '## 4. 审阅区\n### 审阅-生成记录-001-001\n#### 4. 用户确认\n'
                    f'- 决定：批准采用\n- 对应具体候选：[候选](素材/{candidate.name})\n'
                    '#### 5. 采用与后续影响\n- 当前制作适用性：适用\n')
                scene = build_data(self.root.resolve(), load_scope='04-场景资料')['scenes'][0]
                self.assertEqual(len(scene['formal']), int(formal))
                self.assertEqual(len(scene['auxiliary']), int(not formal))
                self.assertEqual(scene['cover'] is not None, formal)

    def test_cover_revision_decision_remains_visible_without_becoming_approval(self):
        folder = self.root / '10-社交媒体资料/封面资料'
        draft = folder / '其他资料/工作稿/封面制作-工作稿.md'
        candidate = draft.parent / '素材/系列通用-通用-竖版封面-候选-v01.png'
        candidate.parent.mkdir(parents=True)
        Image.new('RGB', (12, 16), 'white').save(candidate)
        (folder / '封面索引.md').write_text(
            '| 封面编号 | 封面名称 | 适用范围 | 版式 | 适用平台 | 目标比例 | 目标尺寸 | 成品文件 | 采用原图 | 采用版本 | 审阅记录 | 处理记录 |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n'
            f'| COV001 | 通用竖版 | 系列通用 | 竖版 | 通用 | 3:4 | 12×16 | 待处理 | [原图](其他资料/工作稿/素材/{candidate.name}) | v01 | '
            '[审阅](其他资料/工作稿/封面制作-工作稿.md#审阅-生成记录-001-001) | 无 |\n')
        draft.write_text('# 封面记录\n## 2. 逐次生成记录\n### 生成记录-001\n'
            '- 封面编号：COV001\n- 修订轮次：R001\n- 轮次名称：初稿\n'
            f'- 候选文件入口：[候选](素材/{candidate.name})\n'
            '- 用户决定及具体候选、批准依据：修改后再审；标题需要调整\n'
            '## 4. 审阅区\n### 审阅-生成记录-001-001\n#### 4. 用户确认\n'
            f'- 决定：修改后再审\n- 对应具体候选：[候选](素材/{candidate.name})\n')
        data = build_data(self.root.resolve(), load_scope='10-社交媒体资料')['catalogues']['10-社交媒体资料']['covers']
        self.assertEqual(data['candidates'][0]['status'], '修改后再审')
        self.assertFalse(data['items'][0]['approved'])
        self.assertFalse(data['items'][0]['ready'])
        self.assertFalse(data['assets'][0]['rounds'][0]['candidates'][0]['current'])
        self.assertIn('orange', status_markup('修改后再审', ''))

    def test_unregistered_sc_view_is_visible_but_does_not_grant_approval(self):
        self.scene_index()
        image = self.root / '04-场景资料/SC001-办公室/参考图/SC001-V001-场景参考图.png'
        image.parent.mkdir()
        Image.new('RGB', (16, 9), 'white').save(image)
        scene = build_data(self.root.resolve(), load_scope='04-场景资料')['scenes'][0]
        self.assertEqual(len(scene['formal']), 1)
        self.assertEqual(scene['formal'][0]['state'], 'V001')
        self.assertTrue(scene['formal'][0]['directoryDiscovered'])
        self.assertFalse(scene['formal'][0]['approved'])
        self.assertIsNone(scene['cover'])

    def test_existing_handoff_retains_its_historical_path(self):
        self.spec['output'] = self.spec['output'].removesuffix('.png') + '-imagegen.png'
        manifest = self.request.with_name('请求-Imagegen执行清单.json')
        original = json.dumps(dict(request=self.spec, candidate=self.spec['output'],
                                   manifest=str(manifest.relative_to(self.root))))
        manifest.write_text(original)
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['candidate'], self.spec['output'])
        self.assertEqual(manifest.read_text(), original)
        self.assertFalse((self.root / self.spec['draft']).exists())


if __name__ == '__main__':
    unittest.main()
