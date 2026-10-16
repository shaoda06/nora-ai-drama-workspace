"""Tool-owned local preparation report. No remote capability query or generation POST."""
import json
import re
import tempfile
from pathlib import Path

from project_paths import project_file, recorded_paths

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
    for name in ('desktop', 'thread_id', 'source_session_name', 'timeout', 'start_paused'):
        payload.pop(name, None)
    mapping_file = Path(data.record_dir) / '输入映射.json'
    if mapping is None:
        mapping = json.loads(mapping_file.read_text('utf-8-sig')) if mapping_file.exists() else {}
    if mapping:
        payload['mapping'] = recorded_paths(data.project, {name: mapping[name] for name in (
            'scene', 'task_type', 'screenplay_version', 'scene_storyboard_version', 'selected_indices', 'segments') if name in mapping}, relative=True)
    return payload


def sources(data, extra=(), mapping=None):
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
    return {path.relative_to(data.project).as_posix(): [stamp.st_size, stamp.st_mtime_ns]
            for path in sorted(files) for stamp in [path.stat()]}


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


def check_prepared(store, data, *, bound=False, transferred=False, legacy=False):
    report = read_report(data)
    if report is None:
        if legacy:
            return None
        raise ValueError('新任务必须先通过准备检查；请使用--prepare-only完成准备，不会在开工时补查')
    expected, actual = report['prepared_input'].copy(), basis(store, data)
    if 'title' not in expected:  # Reports made before title became a preparation field.
        actual.pop('title', None)
    if transferred:
        expected.pop('url', None)
        actual.pop('url', None)
    if not report['ok'] or expected != actual:
        raise ValueError('准备资料已变化或检查未通过；请在准备阶段重新调用检查，不会边提交边修改')
    if not legacy and not report.get('new_task_ready'):
        raise ValueError('新任务准备报告尚未覆盖完整登记要求；请使用--prepare-only补齐准备，不会在开工时补查')
    for name, stamp in report['sources'].items():
        if bound and name.endswith(('.api.json', '.workflow.json')):
            continue  # The upload binder owns and validates these actual path changes.
        path = project_file(data.project, name)
        try:
            current = path.stat()
        except FileNotFoundError:
            raise ValueError('准备资料已变化：' + name + '；请返回准备阶段') from None
        if [current.st_size, current.st_mtime_ns] != stamp:
            raise ValueError('准备资料已变化：' + name + '；请返回准备阶段')
    if data.task_type.startswith('video-') and 'context_sources' not in report:
        if not legacy:
            raise ValueError('新任务准备报告缺少资料关联检查；请使用--prepare-only补齐准备')
        try:
            extra = context_checks(store, data, segment_plan_checked=data.segment_plan is not None)
        except (ValueError, OSError, KeyError, IndexError, TypeError, store.client.ClientError) as error:
            report.update(ok=False, error='旧报告缺项检查失败：' + str(error), context_checked_during='execution')
            write_report(data, report)
            raise ValueError(report['error']) from error
        report['context_sources'] = extra
        report['context_checked_during'] = 'execution'
        for path in map(Path, extra):
            current = path.stat()
            report['sources'][path.relative_to(data.project).as_posix()] = [current.st_size, current.st_mtime_ns]
        write_report(data, report)
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


def fixed_checks(store, data, *, mapping=None, legacy=False):
    from backend.services.director_uploads import check_pair
    from backend.services import comfy_segments as segments
    fixed_input_checks(store, data)
    if not legacy:
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
    documents = {}
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
            segment_context = segments.validate(data, mapping=mapping, timelines=timelines)
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError('分段计划或输入映射字段不完整：' + str(error)) from error
        if data.outputs:
            raise ValueError('原生分段任务使用segment-plan，不混用末段保存节点作为全组输出')
    result = {'pair': check_pair(Path(data.record_dir), data.workflow, timelines=timelines), 'segments': director_checks(data.workflow, timelines)}
    if data.task_type.startswith('video-'):
        result['context_sources'] = context_checks(store, data, mapping=mapping, documents=documents, timelines=timelines, segment_context=segment_context)
    return result


def context_checks(store, data, *, mapping=None, documents=None, timelines=None, segment_context=None, segment_plan_checked=False):
    documents = {} if documents is None else documents
    planned = {}
    for item in data.uploads:
        value = data.workflow[item['node']]['inputs'][item['input']]
        if 'json-path' in item:
            key = (item['node'], item['input'])
            if key not in documents:
                documents[key] = json.loads(value)
            value = documents[key]
            for part in item['json-path']:
                value = value[part]
        planned[value] = {'input_path': value, 'file': item['file']}
    context = store.generation_context.prepare_generation_context(data.project, Path(data.record_dir),
                data.workflow, data.task_type, planned, check_only=True, mapping=mapping, timelines=timelines,
                segment_context=segment_context, segment_plan_checked=segment_plan_checked)
    return (context or {}).get('files', [])


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
        expected = previous['prepared_input'].copy() if previous else {}
        if previous and 'title' not in expected:
            expected['title'] = data.title
        if previous and previous['ok'] and expected == report['prepared_input']:
            report['sources'] = sources(data, previous.get('context_sources', []), mapping)
            if previous['sources'] == report['sources']:
                report.update(previous)
                changed = False
                if not at_execution and not previous.get('new_task_ready'):
                    check_new_targets(data)
                    report['new_task_ready'] = True
                    changed = True
                if data.task_type.startswith('video-') and 'context_sources' not in previous:
                    extra = context_checks(store, data, mapping=mapping, segment_plan_checked=data.segment_plan is not None)
                    report.update(context_sources=extra, context_checked_during='preparation')
                    report['sources'] = sources(data, extra, mapping)
                    changed = True
                if changed:
                    write_report(data, report)
                return {'prepared': True, 'report': REPORT, 'reused': True,
                        'checks': {key: previous[key] for key in ('pair', 'segments')}}
        report.update(fixed_checks(store, data, mapping=mapping, legacy=at_execution))
        if data.task_type.startswith('video-'):
            report.setdefault('context_sources', [])
        report['sources'] = sources(data, report.get('context_sources', []), mapping)
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
    result = {'prepared': True, 'report': REPORT, 'checks': {key: report[key] for key in ('pair', 'segments')}}
    if at_execution:
        result['sources'] = report['sources']
    return result
