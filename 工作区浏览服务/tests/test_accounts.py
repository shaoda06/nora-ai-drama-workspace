"""Account index and review integration; fixtures never touch real project files."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image

from backend.parsers.accounts import DIRECTORY, INDEX
from backend.parsers.project import build_data


class AccountParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.record = DIRECTORY + '/其他资料/工作稿/平台-A-主页视觉-工作稿.md'
        self.rows = []

    def put(self, key, text):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def visual(self, purpose='头像', version='v08', platform='平台A／账号', extension='png', size=(40, 30)):
        account = platform.replace('／', '-')
        role = '背景图' if purpose == '主页背景图' else purpose
        self.record = f'{DIRECTORY}/其他资料/工作稿/{account}-主页视觉-工作稿.md'
        formal = f'{role}/{account}-{role}.{extension}'
        candidate = f'素材/{account}-{role}-候选-{version}-原生.png'
        for key in (DIRECTORY + '/' + formal, str(Path(self.record).parent / candidate)):
            path = self.root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', size, '#fafafa').save(path)
        heading = purpose + '-审阅-' + version
        body = (f'### {heading}\n- 用户确认：批准采用原生{version}。\n'
                f'- 正式保存：[正式文件](../../{formal})\n'
                f'- 候选：[候选]({candidate})\n')
        previous = (self.root / self.record).read_text() if (self.root / self.record).exists() else ''
        self.put(self.record, previous + body)
        record_link = str(Path(self.record).relative_to(DIRECTORY))
        self.rows.append(f'| {platform} | {purpose} | [正式]({formal}) | 原生{version} | {size[0]}×{size[1]} | [批准]({record_link}#{heading}) | 无尺寸处理 |')
        return DIRECTORY + '/' + formal

    def accounts(self):
        self.put(INDEX, '| 平台／账号代号 | 用途 | 正式文件 | 采用版本 | 实际规格 | 采用依据 | 处理记录 |\n'
                 '| --- | --- | --- | --- | --- | --- | --- |\n' + '\n'.join(self.rows))
        return build_data(self.root, load_scope=DIRECTORY)['catalogues'][DIRECTORY]

    def test_adopted_images_and_records_are_separate_and_format_independent(self):
        self.visual()
        self.visual('主页背景图', 'v04', extension='jpg', size=(80, 45))
        self.visual('头像', 'v02', platform='平台B／另一个账号', size=(32, 48))
        self.put(DIRECTORY + '/其他资料/历史版本/旧稿.md', '# 历史\n不代表当前采用')
        data = self.accounts()
        self.assertEqual(len(data['items']), 3)
        self.assertEqual([(item['media']['width'], item['media']['height']) for item in data['items']],
                         [(40, 30), (80, 45), (32, 48)])
        self.assertEqual(data['issues'], [])
        self.assertNotIn('candidates', data)
        history = next(group for group in data['groups'] if group['name'] == '历史版本')
        self.assertEqual(history['files'][0]['name'], '旧稿.md')
        work = next(group for group in data['groups'] if group['name'] == '工作稿')
        self.assertTrue(any(item['kind'] == 'image' for item in work['files']))

    def test_files_and_index_do_not_imply_approval(self):
        self.visual()
        text = (self.root / self.record).read_text().replace('批准采用', '待确认')
        self.put(self.record, text)
        self.assertEqual(self.accounts()['items'], [])
        self.assertIn('采用记录', self.accounts()['issues'][0])

    def test_index_version_must_match_review_candidate(self):
        self.visual()
        self.rows[0] = self.rows[0].replace('原生v08', '原生v09')
        self.assertEqual(self.accounts()['items'], [])

    def test_review_must_reference_the_same_formal_file(self):
        self.visual()
        text = (self.root / self.record).read_text().replace('[正式文件](../../头像/', '[正式文件](../../背景图/')
        self.put(self.record, text)
        self.assertEqual(self.accounts()['items'], [])

    def test_old_approval_is_not_current_after_replacement(self):
        self.visual()
        text = (self.root / self.record).read_text() + '- 当前处置：已被新版替换并归档。\n'
        self.put(self.record, text)
        self.assertEqual(self.accounts()['items'], [])

    def test_missing_formal_file_is_reported_without_using_candidate(self):
        key = self.visual()
        (self.root / key).unlink()
        data = self.accounts()
        self.assertEqual(data['items'], [])
        self.assertIn('文件缺失', data['issues'][0])

    def test_candidate_or_history_path_cannot_become_formal_through_index(self):
        key = self.visual()
        formal = str(Path(key).relative_to(DIRECTORY))
        row, body = self.rows[0], (self.root / self.record).read_text()
        for folder in ('其他资料/工作稿/素材', '其他资料/历史版本'):
            with self.subTest(folder=folder):
                target = f'{folder}/平台A-账号-头像-候选-v08-原生.png'
                dest = self.root / DIRECTORY / target
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / key, dest)
                self.rows = [row.replace(f']({formal})', f']({target})')]
                link = os.path.relpath(dest, (self.root / self.record).parent)
                self.put(self.record, body.replace(f'../../{formal}', link))
                data = self.accounts()
                self.assertEqual(data['items'], [])
                self.assertIn('正式目录', data['issues'][0])

    def test_index_purpose_must_match_formal_directory(self):
        self.visual()
        self.rows[0] = self.rows[0].replace('| 头像 |', '| 背景图 |')
        self.assertEqual(self.accounts()['items'], [])

    def test_replaced_state_uses_shared_record_field_names(self):
        self.visual()
        body = (self.root / self.record).read_text()
        for label in ('当前处置', '当前状态', '用户采用状态'):
            with self.subTest(label=label):
                self.put(self.record, body + f'- {label}：已被替换／归档\n')
                self.assertEqual(self.accounts()['items'], [])

    def test_existing_skill_template_fields_are_read_without_rewriting(self):
        self.visual('主页背景图', version='v11', platform='平台C／制作号')
        body = (self.root / self.record).read_text().replace('用户确认：', '用户决定、采用范围与依据：')
        body = body.replace('- 候选：', '- 审阅的具体文件及候选版本：')
        body = body.replace('- 正式保存：', '- 正式文件、索引及旧版归档入口：')
        self.put(self.record, body)
        data = self.accounts()
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['version'], '原生v11')

    def test_two_accounts_on_same_platform_and_separate_projects(self):
        workspace = self.root
        outputs = []
        for project, size in (('独立项目甲', (48, 36)), ('另一部短片', (60, 90))):
            self.root = workspace / project
            self.root.mkdir()
            self.rows = []
            self.visual(platform='平台D／账号甲', version='v03', size=size, extension='jpg')
            self.visual(platform='平台D／账号乙', version='v12', size=size)
            data = self.accounts()
            self.assertEqual(len(data['items']), 2)
            self.assertEqual(len({item['media']['key'] for item in data['items']}), 2)
            self.assertEqual({item['platform'] for item in data['items']}, {'平台D／账号甲', '平台D／账号乙'})
            self.assertTrue(all((item['media']['width'], item['media']['height']) == size for item in data['items']))
            outputs.append(data)
        self.assertNotEqual(outputs[0]['items'][0]['media']['width'], outputs[1]['items'][0]['media']['width'])

    def test_unindexed_images_stay_out_of_current_adoption(self):
        self.visual()
        self.put(DIRECTORY + '/其他资料/历史版本/旧版.md', '# 旧版')
        data = build_data(self.root, load_scope=DIRECTORY)['catalogues'][DIRECTORY]
        self.assertEqual(data['items'], [])
        self.assertIsNone(data['index'])
        groups = {group['name']: group['files'] for group in data['groups']}
        self.assertTrue(groups['工作稿'])
        self.assertTrue(groups['历史版本'])

    def test_navigation_label_and_optional_section(self):
        self.assertNotIn(DIRECTORY, [item['name'] for item in build_data(self.root, load_scope='overview')['directories']])
        self.visual()
        overview = build_data(self.root, load_scope='overview')
        self.assertEqual(next(item['label'] for item in overview['directories'] if item['name'] == DIRECTORY), '账号资料')
        self.assertNotIn(DIRECTORY, overview['catalogues'])

    @unittest.skipIf(os.name == 'nt', 'Creating symlinks requires extra privileges on Windows')
    def test_symlink_cannot_escape_project(self):
        key = self.visual()
        outside = self.root.parent / (self.root.name + '-outside.png')
        Image.new('RGB', (2, 2)).save(outside)
        self.addCleanup(outside.unlink)
        (self.root / key).unlink()
        (self.root / key).symlink_to(outside)
        with self.assertRaisesRegex(ValueError, '越出项目'):
            self.accounts()
