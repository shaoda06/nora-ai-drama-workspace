import json
import importlib.util
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main
from backend.parsers.project import build_data
from backend.services.projects import ProjectStore

spec = importlib.util.spec_from_file_location('generation_writer', Path(__file__).resolve().parents[2] /
    '.agents/skills/nora-ai-short-drama/scripts/generation_context.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


class GenerationContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / '示例项目'
        self.episode = '09-剧集制作/EP001'
        self.write(self.episode + '/02-剧集剧本/EP001-本集剧本.md',
                   '## 1. 故事剧本正文\n### EP001-C001\n场次。\n')
        self.write(self.episode + '/03-分镜脚本/EP001-分镜索引.md',
                   '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                   '| EP001-C001 | EP001-C001-P001 | 11 |\n')
        self.write(self.episode + '/03-分镜脚本/EP001-C001-场次分镜.md',
                   self.storyboard('v99', '最新版不应出现'))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, key, text):
        path = self.project / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def storyboard(self, version, body):
        return f'- 文档版本：{version}\n## 1. 镜头正文\n### 分段 P001\n说明不展示。\n' \
            f'#### EP001-SH001\n**镜号**：EP001-SH001\n**时间**：00:00-00:03\n' \
            f'**景别**：{body}\n**时长**：3秒\n### 分段 P002\n#### EP001-SH002\n其他分段不展示。\n'

    def add_run(self, run, stage='一采', source=None):
        identity = 'EP001-C001-P001-' + run + '-' + stage
        root = self.episode + '/其他资料/执行附件/' + identity
        candidate = self.episode + '/其他资料/候选视频/' + identity + '.mp4'
        self.write(candidate, identity)
        if source:
            context = {'identity': identity, 'source': source}
        else:
            storyboard = self.episode + '/其他资料/历史版本/分镜-' + run + '.md'
            self.write(storyboard, self.storyboard('v' + run[1:], run + '当次原文'))
            self.write(root + '/模型提示词.txt', run + ' actual submitted prompt')
            self.write(root + '/中文提示词参考版.txt', run + ' 当次中文')
            for name in ('公共图.png', '首帧.png'):
                self.write(root + '/输入素材/' + name, run + name)
            context = {'identity': identity, 'storyboard': {'file': storyboard, 'version': 'v' + run[1:]},
                       'prompts': {'english': root + '/模型提示词.txt', 'chinese': root + '/中文提示词参考版.txt'},
                       'references': {'common': [{'file': root + '/输入素材/公共图.png', 'label': 'Picture 1'}],
                                      'segment': [{'file': root + '/输入素材/首帧.png', 'label': 'Picture 2'}]}}
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}, ensure_ascii=False))
        return context, root, candidate

    def videos(self):
        return build_data(self.project, web_episode_navigation=True)['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos']

    def test_running_candidate_uses_unique_task_state_and_frozen_inputs(self):
        _, _, candidate = self.add_run('R004')
        owner = self.episode + '/其他资料/工作稿/EP001-C001-P002-视频制作-工作稿.md'
        self.write(owner, '### R009\n- 任务状态：运行中\n- 最近检查时间：2026-10-07 09:30\n'
                          '### R010\n- 任务状态：成功\n')
        record = self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md'
        self.write(record, '### R004\n- 共同任务证据与状态入口：[共同状态](EP001-C001-P002-视频制作-工作稿.md#r009)\n'
                           '- 取回核对状态：运行中已取回，待收尾核对\n')
        before = self.videos()[0]
        self.assertEqual(before['taskStatus'], '运行中')
        self.assertEqual(before['deliveryStatus'], '运行中已取回，待收尾核对')
        self.assertEqual(before['checkedAt'], '2026-10-07 09:30')
        self.assertIn('R004当次原文', before['context']['scriptHtml'])
        self.assertFalse(before['approved'])
        self.write(owner, '### R009\n- 任务状态：失败\n- 最近检查时间：2026-10-07 09:35\n')
        after = self.videos()[0]
        self.assertEqual(after['taskStatus'], '失败')
        self.assertEqual(after['deliveryStatus'], before['deliveryStatus'])
        self.assertEqual(after['url'], before['url'])
        self.assertEqual(after['candidateNumber'], before['candidateNumber'])
        self.assertTrue((self.project / candidate).exists())

    def test_final_replacement_changes_file_url_without_inheriting_old_approval(self):
        _, _, candidate = self.add_run('R004')
        record = self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md'
        adopted = ('## 1. 当前选定结果\n| 处理阶段 | 当前选定文件 | R编号 | 人工批准依据 |\n'
                   '| --- | --- | --- | --- |\n| 一采 | [视频](../候选视频/EP001-C001-P001-R004-一采.mp4) | R004 | 人工批准 |\n')
        entry = '## 2. 逐次执行与采用记录\n### R004\n- 处理阶段：一采\n- 用户决定：批准采用\n'
        self.write(record, adopted + entry + '- 取回核对状态：运行中已取回，待收尾核对\n')
        before = self.videos()[0]
        self.assertTrue(before['approved'])
        # Reuse an unchanged file: status-only changes cannot force a player reload.
        self.write(record, adopted + entry + '- 取回核对状态：已核对不变\n- 任务状态：成功\n')
        self.assertEqual(self.videos()[0]['fileRevision'], before['fileRevision'])
        # Follow the publishing rule: retain the reviewed bytes and review fact, clear current adoption.
        archive = self.episode + '/其他资料/历史版本/EP001-C001-P001-R004-一采-运行中取回-20261007-093600.mp4'
        (self.project / archive).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.project / candidate, self.project / archive)
        self.write(record, '## 1. 当前选定结果\n' + entry.replace('批准采用', '待审核') +
                   '- 取回核对状态：已核对并替换\n- 任务状态：成功\n'
                   '## 4. 审阅区\n原文件曾获用户批准采用，现已留存。\n')
        final = self.episode + '/其他资料/执行附件/EP001-C001-P001-R004-一采/收尾取回.mp4'
        self.write(final, '收尾裁尾后的文件：同一R、同一候选身份')
        (self.project / final).replace(self.project / candidate)
        after = self.videos()[0]
        self.assertEqual(after['key'], before['key'])
        self.assertEqual(after['run'], before['run'])
        self.assertEqual(after['candidateNumber'], before['candidateNumber'])
        self.assertNotEqual(after['fileRevision'], before['fileRevision'])
        self.assertNotEqual(after['url'], before['url'])
        self.assertEqual(after['deliveryStatus'], '已核对并替换')
        self.assertFalse(after['approved'])
        self.assertEqual(after['context'], before['context'])
        self.assertEqual((self.project / archive).read_text(encoding='utf-8'), 'EP001-C001-P001-R004-一采')
        with patch.object(main, 'store', ProjectStore(self.project.parent)), TestClient(main.app) as client:
            video = client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']['C001'][0]['videos'][0]
            response = client.get(video['url'])
            self.assertIn('收尾裁尾', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            # Old native-player range requests must still read the reviewed bytes.
            old_url = '/api/projects/示例项目/files/' + before['url']
            self.assertEqual(client.get(old_url).text, 'EP001-C001-P001-R004-一采')
            ranged = client.get(old_url, headers={'Range': 'bytes=0-4'})
            self.assertEqual(ranged.status_code, 206)
            self.assertEqual(ranged.content, b'EP001')
            self.assertEqual(client.get(video['url'].split('?')[0] + '?v=unknown').status_code, 404)

    def test_unrecorded_history_is_not_assumed_verified_or_successful(self):
        self.add_run('R001')
        video = self.videos()[0]
        self.assertEqual(video['deliveryStatus'], '未记录')
        self.assertEqual(video['taskStatus'], '未记录')
        self.assertEqual(video['checkedAt'], '未记录')
        self.assertIn('?v=', video['url'])

    def test_frozen_workdraft_displays_only_its_current_segment_without_changing_bytes(self):
        context, _, _ = self.add_run('R003')
        text = self.storyboard('v003', '冻结工作稿当次镜头')
        nested = '\n'.join('##' + line if line.startswith('#') else line for line in text.splitlines())
        frozen = '# 场次分镜工作稿\n## 1. 当前内容\n' + nested + '\n## 2. 历史记录\n旧稿不展示。\n'
        self.write(context['storyboard']['file'], frozen)
        result = self.videos()[0]['context']
        self.assertEqual(result['issues'], [])
        self.assertIn('冻结工作稿当次镜头', result['scriptHtml'])
        self.assertNotIn('其他分段不展示', result['scriptHtml'])
        self.assertNotIn('旧稿不展示', result['scriptHtml'])
        self.assertEqual([(shot['id'], shot['duration']) for shot in result['shots']], [('EP001-SH001', 3)])
        self.assertEqual((self.project / context['storyboard']['file']).read_text(encoding='utf-8'), frozen)

    def automatic_task(self, selected=(0, 1), common_enabled=True):
        root = self.project / (self.episode + '/其他资料/执行附件/EP001-C001-P001-R004-一采')
        script = self.episode + '/03-分镜脚本/EP001-C001-场次分镜.md'
        self.write(script, self.storyboard('v21', '当次第一段') + '**时间**：00:11-00:14\n**时长**：3秒\n第二段原文。\n')
        self.write(self.episode + '/03-分镜脚本/EP001-分镜索引.md',
                   '| 场次 | 分段 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                   '| EP001-C001 | EP001-C001-P001 | 11 |\n| EP001-C001 | EP001-C001-P002 | 6 |\n')
        self.write('图片/公共.png', '提交时公共原图')
        self.write('图片/本组.png', '提交时本组原图')
        common = {'prompt': '实际公共正文', 'commonEnabled': common_enabled, 'taskType': 'r2v',
                  'refs': [{'imageFile': 'remote/common.png', 'index': 0}]}
        groups = [{'prompt': '第一段实际英文', 'refs': [{'imageFile': 'remote/local.png', 'index': 1}]},
                  {'prompt': '第二段实际英文', 'refs': []}]
        mapping = {'scene': 'EP001-C001', 'scene_storyboard_version': 'v21', 'selected_indices': list(selected),
                   'segments': [], 'uploads': [{'input_path': 'remote/common.png', 'file': '图片/公共.png'},
                                              {'input_path': 'remote/local.png', 'file': '图片/本组.png'}],
                   'prompt_id': '既有事实不得修改', 'checks': {'原执行检查': True}}
        for number, run in ((1, 'R004'), (2, 'R003')):
            identity = f'EP001-C001-P{number:03d}-{run}-一采'
            directory = self.episode + '/其他资料/执行附件/' + identity
            mapping['segments'].append({'segment': f'EP001-C001-P{number:03d}', 'round': run,
                                        'local_execution_dir': str(self.project / directory)})
            if number - 1 in selected:
                self.write(directory + '/中文提示词参考版.txt', f'当次中文{number}')
                self.write(self.episode + '/其他资料/候选视频/' + identity + '.mp4', identity)
        self.write(str((root / '输入映射.json').relative_to(self.project)), json.dumps(mapping, ensure_ascii=False))
        timeline = {'global': common, 'segments': groups, 'editMode': 'segment', 'runSelectEnabled': len(selected) != 2, 'runSelection': list(selected)}
        workflow = {'105001': {'class_type': 'MiniMaxH3Director',
                              'inputs': {'global_prompt': common['prompt'], 'timeline_data': json.dumps(timeline)}}}
        return root, workflow, mapping

    def test_automatic_submission_inputs_are_read_as_frozen_history(self):
        root, workflow, before = self.automatic_task()
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        mapping = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))
        self.assertEqual({key: mapping[key] for key in before}, before)
        self.assertEqual([context['identity'] for context in mapping['generation_contexts']],
                         ['EP001-C001-P001-R004-一采', 'EP001-C001-P002-R003-一采'])
        self.write(self.episode + '/03-分镜脚本/EP001-C001-场次分镜.md',
                   self.storyboard('v99', '后来新版').replace('### 分段 P002',
                       '**起始画面**：新版开镜。\n\n**结束画面**：新版切走。\n\n'
                       '**转场方式**：新版切点。\n\n### 分段 P002'))
        self.write('图片/公共.png', '后来更新原图')
        with patch.object(main, 'store', ProjectStore(self.project.parent)):
            with TestClient(main.app) as client:
                segments = client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']['C001']
                first, second = [segment['videos'][0]['context'] for segment in segments]
                self.assertIn('当次第一段', first['scriptHtml'])
                self.assertNotIn('后来新版', first['scriptHtml'])
                for label in ('起始画面', '结束画面', '转场方式'):
                    self.assertNotIn('<strong>' + label + '</strong>', first['scriptHtml'])
                    self.assertTrue(all('<strong>' + label + '</strong>' not in shot['html']
                                        for shot in first['shots']))
                self.assertIn('第二段原文', second['scriptHtml'])
                self.assertEqual(first['prompts']['english'], '实际公共正文\n\n第一段实际英文')
                self.assertEqual(second['prompts']['chinese'], '当次中文2')
                self.assertEqual(first['issues'], [])
                self.assertEqual(second['issues'], [])
                self.assertEqual(client.get(first['references']['common'][0]['url']).text, '提交时公共原图')
                self.assertEqual(client.get(first['references']['segment'][0]['url']).text, '提交时本组原图')
                self.assertEqual([(shot['id'], shot['duration']) for shot in second['shots']], [('EP001-SH002', 3)])

    def test_backend_actual_upload_path_keeps_original_local_material(self):
        root, workflow, before = self.automatic_task()
        inputs = workflow['105001']['inputs']
        timeline = json.loads(inputs['timeline_data'])
        timeline['global']['refs'][0]['imageFile'] = 'new-server/renamed.png'
        inputs['timeline_data'] = json.dumps(timeline)
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass',
            {'new-server/renamed.png': {'file': str(self.project / '图片/公共.png')}})
        mapping = json.loads((root / '输入映射.json').read_text('utf-8'))
        self.assertEqual(mapping['uploads'], before['uploads'])
        reference = mapping['generation_contexts'][0]['references']['common'][0]
        self.assertEqual((self.project / reference['file']).read_text('utf-8'), '提交时公共原图')

    def test_workflow_revision_reuses_materials_and_rejects_changed_input(self):
        root, workflow, mapping = self.automatic_task(selected=(0,))
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        old = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts'][0]
        revised = root.with_name('EP001-C001-P001-R005-一采')
        mapping['segments'][0].update(round='R005', local_execution_dir=str(revised),
            materials_from={'mapping': str((root / '输入映射.json').relative_to(self.project)), 'identity': old['identity']})
        mapping['storyboard_file'] = old['storyboard']['file']
        workflow['105001']['inputs']['seed'] = 1234
        self.write(str((revised / '输入映射.json').relative_to(self.project)), json.dumps(mapping))
        writer.prepare_generation_context(self.project, revised, workflow, 'video-first-pass')
        saved = json.loads((revised / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts'][0]
        self.assertEqual(saved['identity'], 'EP001-C001-P001-R005-一采')
        for key in ('storyboard', 'prompts', 'references'):
            self.assertEqual(saved[key], old[key])
        self.assertFalse((revised / '输入素材').exists())
        self.assertFalse((revised / '分镜脚本.md').exists())
        self.write('图片/公共.png', '已被替换的输入')
        with self.assertRaisesRegex(ValueError, '不可覆盖'):
            writer.prepare_generation_context(self.project, revised, workflow, 'video-first-pass')

    def test_same_revision_retry_keeps_context_and_old_mapping(self):
        root, workflow, mapping = self.automatic_task(selected=(0,))
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        original = (root / '输入映射.json').read_bytes()
        old = json.loads(original)['generation_contexts'][0]
        retry = root / '执行-20261008-220000'
        mapping['segments'][0].update(local_execution_dir=str(retry), materials_from={
            'mapping': str((root / '输入映射.json').relative_to(self.project)), 'identity': old['identity']})
        mapping['storyboard_file'] = old['storyboard']['file']
        self.write(str((retry / '输入映射.json').relative_to(self.project)), json.dumps(mapping))
        writer.prepare_generation_context(self.project, retry, workflow, 'video-first-pass')
        self.assertEqual((root / '输入映射.json').read_bytes(), original)
        self.assertEqual(json.loads((retry / '输入映射.json').read_text())['generation_contexts'], [old])
        self.assertEqual(len(self.videos()), 1)

    def test_same_revision_stages_have_separate_status_and_approval(self):
        self.add_run('R000')
        self.add_run('R000', '二采', 'EP001-C001-P001-R000-一采')
        record = self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md'
        self.write(record, '## 1. 当前选定结果\n| 处理阶段 | 当前选定文件 | R编号 | 人工批准依据 |\n'
            '| --- | --- | --- | --- |\n| 一采 | [视频](../候选视频/EP001-C001-P001-R000-一采.mp4) | R000 | 人工批准 |\n'
            '## 2. 修订版各阶段与采用记录\n### R000-一采\n- 处理阶段：一采\n- 任务状态：成功\n- 用户决定：批准采用\n'
            '### R000-二采\n- 处理阶段：二采\n- 任务状态：运行中\n- 用户决定：待审核\n')
        videos = {video['stage']: video for video in self.videos()}
        self.assertEqual(videos['一采']['taskStatus'], '成功')
        self.assertTrue(videos['一采']['approved'])
        self.assertEqual(videos['二采']['taskStatus'], '运行中')
        self.assertFalse(videos['二采']['approved'])

    def test_conflicting_retry_context_is_not_silently_selected(self):
        context, root, _ = self.add_run('R000')
        context['prompts']['english'] = context['prompts']['chinese']
        self.write(root + '/执行-20261008-220000/输入映射.json', json.dumps({'generation_contexts': [context]}))
        with self.assertRaisesRegex(ValueError, '关联重复'):
            self.videos()

    def test_same_revision_replacement_retains_reviewed_file_bytes(self):
        _, _, candidate = self.add_run('R000')
        path = self.project / candidate
        before = path.stat()
        revision = str(before.st_mtime_ns) + '-' + str(before.st_size)
        archive = self.project / (self.episode + '/其他资料/历史版本/' + path.stem + '-替换前-20261008-220000.mp4')
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, archive)
        path.write_text('同R补做后的新文件', encoding='utf-8')
        store = ProjectStore(self.project.parent)
        self.assertEqual(store.file('示例项目', candidate, revision).read_bytes(), archive.read_bytes())
        self.assertNotEqual(store.file('示例项目', candidate).read_bytes(), archive.read_bytes())

    def test_selection_and_disabled_common_inputs_follow_actual_api(self):
        root, workflow, _ = self.automatic_task(selected=(1,), common_enabled=False)
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        contexts = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts']
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]['identity'], 'EP001-C001-P002-R003-一采')
        self.assertEqual(contexts[0]['references'], {'common': [], 'segment': []})
        self.assertEqual((self.project / contexts[0]['prompts']['english']).read_text(encoding='utf-8').strip(), '第二段实际英文')
        self.assertFalse((root / '模型提示词.txt').exists())

    def test_external_groups_cannot_be_misrecorded_as_native_inputs(self):
        root, workflow, _ = self.automatic_task()
        workflow['105001']['inputs']['r2v_groups'] = ['external-node', 0]
        with self.assertRaisesRegex(ValueError, '不可按原生组记录外部输入'):
            writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        self.assertFalse((root / '分镜脚本.md').exists())

    def test_automatic_references_follow_slots_and_local_replacement(self):
        root, workflow, _ = self.automatic_task(selected=(0,))
        timeline = json.loads(workflow['105001']['inputs']['timeline_data'])
        timeline['global']['refs'] = [{'imageFile': 'remote/common.png', 'index': 2}, {'imageFile': 'remote/common.png', 'index': 0}]
        timeline['segments'][0]['refs'] = [{'imageFile': 'remote/local.png', 'index': 2}]
        workflow['105001']['inputs']['timeline_data'] = json.dumps(timeline)
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        context = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts'][0]
        self.assertEqual([item['label'] for item in context['references']['common']], ['<Picture 1>'])
        self.assertEqual([item['label'] for item in context['references']['segment']], ['<Picture 3>'])

    def test_automatic_second_pass_saves_own_inputs_and_source(self):
        root, workflow, mapping = self.automatic_task(selected=(0,))
        directory = root.with_name('EP001-C001-P001-R005-二采')
        mapping['segments'][0].update(round='R005', local_execution_dir=str(directory), source='EP001-C001-P001-R004-一采')
        self.write(str((directory / '输入映射.json').relative_to(self.project)), json.dumps(mapping))
        writer.prepare_generation_context(self.project, directory, workflow, 'video-second-pass')
        context = json.loads((directory / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts'][0]
        self.assertEqual(context['source'], 'EP001-C001-P001-R004-一采')
        self.assertEqual(context['identity'], 'EP001-C001-P001-R005-二采')
        self.assertEqual((self.project / context['prompts']['english']).read_text(encoding='utf-8'), '实际公共正文\n\n第一段实际英文')

    def test_all_media_inputs_are_frozen_and_sorted_for_preview(self):
        root, workflow, mapping = self.automatic_task(selected=(0,))
        timeline = json.loads(workflow['105001']['inputs']['timeline_data'])
        for name, field, file_field in [('公共视频.mp4', 'refVideos', 'videoFile'), ('公共声音.wav', 'refAudios', 'audioFile')]:
            self.write('素材/' + name, '提交时' + name)
            mapping['uploads'].append({'input_path': 'remote/' + name, 'file': '素材/' + name})
            timeline['global'][field] = [{file_field: 'remote/' + name, 'index': 0}]
        self.write(str((root / '输入映射.json').relative_to(self.project)), json.dumps(mapping))
        workflow['105001']['inputs']['timeline_data'] = json.dumps(timeline)
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        self.write('素材/公共视频.mp4', '后来视频')
        self.write('素材/公共声音.wav', '后来声音')
        # Historical mappings may have a different array order; preview still sorts by media type.
        saved = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))
        saved['generation_contexts'][0]['references']['common'].reverse()
        self.write(str((root / '输入映射.json').relative_to(self.project)), json.dumps(saved))
        with patch.object(main, 'store', ProjectStore(self.project.parent)), TestClient(main.app) as client:
            references = client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']['C001'][0]['videos'][0]['context']['references']['common']
            self.assertEqual([(item['kind'], item['label']) for item in references],
                             [('image', '<Picture 1>'), ('video', '<Video 1>'), ('audio', '<Audio 1>')])
            self.assertEqual(client.get(references[1]['url']).text, '提交时公共视频.mp4')
            self.assertEqual(client.get(references[2]['url']).text, '提交时公共声音.wav')

    def test_multimedia_common_override_is_independent_for_each_type(self):
        for enabled in (True, False):
            with self.subTest(common_enabled=enabled):
                root, workflow, mapping = self.automatic_task(selected=(0,), common_enabled=enabled)
                # Separate execution records for the two cases.
                root = root.with_name('EP001-C001-P001-R006-一采' if enabled else 'EP001-C001-P001-R007-一采')
                mapping['segments'][0].update(round='R006' if enabled else 'R007', local_execution_dir=str(root))
                timeline = json.loads(workflow['105001']['inputs']['timeline_data'])
                for scope, target in [('公共', timeline['global']), ('本组', timeline['segments'][0])]:
                    for extension, field, file_field in [('mp4', 'refVideos', 'videoFile'), ('wav', 'refAudios', 'audioFile')]:
                        name = scope + '.' + extension
                        self.write('素材/' + name, name)
                        mapping['uploads'].append({'input_path': name, 'file': '素材/' + name})
                        target[field] = [{file_field: name, 'index': 0}]
                timeline['global']['refVideos'].append({'videoFile': '公共.mp4', 'index': 2})
                self.write(str((root / '输入映射.json').relative_to(self.project)), json.dumps(mapping))
                workflow['105001']['inputs']['timeline_data'] = json.dumps(timeline)
                writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
                refs = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts'][0]['references']
                self.assertEqual([item['label'] for item in refs['common']], ['<Picture 1>', '<Video 3>'] if enabled else [])
                self.assertEqual([item['label'] for item in refs['segment']], ['<Picture 2>', '<Video 1>', '<Audio 1>'])

    def test_legacy_video_input_is_slot_one_and_native_slot_one_wins(self):
        root, workflow, mapping = self.automatic_task(selected=(0,))
        self.write('素材/兼容.mp4', '实际兼容输入')
        mapping['uploads'].append({'input_path': 'legacy.mp4', 'file': '素材/兼容.mp4'})
        self.write(str((root / '输入映射.json').relative_to(self.project)), json.dumps(mapping))
        timeline = json.loads(workflow['105001']['inputs']['timeline_data'])
        timeline['global']['referenceVideo'] = {'fileName': 'legacy.mp4'}
        timeline['segments'][0]['referenceVideo'] = {'videoFile': 'unsubmitted.mp4'}
        timeline['segments'][0]['refVideos'] = [{'videoFile': 'legacy.mp4', 'index': 0}]
        workflow['105001']['inputs']['timeline_data'] = json.dumps(timeline)
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        refs = json.loads((root / '输入映射.json').read_text(encoding='utf-8'))['generation_contexts'][0]['references']
        self.assertEqual([item['label'] for item in refs['common']], ['<Picture 1>'])
        self.assertEqual([item['label'] for item in refs['segment']], ['<Picture 2>', '<Video 1>'])
        self.assertEqual((self.project / refs['segment'][1]['file']).read_text(encoding='utf-8'), '实际兼容输入')

    def test_same_preparation_is_idempotent_and_changed_input_cannot_overwrite(self):
        root, workflow, _ = self.automatic_task()
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        saved = (root / '输入映射.json').read_bytes()
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        self.assertEqual((root / '输入映射.json').read_bytes(), saved)
        self.write('图片/公共.png', '另一版图')
        with self.assertRaisesRegex(ValueError, '不可覆盖'):
            writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        self.assertEqual((root / '输入素材/公共.png').read_text(encoding='utf-8'), '提交时公共原图')
        self.assertEqual((root / '输入映射.json').read_bytes(), saved)

    def test_mismatched_prepared_prompt_cannot_be_saved_as_actual(self):
        root, workflow, _ = self.automatic_task()
        self.write(str((root / '模型提示词.txt').relative_to(self.project)), '错误正文')
        with self.assertRaisesRegex(ValueError, '冻结英文与本次实际API'):
            writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        self.assertNotIn('generation_contexts', json.loads((root / '输入映射.json').read_text(encoding='utf-8')))
        self.assertFalse((root / '分镜脚本.md').exists())

    def test_postprocess_automatically_binds_source_without_own_empty_inputs(self):
        root, workflow, _ = self.automatic_task()
        writer.prepare_generation_context(self.project, root, workflow, 'video-first-pass')
        original = self.videos()[0]['context']
        identity = 'EP001-C001-P001-R005-后处理'
        record = self.project / (self.episode + '/其他资料/执行附件/' + identity)
        self.write(str((record / '输入映射.json').relative_to(self.project)), json.dumps({
            'scene': 'EP001-C001', 'selected_indices': [0],
            'segments': [{'segment': 'EP001-C001-P001', 'round': 'R005', 'source': 'EP001-C001-P001-R004-一采'}]}))
        self.write(self.episode + '/其他资料/候选视频/' + identity + '.mp4', identity)
        writer.prepare_generation_context(self.project, record, {}, 'video-postprocess')
        result = self.videos()[-1]['context']
        self.assertEqual(result['shots'], original['shots'])
        self.assertEqual(result['prompts'], original['prompts'])
        self.assertEqual(result['references'], original['references'])
        self.assertEqual(result['source'], 'EP001-C001-P001-R004-一采')

    def test_all_four_surfaces_follow_exact_run_and_original_file_links(self):
        self.add_run('R001')
        self.add_run('R002')
        with patch.object(main, 'store', ProjectStore(self.project.parent)):
            with TestClient(main.app) as client:
                videos = client.get('/api/projects/示例项目/sections/09-剧集制作').json()['children'][0]['segments']['C001'][0]['videos']
                for video in videos:
                    run = video['run']
                    context = video['context']
                    self.assertIn(run + '当次原文', context['scriptHtml'])
                    for excluded in ('最新版', '其他分段', '说明不展示', '镜号'):
                        self.assertNotIn(excluded, context['scriptHtml'])
                    self.assertEqual(context['prompts']['english'], run + ' actual submitted prompt')
                    self.assertEqual(context['prompts']['chinese'], run + ' 当次中文')
                    self.assertEqual(context['issues'], [])
                    self.assertLess(context['scriptHtml'].index('时间'), context['scriptHtml'].index('时长'))
                    self.assertLess(context['scriptHtml'].index('时长'), context['scriptHtml'].index('景别'))
                    self.assertEqual([(shot['id'], shot['duration']) for shot in context['shots']], [('EP001-SH001', 3)])
                    self.assertIn(run + '当次原文', context['shots'][0]['html'])
                    self.assertIn(run, client.get(context['scriptUrl']).text)
                    self.assertEqual(client.get(context['references']['common'][0]['url']).text, run + '公共图.png')
                    self.assertEqual(client.get(context['references']['segment'][0]['url']).text, run + '首帧.png')

    def test_shared_mapping_can_hold_different_segment_run_numbers(self):
        first, root, _ = self.add_run('R003')
        other, other_root, _ = self.add_run('R002', '二采')
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [first, other]}))
        (self.project / (other_root + '/输入映射.json')).unlink()
        self.assertEqual(self.videos()[0]['context']['prompts']['english'], 'R002 actual submitted prompt')
        self.assertEqual(self.videos()[1]['context']['prompts']['english'], 'R003 actual submitted prompt')

    def test_large_mapping_is_not_limited_to_the_text_preview_prefix(self):
        context, root, _ = self.add_run('R001')
        self.write(root + '/输入映射.json', json.dumps({'recorded_request': 'x' * (300 * 1024),
                                                     'generation_contexts': [context]}))
        self.assertEqual(self.videos()[0]['context']['prompts']['english'], 'R001 actual submitted prompt')

    def test_postprocess_inherits_recorded_source_not_newest_candidate(self):
        self.add_run('R001')
        self.add_run('R002')
        self.add_run('R003', '二采', source='EP001-C001-P001-R001-一采')
        self.add_run('R004', '后处理', source='EP001-C001-P001-R003-二采')
        context = self.videos()[-1]['context']
        self.assertIn('R001当次原文', context['scriptHtml'])
        self.assertEqual(context['prompts']['english'], 'R001 actual submitted prompt')
        self.assertEqual(context['source'], 'EP001-C001-P001-R003-二采')
        self.assertEqual(context['shots'], self.videos()[0]['context']['shots'])

    def test_second_pass_uses_its_own_snapshot_and_retains_source(self):
        self.add_run('R001')
        context, root, _ = self.add_run('R002', '二采')
        context['source'] = 'EP001-C001-P001-R001-一采'
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        result = self.videos()[-1]['context']
        self.assertEqual(result['prompts']['english'], 'R002 actual submitted prompt')
        self.assertIn('R002当次原文', result['scriptHtml'])
        self.assertEqual(result['source'], 'EP001-C001-P001-R001-一采')

    def test_adoption_keeps_generation_context_and_candidate_identity(self):
        self.add_run('R001')
        _, _, candidate = self.add_run('R002')
        before = self.videos()[1]['context']
        adopted = self.episode + '/06-阶段采用视频/01-一采/C001-场次/EP001-C001-P001-R002-一采.mp4'
        (self.project / adopted).parent.mkdir(parents=True)
        (self.project / candidate).rename(self.project / adopted)
        self.write(self.episode + '/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md',
                   '## 1. 当前选定结果\n| 处理阶段 | 当前选定文件 | R编号 | 来源任务 | 人工批准依据 |\n'
                   '| --- | --- | --- | --- | --- |\n'
                   '| 一采 | [选定](../../06-阶段采用视频/01-一采/C001-场次/EP001-C001-P001-R002-一采.mp4) | R002 | 当次任务 | 用户批准 |\n'
                   '## 2. 逐次执行与采用记录\n### R002\n- 处理阶段：一采\n- 用户决定：批准采用\n')
        current = self.videos()[1]
        self.assertTrue(current['approved'])
        self.assertEqual(current['candidateNumber'], 2)
        self.assertEqual(current['context'], before)

    def test_missing_or_mismatched_history_never_uses_current_sources(self):
        context, root, _ = self.add_run('R001')
        self.write(context['storyboard']['file'], self.storyboard('v99', '错误版本'))
        (self.project / (root + '/输入素材/首帧.png')).unlink()
        result = self.videos()[0]['context']
        self.assertEqual(result['scriptHtml'], '')
        self.assertEqual(result['shots'], [])
        self.assertTrue(result['references']['segment'][0]['missing'])
        self.assertIn('文件版本与记录不一致', ' '.join(result['issues']))
        (self.project / (root + '/输入映射.json')).unlink()
        result = self.videos()[0]['context']
        self.assertEqual(result['scriptHtml'], '')
        self.assertEqual(result['prompts']['english'], '')

    def test_shots_keep_historical_order_durations_and_scene_times(self):
        context, _, _ = self.add_run('R001')
        text = ('- 文档版本：v001\n## 1. 镜头正文\n### 分段 P001\n'
                '#### EP001-SH003\n**时间**：00:11-00:14\n**时长**：3秒\n**景别**：第一镜。\n'
                '#### EP001-SH004\n**时间**：00:14-00:17.5\n**时长**：3.5秒。\n**景别**：第二镜。\n'
                '### 分段 P002\n#### EP001-SH005\n**时长**：9秒\n下一段。\n')
        self.write(context['storyboard']['file'], text)
        result = self.videos()[0]['context']
        self.assertEqual([(shot['id'], shot['duration']) for shot in result['shots']],
                         [('EP001-SH003', 3), ('EP001-SH004', 3.5)])
        self.assertIn('00:11-00:14', result['shots'][0]['html'])
        self.assertIn('第一镜', result['shots'][0]['html'])
        self.assertNotIn('第二镜', result['shots'][0]['html'])
        self.assertNotIn('下一段', result['shots'][1]['html'])
        self.assertEqual(result['issues'], [])
        self.assertEqual((self.project / context['storyboard']['file']).read_text(encoding='utf-8'), text)

    def test_missing_or_invalid_shot_duration_is_not_invented(self):
        context, _, _ = self.add_run('R001')
        for value in ('', '**时长**：0秒', '**时长**：待定', '**时长**：-3秒'):
            with self.subTest(value=value):
                self.write(context['storyboard']['file'], self.storyboard('v001', '原文保持').replace('**时长**：3秒', value))
                result = self.videos()[0]['context']
                self.assertIsNone(result['shots'][0]['duration'])
                self.assertIn('原文保持', result['scriptHtml'])
                self.assertIn('无法跟视频对齐', ' '.join(result['issues']))

    def test_context_sources_cannot_escape_project_or_form_a_cycle(self):
        context, root, _ = self.add_run('R001')
        context['storyboard']['file'] = '../outside.md'
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        with self.assertRaisesRegex(ValueError, '越出项目'):
            self.videos()
        context = {'identity': context['identity'], 'source': context['identity']}
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        with self.assertRaisesRegex(ValueError, '来源循环'):
            self.videos()

    def test_archived_chinese_requires_same_submitted_english(self):
        context, root, _ = self.add_run('R001')
        archive = self.episode + '/其他资料/历史版本/提示词旧版.md'
        context['prompts']['chinese'] = archive
        self.write(root + '/输入映射.json', json.dumps({'generation_contexts': [context]}))
        for english, expected in [('R001 actual submitted prompt', '对应翻译'), ('新版不同的英文', '')]:
            self.write(archive, '## 提交给模型的完整提示词\n```text\n' + english + '\n```\n'
                       '## 中文提示词参考版\n```text\n对应翻译\n```\n')
            self.assertEqual(self.videos()[0]['context']['prompts']['chinese'], expected)
        self.write(root + '/模型提示词.txt', 'R001 actual submitted prompt\r\n')
        self.write(archive, '## 提交给模型的完整提示词\n```text\nR001 actual submitted prompt\n```\n'
                   '## 中文提示词参考版\n```text\n对应翻译\n```\n')
        self.assertEqual(self.videos()[0]['context']['prompts']['chinese'], '对应翻译')
