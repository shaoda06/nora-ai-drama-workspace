"""Tool-owned local preparation report. No remote capability query or generation POST."""
import json
import re
import tempfile
from pathlib import Path

from project_paths import project_file

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


def basis(store, data):
    payload = store.portable_input(data)
    for name in ('desktop', 'thread_id', 'source_session_name', 'title', 'timeout', 'start_paused'):
        payload.pop(name, None)
    mapping_file = Path(data.record_dir) / '输入映射.json'
    if mapping_file.exists():
        mapping = json.loads(mapping_file.read_text('utf-8-sig'))
        payload['mapping'] = {name: mapping[name] for name in (
            'scene', 'task_type', 'screenplay_version', 'scene_storyboard_version', 'selected_indices', 'segments') if name in mapping}
    return payload


def sources(data):
    files = {Path(item['file']).resolve() for item in data.uploads}
    record = Path(data.record_dir)
    files.update(record.glob('*.api.json'))
    files.update(record.glob('*.workflow.json'))
    mapping_file = record / '输入映射.json'
    if mapping_file.exists():
        mapping = json.loads(mapping_file.read_text('utf-8-sig'))
        if mapping.get('storyboard_file'):
            files.add(project_file(data.project, mapping['storyboard_file'], recorded=True))
        for context in mapping.get('generation_contexts', []):
            files.update(project_file(data.project, name, recorded=True) for name in context.get('prompts', {}).values())
    return {path.relative_to(data.project).as_posix(): [path.stat().st_size, path.stat().st_mtime_ns]
            for path in sorted(files)}


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


def check_prepared(store, data, *, bound=False, transferred=False):
    report = read_report(data)
    if report is None:
        return None  # Existing queued tasks can perform their first tool check at execution.
    expected, actual = report['prepared_input'].copy(), basis(store, data)
    if transferred:
        expected.pop('url', None)
        actual.pop('url', None)
    if not report['ok'] or expected != actual:
        raise ValueError('准备资料已变化或检查未通过；请在准备阶段重新调用检查，不会边提交边修改')
    for name, stamp in report['sources'].items():
        if bound and name.endswith(('.api.json', '.workflow.json')):
            continue  # The upload binder owns and validates these actual path changes.
        path = project_file(data.project, name)
        if not path.exists() or [path.stat().st_size, path.stat().st_mtime_ns] != stamp:
            raise ValueError('准备资料已变化：' + name + '；请返回准备阶段')
    return report


def director_checks(workflow):
    rows = []
    for node in workflow.values():
        if node['class_type'] != 'MiniMaxH3Director':
            continue
        timeline = json.loads(node['inputs']['timeline_data'])
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
    for item in data.uploads:
        client.remote_path(item['subfolder'])
    for source in {Path(item['file']) for item in data.uploads}:
        if not source.is_absolute():
            raise ValueError('上传映射必须使用本机绝对路径')
        client.remote_path(source.name, filename=True)
        if '"' in source.name:
            raise client.ClientError('invalid_filename', 'Upload filename cannot contain a quote')


def fixed_checks(store, data):
    from backend.services.director_uploads import check_pair
    from backend.services import comfy_segments as segments
    fixed_input_checks(store, data)
    store.client.validate_workflow(data.workflow)
    if (any(node['class_type'] in ('MiniMaxH3Director', 'MiniMaxH3ReferenceToVideo') for node in data.workflow.values())
            and data.task_type not in ('video-first-pass', 'video-second-pass')):
        raise store.client.ClientError('invalid_task_type', 'H3 generation requires a first-pass or second-pass task type')
    targets = [Path(output.path).resolve() for output in data.outputs]
    if len(targets) != len(set(targets)):
        raise ValueError('成果保存路径不能重复')
    selectors = [(out.node_id, out.output_key, out.index) for out in data.outputs]
    if any(output.node_id not in data.workflow for output in data.outputs):
        raise ValueError('预期输出节点不在工作流中')
    if len(selectors) != len(set(selectors)):
        raise ValueError('输出身份不能重复')
    for item in data.uploads:
        if item['node'] not in data.workflow or item['input'] not in data.workflow[item['node']]['inputs']:
            raise ValueError('上传映射必须绑定已有输入')
    native_segments = [node for node in data.workflow.values() if node['class_type'] == 'MiniMaxH3Director'
        and json.loads(node['inputs']['timeline_data']).get('output', {}).get('exportMode') == 'segments']
    if native_segments and not data.segment_plan:
        raise ValueError('原生H3分段任务必须登记segment-plan以对应最终成果')
    if data.segment_plan:
        try:
            segments.validate(data)
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError('分段计划或输入映射字段不完整：' + str(error)) from error
        if data.outputs:
            raise ValueError('原生分段任务使用segment-plan，不混用末段保存节点作为全组输出')
    return {'pair': check_pair(Path(data.record_dir), data.workflow), 'segments': director_checks(data.workflow)}


def prepare_report(store, data, *, at_execution=False):
    """Fixed checks, including legacy execution fallback; never uploads or submits generation."""
    previous = read_report(data)
    report = {'ok': False, 'checked_at': store.client.now(), 'prepared_input': basis(store, data), 'sources': {},
              'checked_during': 'execution' if at_execution else 'preparation'}
    try:
        if previous and previous['ok'] and previous['prepared_input'] == report['prepared_input']:
            report['sources'] = sources(data)
            if previous['sources'] == report['sources']:
                return {'prepared': True, 'report': REPORT, 'reused': True,
                        'checks': {key: previous[key] for key in ('pair', 'segments')}}
        report.update(fixed_checks(store, data))
        report['sources'] = sources(data)
        report['ok'] = True
    except (ValueError, OSError, store.client.ClientError) as error:
        report['error'] = str(error)
        write_report(data, report)
        raise
    except (KeyError, IndexError, TypeError) as error:
        report['error'] = '本地准备字段不完整或类型不正确：' + str(error)
        write_report(data, report)
        raise ValueError(report['error']) from error
    write_report(data, report)
    return {'prepared': True, 'report': REPORT, 'checks': {key: report[key] for key in ('pair', 'segments')}}
