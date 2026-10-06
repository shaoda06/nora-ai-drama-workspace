import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.parsers import project as parser
from backend.services.projects import ProjectStore


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        (self.project / '00-项目定位').mkdir(parents=True)
        self.source = self.project / '00-项目定位/项目基本定位.md'
        self.source.write_text('# 项目定位\n\n## 内容\n第一版。\n', encoding='utf-8')
        self.store = ProjectStore(self.root)
        self.override = patch.object(main, 'store', self.store)
        self.override.start()
        self.client = TestClient(main.app, base_url='http://localhost:8780')

    def tearDown(self):
        self.client.close()
        self.override.stop()
        self.temp.cleanup()

    def test_production_titles_from_current_outline_and_existing_directories(self):
        outlines = self.project / '06-分集大纲'
        outlines.mkdir()
        for number, text in (('EP001', '本集题名：先撑过今晚。来源范围：旧场次。'),
                             ('EP002', '- 本集题名：婶子也不能白拿。'),
                             ('EP003', '- 一句话概要：没有题名。'),
                             ('EP004', '本集题名：仅有大纲，没有制作目录。')):
            (outlines / (number + '-分集大纲.md')).write_text('# 分集大纲\n\n' + text + '\n', encoding='utf-8')
        for number in ('EP001', 'EP002', 'EP003', 'EP005'):
            folder = self.project / '09-剧集制作' / number / '02-剧集剧本'
            folder.mkdir(parents=True)
            (folder / (number + '-本集剧本.md')).write_text('# 本集剧本\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertEqual([(item['name'], item['title']) for item in data['children']],
                         [('EP001', '先撑过今晚'), ('EP002', '婶子也不能白拿'), ('EP003', ''), ('EP005', '')])
        self.assertIn('EP001-本集剧本.md', str(data['children'][0]['children']))

    def test_production_statistics_count_episodes_not_preparation_states(self):
        outlines = self.project / '06-分集大纲'
        outlines.mkdir()
        (outlines / '分集索引.md').write_text(
            '# 分集索引\n\n| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n'
            '| EP001 | 一 | [大纲](EP001-分集大纲.md) |\n'
            '| EP002 | 二 | [大纲](EP002-分集大纲.md) |\n'
            '| EP002 | 重复条目 | [大纲](EP002-分集大纲.md) |\n'
            '| EP003 | 三 | [大纲](EP003-分集大纲.md) |\n', encoding='utf-8')
        for number in ('EP001', 'EP002', 'EP004'):
            (self.project / '09-剧集制作' / number).mkdir(parents=True)
        (self.project / '项目进度.md').write_text(
            '# 项目进度\n\n| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n'
            '| --- | --- | --- | --- | --- | --- |\n'
            '| EP001 制作 | 无 | 已完成 | 无 | 无 | 无 |\n'
            '| EP002 制作 | 无 | 进行中 | 无 | 无 | 无 |\n'
            '| EP003 剧本 | 无 | 已完成 | 无 | 无 | 无 |\n'
            '| EP004 分镜 | 无 | 已完成 | 无 | 无 | 无 |\n'
            '| EP004 制作 | 无 | 已确认 | 无 | 无 | 无 |\n', encoding='utf-8')
        data = self.client.get('/api/projects/示例项目/sections/09-剧集制作').json()
        self.assertEqual(data['statistics'], {'total': 4, 'completed': 1, 'remaining': 3, 'running': 1})
        self.assertEqual([item['name'] for item in data['children']], ['EP001', 'EP002', 'EP004'])
        self.assertNotIn('已完成', data['children'][2]['statusHtml'])
        self.assertIn('已确认', data['children'][2]['statusHtml'])

    def test_discovery_and_dynamic_document(self):
        self.assertEqual(self.client.get('/api/projects').json()[0]['name'], '示例项目')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位')
        self.assertIn('第一版', section.json()['bodyHtml'])
        previous = self.store.status('示例项目')['revision']
        self.source.write_text('# 项目定位\n\n## 内容\n第二版，增加内容。\n', encoding='utf-8')
        self.store.get('示例项目')['checked'] = 0
        self.store.status('示例项目')
        for _ in range(100):
            if not self.store.get('示例项目')['updating']:
                break
            time.sleep(.01)
        self.assertGreater(self.store.status('示例项目')['revision'], previous)
        self.assertIn('第二版', self.client.get('/api/projects/示例项目/sections/00-项目定位').json()['bodyHtml'])
        (self.root / '新项目').mkdir()
        self.assertEqual(len(self.client.get('/api/projects').json()), 2)

    def test_file_boundaries_and_range(self):
        video = self.project / '测试.mp4'
        video.write_bytes(bytes(range(100)))
        ranged = self.client.get('/api/projects/示例项目/files/测试.mp4', headers={'Range': 'bytes=10-19'})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.content, bytes(range(10, 20)))
        with self.assertRaises(FileNotFoundError):
            self.store.file('示例项目', '../outside.md')
        hidden = self.project / '.private'
        hidden.write_text('private')
        self.assertEqual(self.client.get('/api/projects/示例项目/files/.private').status_code, 404)
        self.assertEqual(self.client.get('/api/history/document?path=../../AGENTS.md').status_code, 404)
        self.assertEqual(self.client.get('/api/krea2/files/../使用说明.md').status_code, 404)

    def test_changes_include_additions_removal_and_rename(self):
        before = self.store.snapshot(self.project)
        path = self.project / '新增.txt'
        path.write_text('hello')
        self.assertNotEqual(before, self.store.snapshot(self.project))
        current = self.store.snapshot(self.project)
        path.rename(self.project / '改名.txt')
        self.assertNotEqual(current, self.store.snapshot(self.project))
        (self.project / '改名.txt').unlink()
        self.assertEqual(before, self.store.snapshot(self.project))

    def test_refresh_failure_retains_previous_data_and_reports_error(self):
        entry = self.store.get('示例项目')
        data = entry['data']
        with patch('backend.services.projects.build_data', side_effect=ValueError('错误源文件')):
            self.store.refresh('示例项目', entry, self.store.snapshot(self.project))
        self.assertIs(entry['data'], data)
        self.assertEqual(entry['error'], '错误源文件')

    def test_lan_can_manage_with_same_origin_and_token(self):
        lan = TestClient(main.app, base_url='http://192.168.10.15:8780', client=('192.168.10.30', 44321))
        state = lan.get('/api/krea2/state').json()
        self.assertTrue(state['canManage'])
        self.assertEqual(state['token'], main.krea2.updater.TOKEN)
        with patch.object(main.krea2.updater, 'start_job') as job:
            result = lan.post('/api/krea2/action', headers={'Origin': 'http://192.168.10.15:8780', 'X-Krea-Token': main.krea2.updater.TOKEN}, json={'source': 'clio', 'action': 'apply'})
            self.assertEqual(result.status_code, 202)
            job.assert_called_once_with('apply', 'clio')
            job.reset_mock()
            payload = {'source': 'clio', 'action': 'check'}
            for headers in (
                {'Origin': 'http://outside.site', 'X-Krea-Token': state['token']},
                {'Origin': 'http://192.168.10.15:8780', 'X-Krea-Token': 'wrong-token'},
                {'Origin': 'http://192.168.10.15', 'Sec-Fetch-Site': 'same-origin', 'X-Krea-Token': state['token']},
            ):
                self.assertEqual(lan.post('/api/krea2/action', headers=headers, json=payload).status_code, 403)
            job.assert_not_called()
            self.assertEqual(lan.post('/api/krea2/action', headers={'Origin': 'http://192.168.10.15', 'Referer': 'http://192.168.10.15:8780/', 'Sec-Fetch-Site': 'same-origin', 'X-Krea-Token': state['token']}, json=payload).status_code, 202)
            job.assert_called_once_with('check', 'clio')
        lan.close()

    def test_public_peer_or_non_lan_host_cannot_manage(self):
        for host, peer in (('192.168.10.15', '8.8.8.8'), ('outside.site', '192.168.10.30'), ('8.8.8.8', '192.168.10.30')):
            with TestClient(main.app, base_url=f'http://{host}:8780', client=(peer, 44321)) as client:
                state = client.get('/api/krea2/state').json()
                self.assertFalse(state['canManage'])
                self.assertNotIn('token', state)
                with patch.object(main.krea2.updater, 'start_job') as job:
                    result = client.post('/api/krea2/action', headers={'Origin': f'http://{host}:8780', 'X-Krea-Token': main.krea2.updater.TOKEN}, json={'source': 'ray', 'action': 'restore'})
                    self.assertEqual(result.status_code, 403)
                    job.assert_not_called()

    def test_local_management_requires_origin_and_token(self):
        state = self.client.get('/api/krea2/state').json()
        self.assertTrue(state['canManage'])
        with patch.object(main.krea2.updater, 'start_job') as job:
            payload = {'source': 'ray', 'action': 'check'}
            headers = {'Origin': 'http://localhost:8780', 'X-Krea-Token': state['token']}
            self.assertEqual(self.client.post('/api/krea2/action', headers=headers, json=payload).status_code, 202)
            job.assert_called_once_with('check', 'ray')
            for invalid in ({'Origin': 'http://other.site', 'X-Krea-Token': state['token']}, {'Origin': 'http://localhost:8780'}):
                self.assertEqual(self.client.post('/api/krea2/action', headers=invalid, json=payload).status_code, 403)

    def test_catalog_is_paged_and_resource_remains_readable(self):
        first = self.client.get('/api/krea2/catalog').json()
        self.assertEqual(len(first['items']), 36)
        self.assertGreater(first['total'], 36)
        second = self.client.get('/api/krea2/catalog?page=2').json()
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        style = self.client.get('/api/krea2/styles/' + first['items'][0]['id']).json()
        self.assertEqual(self.client.get('/api/krea2/files/' + style['folder'] + '/positive.txt').text, style['prompt'])

    def test_generation_record_urls_use_project_endpoint_and_keep_fragment(self):
        result = main.view({'recordUrl': '03-test%5C记录.md#生成记录-001', 'sourceUrl': 'https://example.com/source'}, '示例项目')
        self.assertEqual(result['recordUrl'], '/api/projects/%E7%A4%BA%E4%BE%8B%E9%A1%B9%E7%9B%AE/files/03-test/记录.md#生成记录-001')
        self.assertEqual(result['sourceUrl'], 'https://example.com/source')

    def test_markdown_table_with_blank_lines_keeps_rows_and_links(self):
        rendered = parser.markdown('| 类型 | 种子 | 来源 |\n\n| --- | --- | --- |\n\n| 肖像 | 123 | [记录](记录.md) |\n\n| 六视图 | 456 | 已采用 |\n\n下一段。', parser.POSITION)
        self.assertEqual(rendered.count('<table>'), 1)
        self.assertEqual(rendered.count('<td>'), 6)
        self.assertIn('data-doc="00-项目定位/记录.md"', rendered)
        self.assertIn('</table></div>\n<p>下一段。</p>', rendered)

    def test_phase_status_targets_the_matching_progress_row(self):
        progress = '| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n| --- | --- | --- | --- | --- | --- |\n| 人物资料卡 | 会话 | 待确认 | 资料卡 | CH042细节待确认 | 按用户意见修订 |\n'
        (self.project / '项目进度.md').write_text(progress, encoding='utf-8')
        data = self.store.get('示例项目')['data']
        stage = next(item for item in data['active'] if item['name'] == '人物资料卡')
        self.assertIn('id="' + stage['anchor'] + '"', data['documents']['项目进度.md']['html'])
        self.assertIn('CH042细节待确认', data['documents']['项目进度.md']['html'])

    def test_phase_table_with_blank_lines_reads_all_actual_states(self):
        progress = ('| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n\n'
                    '| --- | --- | --- | --- | --- | --- |\n\n'
                    '| 人物资料卡 | 会话 | 待确认 | 卡 | 待审 | 修改 |\n\n'
                    '| EP001 制作 | 会话 | 进行中 | 剧本 | 待审 | 制作 |\n\n'
                    '| 分集大纲 | 会话 | 已完成 | 大纲 | 无 | 接续 |\n\n## 其他内容\n')
        path = self.project / '项目进度.md'
        path.write_text(progress, encoding='utf-8')
        value = self.client.get('/api/projects/示例项目/overview').json()
        self.assertEqual([(item['name'], item['status']) for item in value['active']],
                         [('人物资料卡', '待确认'), ('EP001 制作', '进行中')])
        self.assertEqual(path.read_text(encoding='utf-8'), progress)

    def test_document_header_preserves_extra_fields_and_source_links(self):
        source = ('# 项目定位\n\n- 项目名称或代号：示例项目\n- 文档版本：v03\n'
                  '- 更新日期：2026-10-06\n- 确认状态：部分确认；旧限定说明。\n'
                  '- 确认范围：主线已确认\n- 确认依据：[决定](决定.md)\n'
                  '- 旧制作目标：全部保留\n\n额外说明也保留。\n\n## 正文\n'
                  '- 确认范围：这是正文字段。\n')
        self.source.write_text(source, encoding='utf-8')
        value = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertIn('旧制作目标：全部保留', value['headerHtml'])
        self.assertIn('旧限定说明', value['headerHtml'])
        self.assertIn('额外说明也保留', value['headerHtml'])
        self.assertIn('data-doc="00-项目定位/决定.md"', value['headerHtml'])
        self.assertNotIn('这是正文字段', value['headerHtml'])
        preview = self.client.get('/api/projects/示例项目/document', params={'path': parser.POSITION}).json()
        self.assertEqual(preview['headerHtml'], value['headerHtml'])
        self.assertNotIn('旧制作目标', preview['contentHtml'])
        self.assertIn('这是正文字段', preview['contentHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)

    def test_sample_resolution_moves_to_title_and_keeps_three_record_fields(self):
        source = ('#### 男性样例\n\n![男性](男.png)\n\n'
                  '- 分辨率：1024×1024\n- 样例版本：v15\n'
                  '- 确认依据：旧说明有512×512；[采用](采用.md)\n'
                  '- 执行记录：[生成](生成.md)\n\n'
                  '#### 女性样例\n\n- 分辨率：待确认\n- 样例版本：v05\n'
                  '- 确认依据：尚未确认\n- 执行记录：[旧试验](试验.md)\n')
        rendered = parser.markdown(source, parser.POSITION)
        self.assertIn('<h4 id="男性样例">男性样例，1024×1024</h4>', rendered)
        self.assertIn('<h4 id="女性样例">女性样例，待确认</h4>', rendered)
        self.assertNotIn('<li>分辨率', rendered)
        self.assertEqual(rendered.count('<li>'), 6)
        self.assertEqual(rendered.count('class="style-sample-card"'), 1)
        self.assertIn('旧说明有512×512', rendered)
        self.assertIn('data-doc="00-项目定位/采用.md"', rendered)
        self.assertIn('data-doc="00-项目定位/生成.md"', rendered)
        old = parser.markdown('#### 男性样例\n\n![男性](男.png)\n\n- 确认依据：旧尺寸512×512\n', parser.POSITION)
        self.assertIn('<h4 id="男性样例">男性样例</h4>', old)
        self.assertNotIn('男性样例，512', old)

    def test_position_title_and_status_do_not_change_the_source(self):
        source = '# 项目定位\n\n- 项目名称：示例项目，全名。\n\n## 视觉表现\n\n- 画风确认状态：已确认；采用依据保留。\n'
        self.source.write_text(source, encoding='utf-8')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertEqual(section['title'], '示例项目，全名')
        overview = self.client.get('/api/projects/示例项目/overview').json()
        self.assertEqual(overview['positionTitle'], section['title'])
        self.assertEqual(overview['project'], '示例项目')
        self.assertEqual(section['introHtml'], '')
        self.assertIn('status-green', section['bodyHtml'])
        self.assertIn('采用依据保留', section['bodyHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)

    def test_position_template_preserves_scope_evidence_and_sample_ownership(self):
        source = ('# 项目基本定位\n\n- 项目名称或代号：模板项目\n- 文档版本：v2\n'
                  '- 更新日期：2026-10-06\n- 确认状态：部分确认\n- 确认范围：仅EP001\n'
                  '- 确认依据：[决定](决定.md)\n\n## 5. 视觉表现形式\n\n### 视觉规格\n'
                  '- 正式画幅：待确认\n- 画幅待确认事项：候选16:9或9:16\n'
                  '- 画幅确认状态：待确认\n\n### 画风与美术实现正文\n\n#### 中文\n'
                  '~~~text\n完整中文正文\n~~~\n\n#### 英文\n'
                  '- 对应中文版本：v1\n- 适配确认状态：已确认\n\n~~~text\nFull English text\n~~~\n'
                  '\n### 已确认画风样例\n\n#### 男性样例\n\n![男性](男.png)\n'
                  '\n- 样例版本：v3\n- 确认依据：[男性决定](男.md)\n'
                  '\n#### 女性样例\n\n- 样例版本：待确认\n- 确认依据：尚未确认\n')
        self.source.write_text(source, encoding='utf-8')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertEqual(section['title'], '模板项目')
        self.assertIn('仅EP001', section['summaryHtml'])
        self.assertNotIn('仅EP001', section['introHtml'])
        self.assertIn('data-doc="00-项目定位/决定.md"', section['introHtml'])
        self.assertNotIn('项目名称或代号', section['introHtml'])
        self.assertIn('status-orange', section['confirmationHtml'])
        self.assertIn('正式画幅：待确认', section['bodyHtml'])
        self.assertIn('候选16:9或9:16', section['bodyHtml'])
        self.assertIn('完整中文正文', section['bodyHtml'])
        self.assertIn('Full English text', section['bodyHtml'])
        self.assertEqual(section['bodyHtml'].count('class="style-sample-card"'), 1)
        self.assertIn('data-gender="male"', section['bodyHtml'])
        self.assertIn('男性决定', section['bodyHtml'])
        self.assertIn('女性样例', section['bodyHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)

    def test_root_other_materials_opens_files_without_mixing_stage_records(self):
        root_record = self.project / '其他资料/历史版本/项目进度-归档.md'
        stage_record = self.project / '00-项目定位/其他资料/审阅记录/定位-审阅.md'
        for path in (root_record, stage_record):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# 记录\n\n原始依据。', encoding='utf-8')
        overview = self.client.get('/api/projects/示例项目/overview').json()
        self.assertIn('其他资料', [item['name'] for item in overview['directories']])
        response = self.client.get('/api/projects/示例项目/sections/其他资料')
        self.assertEqual(response.status_code, 200)
        files = response.json()['children'][0]['children']
        self.assertEqual([item['key'] for item in files], ['其他资料/历史版本/项目进度-归档.md'])
        preview = self.client.get('/api/projects/示例项目/document', params={'path': files[0]['key']})
        self.assertIn('原始依据', preview.json()['html'])
        self.assertEqual(self.client.get('/api/projects/示例项目/sections/不存在').status_code, 404)

    def test_common_header_keeps_scope_and_legacy_notes_separate(self):
        for directory, name in [('01-主旨与简介', '主旨与简介'), ('02-故事大纲', '故事大纲')]:
            path = self.project / directory / (name + '.md')
            path.parent.mkdir(parents=True, exist_ok=True)
            source = ('# ' + name + '\n\n- 项目名称或代号：示例项目\n'
                      '- 文档版本：v02\n- 更新日期：2026-10-06\n'
                      '- 确认状态：部分确认\n- 确认范围：主线已确认，细节待定。\n'
                      '- 确认依据：[决定](决定.md)\n- 确认说明：旧说明完整保留。\n'
                      '\n## 正文\n\n- 确认范围：这是正文原句，不是头部字段。\n')
            path.write_text(source, encoding='utf-8')
        for directory, name in [('01-主旨与简介', '主旨与简介'), ('02-故事大纲', '故事大纲')]:
            with self.subTest(document=name):
                path = self.project / directory / (name + '.md')
                source = path.read_text(encoding='utf-8')
                value = self.client.get('/api/projects/示例项目/sections/' + directory).json()
                self.assertIn('主线已确认，细节待定', value['summaryHtml'])
                self.assertNotIn('主线已确认', value['introHtml'])
                self.assertIn('旧说明完整保留', value['introHtml'])
                self.assertIn('data-doc="' + directory + '/决定.md"', value['introHtml'])
                self.assertIn('这是正文原句', value['bodyHtml'])
                self.assertNotIn('这是正文原句', value['summaryHtml'])
                self.assertEqual(path.read_text(encoding='utf-8'), source)

    def test_position_current_fields_are_separate_from_adoption_history(self):
        source = ('# 项目定位\n\n- 确认范围：画幅已确认，地理待定。\n'
                  '- 单集目标时长：1—2分钟\n- 确认依据：[采用](采用.md)\n'
                  '- 采用经过：旧42集改为71集，依据保留。\n\n## 1. 正文\n'
                  '单集目标时长：这句话属于正文，应完整保留。\n'
                  '\n### 制作规格\n\n- 单集目标时长：2—3分钟\n')
        self.source.write_text(source, encoding='utf-8')
        section = self.client.get('/api/projects/示例项目/sections/00-项目定位').json()
        self.assertIn('地理待定', section['summaryHtml'])
        self.assertNotIn('单集目标时长', section['summaryHtml'])
        self.assertIn('1—2分钟', section['introHtml'])
        self.assertNotIn('采用经过', section['summaryHtml'])
        self.assertNotIn('地理待定', section['introHtml'])
        self.assertIn('旧42集改为71集', section['introHtml'])
        self.assertIn('data-doc="00-项目定位/采用.md"', section['introHtml'])
        self.assertIn('这句话属于正文，应完整保留', section['bodyHtml'])
        self.assertIn('制作规格', section['bodyHtml'])
        self.assertIn('2—3分钟', section['bodyHtml'])
        self.assertNotIn('2—3分钟', section['introHtml'])
        self.assertEqual(self.source.read_text(encoding='utf-8'), source)


if __name__ == '__main__':
    unittest.main()
