"""Offline authoring CLI exercises real documents without a workflow or network."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('h3_prompt_checks.py')
TEXT = '''subject_definitions:
<Subject 1>北方守卫：参考人物。
summary:
东方幻想三维角色渲染。
retention_analysis:
<Subject 1>北方守卫：保留面容。
detailed_description:
全程不要出现字幕。
[Shot 1] <Subject 1>北方守卫在画面左侧，右方石门打开。他说<d>往北走。</d>。
overall_soundscape:
风声。
non_diegetic_music:
N/A'''


class DocumentCLI(unittest.TestCase):
    def test_document_warnings_do_not_block_but_structure_and_output_conflicts_do(self):
        with tempfile.TemporaryDirectory() as temp:
            path, report = Path(temp) / 'prompt.md', Path(temp) / 'report.json'
            def run(text):
                path.write_text('## 提交给模型的完整提示词\n```text\n' + TEXT +
                                '\n```\n## 中文提示词参考版\n```text\n' + text + '\n```\n')
                return subprocess.run([sys.executable, str(SCRIPT), '--document', str(path)], capture_output=True, text=True)
            good = run(TEXT)
            self.assertEqual(good.returncode, 0, good.stderr)
            bad = run(TEXT.replace('在画面左侧', '在白台北3米'))
            self.assertEqual(bad.returncode, 0)
            self.assertIn('spatial_coordinates', [x['code'] for x in json.loads(bad.stdout)['documents'][0]['warnings']])
            malformed = run(TEXT.replace('summary:', 'missing_summary:'))
            self.assertNotEqual(malformed.returncode, 0)
            self.assertIn('translation_sections', [x['code'] for x in json.loads(malformed.stdout)['documents'][0]['issues']])
            report.write_text('keep existing report')
            result = subprocess.run([sys.executable, str(SCRIPT), '--document', str(path), '--output', str(report)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report.read_text(), 'keep existing report')


if __name__ == '__main__':
    unittest.main()
