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


def canvas_api(canvas, workflow):
    graph = pairs.Canvas(canvas)
    actual = {}
    for key in workflow:
        actual.update(graph.api(key, optional=False))
    if pairs.semantic(actual) != pairs.semantic(workflow):
        raise ValueError('实际 API 与来源画布不配对')


def source(root, item):
    mapping_path = adopt.local_path(root, item['mapping'])
    mapping = adopt.load(mapping_path)
    contexts = [c for c in mapping['generation_contexts'] if c['identity'] == item['identity']]
    if len(contexts) != 1:
        raise ValueError('来源映射身份不唯一：' + item['identity'])
    api_path = adopt.local_path(root, item['api'])
    canvas_path = adopt.local_path(root, item['canvas'])
    workflow, canvas = adopt.load(api_path), adopt.load(canvas_path)
    request = adopt.load(mapping_path.parent / '请求.json')
    response = adopt.load(mapping_path.parent / '提交响应.json')
    accepted = response.get('data', response)
    if (not mapping.get('prompt_id') or accepted.get('prompt_id') != mapping['prompt_id']
            or pairs.semantic(request['prompt']) != pairs.semantic(workflow)):
        raise ValueError('来源 API／提交响应与实际获批任务不一致：' + item['identity'])
    canvas_api(canvas, workflow)
    return {'identity': item['identity'], 'mapping_path': mapping_path, 'mapping': mapping,
            'context': contexts[0], 'api_path': api_path, 'canvas_path': canvas_path,
            'api': workflow, 'canvas': canvas}


def director(source_item, part):
    nodes = [(k, n) for k, n in source_item['api'].items() if n['class_type'] == 'MiniMaxH3Director']
    if len(nodes) != 1:
        raise ValueError('来源需要唯一原生导演台：' + source_item['identity'])
    key, node = nodes[0]
    timeline = client.strict_json(node['inputs']['timeline_data'])
    if timeline['editMode'] != 'segment' or not timeline['global']['taskType'].startswith('r2v'):
        raise ValueError('场次留档目前支持原生 r2v 分组导演台')
    groups = [(i, g) for i, g in enumerate(timeline['segments']) if g['id'] == part]
    if len(groups) != 1:
        raise ValueError('实际时间线缺少唯一分段：' + part)
    index, group = groups[0]
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


def prepare(root, plan):
    episode, scene, stage = plan['episode'], plan['scene'], plan['stage']
    if not re.fullmatch(r'EP\d{3}', episode) or not re.fullmatch(r'C\d{3}', scene) or stage not in adopt.STAGES:
        raise ValueError('需要明确 EP编号／C编号／一采、二采或后处理')
    ep = root / '09-剧集制作' / episode
    index_file = ep / '03-分镜脚本' / f'{episode}-分镜索引.md'
    expected = re.findall(r'^\| ' + episode + '-' + scene + r' \|[^\n]*?\| (' + episode + '-' + scene + r'-P\d{3}) \|',
                          index_file.read_text(encoding='utf-8-sig'), re.M)
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
        reviews = set(re.findall(r'\]\(#([^)]*)\)', row))
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
            raise ValueError('取回凭据须在实际共同执行附件内')
        receipt_document = adopt.load(receipt_path)
        receipt = receipt_document.get('data', receipt_document)
        mapped_parts = [s for i, s in enumerate(actual['mapping']['segments'])
                        if i in actual['mapping']['selected_indices']
                        and s['segment'] + '-' + s['round'] + '-' + stage == item['identity']]
        if len(mapped_parts) != 1:
            raise ValueError('来源映射的实际执行范围与采用身份不符')
        mapped_part = mapped_parts[0]
        remote = mapped_part.get('remote', mapped_part.get('remote_output', actual['mapping'].get('remote_output')))
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
            adopt.check_file(source_video, {'bytes': actual['mapping']['source_bytes'],
                                            'sha256': actual['mapping']['source_sha256']})
            uploads = [u for u in actual['mapping']['uploads']
                       if Path(u['file']).name == source_video.name]
            loaders = [n['inputs']['file'] for n in actual['api'].values() if n['class_type'] == 'LoadVideo']
            if len(uploads) != 1 or loaders != [uploads[0]['input_path']]:
                raise ValueError('后处理实际输入视频与上传映射不对应：' + part)
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
                         'seed': content['director'][1]['inputs']['seed'], 'receipt': item['receipt']})
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
    canvas_api(canvas, workflow)
    urls = {content['mapping']['url'].rstrip('/') for _, content in sources}
    if len(urls) != 1:
        raise ValueError('引用媒体分属不同服务，不能用单一服务原生导出')
    edition = plan.get('edition', '')
    if edition and not re.fullmatch(r'\d{3}', edition):
        raise ValueError('edition 须为三位留档序号，不是生成R编号')
    stem = f'{episode}-{scene}-{stage}定稿' + ('-' + edition if edition else '')
    final = adopt.local_path(root, ep / '06-阶段采用视频' / adopt.STAGES[stage] / f'{scene}-场次' / '导演包')
    record = sources[0][0]['mapping_path'].parent
    return {'workflow': workflow, 'canvas': canvas, 'timeline': timeline, 'node': key,
            'url': next(iter(urls)), 'sources': sources, 'evidence': evidence, 'media': media,
            'pack': final / (stem + '-导演包.mmxpack.zip'), 'canvas_path': final / (stem + '.workflow.json'),
            'api_path': record / (stem + '.api.json'), 'receipt': record / (stem + '-导出响应.json'),
            'record': record / (stem + '-留档记录.json'), 'drafts': drafts,
            'summary': adopt.local_path(root, ep / '其他资料' / '工作稿' / f'{episode}-生成说明-工作稿.md'),
            'progress': adopt.local_path(root, root / '项目进度.md'), 'heading': f'定稿留档-{episode}-{scene}-{stage}'}


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


def finalize(args):
    root = Path(args.project).resolve(strict=True)
    plan_path = Path(args.plan)
    plan = adopt.load(plan_path if plan_path.is_absolute() else root / plan_path)
    p = prepare(root, plan)
    for path in [*p['drafts'], p['summary'], p['progress']]:
        path.read_text(encoding='utf-8-sig')
    record = {'stage': plan['stage'], 'sources': p['evidence'], 'url': p['url'], 'node_id': p['node'],
              'pack': str(p['pack']), 'canvas': str(p['canvas_path']), 'api': str(p['api_path'])}
    if p['record'].exists():
        old = adopt.load(p['record'])
        if any(old[k] != v for k, v in record.items()):
            raise ValueError('已有留档来源不同，保留原附件；使用新的 edition 明确另存版本')
    for path, value in ((p['api_path'], p['workflow']), (p['canvas_path'], p['canvas'])):
        if path.exists() and adopt.load(path) != value:
            raise ValueError('已有汇总工程不同，不能覆盖：' + str(path))
    if p['pack'].exists() and not p['record'].exists():
        raise ValueError('已有同名导演包缺少本次留档来源记录，不能当作本轮导出')
    result = {'state': 'ready', 'mode': 'apply' if args.apply else 'dry_run', **record,
              'record': str(p['record']), 'browser_sync': 'not_checked'}
    if not args.apply:
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
            response = client.export_pack(client.Client(p['url'], args.timeout),
                                          argparse.Namespace(workflow=p['api_path'], node_id=p['node'], output=p['pack']))
        except (client.ClientError, ValueError, OSError, zipfile.BadZipFile) as error:
            failure = {'ok': False, 'recorded_at': client.now(), 'error': str(error),
                       'code': error.code if isinstance(error, client.ClientError) else type(error).__name__,
                       'details': error.details if isinstance(error, client.ClientError) else {}}
            client.write_new(p['receipt'], failure)
            save_json(p['record'], {**record, 'state': 'export_failed', 'error': failure, 'receipt': str(p['receipt'])})
            raise
        client.write_new(p['receipt'], {'ok': True, 'recorded_at': client.now(), 'data': response})
    try:
        verify_pack(p)
        if p['receipt'].exists():
            adopt.check_file(p['pack'], adopt.load(p['receipt'])['data'])
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        save_json(p['record'], {**record, 'state': 'verification_failed', 'error': str(error)})
        for path in [*p['drafts'], p['summary'], p['progress']]:
            text = path.read_text(encoding='utf-8-sig')
            if re.search(r'^### ' + re.escape(p['heading']) + r'\s*$', text, re.M):
                a, b = adopt.section(text, p['heading'])
                body = adopt.field(text[a:b], '状态', '整场该阶段定稿留档核对失败；具体问题见留档记录，视频批准事实保持。')
                replace_file(path, text[:a] + body + '\n' + text[b:])
        raise
    if not p['receipt'].exists():
        # The native client may have published the ZIP before an interrupted receipt write.
        with p['pack'].open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        client.write_new(p['receipt'], {'ok': True, 'recovered_at': client.now(),
                                      'basis': '已有准备记录及实际包内容／素材字节核对；原远端导出时间未记录',
                                      'data': {'path': str(p['pack']), 'bytes': p['pack'].stat().st_size, 'sha256': digest}})
    stamp = adopt.load(p['record']).get('verified_at', client.now())
    for path in [*p['drafts'], p['summary'], p['progress']]:
        text = path.read_text(encoding='utf-8-sig')
        body = (f'\n- 状态：整场该阶段定稿留档完成；视频批准依据保持原记录。\n'
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
                           'checks': '全部P段实际批准／实际提交来源／API画布配对／原生包正文与素材字节／记录入口',
                           'records': [str(path) for path in [*p['drafts'], p['summary'], p['progress']]],
                           'receipt': str(p['receipt'])})
    result['state'] = 'completed'
    return result


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
