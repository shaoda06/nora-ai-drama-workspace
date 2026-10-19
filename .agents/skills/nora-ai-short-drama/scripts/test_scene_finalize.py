"""阶段留档行为测试：隔离项目、真实基准画布和模拟原生导出；不访问远端。"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import scene_finalize as tool

BASE = Path(__file__).resolve().parents[1] / 'references/comfyui-workflow'


class NativeClient:
    calls = []
    media = {}
    corrupt = False
    missing = False

    def __init__(self, url, timeout):
        self.url = url

    def json(self, route, data, headers):
        self.calls.append(('preflight', route))
        return {'missing': ['missing.png'] if self.missing else []}

    def open(self, route, data, headers):
        self.calls.append(('export', route))
        body = json.loads(data)
        timeline = body['timeline']
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            def portable(value):
                if isinstance(value, dict):
                    for k, v in value.items():
                        if k in tool.MEDIA and v:
                            dest = 'extra/' + Path(v).name
                            if dest not in archive.namelist():
                                archive.writestr(dest, self.media[v])
                            value[k] = dest
                        else:
                            portable(v)
                elif isinstance(value, list):
                    for item in value:
                        portable(item)
            portable(timeline)
            if self.corrupt:
                timeline['segments'][0]['prompt'] = '错误正文'
            archive.writestr('pack.json', json.dumps({'format': 'minimax-h3-director-pack', 'formatVersion': 1,
                                                     'widgets': body['widgets'], 'output': timeline['output']}))
            archive.writestr('timeline.json', json.dumps(timeline))
            archive.writestr('shared_params/shared_params.json', json.dumps(timeline['global']))
            for i, g in enumerate(timeline['segments']):
                archive.writestr(f'asset_groups/{i + 1:02d}/group.json', json.dumps(g))
        stream = io.BytesIO(payload.getvalue())
        stream.headers = {'Content-Type': 'application/zip', 'Content-Length': str(len(payload.getvalue())),
                          'X-Pack-Missing': '[]', 'X-Pack-Download-Name': 'native.mmxpack.zip'}
        return stream


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "projects/test"
        self.ep = self.root / '09-剧集制作/EP001'
        self.extra = self.ep / '其他资料'
        self.put(self.root / '项目进度.md', '# 原项目进度\n')
        self.put(self.extra / '工作稿/EP001-生成说明-工作稿.md', '# 原生成说明\n')
        self.put(self.ep / '03-分镜脚本/EP001-分镜索引.md',
                 '| EP001-C001 | [分镜](scene.md) | EP001-C001-P001 | 其他 |\n'
                 '| EP001-C001 | [分镜](scene.md) | EP001-C001-P002 | 其他 |\n')
        self.plan = {'episode': 'EP001', 'scene': 'C001', 'stage': '一采', 'items': []}
        NativeClient.calls, NativeClient.media = [], {'ref.png': b'frozen image'}
        NativeClient.corrupt, NativeClient.missing = False, False
        self.put(self.root / '素材/ref.png', b'frozen image')
        self.originals = {}

    def put(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def pair(self, stage, part, identity):
        name = 'Nora-RTX-RIFE-自动切镜保护超分插帧' if stage == '后处理' else 'Minimax-H3-导演台-视频生成-标准版'
        api = tool.adopt.load(BASE / (name + '.api.json'))
        canvas = tool.adopt.load(BASE / (name + '.workflow.json'))
        if stage == '后处理':
            key = next(k for k, n in api.items() if n['class_type'] == 'LoadVideo')
            file = f'EP001-C001-{part}-R001-二采.mp4'
            api[key]['inputs']['file'] = file
            n = next(n for n in canvas['nodes'] if str(n['id']) == key)
            n['widgets_values_named']['file'] = file
            n['widgets_values'] = list(n['widgets_values_named'].values())
        else:
            key = next(k for k, n in api.items() if n['class_type'] == 'MiniMaxH3Director')
            inputs = api[key]['inputs']
            t = json.loads(inputs['timeline_data'])
            g = {'id': f'EP001-C001-{part}', 'start': 0, 'length': 25, 'frameCount': 25, 'durationSec': 1,
                 'prompt': part + ' <Picture 1>', 'negativePrompt': '', 'taskType': 'r2v', 'refs': [],
                 'refAudios': [], 'refVideos': [], 'genImage': {'imageFile': '', 'fileName': ''},
                 'startImage': None, 'endImage': None, 'continuityFromPrev': False,
                 'refImageSize': 'max', 'loras': [], 'referenceVideo': {'videoFile': '', 'fileName': ''}}
            t.update(editMode='segment', totalFrames=25, segments=[g], runSelectEnabled=True, runSelection=[0],
                     selectedIndex=0, keyframes=[], videoClips=[], durationSec=1,
                     video={'fileName': '', 'sourceFrameCount': 25, 'frames': []})
            t['global'].update(taskType='r2v', prompt='共同正文', commonEnabled=True,
                               refs=[{'index': 0, 'imageFile': 'ref.png', 'fileName': 'ref.png', 'type': 'input', 'subfolder': ''}],
                               refAudios=[], refVideos=[])
            t['batchWorkspaces'] = {'r2v': {'globalCommon': copy.deepcopy(t['global']), 'segments': copy.deepcopy(t['segments']),
                                          'selectedIndex': 0, 'editMode': 'segment', 'runSelectEnabled': True, 'runSelection': [0]}}
            inputs.update(timeline_data=json.dumps(t, ensure_ascii=False), global_prompt='共同正文', total_frames=25)
            n = next(n for n in canvas['nodes'] if str(n['id']) == key)
            for field in ('timeline_data', 'global_prompt', 'total_frames'):
                n['widgets_values_named'][field] = inputs[field]
            n['widgets_values'] = list(n['widgets_values_named'].values())
        return api, canvas

    def item(self, part, stage='一采', content=None):
        identity = f'EP001-C001-{part}-R001-{stage}'
        record = self.extra / '执行附件' / identity
        api, canvas = self.pair(stage, part, identity)
        frozen = record / '模型提示词.txt'
        if stage != '后处理':
            self.put(frozen, '共同正文\n\n' + part + ' <Picture 1>')
        remote = {'filename': part + '.mp4', 'subfolder': identity, 'type': 'output'}
        selected = self.ep / '06-阶段采用视频' / tool.adopt.STAGES[stage] / 'C001-场次' / (identity + '.mp4')
        data = identity.encode()
        self.put(selected, data)
        receipt = {'remote': remote, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'path': str(selected)}
        self.put(record / '取回响应.json', {'data': receipt})
        context = {'identity': identity}
        mapped = {'prompt_id': identity + '-prompt', 'url': 'http://example.invalid', 'selected_indices': [0],
                  'segments': [{'segment': 'EP001-C001-' + part, 'round': 'R001', 'remote': remote}],
                  'uploads': [{'input_path': 'ref.png', 'file': '素材/ref.png'}], 'generation_contexts': [context]}
        if stage != '后处理':
            context.update(prompts={'english': str(frozen)}, references={'common': [{'label': '<Picture 1>', 'file': '素材/ref.png'}], 'segment': []})
        else:
            context['source'] = content['identity']
            source_video = self.ep / '06-阶段采用视频/02-二采/C001-场次' / (content['identity'] + '.mp4')
            video = source_video.read_bytes()
            mapped.update(source_bytes=len(video), source_sha256=hashlib.sha256(video).hexdigest(),
                          uploads=[{'input_path': source_video.name, 'file': str(source_video)}])
        self.put(record / '输入映射.json', mapped)
        self.put(record / '实际.api.json', api)
        self.put(record / '实际.workflow.json', canvas)
        self.put(record / '请求.json', {'prompt': api})
        self.put(record / '提交响应.json', {'data': {'prompt_id': mapped['prompt_id']}})
        draft = self.extra / '工作稿' / f'EP001-C001-{part}-视频制作-工作稿.md'
        text = draft.read_text(encoding='utf-8') if draft.exists() else '# 工作稿\n## 1. 当前选定结果\n\n'
        heading = '审阅-r001-' + stage
        row = f'| {stage} | [{selected.name}]({tool.adopt.link(draft, selected)}) | R001 | [审核](#{heading}) | [依据](#{heading}) |\n'
        if '\n## 2.' in text:
            text = text.replace('\n## 2.', row + '\n## 2.', 1)
        else:
            text += row + '\n## 2. 执行和审核\n'
        text += f'\n### {heading}\n- 决定：批准采用\n- 对应具体输出：{selected.name}\n'
        self.put(draft, text)
        item = {'identity': identity, 'mapping': str(record / '输入映射.json'), 'api': str(record / '实际.api.json'),
                'canvas': str(record / '实际.workflow.json'), 'receipt': str(record / '取回响应.json')}
        if content:
            item.update(content=content, source_video=str(source_video))
        self.originals[record / '请求.json'] = (record / '请求.json').read_bytes()
        self.originals[record / '实际.api.json'] = (record / '实际.api.json').read_bytes()
        self.originals[record / '实际.workflow.json'] = (record / '实际.workflow.json').read_bytes()
        return item

    def run_plan(self, apply=True):
        path = self.extra / '执行附件/阶段留档请求.json'
        self.put(path, self.plan)
        with patch.object(tool.client, 'Client', NativeClient):
            return tool.finalize(argparse.Namespace(project=str(self.root), plan=str(path), apply=apply, timeout=30))

    def replace_timeline(self, item, timeline):
        api = tool.adopt.load(Path(item['api']))
        key = next(k for k, n in api.items() if n['class_type'] == 'MiniMaxH3Director')
        api[key]['inputs']['timeline_data'] = json.dumps(timeline, ensure_ascii=False)
        canvas = tool.adopt.load(Path(item['canvas']))
        node = next(n for n in canvas['nodes'] if str(n['id']) == key)
        node['widgets_values_named']['timeline_data'] = api[key]['inputs']['timeline_data']
        node['widgets_values'] = list(node['widgets_values_named'].values())
        self.put(Path(item['api']), api)
        self.put(Path(item['canvas']), canvas)
        self.put(Path(item['mapping']).parent / '请求.json', {'prompt': api})

    def test_independent_group_ids_follow_mapping_order_and_keep_original_ids(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        for i, item in enumerate(self.plan['items']):
            api = tool.adopt.load(Path(item['api']))
            node = next(n for n in api.values() if n['class_type'] == 'MiniMaxH3Director')
            timeline = json.loads(node['inputs']['timeline_data'])
            timeline['segments'][0]['id'] = '项目-独立组-' + str(i)
            mapping = tool.adopt.load(Path(item['mapping']))
            if i == 0:
                decoy = copy.deepcopy(timeline['segments'][0])
                decoy.update(id='未运行组', prompt='不能选用的正文')
                timeline['segments'].insert(0, decoy)
                timeline['runSelection'] = [1]
                mapping['segments'].insert(0, {'segment': 'EP001-C001-P002', 'round': 'R001'})
                mapping['selected_indices'] = [1]
            timeline['batchWorkspaces']['r2v'].update(
                segments=copy.deepcopy(timeline['segments']), runSelection=timeline['runSelection'])
            self.replace_timeline(item, timeline)
            self.put(Path(item['mapping']), mapping)
        result = self.run_plan()
        with zipfile.ZipFile(result['pack']) as archive:
            timeline = json.loads(archive.read('timeline.json'))
        self.assertEqual([g['id'] for g in timeline['segments']], ['项目-独立组-0', '项目-独立组-1'])
        self.assertEqual([g['prompt'] for g in timeline['segments']], ['P001 <Picture 1>', 'P002 <Picture 1>'])

    def test_group_mapping_length_mismatch_stops_before_export(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        item = self.plan['items'][0]
        mapping = tool.adopt.load(Path(item['mapping']))
        mapping['segments'].append({'segment': 'EP001-C001-P003', 'round': 'R001'})
        self.put(Path(item['mapping']), mapping)
        with self.assertRaisesRegex(ValueError, '原组序'):
            self.run_plan()
        self.assertFalse(NativeClient.calls)

    def test_postprocess_without_uploads_uses_successful_task_upload_records(self):
        contents = [self.item(p, '二采') for p in ('P001', 'P002')]
        self.plan['stage'] = '后处理'
        self.plan['items'] = [self.item(p, '后处理', c) for p, c in zip(('P001', 'P002'), contents)]
        originals = {}
        for item in self.plan['items']:
            folder = Path(item['mapping']).parent
            mapping = tool.adopt.load(Path(item['mapping']))
            upload = mapping.pop('uploads')[0]
            request = tool.adopt.load(folder / '请求.json')
            loader = next(n for n in request['prompt'].values() if n['class_type'] == 'LoadVideo')
            loader['inputs']['file'] = 'uploaded/' + loader['inputs']['file']
            self.put(folder / '请求.json', request)
            self.put(Path(item['mapping']), mapping)
            self.put(folder / '后台过程记录.json', [
                {'stage': 'upload', 'result': 'started', 'file': upload['file']},
                {'stage': 'upload', 'result': 'success', 'file': upload['file'], 'remote': {
                    'input_path': loader['inputs']['file'], 'bytes': mapping['source_bytes'],
                    'sha256': mapping['source_sha256']}}])
            originals[Path(item['mapping'])] = Path(item['mapping']).read_bytes()
        result = self.run_plan()
        self.assertEqual(result['state'], 'completed')
        canvas = tool.adopt.load(Path(result['canvas']))
        paths = [n['widgets_values_named']['file'] for n in canvas['nodes'] if n['type'] == 'LoadVideo']
        self.assertEqual(paths, ['uploaded/EP001-C001-P001-R001-二采.mp4',
                                 'uploaded/EP001-C001-P002-R001-二采.mp4'])
        for path, data in originals.items():
            current = tool.adopt.load(path)
            self.assertNotIn('uploads', current)
            del current['scene_finalizations']
            self.assertEqual(current, json.loads(data))

    def test_postprocess_missing_upload_records_does_not_infer_from_request(self):
        contents = [self.item(p, '二采') for p in ('P001', 'P002')]
        self.plan['stage'] = '后处理'
        self.plan['items'] = [self.item(p, '后处理', c) for p, c in zip(('P001', 'P002'), contents)]
        item = self.plan['items'][0]
        mapping = tool.adopt.load(Path(item['mapping']))
        del mapping['uploads']
        self.put(Path(item['mapping']), mapping)
        with self.assertRaisesRegex(ValueError, '后台成功上传记录'):
            self.run_plan()
        self.assertFalse(NativeClient.calls)

    def test_postprocess_upload_record_must_match_exact_source_not_basename(self):
        contents = [self.item(p, '二采') for p in ('P001', 'P002')]
        self.plan['stage'] = '后处理'
        self.plan['items'] = [self.item(p, '后处理', c) for p, c in zip(('P001', 'P002'), contents)]
        item = self.plan['items'][0]
        folder = Path(item['mapping']).parent
        mapping = tool.adopt.load(Path(item['mapping']))
        upload = mapping.pop('uploads')[0]
        wrong_source = self.root / '其他素材' / Path(upload['file']).name
        self.put(wrong_source, Path(upload['file']).read_bytes())
        self.put(Path(item['mapping']), mapping)
        self.put(folder / '后台过程记录.json', [{
            'stage': 'upload', 'result': 'success', 'file': str(wrong_source), 'remote': {
                'input_path': upload['input_path'], 'bytes': mapping['source_bytes'],
                'sha256': mapping['source_sha256']}}])
        with self.assertRaisesRegex(ValueError, '实际输入视频与上传映射不对应'):
            self.run_plan()
        self.assertFalse(NativeClient.calls)

    def test_all_three_stages_single_pair_repeat_and_originals(self):
        for stage in tool.adopt.STAGES:
            with self.subTest(stage=stage):
                self.plan['stage'] = stage
                if stage == '后处理':
                    contents = self.plan['items']
                    self.plan['items'] = [self.item(f'P{i + 1:03d}', stage, c) for i, c in enumerate(contents)]
                else:
                    self.plan['items'] = [self.item(p, stage) for p in ('P001', 'P002')]
                before = len(NativeClient.calls)
                preview = self.run_plan(False)
                self.assertEqual(preview['state'], 'ready')
                self.assertFalse(Path(preview['pack']).exists())
                result = self.run_plan()
                self.assertEqual(result['state'], 'completed')
                self.assertEqual(len(NativeClient.calls), before + 2)
                files = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                self.run_plan()
                self.assertEqual(files, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
                self.assertFalse(list(self.extra.rglob('*.zip')))
                self.assertEqual(len(list(Path(result['pack']).parent.glob('*.workflow.json'))), 1)
                canvas = tool.adopt.load(Path(result['canvas']))
                if stage == '后处理':
                    self.assertEqual(sum(n['type'] == 'RTXVideoSuperResolution' for n in canvas['nodes']), 2)
                    self.assertEqual(sum(n['type'] == 'NoraRIFEInterpolationCutTest' for n in canvas['nodes']), 2)
                for path, data in self.originals.items():
                    self.assertEqual(path.read_bytes(), data)

    def test_partial_scope_unapproved_wrong_request_and_config_stop_before_export(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        full = copy.deepcopy(self.plan)
        self.plan['items'] = self.plan['items'][:1]
        with self.assertRaisesRegex(ValueError, '完整'):
            self.run_plan()
        self.plan = full
        item = self.plan['items'][1]
        api = tool.adopt.load(Path(item['api']))
        director = next(n for n in api.values() if n['class_type'] == 'MiniMaxH3Director')
        director['inputs']['seed'] += 1
        self.put(Path(item['api']), api)
        with self.assertRaisesRegex(ValueError, '实际获批任务'):
            self.run_plan()
        self.put(Path(item['mapping']).parent / '请求.json', {'prompt': api})
        canvas = tool.adopt.load(Path(item['canvas']))
        node = next(n for n in canvas['nodes'] if n['type'] == 'MiniMaxH3Director')
        node['widgets_values_named']['seed'] = director['inputs']['seed']
        node['widgets_values'] = list(node['widgets_values_named'].values())
        self.put(Path(item['canvas']), canvas)
        with self.assertRaisesRegex(ValueError, '无法合并'):
            self.run_plan()
        self.assertEqual(NativeClient.calls, [])

    def test_common_differences_move_into_groups_preserving_tags(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        item = self.plan['items'][1]
        api = tool.adopt.load(Path(item['api']))
        node = next(n for n in api.values() if n['class_type'] == 'MiniMaxH3Director')
        t = json.loads(node['inputs']['timeline_data'])
        t['global']['prompt'] = '另一公共正文'
        t['batchWorkspaces']['r2v']['globalCommon']['prompt'] = '另一公共正文'
        node['inputs'].update(global_prompt='另一公共正文', timeline_data=json.dumps(t, ensure_ascii=False))
        canvas = tool.adopt.load(Path(item['canvas']))
        n = next(n for n in canvas['nodes'] if n['type'] == 'MiniMaxH3Director')
        n['widgets_values_named'].update(global_prompt='另一公共正文', timeline_data=node['inputs']['timeline_data'])
        n['widgets_values'] = list(n['widgets_values_named'].values())
        self.put(Path(item['api']), api)
        self.put(Path(item['canvas']), canvas)
        self.put(Path(item['mapping']).parent / '请求.json', {'prompt': api})
        self.put(Path(item['mapping']).parent / '模型提示词.txt', '另一公共正文\n\nP002 <Picture 1>')
        result = self.run_plan()
        with zipfile.ZipFile(result['pack']) as archive:
            t = json.loads(archive.read('timeline.json'))
            self.assertFalse(t['global']['commonEnabled'])
            self.assertEqual([g['prompt'] for g in t['segments']],
                             ['共同正文\n\nP001 <Picture 1>', '另一公共正文\n\nP002 <Picture 1>'])
            self.assertEqual([g['refs'][0]['index'] for g in t['segments']], [0, 0])

    def test_existing_review_column_shared_receipt_and_summary(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        item = self.plan['items'][1]
        receipt = self.extra / '执行附件/分段取回/取回响应.json'
        self.put(receipt, tool.adopt.load(Path(item['receipt'])))
        item['receipt'] = str(receipt)
        mapping = tool.adopt.load(Path(item['mapping']))
        with self.assertRaisesRegex(ValueError, '明确关联'):
            self.run_plan()
        mapping['segments'][0]['download_receipt'] = str(receipt)
        mapping['segments'][0]['final_output'] = {'remote': mapping['segments'][0].pop('remote')}
        self.put(Path(item['mapping']), mapping)
        draft = self.extra / '工作稿/EP001-C001-P002-视频制作-工作稿.md'
        self.put(draft, draft.read_text(encoding='utf-8').replace('| [审核]', '| [执行](#执行-r001)；[审核]'))
        summary = self.extra / '工作稿/EP001-分镜索引-工作稿.md'
        self.put(summary, '# 现有分镜索引汇总\n')
        self.plan['summary'] = str(summary)
        result = self.run_plan()
        self.assertEqual(result['state'], 'completed')
        self.assertIn('定稿留档完成', summary.read_text(encoding='utf-8'))

    def test_restore_canvas_from_matching_widget_copy_without_changing_source(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        for i, item in enumerate(self.plan['items']):
            canvas = tool.adopt.load(Path(item['canvas']))
            node = next(n for n in canvas['nodes'] if n['type'] == 'MiniMaxH3Director')
            position = list(node['widgets_values_named']).index('seed')
            if i == 0:
                node['widgets_values_named']['seed'] += 1
            else:
                node['widgets_values'][position] += 1
            self.put(Path(item['canvas']), canvas)
            self.originals[Path(item['canvas'])] = Path(item['canvas']).read_bytes()
        result = self.run_plan()
        self.assertTrue(all(s['restoration'] for s in result['sources']))
        for item in self.plan['items']:
            self.assertEqual(Path(item['canvas']).read_bytes(), self.originals[Path(item['canvas'])])
        canvas = tool.adopt.load(Path(self.plan['items'][0]['canvas']))
        node = next(n for n in canvas['nodes'] if n['type'] == 'MiniMaxH3Director')
        node['widgets_values'][list(node['widgets_values_named']).index('seed')] += 2
        self.put(Path(self.plan['items'][0]['canvas']), canvas)
        with self.assertRaisesRegex(ValueError, '无法依据实际API恢复'):
            self.run_plan()

    def test_post_upload_path_restored_only_with_exact_request_and_upload(self):
        contents = [self.item(p, '二采') for p in ('P001', 'P002')]
        self.plan['stage'] = '后处理'
        self.plan['items'] = [self.item(p, '后处理', c) for p, c in zip(('P001', 'P002'), contents)]
        item = self.plan['items'][0]
        folder = Path(item['mapping']).parent
        request = tool.adopt.load(folder / '请求.json')
        loader = next(n for n in request['prompt'].values() if n['class_type'] == 'LoadVideo')
        loader['inputs']['file'] = 'uploaded/' + loader['inputs']['file']
        mapping = tool.adopt.load(Path(item['mapping']))
        mapping['uploads'][0]['input_path'] = loader['inputs']['file']
        self.put(folder / '请求.json', request)
        self.put(Path(item['mapping']), mapping)
        result = self.run_plan()
        self.assertTrue(result['sources'][0]['restoration'])
        for field in ('api', 'canvas'):
            self.assertEqual(Path(item[field]).read_bytes(), self.originals[Path(item[field])])
        model = next(n for n in request['prompt'].values() if n['class_type'] == 'RTXVideoSuperResolution')
        model['inputs']['scale'] = 999
        self.put(folder / '请求.json', request)
        with self.assertRaisesRegex(ValueError, '实际获批任务'):
            self.run_plan()

    def test_authorized_configuration_batches_full_coverage_and_resume(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        item = self.plan['items'][1]
        api = tool.adopt.load(Path(item['api']))
        node = next(n for n in api.values() if n['class_type'] == 'MiniMaxH3Director')
        node['inputs']['seed'] += 1
        canvas = tool.adopt.load(Path(item['canvas']))
        stored = next(n for n in canvas['nodes'] if n['type'] == 'MiniMaxH3Director')
        stored['widgets_values_named']['seed'] = node['inputs']['seed']
        stored['widgets_values'] = list(stored['widgets_values_named'].values())
        self.put(Path(item['api']), api)
        self.put(Path(item['canvas']), canvas)
        self.put(Path(item['mapping']).parent / '请求.json', {'prompt': api})
        self.plan['configuration_batches'] = [{'name': p, 'parts': ['EP001-C001-' + p]} for p in ('P001', 'P002')]
        with self.assertRaisesRegex(ValueError, '明确授权'):
            self.run_plan()
        self.plan['configuration_batch_authorization'] = '用户允许按实际配置分批留档'
        preview = self.run_plan(False)
        self.assertEqual(len(preview['batches']), 2)
        self.assertFalse(NativeClient.calls)
        result = self.run_plan()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(len(list(self.ep.rglob('*.zip'))), 2)
        self.assertEqual(len(NativeClient.calls), 4)
        self.run_plan()
        self.assertEqual(len(NativeClient.calls), 4)
        self.plan['configuration_batches'][1]['parts'] = ['EP001-C001-P001']
        with self.assertRaisesRegex(ValueError, '唯一归属'):
            self.run_plan()

    def test_record_failure_recovers_without_second_export(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        original = tool.replace_file
        def interrupted(path, text):
            if path.resolve() == (self.root / '项目进度.md').resolve():
                raise OSError('模拟记录写入中断')
            return original(path, text)
        with patch.object(tool, 'replace_file', interrupted), self.assertRaises(OSError):
            self.run_plan()
        self.assertEqual(len(NativeClient.calls), 2)
        self.run_plan()
        self.assertEqual(len(NativeClient.calls), 2)

    def test_published_pack_without_receipt_recovers_and_tampering_is_reported(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        original = tool.client.write_new
        def interrupted(path, data):
            if str(path).endswith('-导出响应.json'):
                raise OSError('模拟已发布包后响应写入中断')
            return original(path, data)
        with patch.object(tool.client, 'write_new', interrupted), self.assertRaises(OSError):
            self.run_plan()
        result = self.run_plan()
        self.assertEqual(len(NativeClient.calls), 2)
        receipt = tool.adopt.load(Path(result['record']).with_name(Path(result['record']).name.replace('-留档记录.json', '-导出响应.json')))
        self.assertIn('原远端导出时间未记录', receipt['basis'])
        with zipfile.ZipFile(result['pack'], 'a') as archive:
            archive.writestr('unexpected.txt', 'changed bytes')
        with self.assertRaisesRegex(ValueError, '长度不符合'):
            self.run_plan()
        self.assertEqual(tool.adopt.load(Path(result['record']))['state'], 'verification_failed')
        self.assertIn('定稿留档核对失败', (self.root / '项目进度.md').read_text(encoding='utf-8'))

    def test_missing_assets_and_wrong_pack_never_mark_completed(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        NativeClient.missing = True
        with self.assertRaises(tool.client.ClientError):
            self.run_plan()
        self.assertEqual(len(NativeClient.calls), 1)
        with self.assertRaisesRegex(ValueError, '不自动再次导出'):
            self.run_plan()
        self.assertEqual(len(NativeClient.calls), 1)
        self.plan['edition'] = '002'
        NativeClient.missing, NativeClient.corrupt = False, True
        with self.assertRaisesRegex(ValueError, '正文'):
            self.run_plan()
        self.assertNotIn('定稿留档完成', (self.root / '项目进度.md').read_text(encoding='utf-8'))

    def test_unapproved_or_changed_video_stops_before_writes(self):
        self.plan['items'] = [self.item(p) for p in ('P001', 'P002')]
        draft = self.extra / '工作稿/EP001-C001-P002-视频制作-工作稿.md'
        original = draft.read_text(encoding='utf-8')
        self.put(draft, original.replace('批准采用', '待审核'))
        with self.assertRaisesRegex(ValueError, '尚未批准'):
            self.run_plan()
        self.put(draft, original)
        selected = self.ep / '06-阶段采用视频/01-一采/C001-场次/EP001-C001-P002-R001-一采.mp4'
        self.put(selected, b'changed bytes')
        with self.assertRaisesRegex(ValueError, '长度不符合'):
            self.run_plan()
        self.assertEqual(NativeClient.calls, [])
        self.assertFalse(list(self.extra.rglob('*-留档记录.json')))

    def test_seven_groups_are_ordered_by_formal_index(self):
        self.put(self.ep / '03-分镜脚本/EP001-分镜索引.md', ''.join(
            f'| EP001-C001 | 分镜 | EP001-C001-P{i:03d} | 镜号 |\n' for i in range(1, 8)))
        self.plan['items'] = [self.item(f'P{i:03d}') for i in range(7, 0, -1)]
        result = self.run_plan()
        with zipfile.ZipFile(result['pack']) as archive:
            timeline = json.loads(archive.read('timeline.json'))
            self.assertEqual([g['id'] for g in timeline['segments']], [f'EP001-C001-P{i:03d}' for i in range(1, 8)])
            self.assertEqual([g['start'] for g in timeline['segments']], list(range(0, 175, 25)))
            self.assertEqual(timeline['batchWorkspaces']['r2v']['segments'], timeline['segments'])


if __name__ == '__main__':
    unittest.main()
