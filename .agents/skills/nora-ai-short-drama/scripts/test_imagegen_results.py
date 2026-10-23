"""Exercise the fixed Imagegen CLI in temporary projects without generating images."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).with_name('imagegen_results.py')


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
        self.spec.update(kind='社交媒体', formal='11-社交媒体资料/头像/平台-账号-头像.png',
                         draft='11-社交媒体资料/其他资料/工作稿/平台-账号-主页视觉-工作稿.md')
        for suffix in ['原生', '1080x1080', '原生-imagegen']:
            with self.subTest(suffix=suffix):
                self.spec['output'] = '11-社交媒体资料/其他资料/工作稿/素材/平台-账号-头像-候选-v01-' + suffix + '.png'
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
