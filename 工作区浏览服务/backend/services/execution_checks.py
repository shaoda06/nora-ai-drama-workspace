"""Tool-owned local preparation report. No remote capability query or generation POST."""
import json
import re
import tempfile
from pathlib import Path

from project_paths import project_file, recorded_paths, PreparationPaths

REPORT = '执行检查报告.json'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def basis(store, data, mapping=None):
    payload = store.portable_input(data)
    for name in ('image_plan', 'video_plan'):
        if payload.get(name) is None:
            payload.pop(name, None)  # Existing reports have no newer media associations.
    for name in ('desktop', 'thread_id', 'source_session_name', 'timeout', 'start_paused',
                 'image_batch_id', 'image_batch_size'):
        payload.pop(name, None)
    mapping_file = Path(data.record_dir) / '输入映射.json'
    if mapping is None:
        mapping = json.loads(mapping_file.read_text('utf-8-sig')) if mapping_file.exists() else {}
    if mapping:
        payload['mapping'] = recorded_paths(data.project, {name: mapping[name] for name in (
            'scene', 'task_type', 'screenplay_version', 'scene_storyboard_version', 'scene_modification_round', 'selected_indices', 'segments', 'content_review') if name in mapping}, relative=True)
        if data.task_type.startswith('video-'):
            revision = store.generation_context.scene_round_basis(data.project, mapping, data.task_type)
            if revision is not None:
                payload['scene_composition'] = revision
    return payload


def _file_stamp(path, observed):
    if path not in observed:
        current = path.stat()
        observed[path] = (current.st_size, current.st_mtime_ns)
    return observed[path]


def sources(data, extra=(), mapping=None, *, observed=None, composition=None):
    observed = {} if observed is None else observed
    files = {Path(item['file']) for item in data.uploads}
    files.update(Path(path) for path in extra)
    record = Path(data.record_dir)
    files.update(record.glob('*.api.json'))
    files.update(record.glob('*.workflow.json'))
    mapping_file = record / '输入映射.json'
    if mapping is None:
        mapping = json.loads(mapping_file.read_text('utf-8-sig')) if mapping_file.exists() else {}
    if mapping:
        if mapping.get('storyboard_file'):
            files.add(project_file(data.project, mapping['storyboard_file'], recorded=True))
        for context in mapping.get('generation_contexts', []):
            files.update(project_file(data.project, name, recorded=True) for name in context.get('prompts', {}).values())
    if composition:
        files.update(project_file(data.project, composition[kind]['file'], recorded=True) for kind in ('script', 'storyboard'))
    return {path.relative_to(data.project).as_posix(): list(_file_stamp(path, observed)) for path in sorted(files)}


def read_report(data):
    path = Path(data.record_dir) / REPORT
    if not path.exists():
        return None
    report = json.loads(path.read_text('utf-8'))
    if not isinstance(report, dict) or 'prepared_input' not in report:
        raise ValueError('执行检查报告位置已有其他资料；不覆盖，请核对目录')
    return report


def write_report(data, report):
    path = Path(data.record_dir) / REPORT
    write_json(path, report)


def check_prepared(store, data, *, bound=False, transferred=False, legacy=False, require_scene_round=True, require_content_review=True, file_stamps=None):
    observed = {}
    report = read_report(data)
    if report is None:
        if legacy:
            return None
        raise ValueError('新任务必须先通过准备检查；请使用--prepare-only完成准备，不会在开工时补查')
    expected, actual = report['prepared_input'].copy(), basis(store, data)
    if not require_content_review and 'content_review' not in expected.get('mapping', {}):
        actual.get('mapping', {}).pop('content_review', None)
    if 'title' not in expected:  # Reports made before title became a preparation field.
        actual.pop('title', None)
    if transferred:
        expected.pop('url', None)
        actual.pop('url', None)
    if not report['ok'] or expected != actual:
        raise ValueError('准备资料已变化或检查未通过；请在准备阶段重新调用检查，不会边提交边修改')
    if not legacy and require_scene_round and data.task_type.startswith('video-') and 'scene_composition' not in expected:
        raise ValueError('新视频任务必须先关联场次修改轮次；请使用--prepare-only补齐准备，旧登记任务仍按原记录恢复')
    if not legacy and not report.get('new_task_ready'):
        raise ValueError('新任务准备报告尚未覆盖完整登记要求；请使用--prepare-only补齐准备，不会在开工时补查')
    if not legacy:
        check_existing_video_identity(data, actual.get('mapping'))
    if not legacy and require_content_review and needs_content_review(data):
        content = report.get('content_checks', {})
        if content.get('version') != 1 or content.get('ok') is not True:
            raise ValueError('新H3任务缺少本版内容核对及文本检查；请使用--prepare-only补齐，不上传或提交')
    for name, stamp in report['sources'].items():
        if bound and name.endswith(('.api.json', '.workflow.json')):
            continue  # The upload binder owns and validates these actual path changes.
        path = project_file(data.project, name)
        try:
            current = _file_stamp(path, observed)
        except FileNotFoundError:
            raise ValueError('准备资料已变化：' + name + '；请返回准备阶段') from None
        if list(current) != stamp:
            raise ValueError('准备资料已变化：' + name + '；请返回准备阶段')
    if data.task_type.startswith('video-') and 'context_sources' not in report:
        if not legacy:
            raise ValueError('新任务准备报告缺少资料关联检查；请使用--prepare-only补齐准备')
        try:
            extra = context_checks(store, data, segment_plan_checked=data.segment_plan is not None)
            added_sources = {path.relative_to(data.project).as_posix(): list(_file_stamp(path, observed))
                             for path in map(Path, extra)}
        except (ValueError, OSError, KeyError, IndexError, TypeError, store.client.ClientError) as error:
            report.update(ok=False, error='旧报告缺项检查失败：' + str(error), context_checked_during='execution')
            write_report(data, report)
            raise ValueError(report['error']) from error
        report['context_sources'] = extra
        report['context_checked_during'] = 'execution'
        report['sources'].update(added_sources)
        write_report(data, report)
    if file_stamps is not None:
        file_stamps.update(observed)
    return report


def director_checks(workflow, timelines=None):
    rows = []
    for node in workflow.values():
        if node['class_type'] != 'MiniMaxH3Director':
            continue
        timeline = timelines[id(node)] if timelines is not None else json.loads(node['inputs']['timeline_data'])
        common = timeline['global']
        enabled = common.get('commonEnabled', False)
        indices = timeline['runSelection'] if timeline.get('runSelectEnabled') else range(len(timeline['segments']))
        for index in indices:
            group = timeline['segments'][index]
            prompt = '\n\n'.join(part.strip() for part in ([common.get('prompt', ''), group['prompt']] if enabled else [group['prompt']]) if part.strip())
            if len(prompt) > 7000:
                raise ValueError(f'原组{index}完整提示词超过7000字符')
            if not 0 < group['durationSec'] <= 15:
                raise ValueError(f'原组{index}请求时长不在0—15秒范围内')
            labels, counts, durations = set(), {}, {}
            for field, file_key, label, limit in (
                ('refs', 'imageFile', 'Picture', 9), ('refVideos', 'videoFile', 'Video', 3), ('refAudios', 'audioFile', 'Audio', 3)):
                public, local = list(common.get(field, [])) if enabled else [], list(group.get(field, []))
                if field == 'refVideos':
                    for block, items in ((common, public), (group, local)):
                        legacy = block.get('referenceVideo')
                        if (block is not common or enabled) and legacy and (legacy.get('videoFile') or legacy.get('fileName')) and not any(item['index'] == 0 for item in items):
                            items.insert(0, {**legacy, 'index': 0, 'videoFile': legacy.get('videoFile') or legacy['fileName']})
                if len({item['index'] for item in public}) != len(public) or len({item['index'] for item in local}) != len(local):
                    raise ValueError(f'原组{index}的{label}槽位重复')
                merged = {item['index']: item for item in public}
                merged.update({item['index']: item for item in local})
                if any(type(slot) is not int or slot < 0 or slot >= limit or not item.get(file_key) for slot, item in merged.items()):
                    raise ValueError(f'原组{index}的{label}槽位无效或超限')
                counts[label] = len(merged)
                labels.update((label, slot + 1) for slot in merged)
                if field != 'refs':
                    seconds = [item.get('durationSec') for item in merged.values()]
                    if any(not isinstance(value, (int, float)) or not 2 <= value <= 15 for value in seconds) or sum(seconds) > 15:
                        raise ValueError(f'原组{index}的{label}缺少有效时长或总时长超过15秒')
                    durations[label] = sum(seconds)
            if sum(counts.values()) > 12 or counts['Audio'] and not (counts['Picture'] or counts['Video']):
                raise ValueError(f'原组{index}参考素材组合超限')
            if any((kind, int(slot)) not in labels for kind, slot in re.findall(r'<(Picture|Video|Audio) (\d+)>', prompt)):
                raise ValueError(f'原组{index}正文标签没有对应的实际输入')
            rows.append({'index': index, 'characters': len(prompt), 'remaining': 7000 - len(prompt),
                         'seconds': group['durationSec'], 'counts': counts, 'reference_seconds': durations})
    return rows


def fixed_input_checks(store, data):
    client = store.client
    if not data.title.strip():
        raise ValueError('任务标题不能为空')
    for item in data.uploads:
        required = {'file', 'node', 'input', 'subfolder', 'response-name'}
        if not required.issubset(item) or set(item) - required - {'json-path'} or not all(isinstance(item[name], str) for name in required):
            raise ValueError('上传映射字段不完整或类型不正确')
        if 'json-path' in item and (not isinstance(item['json-path'], list) or not item['json-path']
                                   or any(type(part) not in (str, int) for part in item['json-path'])):
            raise ValueError('JSON素材绑定必须提供字段路径数组')
    names = [data.attempt_name, data.request_name, data.response_name, data.history_name,
             '后台任务状态.json', '后台过程记录.json']
    names += [output.response_name for output in data.outputs]
    names += [item['response-name'] for item in data.uploads]
    if data.segment_plan:
        names += [item.response_name for item in data.segment_plan.targets]
    elif not data.outputs:
        raise ValueError('必须登记预期成果保存映射')
    for name in names:
        client.remote_path(name, filename=True)
    if len(names) != len(set(names)):
        raise ValueError('证据文件名不能重复')
    if '执行检查报告.json' in names:
        raise ValueError('证据文件名不能占用执行检查报告.json')
    for folder in {item['subfolder'] for item in data.uploads}:
        client.remote_path(folder)
    for source in {Path(item['file']) for item in data.uploads}:
        client.remote_path(source.name, filename=True)
        if '"' in source.name:
            raise client.ClientError('invalid_filename', 'Upload filename cannot contain a quote')


def check_new_targets(data):
    if data.segment_plan and not data.segment_plan.targets:
        raise ValueError('新导演台任务必须显式提供每段本机成果保存路径')


def check_existing_video_identity(data, mapping):
    if not data.task_type.startswith('video-') or not mapping:
        return
    stage = {'video-first-pass': '一采', 'video-second-pass': '二采', 'video-postprocess': '后处理'}[data.task_type]
    stage_folder = {'一采': '01-一采', '二采': '02-二采', '后处理': '03-后处理'}[stage]
    for index in mapping['selected_indices']:
        entry = mapping['segments'][index]
        identity = entry['segment'] + '-' + entry['round'] + '-' + stage
        episode, scene = entry['segment'].split('-')[:2]
        root = Path(data.project) / '09-剧集制作' / episode
        folders = [root / '其他资料/候选视频', root / '06-阶段采用视频' / stage_folder / (scene + '-场次'),
                   root / '其他资料/阶段采用视频' / stage_folder / (scene + '-场次')]
        if any(file.is_file() and file.suffix in ('.mp4', '.webm', '.mov')
               for folder in folders for file in folder.glob(identity + '.*')):
            raise ValueError('候选编号已有视频文件，重新生成须使用新R；失败取回请沿原任务恢复：' + identity)


def fixed_checks(store, data, *, mapping=None, legacy=False):
    from backend.services.director_uploads import pairs
    from backend.services import comfy_segments as segments
    fixed_input_checks(store, data)
    if data.image_plan is not None:
        from backend.services.image_closeout import validate_plan
        validate_plan(data)
    path_scope = PreparationPaths.from_resolved(data.project,
                        [data.record_dir, *(item['file'] for item in data.uploads)])
    if not legacy:
        pairs.validate_rtx_inputs(data.workflow)
        check_new_targets(data)
    store.client.validate_workflow(data.workflow)
    if not data.segment_plan and any(node['class_type'] in ('MiniMaxH3Director', 'MiniMaxH3ReferenceToVideo') for node in data.workflow.values()):
        segments.validate_h3_stage(data.task_type)
    targets = [Path(output.path) for output in data.outputs]
    if len(targets) != len(set(targets)):
        raise ValueError('成果保存路径不能重复')
    selectors = [(out.node_id, out.output_key, out.index) for out in data.outputs]
    if any(output.node_id not in data.workflow for output in data.outputs):
        raise ValueError('预期输出节点不在工作流中')
    if len(selectors) != len(set(selectors)):
        raise ValueError('输出身份不能重复')
    documents, bindings = {}, []
    for item in data.uploads:
        if item['node'] not in data.workflow or item['input'] not in data.workflow[item['node']]['inputs']:
            raise ValueError('上传映射必须绑定已有输入')
        if 'json-path' in item:
            field = (item['node'], item['input'])
            if field not in documents:
                documents[field] = json.loads(data.workflow[field[0]]['inputs'][field[1]])
            value = documents[field]
            try:
                for part in item['json-path']:
                    value = value[part]
            except (KeyError, IndexError, TypeError) as error:
                raise ValueError('素材JSON字段路径不匹配：' + str(item['json-path'])) from error
        else:
            value = data.workflow[item['node']]['inputs'][item['input']]
        bindings.append((item, value))
    timelines = {id(node): (documents[(key, 'timeline_data')] if (key, 'timeline_data') in documents
                 else json.loads(node['inputs']['timeline_data'])) for key, node in data.workflow.items()
                 if node['class_type'] == 'MiniMaxH3Director'}
    native_segments = [node for node in data.workflow.values() if node['class_type'] == 'MiniMaxH3Director'
        and timelines[id(node)].get('output', {}).get('exportMode') == 'segments']
    if native_segments and not data.segment_plan:
        raise ValueError('原生H3分段任务必须登记segment-plan以对应最终成果')
    segment_context = None
    if data.segment_plan:
        try:
            segment_context = segments.validate(data, mapping=mapping, timelines=timelines, path_scope=path_scope)
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError('分段计划或输入映射字段不完整：' + str(error)) from error
        if data.outputs:
            raise ValueError('原生分段任务使用segment-plan，不混用末段保存节点作为全组输出')
    result = {'segments': director_checks(data.workflow, timelines)}
    if data.task_type.startswith('video-'):
        result['context_sources'] = context_checks(store, data, mapping=mapping, bindings=bindings,
                                                  timelines=timelines, segment_context=segment_context, path_scope=path_scope)
    return result


def context_checks(store, data, *, mapping=None, bindings=None, timelines=None, segment_context=None, segment_plan_checked=False, path_scope=None):
    if bindings is None:  # Legacy supplement or standalone context-only check.
        documents, bindings = {}, []
        for item in data.uploads:
            value = data.workflow[item['node']]['inputs'][item['input']]
            if 'json-path' in item:
                key = (item['node'], item['input'])
                if key not in documents:
                    documents[key] = json.loads(value)
                value = documents[key]
                for part in item['json-path']:
                    value = value[part]
            bindings.append((item, value))
    planned = {value: {'input_path': value, 'file': item['file']} for item, value in bindings}
    context = store.generation_context.prepare_generation_context(data.project, Path(data.record_dir),
                data.workflow, data.task_type, planned, check_only=True, mapping=mapping, timelines=timelines,
                segment_context=segment_context, segment_plan_checked=segment_plan_checked, path_scope=path_scope)
    return (context or {}).get('files', [])


def needs_content_review(data):
    return data.task_type in ('video-first-pass', 'video-second-pass') and any(
        node['class_type'] == 'MiniMaxH3Director' for node in data.workflow.values())


def storyboard_index_checks(data, mapping):
    from backend.parsers.project import table_records, storyboard_index_identity, production_scene_ids
    episode = mapping['scene'].split('-')[0]
    base = '09-剧集制作/' + episode
    script_key = base + '/02-剧集剧本/' + episode + '-本集剧本.md'
    index_key = base + '/03-分镜脚本/' + episode + '-分镜索引.md'
    script = project_file(data.project, script_key).read_text('utf-8-sig')
    index = project_file(data.project, index_key).read_text('utf-8-sig')
    scenes = production_scene_ids(script, episode)
    if not scenes:
        raise ValueError(script_key + '：缺少内容正文或完整场次标题')
    rows = table_records(index, ('场次', '分段', '分段计划时长（秒）'))
    if not rows:
        raise ValueError(index_key + '：没有可读取的分段表')
    for row in rows:
        try:
            storyboard_index_identity(episode, scenes, row)
        except ValueError as error:
            raise ValueError(index_key + '：' + str(error)) from error
    return {'ok': True, 'rows': len(rows),
            'files': [str(project_file(data.project, key)) for key in (script_key, index_key)]}


def content_checks(data, mapping, report):
    from h3_prompt_checks import audit
    result = audit(data.project, data.workflow, mapping)
    report['content_checks'] = result
    if not result['ok']:
        issues = result['issues'] + [issue for group in result['groups'] for issue in group['issues']]
        raise ValueError('H3正文与内容核对未通过：' + '；'.join(
            dict.fromkeys(issue['code'] + ': ' + issue['detail'] for issue in issues)))
    return result['sources']


def prepare_report(store, data, *, at_execution=False, previous=...):
    """Fixed checks, including legacy execution fallback; never uploads or submits generation."""
    if previous is ...:
        previous = read_report(data)
    report = {'ok': False, 'checked_at': store.client.now(), 'prepared_input': {}, 'sources': {},
              'checked_during': 'execution' if at_execution else 'preparation'}
    try:
        mapping_file = Path(data.record_dir) / '输入映射.json'
        mapping = json.loads(mapping_file.read_text('utf-8-sig')) if mapping_file.exists() else {}
        report['prepared_input'] = basis(store, data, mapping)
        if not at_execution:
            check_existing_video_identity(data, mapping)
        if not at_execution and data.task_type.startswith('video-'):
            if 'scene_composition' not in report['prepared_input']:
                check_new_targets(data)
                raise ValueError('新视频任务必须填写scene_modification_round，关联单集修改轮次后再准备；不得用执行时间线代替')
            from episode_rounds import episode_manifest_key, validate_episode_manifest
            episode = mapping['scene'].split('-')[0]
            manifest = Path(data.project) / episode_manifest_key(episode)
            if not manifest.exists() or not any(item['number'] == mapping['scene_modification_round']
                    for item in validate_episode_manifest(json.loads(manifest.read_text('utf-8-sig')), episode)['rounds']):
                raise ValueError('新视频任务须先登记单集共用的修改轮次，旧场次轮次仅用于历史任务')
        composition = report['prepared_input'].get('scene_composition')
        expected = previous['prepared_input'].copy() if previous else {}
        if previous and 'title' not in expected:
            expected['title'] = data.title
        requires_content = not at_execution and needs_content_review(data)
        requires_index = not at_execution and data.task_type.startswith('video-')
        content_current = (not requires_content or previous is not None
                           and previous.get('content_checks', {}).get('version') == 1
                           and previous['content_checks'].get('ok') is True)
        if previous and previous['ok'] and expected == report['prepared_input']:
            observed = {}
            index_files = previous.get('storyboard_index', {}).get('files', [])
            report['sources'] = sources(data, previous.get('context_sources', []) + previous.get('content_checks', {}).get('sources', []) + index_files, mapping, observed=observed, composition=composition)
            if previous['sources'] == report['sources']:
                report.update(previous)
                changed = False
                if not content_current:
                    content_checks(data, mapping, report)
                    report['sources'] = sources(data, previous.get('context_sources', []) + report['content_checks']['sources'], mapping, observed=observed, composition=composition)
                    changed = True
                if requires_index and not previous.get('storyboard_index', {}).get('ok'):
                    report['storyboard_index'] = storyboard_index_checks(data, mapping)
                    changed = True
                if not at_execution and not previous.get('new_task_ready'):
                    check_new_targets(data)
                    report['new_task_ready'] = True
                    changed = True
                if data.task_type.startswith('video-') and 'context_sources' not in previous:
                    extra = context_checks(store, data, mapping=mapping, segment_plan_checked=data.segment_plan is not None)
                    report.update(context_sources=extra, context_checked_during='preparation')
                    report['sources'] = sources(data, extra + report.get('content_checks', {}).get('sources', []), mapping, observed=observed, composition=composition)
                    changed = True
                if changed:
                    report['sources'] = sources(data, report.get('context_sources', []) + report.get('content_checks', {}).get('sources', []) + report.get('storyboard_index', {}).get('files', []), mapping, observed=observed, composition=composition)
                    write_report(data, report)
                return {'prepared': True, 'report': REPORT, 'reused': True,
                        'checks': {'segments': previous['segments']}}
        if requires_index:
            report['storyboard_index'] = storyboard_index_checks(data, mapping)
        if requires_content:
            content_checks(data, mapping, report)
        report.update(fixed_checks(store, data, mapping=mapping, legacy=at_execution))
        if data.task_type.startswith('video-'):
            report.setdefault('context_sources', [])
        report['sources'] = sources(data, report.get('context_sources', []) + report.get('content_checks', {}).get('sources', []) + report.get('storyboard_index', {}).get('files', []), mapping, composition=composition)
        report['ok'] = True
        if not at_execution:
            report['new_task_ready'] = True
    except (ValueError, OSError, store.client.ClientError) as error:
        report['ok'] = False
        report['error'] = str(error)
        write_report(data, report)
        raise
    except (KeyError, IndexError, TypeError) as error:
        report['ok'] = False
        report['error'] = '本地准备字段不完整或类型不正确：' + str(error)
        write_report(data, report)
        raise ValueError(report['error']) from error
    write_report(data, report)
    result = {'prepared': True, 'report': REPORT, 'checks': {'segments': report['segments']}}
    if at_execution:
        result['sources'] = report['sources']
    return result
