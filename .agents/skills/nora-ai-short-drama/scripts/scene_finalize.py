#!/usr/bin/env python3
"""汇总已批准的整场阶段，原生导出导演包、配对画布并补齐现有记录。"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile
from urllib.parse import unquote

import video_adopt as adopt
import workflow_baselines as pairs
import comfyui_config
import project_progress

client = adopt.client
MEDIA = ('imageFile', 'audioFile', 'videoFile', 'pairedAudioFile')
WIDGETS = ('steps', 'sampler', 'scheduler', 'cfg', 'shift_video', 'shift_audio', 'seed', 'task_type')


def replace_file(path, text):
    if path.exists() and path.read_text(encoding='utf-8-sig') == text:
        return
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent,
                                     prefix='.' + path.name, delete=False) as out:
        out.write(text)
        temporary = Path(out.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_json(path, value):
    replace_file(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def indexed_parts(root, episode):
    path = root / '09-剧集制作' / episode / '03-分镜脚本' / (episode + '-分镜索引.md')
    return re.findall(r'^\| (' + re.escape(episode) + r'-C\d{3}) \|[^\n]*?\| ('
                      + re.escape(episode) + r'-C\d{3}-P\d{3}) \|', path.read_text('utf-8-sig'), re.M)


def selected(root, part, stage):
    draft = root / '09-剧集制作' / part.split('-')[0] / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
    text = draft.read_text('utf-8-sig')
    _, _, row = adopt.selected_row(text, stage)
    names = re.findall(re.escape(part) + r'-R\d{3}-' + stage + r'\.\w+', row)
    anchors = re.findall(r'\]\(#([^)]*)\)', row.strip().strip('|').split('|')[-1])
    approved = names and len(anchors) == 1 and adopt.approved_row(text, names[0] + ' [审核](#' + anchors[0] + ')', names[0])
    return Path(names[0]).stem if approved else None


def episode_missing(root, episode):
    """Check current approved identities against their actual finalization records."""
    missing, records = [], {}
    for scene, part in indexed_parts(root, episode):
        draft = root / '09-剧集制作' / episode / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
        text = draft.read_text('utf-8-sig')
        for stage in adopt.STAGES:
            identity = selected(root, part, stage)
            if identity is None:
                missing.append(part + ' ' + stage + '未采用')
                continue
            headings = re.findall(r'^### (定稿留档-' + re.escape(scene + '-' + stage) + r'[^\n]*)$', text, re.M)
            covered = False
            for heading in headings:
                a, b = adopt.section(text, heading)
                for reference in re.findall(r'\[留档记录\]\(([^)]+)\)', text[a:b]):
                    path = adopt.local_path(root, draft.parent / unquote(reference))
                    if path not in records:
                        records[path] = adopt.load(path)
                    record = records[path]
                    if (record['state'] == 'completed' and identity in {s['identity'] for s in record['sources']}
                            and all(adopt.local_path(root, record[k]).is_file() for k in ('pack', 'canvas'))):
                        covered = True
            if not covered:
                missing.append(identity + '缺少当前版本定稿留档')
    return missing


def update_progress(root, episode, scene, stage, summary, *, failure_record=None):
    path = root / '项目进度.md'
    pending, next_steps = [], []
    indexed = indexed_parts(root, episode)
    missing = episode_missing(root, episode)
    if failure_record is not None:
        reference = '[本场' + stage + '留档记录](' + adopt.link(path, failure_record) + ')'
        reason = {'export_failed': '导出失败', 'verification_failed': '核对失败'}[adopt.load(failure_record)['state']]
        pending.append(reference + reason)
        next_steps.append('核对' + reference + '并恢复定稿留档')
    else:
        for current_scene, part in indexed:
            if current_scene == scene and selected(root, part, stage) is None:
                draft = root / '09-剧集制作' / episode / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
                pending.append('[' + part + '](' + adopt.link(path, draft) + ')的' + stage + '尚未采用')
    for current_scene in dict.fromkeys(s for s, _ in indexed):
        parts = [part for s, part in indexed if s == current_scene]
        for current_stage in adopt.STAGES:
            if failure_record is not None and (current_scene, current_stage) == (scene, stage):
                continue
            if any(part + ' ' + current_stage + '未采用' in missing for part in parts):
                continue
            if any(item.startswith(current_scene + '-') and item.endswith(current_stage + '缺少当前版本定稿留档')
                   for item in missing):
                reference = '[' + current_scene + current_stage + '](' + adopt.link(path, summary) + ')'
                pending.append(reference + '定稿留档尚未齐备')
                next_steps.append('补齐' + reference + '的定稿留档')
    complete = failure_record is None and not missing
    folder = root / '09-剧集制作' / episode / '06-阶段采用视频' / adopt.STAGES[stage] / (scene.split('-')[-1] + '-场次')
    outputs = '[' + scene + stage + '采用视频](' + adopt.link(path, folder) + ')、[制作与留档记录](' + adopt.link(path, summary) + ')'
    text = path.read_text('utf-8-sig')
    replace_file(path, project_progress.update(text, episode, status='已完成' if complete else '进行中',
                                             outputs=outputs, pending=pending, next_steps=next_steps))
    return complete


def postprocess_uploads(root, record):
    """从本任务成功上传记录读取实际素材，不扫描或猜测上传响应文件名。"""
    events_file = record / '后台过程记录.json'
    if not events_file.is_file():
        raise ValueError('后处理缺少 uploads 和后台成功上传记录：' + str(record))
    uploads = []
    for event in adopt.load(events_file):
        if event['stage'] == 'upload' and event['result'] == 'success':
            receipt = event['remote']
            local = adopt.local_path(root, event['file'])
            adopt.check_file(local, receipt)
            uploads.append({'file': str(local), 'input_path': receipt['input_path']})
    if not uploads:
        raise ValueError('后处理缺少 uploads 和后台成功上传记录：' + str(record))
    return uploads


def source(root, item):
    mapping_path = adopt.local_path(root, item['mapping'])
    mapping = adopt.execution_metadata(root, mapping_path, adopt.load(mapping_path))
    contexts = [c for c in mapping['generation_contexts'] if c['identity'] == item['identity']]
    if len(contexts) != 1:
        raise ValueError('来源映射身份不唯一：' + item['identity'])
    api_path = adopt.local_path(root, item['api'])
    canvas_path = adopt.local_path(root, item['canvas'])
    workflow, canvas = adopt.load(api_path), adopt.load(canvas_path)
    request = adopt.load(mapping_path.parent / '请求.json')
    response = adopt.load(mapping_path.parent / '提交响应.json')
    accepted = response.get('data', response)
    restoration = []
    verified_uploads = None
    if item['identity'].endswith('-后处理'):
        load_paths = [n['inputs']['file'] for n in request['prompt'].values() if n['class_type'] == 'LoadVideo']
        bound_paths = [u['input_path'] for u in mapping.get('uploads', [])]
        if 'source_bytes' not in mapping or any(path not in bound_paths for path in load_paths):
            verified_uploads = postprocess_uploads(root, mapping_path.parent)
        if not mapping.get('uploads') or any(path not in bound_paths for path in load_paths):
            mapping['uploads'] = verified_uploads
            restoration.append('依据本任务后台成功上传记录关联实际 input_path 与本地来源；原映射保留')
    # Populate the export copy from the actual API; source canvas bytes stay untouched.
    for stored in canvas['nodes']:
        named = stored.get('widgets_values_named', {})
        key = str(stored['id'])
        if named and key in workflow:
            named.update({k: v for k, v in workflow[key]['inputs'].items() if k in named and not pairs.is_link(v)})
            stored['widgets_values'] = list(named.values())
    if pairs.semantic(request['prompt']) != pairs.semantic(workflow) and item['identity'].endswith('-后处理'):
        # Some saved preparation pairs precede the upload. Restore only the exact
        # LoadVideo path recorded by that task's upload and submitted request.
        restored = copy.deepcopy(workflow)
        for key, node in restored.items():
            if node['class_type'] == 'LoadVideo':
                path = request['prompt'][key]['inputs']['file']
                if path not in [u['input_path'] for u in mapping['uploads']]:
                    raise ValueError('实际提交的视频路径未在上传映射中关联')
                node['inputs']['file'] = path
                graph, node_id = pairs.Canvas(canvas).find(key)
                stored = graph.nodes[node_id]
                stored['widgets_values_named']['file'] = path
                stored['widgets_values'] = list(stored['widgets_values_named'].values())
        if pairs.semantic(restored) != pairs.semantic(request['prompt']):
            raise ValueError('来源 API／提交响应与实际获批任务不一致：' + item['identity'])
        workflow = restored
        restoration.append('以本任务请求及上传映射恢复LoadVideo文件路径；原准备API和画布保留')
    if (not mapping.get('prompt_id') or accepted.get('prompt_id') != mapping['prompt_id']
            or pairs.semantic(request['prompt']) != pairs.semantic(workflow)):
        raise ValueError('来源 API／提交响应与实际获批任务不一致：' + item['identity'])
    return {'identity': item['identity'], 'mapping_path': mapping_path, 'mapping': mapping,
            'context': contexts[0], 'api_path': api_path, 'canvas_path': canvas_path,
            'api': workflow, 'canvas': canvas, 'restoration': restoration, 'verified_uploads': verified_uploads}


def director(source_item, part):
    nodes = [(k, n) for k, n in source_item['api'].items() if n['class_type'] == 'MiniMaxH3Director']
    if len(nodes) != 1:
        raise ValueError('来源需要唯一原生导演台：' + source_item['identity'])
    key, node = nodes[0]
    timeline = client.strict_json(node['inputs']['timeline_data'])
    if timeline['editMode'] != 'segment' or not timeline['global']['taskType'].startswith('r2v'):
        raise ValueError('场次留档目前支持原生 r2v 分组导演台')
    mapping = source_item['mapping']
    stage = source_item['identity'].rsplit('-', 1)[1]
    indices = [i for i, s in enumerate(mapping['segments'])
               if s['segment'] == part and s['segment'] + '-' + s['round'] + '-' + stage == source_item['identity']]
    if len(mapping['segments']) != len(timeline['segments']) or len(indices) != 1:
        raise ValueError('输入映射原组序无法唯一对应实际时间线分段：' + part)
    index = indices[0]
    group = timeline['segments'][index]
    if index not in mapping['selected_indices']:
        raise ValueError('该分段不在输入映射实际执行范围：' + part)
    if timeline.get('runSelectEnabled') and index not in timeline['runSelection']:
        raise ValueError('该分段不在来源任务实际执行范围：' + part)
    editor = timeline['batchWorkspaces']['r2v']
    if (pairs.director_editor_state(editor['globalCommon'], True) != pairs.director_editor_state(timeline['global'], True)
            or [pairs.director_editor_state(g) for g in editor['segments']]
            != [pairs.director_editor_state(g) for g in timeline['segments']]):
        raise ValueError('来源导演台根／编辑工作区不同步：' + part)
    if timeline['keyframes'] or timeline['videoClips'] or timeline['video'].get('fileName'):
        raise ValueError('分组汇总不改写带源视频／关键帧时间轴的工程：' + part)
    prompt = '\n\n'.join(p.strip() for p in
                         ([timeline['global']['prompt'], group['prompt']] if timeline['global']['commonEnabled']
                          else [group['prompt']]) if p.strip())
    frozen = adopt.local_path(source_item['root'], source_item['context']['prompts']['english'])
    if frozen.read_text(encoding='utf-8-sig').strip() != prompt:
        raise ValueError('实际正文与冻结提示词不同：' + part)
    return key, node, timeline, group


def lift_common(common, group):
    """公共区差异移入各组；保留绝对素材槽位，本组覆盖公共同槽。"""
    group = copy.deepcopy(group)
    if common['commonEnabled']:
        group['prompt'] = '\n\n'.join(p.strip() for p in (common['prompt'], group['prompt']) if p.strip())
        for field in ('refs', 'refAudios', 'refVideos'):
            local = {r['index']: r for r in group[field]}
            group[field] = sorted({**{r['index']: copy.deepcopy(r) for r in common[field]}, **local}.values(),
                                  key=lambda r: r['index'])
    return group


def merge_graph(canvas, workflow, addition, offset):
    """后处理各段的实际节点分支并列保存，不改处理参数或输入路径。"""
    graph, api = copy.deepcopy(addition['canvas']), copy.deepcopy(addition['api'])
    if graph.get('definitions', {}).get('subgraphs'):
        raise ValueError('后处理来源含子图，当前合并器不支持；保留来源并报告缺项')
    ids = {n['id']: canvas['last_node_id'] + i + 1 for i, n in enumerate(graph['nodes'])}
    links = {pairs.link_tuple(l)[0]: canvas['last_link_id'] + i + 1 for i, l in enumerate(graph['links'])}
    for n in graph['nodes']:
        n['id'] = ids[n['id']]
        n['pos'][0] += offset
        for entry in n.get('inputs', []):
            if entry.get('link') is not None:
                entry['link'] = links[entry['link']]
        for entry in n.get('outputs', []):
            if entry.get('links'):
                entry['links'] = [links[x] for x in entry['links']]
    for entry in graph['links']:
        if isinstance(entry, dict):
            entry.update(id=links[entry['id']], origin_id=ids[entry['origin_id']], target_id=ids[entry['target_id']])
        else:
            entry[0], entry[1], entry[3] = links[entry[0]], ids[entry[1]], ids[entry[3]]
    for key, node in api.items():
        for field, value in node['inputs'].items():
            if pairs.is_link(value):
                node['inputs'][field] = [str(ids[int(value[0])]), value[1]]
        workflow[str(ids[int(key)])] = node
    canvas['nodes'].extend(graph['nodes'])
    canvas['links'].extend(graph['links'])
    canvas['last_node_id'], canvas['last_link_id'] = max(ids.values()), max(links.values(), default=canvas['last_link_id'])
    for group in graph.get('groups', []):
        group['bounding'][0] += offset
        canvas.setdefault('groups', []).append(group)


def prepare(root, plan, batch_parts=None, batch_name=None):
    episode, scene, stage = plan['episode'], plan['scene'], plan['stage']
    if not re.fullmatch(r'(?:EP\d{3}|片头|片尾)', episode) or not re.fullmatch(r'C\d{3}', scene) or stage not in adopt.STAGES:
        raise ValueError('需要明确 EP编号或片头／片尾、C编号以及一采、二采或后处理')
    ep = root / '09-剧集制作' / episode
    index_file = ep / '03-分镜脚本' / f'{episode}-分镜索引.md'
    expected = re.findall(r'^\| ' + episode + '-' + scene + r' \|[^\n]*?\| (' + episode + '-' + scene + r'-P\d{3}) \|',
                          index_file.read_text(encoding='utf-8-sig'), re.M)
    if batch_parts is not None:
        expected = [p for p in expected if p in batch_parts]
    identities = [item['identity'] for item in plan['items']]
    parts = [adopt.IDENTITY.fullmatch(i).groups() if adopt.IDENTITY.fullmatch(i) else () for i in identities]
    if (not expected or len(expected) != len(set(expected)) or len(identities) != len(set(identities))
            or any(not p or p[0] != episode or p[1] != scene or p[4] != stage for p in parts)
            or {f'{p[0]}-{p[1]}-{p[2]}' for p in parts} != set(expected)):
        raise ValueError('留档范围必须完整、唯一覆盖正式分镜索引中的当前场次该阶段全部P段')
    items = sorted(plan['items'], key=lambda item: expected.index(item['identity'].rsplit('-', 2)[0]))
    sources, drafts, evidence, media = [], [], [], {}
    for item in items:
        part = item['identity'].rsplit('-', 2)[0]
        draft = ep / '其他资料' / '工作稿' / f'{part}-视频制作-工作稿.md'
        text = draft.read_text(encoding='utf-8-sig')
        _, _, row = adopt.selected_row(text, stage)
        links = [unquote(u) for u in re.findall(r'\]\(([^)#]+)\)', row) if Path(unquote(u)).stem == item['identity']]
        reviews = set(re.findall(r'\]\(#([^)]*)\)', row.strip().strip('|').split('|')[-1]))
        if len(links) != 1 or len(reviews) != 1:
            raise ValueError('当前采用入口／人工审核依据不唯一：' + part)
        selected = adopt.local_path(root, draft.parent / links[0])
        if not selected.is_relative_to(ep / '06-阶段采用视频' / adopt.STAGES[stage] / f'{scene}-场次'):
            raise ValueError('当前采用文件未归位对应阶段定稿目录：' + part)
        review = next(iter(reviews))
        if not adopt.approved_row(text, selected.name + f' [审核](#{review})', selected.name):
            raise ValueError('当前具体版本尚未批准采用：' + item['identity'])
        actual = source(root, item)
        receipt_path = adopt.local_path(root, item['receipt'])
        if not receipt_path.is_relative_to(actual['mapping_path'].parent):
            paths = [s.get(field) for s in actual['mapping']['segments']
                     for field in ('download_response', 'download_receipt', 'final_download_receipt') if s.get(field)]
            if receipt_path not in [adopt.local_path(root, p) for p in paths]:
                raise ValueError('共同任务外的取回凭据须已在输入映射中明确关联')
        receipt_document = adopt.load(receipt_path)
        receipt = receipt_document.get('data', receipt_document)
        mapped_parts = [s for i, s in enumerate(actual['mapping']['segments'])
                        if i in actual['mapping']['selected_indices']
                        and s['segment'] + '-' + s['round'] + '-' + stage == item['identity']]
        if len(mapped_parts) != 1:
            raise ValueError('来源映射的实际执行范围与采用身份不符')
        mapped_part = mapped_parts[0]
        remote = mapped_part.get('remote', mapped_part.get('remote_output', actual['mapping'].get('remote_output')))
        if remote is None and mapped_part.get('final_output'):
            remote = mapped_part['final_output']['remote']
        if remote is None:
            outputs = [o for o in actual['mapping'].get('outputs', []) if o.get('identity') == item['identity']]
            if len(outputs) != 1 or adopt.local_path(root, outputs[0]['receipt']) != receipt_path:
                raise ValueError('后台输出未唯一关联本段及指定取回凭据')
            remote = outputs[0]['remote']
        if remote != receipt['remote']:
            raise ValueError('取回凭据的远端输出与本段映射不对应')
        adopt.check_file(selected, receipt)
        content = actual
        if stage == '后处理':
            content = source(root, item['content'])
            if (actual['context']['source'] != content['identity']
                    or content['identity'].rsplit('-', 2)[0] != part
                    or not content['identity'].endswith('-二采')):
                raise ValueError('后处理正文来源须为该获批任务明确接续的同段二采')
            source_video = adopt.local_path(root, item['source_video'])
            if source_video.stem != content['identity']:
                raise ValueError('后处理源视频身份不符合二采来源')
            uploads = [u for u in actual['mapping']['uploads']
                       if adopt.local_path(root, u['file']) == source_video]
            loaders = [n['inputs']['file'] for n in actual['api'].values() if n['class_type'] == 'LoadVideo']
            if len(uploads) != 1 or loaders != [uploads[0]['input_path']]:
                raise ValueError('后处理实际输入视频与上传映射不对应：' + part)
            if 'source_bytes' in actual['mapping']:
                adopt.check_file(source_video, {'bytes': actual['mapping']['source_bytes'],
                                                'sha256': actual['mapping']['source_sha256']})
            else:
                # Backend upload receipts already bind the actual source bytes.
                verified = [u for u in actual['verified_uploads']
                            if adopt.local_path(root, u['file']) == source_video
                            and u['input_path'] == loaders[0]]
                if len(verified) != 1:
                    raise ValueError('后处理源视频没有唯一匹配的成功上传凭据：' + part)
        content['root'] = root
        content['director'] = director(content, part)
        sources.append((actual, content))
        drafts.append(draft)
        refs = content['context']['references']
        for scope_name, scope in refs.items():
            for ref in scope:
                local = adopt.local_path(root, ref['file'])
                if not local.is_file():
                    raise ValueError('冻结素材缺失：' + str(local))
                block = content['director'][2]['global'] if scope_name == 'common' else content['director'][3]
                paths = [r[file_field] for field, file_field, label in
                         (('refs', 'imageFile', 'Picture'), ('refAudios', 'audioFile', 'Audio'), ('refVideos', 'videoFile', 'Video'))
                         for r in block[field] if ref['label'] == f'<{label} {r["index"] + 1}>']
                if len(paths) != 1:
                    raise ValueError('冻结素材标签与实际时间线不对应：' + ref['label'])
                remote_path = paths[0]
                if remote_path in media and media[remote_path].read_bytes() != local.read_bytes():
                    raise ValueError('不同来源同一远端素材路径字节冲突：' + remote_path)
                media[remote_path] = local
        for upload in content['mapping']['uploads']:
            local = adopt.local_path(root, upload['file'])
            if local.is_file():
                if upload['input_path'] in media and media[upload['input_path']].read_bytes() != local.read_bytes():
                    raise ValueError('不同来源同一远端素材路径字节冲突：' + upload['input_path'])
                media.setdefault(upload['input_path'], local)
        evidence.append({'identity': item['identity'], 'selected_path': str(selected), 'review': review,
                         'mapping': str(actual['mapping_path']), 'api': str(actual['api_path']),
                         'canvas': str(actual['canvas_path']), 'prompt_id': actual['mapping']['prompt_id'],
                         'content_identity': content['identity'], 'content_mapping': str(content['mapping_path']),
                         'content_api': str(content['api_path']), 'content_canvas': str(content['canvas_path']),
                         'seed': content['director'][1]['inputs']['seed'], 'receipt': item['receipt'],
                         'restoration': actual['restoration'], 'content_restoration': content['restoration']})
    first = sources[0][1]
    key, node, timeline, _ = first['director']
    workflow, canvas, timeline = copy.deepcopy(first['api']), copy.deepcopy(first['canvas']), copy.deepcopy(timeline)
    # Compare full active model/SIGMAS/Refine graph by class and dependency structure, independent of IDs.
    def graph_signature(api, director_key):
        def walk(node_key):
            n = api[node_key]
            values = {k: walk(v[0]) + [v[1]] if pairs.is_link(v) else v for k, v in n['inputs'].items()
                      if not (node_key == director_key and k in ('timeline_data', 'global_prompt', 'total_frames'))}
            return [n['class_type'], values]
        return walk(director_key)
    for _, content in sources[1:]:
        other_key, _, other_t, _ = content['director']
        if (graph_signature(first['api'], key) != graph_signature(content['api'], other_key)
                or any(timeline[f] != other_t[f] for f in ('frameRate', 'width', 'height', 'refMaxSize', 'output'))):
            raise ValueError(f'无法合并必要配置（模型链／SIGMAS／Refine／种子／尺寸）：{first["identity"]} 与 {content["identity"]}')
    globals_ = [content['director'][2]['global'] for _, content in sources]
    common_same = all(g == globals_[0] for g in globals_)
    if not common_same:
        ignored = {'prompt', 'refs', 'refAudios', 'refVideos', 'commonEnabled', 'commonCollapsed'}
        if any({k: v for k, v in g.items() if k not in ignored} != {k: v for k, v in globals_[0].items() if k not in ignored}
               for g in globals_):
            raise ValueError('公共区模式配置冲突，无法只移入各组正文／引用素材')
        if any(g.get('referenceVideo', {}).get('videoFile') for g in globals_):
            raise ValueError('公共旧版referenceVideo差异需要先规范化，不能丢失引用')
        timeline['global'].update(commonEnabled=False, prompt='', refs=[], refAudios=[], refVideos=[])
    groups, frame = [], 0
    for _, content in sources:
        _, _, t, group = content['director']
        group = copy.deepcopy(group) if common_same else lift_common(t['global'], group)
        group['start'] = frame
        frame += group['frameCount']
        groups.append(group)
    timeline.update(segments=groups, totalFrames=frame, durationSec=sum(g['durationSec'] for g in groups),
                    runSelectEnabled=True, runSelection=list(range(len(groups))), selectedIndex=0)
    timeline['video']['sourceFrameCount'] = frame
    timeline['batchWorkspaces'] = {'r2v': {'globalCommon': copy.deepcopy(timeline['global']), 'segments': copy.deepcopy(groups),
                                         'selectedIndex': 0, 'editMode': 'segment', 'runSelectEnabled': True,
                                         'runSelection': list(range(len(groups)))}}
    workflow[key]['inputs'].update(timeline_data=json.dumps(timeline, ensure_ascii=False), total_frames=frame,
                                  global_prompt=timeline['global']['prompt'])
    graph, node_id = pairs.Canvas(canvas).find(key)
    stored = graph.nodes[node_id]
    for field in ('timeline_data', 'total_frames', 'global_prompt'):
        stored['widgets_values_named'][field] = workflow[key]['inputs'][field]
    stored['widgets_values'] = list(stored['widgets_values_named'].values())
    if stage == '后处理':
        for i, (actual, _) in enumerate(sources):
            merge_graph(canvas, workflow, actual, 2200 * (i + 1))
    canvas.setdefault('extra', {})['nora_scene_finalization'] = {'stage': stage, 'sources': evidence,
                                                              'purpose': '整场汇总工程；不是单次执行原始画布；不恢复一采缓存'}
    urls = {content['mapping']['url'].rstrip('/') for _, content in sources}
    if len(urls) != 1:
        raise ValueError('引用媒体分属不同服务，不能用单一服务原生导出')
    edition = plan.get('edition', '')
    if edition and not re.fullmatch(r'\d{3}', edition):
        raise ValueError('edition 须为三位留档序号，不是生成R编号')
    stem = f'{episode}-{scene}-{stage}定稿' + ('-' + batch_name if batch_name else '') + ('-' + edition if edition else '')
    final = adopt.local_path(root, ep / '06-阶段采用视频' / adopt.STAGES[stage] / f'{scene}-场次' / '导演包')
    record = sources[0][0]['mapping_path'].parent
    return {'workflow': workflow, 'canvas': canvas, 'timeline': timeline, 'node': key,
            'url': next(iter(urls)), 'sources': sources, 'evidence': evidence, 'media': media,
            'pack': final / (stem + '-导演包.mmxpack.zip'), 'canvas_path': final / (stem + '.workflow.json'),
            'api_path': record / (stem + '.api.json'), 'receipt': record / (stem + '-导出响应.json'),
            'record': record / (stem + '-留档记录.json'), 'drafts': drafts,
            'summary': adopt.local_path(root, plan.get('summary', ep / '其他资料' / '工作稿' / f'{episode}-生成说明-工作稿.md')),
            'progress': adopt.local_path(root, root / '项目进度.md'),
            'heading': f'定稿留档-{episode}-{scene}-{stage}' + ('-' + batch_name if batch_name else ''),
            'scope': '该配置批次' if batch_name else '整场该阶段'}


def verify_pack(prepared):
    """核对原生可移植路径和素材字节，而不是把路径改写误判为正文变化。"""
    with zipfile.ZipFile(prepared['pack']) as archive:
        if archive.testzip():
            raise ValueError('导演包 ZIP 校验失败')
        metadata = client.strict_json(archive.read('pack.json'))
        if metadata['format'] != 'minimax-h3-director-pack' or metadata['formatVersion'] != 1:
            raise ValueError('原生导演包格式不符')
        widgets = {k: prepared['workflow'][prepared['node']]['inputs'][k] for k in WIDGETS
                   if k in prepared['workflow'][prepared['node']]['inputs']}
        if metadata['widgets'] != widgets or metadata['output'] != prepared['timeline']['output']:
            raise ValueError('包内控件／输出配置与整场工程不一致')

        def compare(before, after, where):
            if isinstance(before, dict):
                for key in before:
                    if key in ('fileName', 'subfolder', 'type') and any(before.get(f) for f in MEDIA):
                        continue
                    if key in ('imageB64', 'previewB64', 'previewFrames', 'previewMime'):
                        continue
                    if key in MEDIA and before[key]:
                        media = prepared['media'].get(before[key])
                        if media is None or archive.read(after[key]) != media.read_bytes():
                            raise ValueError('包内素材无法对应冻结字节：' + where + '/' + key)
                    else:
                        compare(before[key], after[key], where + '/' + key)
            elif isinstance(before, list):
                if len(before) != len(after):
                    raise ValueError('包内组序／内容数量不一致：' + where)
                for i, (a, b) in enumerate(zip(before, after)):
                    compare(a, b, where + '/' + str(i))
            elif before != after:
                raise ValueError('包内正文／标签／配置不一致：' + where)

        portable = client.strict_json(archive.read('timeline.json'))
        compare(prepared['timeline'], portable, 'timeline')
        shared = client.strict_json(archive.read('shared_params/shared_params.json'))
        if {k: portable['global'][k] for k in shared} != shared:
            raise ValueError('包内公共区与时间线不一致')
        group_names = sorted((n for n in archive.namelist() if re.fullmatch(r'asset_groups/\d+/group.json', n)),
                             key=lambda n: int(n.split('/')[1]))
        if len(group_names) != len(portable['segments']):
            raise ValueError('导演包分组文件未完整覆盖整场')
        for group, filename in zip(portable['segments'], group_names):
            actual = client.strict_json(archive.read(filename))
            if {k: group[k] for k in actual} != actual:
                raise ValueError('包内分组与时间线不一致：' + filename)


def finalize_one(root, plan, p, apply, timeout):
    for path in [*p['drafts'], p['summary'], p['progress']]:
        path.read_text(encoding='utf-8-sig')
    project_progress.phase_row(p['progress'].read_text('utf-8-sig'), plan['episode'])
    record = {'stage': plan['stage'], 'sources': p['evidence'], 'url': p['url'], 'node_id': p['node'],
              'pack': str(p['pack']), 'canvas': str(p['canvas_path']), 'api': str(p['api_path']),
              'configuration_batch_authorization': plan.get('configuration_batch_authorization')}
    if p['record'].exists():
        old = adopt.load(p['record'])
        if any(old[k] != v for k, v in record.items()):
            raise ValueError('已有留档来源不同，保留原附件；使用新的 edition 明确另存版本')
    for path, value in ((p['api_path'], p['workflow']), (p['canvas_path'], p['canvas'])):
        if path.exists() and adopt.load(path) != value:
            raise ValueError('已有汇总工程不同，不能覆盖：' + str(path))
    if p['pack'].exists() and not p['record'].exists():
        raise ValueError('已有同名导演包缺少本次留档来源记录，不能当作本轮导出')
    result = {'state': 'ready', 'mode': 'apply' if apply else 'dry_run', **record,
              'record': str(p['record']), 'browser_sync': 'not_checked'}
    if not apply:
        return result
    if not p['record'].exists():
        client.write_new(p['record'], {**record, 'state': 'prepared'})
    if not p['api_path'].exists():
        client.write_new(p['api_path'], p['workflow'])
    p['canvas_path'].parent.mkdir(parents=True, exist_ok=True)
    if not p['canvas_path'].exists():
        client.write_new(p['canvas_path'], p['canvas'])
    if not p['pack'].exists():
        if p['receipt'].exists():
            raise ValueError('已有导出响应但定稿包缺失，须先核对，不自动再次导出')
        try:
            response = client.export_pack(comfyui_config.client_for(comfyui_config.workspace_for_project(root), p['url'], timeout),
                                          argparse.Namespace(workflow=p['api_path'], node_id=p['node'], output=p['pack']))
        except (client.ClientError, ValueError, OSError, zipfile.BadZipFile) as error:
            failure = {'ok': False, 'recorded_at': client.now(), 'error': str(error),
                       'code': error.code if isinstance(error, client.ClientError) else type(error).__name__,
                       'details': error.details if isinstance(error, client.ClientError) else {}}
            client.write_new(p['receipt'], failure)
            save_json(p['record'], {**record, 'state': 'export_failed', 'error': failure, 'receipt': str(p['receipt'])})
            update_progress(root, plan['episode'], plan['episode'] + '-' + plan['scene'], plan['stage'],
                            p['summary'], failure_record=p['record'])
            raise
        client.write_new(p['receipt'], {'ok': True, 'recorded_at': client.now(), 'data': response})
    try:
        verify_pack(p)
        if p['receipt'].exists():
            adopt.check_file(p['pack'], adopt.load(p['receipt'])['data'])
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        save_json(p['record'], {**record, 'state': 'verification_failed', 'error': str(error)})
        for path in [*p['drafts'], p['summary']]:
            text = path.read_text(encoding='utf-8-sig')
            if re.search(r'^### ' + re.escape(p['heading']) + r'\s*$', text, re.M):
                a, b = adopt.section(text, p['heading'])
                body = adopt.field(text[a:b], '状态', p['scope'] + '定稿留档核对失败；具体问题见留档记录，视频批准事实保持。')
                replace_file(path, text[:a] + body + '\n' + text[b:])
        update_progress(root, plan['episode'], plan['episode'] + '-' + plan['scene'], plan['stage'],
                        p['summary'], failure_record=p['record'])
        raise
    if not p['receipt'].exists():
        # The native client may have published the ZIP before an interrupted receipt write.
        with p['pack'].open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        client.write_new(p['receipt'], {'ok': True, 'recovered_at': client.now(),
                                      'basis': '已有准备记录及实际包内容／素材字节核对；原远端导出时间未记录',
                                      'data': {'path': str(p['pack']), 'bytes': p['pack'].stat().st_size, 'sha256': digest}})
    stamp = adopt.load(p['record']).get('verified_at', client.now())
    for path in [*p['drafts'], p['summary']]:
        text = path.read_text(encoding='utf-8-sig')
        body = (f'\n- 状态：{p["scope"]}定稿留档完成；视频批准依据保持原记录。\n'
                f'- 导演包：[下载]({adopt.link(path, p["pack"])})\n'
                f'- 配对画布：[下载]({adopt.link(path, p["canvas_path"])})\n'
                f'- 来源及文件核对：[留档记录]({adopt.link(path, p["record"])})；'
                f'[导出响应]({adopt.link(path, p["receipt"])})\n')
        if re.search(r'^### ' + re.escape(p['heading']) + r'\s*$', text, re.M):
            a, b = adopt.section(text, p['heading'])
            text = text[:a] + body + '\n' + text[b:]
        else:
            text = text.rstrip() + '\n\n### ' + p['heading'] + '\n' + body + '\n'
        replace_file(path, text)
    for actual, _ in p['sources']:
        mapped = adopt.load(actual['mapping_path'])
        mapped.setdefault('scene_finalizations', {})[plan['stage']] = str(p['record'])
        save_json(actual['mapping_path'], mapped)
    save_json(p['record'], {**record, 'state': 'completed', 'verified_at': stamp,
                           'checks': '全部P段实际批准／实际提交来源／原生包正文与素材字节／记录入口',
                           'records': [str(path) for path in [*p['drafts'], p['summary']]],
                           'receipt': str(p['receipt'])})
    update_progress(root, plan['episode'], plan['episode'] + '-' + plan['scene'], plan['stage'], p['summary'])
    saved = adopt.load(p['record'])
    save_json(p['record'], {**saved, 'records': saved['records'] + [str(p['progress'])]})
    result['state'] = 'completed'
    return result


def finalize(args, *, plan=None):
    root = Path(args.project).resolve(strict=True)
    if plan is None:
        plan_path = Path(args.plan)
        plan = adopt.load(plan_path if plan_path.is_absolute() else root / plan_path)
    if not plan.get('configuration_batches'):
        return finalize_one(root, plan, prepare(root, plan), args.apply, args.timeout)
    if not plan.get('configuration_batch_authorization'):
        raise ValueError('按配置分批留档须填写用户本次明确授权依据')
    batches = plan['configuration_batches']
    names = [b['name'] for b in batches]
    parts = [p for b in batches for p in b['parts']]
    expected = re.findall(r'^\| ' + re.escape(plan['episode'] + '-' + plan['scene']) + r' \|[^\n]*?\| ('
                          + re.escape(plan['episode'] + '-' + plan['scene']) + r'-P\d{3}) \|',
                          (root / '09-剧集制作' / plan['episode'] / '03-分镜脚本'
                           / (plan['episode'] + '-分镜索引.md')).read_text(encoding='utf-8-sig'), re.M)
    item_parts = [i['identity'].rsplit('-', 2)[0] for i in plan['items']]
    if (not expected or len(expected) != len(set(expected)) or len(names) != len(set(names))
            or any(not re.fullmatch(r'[\w-]+', n) for n in names)
            or len(parts) != len(set(parts)) or len(item_parts) != len(set(item_parts))
            or set(parts) != set(expected) or set(item_parts) != set(expected)
            or any(not b['parts'] for b in batches)):
        raise ValueError('授权分批必须各段唯一归属，并完整覆盖正式索引及本次留档清单')
    prepared = []
    for batch in batches:
        sub = {**plan, 'items': [i for i in plan['items'] if i['identity'].rsplit('-', 2)[0] in batch['parts']]}
        prepared.append((sub, prepare(root, sub, batch['parts'], batch['name'])))
    # Validate every source and configuration before the first remote export.
    results = [finalize_one(root, sub, p, args.apply, args.timeout) for sub, p in prepared]
    return {'state': 'completed' if args.apply else 'ready', 'mode': 'apply' if args.apply else 'dry_run',
            'authorization': plan['configuration_batch_authorization'], 'batches': results,
            'browser_sync': 'not_checked'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Python 3.11+，标准库。预览离线；--apply 仅原生导出，绝不生成视频。路径及请求格式见 comfyui-scripts/README.md。')
    parser.add_argument('--project', required=True, help='项目根；相对当前工作目录解析')
    parser.add_argument('--plan', required=True, help='阶段留档请求JSON；相对项目根解析')
    parser.add_argument('--apply', action='store_true', help='直接导出到阶段定稿目录并补齐现有记录；默认只读预览')
    parser.add_argument('--timeout', type=float, default=30, help='每次导出HTTP请求超时秒数，默认30秒，无自动重试')
    args = parser.parse_args()
    try:
        print(json.dumps(finalize(args), ensure_ascii=False))
    except (ValueError, KeyError, OSError, AssertionError, zipfile.BadZipFile, client.ClientError) as error:
        print(json.dumps({'ok': False, 'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
