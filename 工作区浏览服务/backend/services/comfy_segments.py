"""Retrieve native H3 segments only from a completed task’s final report."""
import argparse
import asyncio
import json
from pathlib import Path, PureWindowsPath, PurePosixPath
import re

from pydantic import BaseModel, Field
from backend.services.collection_retry import failure, saved_files


class SegmentTarget(BaseModel):
    index: int = Field(ge=0)
    path: str
    response_name: str


class SegmentPlan(BaseModel):
    director_node: str
    report_node: str
    output_root: str
    targets: list[SegmentTarget] = Field(default_factory=list)


REPORT = re.compile(r'^Segment (\d+)(?:/\d+)?: (一采 mp4|mp4) (saved|updated after continuity trim) → (.+)$', re.M)


def remote_file(root, absolute):
    cls = PureWindowsPath if re.match(r'^[A-Za-z]:[\\/]', root) else PurePosixPath
    root, absolute = cls(root), cls(absolute.strip())
    if not root.is_absolute() or not absolute.is_absolute() or '..' in absolute.parts:
        raise ValueError('分段来源必须是已核实output根目录内的绝对路径')
    relative = absolute.relative_to(root)
    if not relative.parts or relative.parts[0] != 'minimax_seg_export' or relative.suffix != '.mp4':
        raise ValueError('分段来源不属于原生MP4导出目录')
    return {'filename': relative.name, 'subfolder': relative.parent.as_posix(), 'type': 'output'}


def targets(data, mapping=None, *, segment_context=None):
    from backend.services.comfy_tasks import paths
    project = Path(data.project).resolve()
    if mapping is None:
        mapping = json.loads((Path(data.record_dir) / '输入映射.json').read_text('utf-8-sig'))
    stage = {'video-first-pass': '一采', 'video-second-pass': '二采'}[data.task_type]
    result = []
    for index in mapping['selected_indices']:
        segment = mapping['segments'][index]
        identity = f"{segment['segment']}-{segment['round']}-{stage}"
        record = (segment_context['entries'][index]['directory'] if segment_context is not None
                  else paths.project_file(project, segment['local_execution_dir'], recorded=True))
        episode = segment['segment'].split('-')[0]
        explicit = next((item for item in data.segment_plan.targets if item.index == index), None)
        candidate = Path(explicit.path) if explicit else project / '09-剧集制作' / episode / '其他资料/候选视频' / (identity + '.mp4')
        result.append({'index': index, 'identity': identity, 'record': record, 'candidate': candidate, 'response_name': explicit.response_name if explicit else f'最终取回-{index:03d}.json'})
    return result


def validate_h3_stage(task_type):
    from backend.services.comfy_tasks import client
    if task_type not in ('video-first-pass', 'video-second-pass'):
        raise client.ClientError('invalid_task_type', 'H3 generation requires a first-pass or second-pass task type')


def validate(data, *, mapping=None, timelines=None):
    from backend.services.comfy_tasks import generation_context
    plan = data.segment_plan
    validate_h3_stage(data.task_type)
    if mapping is None:
        mapping = json.loads((Path(data.record_dir) / '输入映射.json').read_text('utf-8-sig'))
    context = generation_context.validate_segment_context(data.project, data.workflow, data.task_type, mapping, timelines=timelines)
    director = data.workflow[plan.director_node]
    if director is not context['director'] or plan.report_node not in data.workflow:
        raise ValueError('分段计划必须绑定实际导演台及报告节点')
    # Require the report node's input to be this director's report output (slot 5).
    if [plan.director_node, 5] not in data.workflow[plan.report_node]['inputs'].values():
        raise ValueError('报告节点未连接该导演台report输出')
    timeline = context['timeline']
    if timeline['output'].get('exportMode') != 'segments':
        raise ValueError('分段取回需要原生segments导出')
    selected = context['indices']
    explicit = plan.targets
    if explicit and (len(explicit) != len(selected) or {item.index for item in explicit} != set(selected)):
        raise ValueError('本机成果目标必须逐一对应实际执行分段')
    if len({Path(item.path) for item in explicit}) != len(explicit):
        raise ValueError('分段目标路径不能重复')
    for item in targets(data, mapping, segment_context=context):
        if item['candidate'].exists():
            raise ValueError('本轮候选已存在；核对原任务，不得重复提交')
    remote_file(plan.output_root, plan.output_root.rstrip('/\\') + '/minimax_seg_export/validation/seg_0000.mp4')
    return context


async def finish(store, key, result):
    from backend.services.comfy_tasks import paths as project_paths
    data, state = store.rows[key]['input'], store.rows[key]['state']
    row = store.rows[key]
    if row.get('_segment_result') is not result:
        outputs = result['history'].get('outputs', {}).get(data.segment_plan.report_node, {})
        text = '\n'.join(value for values in outputs.values() if isinstance(values, list)
                         for value in values if isinstance(value, str))
        paths = {}
        for match in REPORT.finditer(text):
            if (match[2] == '一采 mp4') == (data.task_type == 'video-first-pass'):
                paths[int(match[1]) - 1] = match[4].strip()
        row['_segment_paths'], row['_segment_result'] = paths, result
    paths = row['_segment_paths']
    problems, collected = [], 0
    state.setdefault('segments', {})
    expected_targets = store.rows[key].get('_collection_targets')
    if expected_targets is None:
        expected_targets = store.rows[key]['_collection_targets'] = targets(data)
    verified = store.rows[key].setdefault('_collection_ok', {})
    if state['expected'] != len(expected_targets):
        store.save(key, expected=len(expected_targets))
    for target in expected_targets:
        item = state['segments'].setdefault(str(target['index']), {
            'identity': target['identity'], 'index': target['index'], 'check': '未取回', 'error': None})
        try:
            if target['index'] not in paths:
                raise ValueError('最终报告缺少该段的保存路径')
            source = remote_file(data.segment_plan.output_root, paths[target['index']])
            expected = f"seg_{target['index']:04d}{'_pre' if data.task_type == 'video-first-pass' else ''}.mp4"
            if source['filename'] != expected:
                raise ValueError('最终报告路径与分段身份不一致')
            receipt_path = Path(data.record_dir) / target['response_name']
            candidate = target['candidate']
            stamp, receipt_exists = saved_files(receipt_path, candidate)
            proof = (state['prompt_id'], source, stamp)
            fresh = False
            if proof[-1] is not None and verified.get(str(receipt_path)) == proof:
                pass
            elif receipt_exists:
                receipt = store.client.strict_json(receipt_path.read_bytes())
                downloaded = receipt['data']
                if (receipt['prompt_id'] != state['prompt_id'] or downloaded['remote'] != source
                        or project_paths.project_file(data.project, downloaded['path'], recorded=True) != candidate
                        or proof[-1] is None or proof[-1][1][0] != downloaded['bytes']):
                    raise ValueError('已有最终下载凭据与文件不一致，不覆盖文件')
            else:
                downloaded = await asyncio.to_thread(store.client.download, store.client_for(data), argparse.Namespace(
                    filename=source['filename'], subfolder=source['subfolder'], type='output', output=str(candidate), sha256=None))
                downloaded['path'] = store.record_paths(key).relative_file(downloaded['path'])
                store.client.write_new(receipt_path, {'time': store.client.now(), 'prompt_id': state['prompt_id'],
                                                     'identity': target['identity'], 'data': downloaded})
                proof = (state['prompt_id'], source, saved_files(receipt_path, candidate)[0])
                fresh = True
            verified[str(receipt_path)] = proof
            item.update(remote=source, path=str(candidate), receipt=str(receipt_path), bytes=proof[-1][1][0], check='已取回', error=None)
            collected += 1
            if fresh:
                store.record(key, 'download', 'success', path=str(candidate), remote=source, receipt=str(receipt_path),
                             attempt=state.get('collection_attempt', 1), _changes={'collected': collected})
        except (store.client.ClientError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            item.update(error=str(error), check='取回失败')
            issue = failure(error, store.client.ClientError, identity=target['identity'])
            problems.append(issue)
            store.record(key, 'download', 'failed', **issue, attempt=state.get('collection_attempt', 1))
    if state['collected'] != collected:
        store.save(key, collected=collected)
    return problems
