"""Retrieve native H3 segments only from a completed task’s final report."""
import argparse
import asyncio
import json
from pathlib import Path, PureWindowsPath, PurePosixPath
import re

from pydantic import BaseModel, Field


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


def targets(data):
    project = Path(data.project).resolve()
    mapping = json.loads((Path(data.record_dir) / '输入映射.json').read_text('utf-8-sig'))
    stage = {'video-first-pass': '一采', 'video-second-pass': '二采'}[data.task_type]
    result = []
    for index in mapping['selected_indices']:
        segment = mapping['segments'][index]
        identity = f"{segment['segment']}-{segment['round']}-{stage}"
        record = (project / segment['local_execution_dir']).resolve()
        episode = segment['segment'].split('-')[0]
        explicit = next((item for item in data.segment_plan.targets if item.index == index), None)
        candidate = Path(explicit.path).resolve() if explicit else project / '09-剧集制作' / episode / '其他资料/候选视频' / (identity + '.mp4')
        result.append({'index': index, 'identity': identity, 'record': record, 'candidate': candidate, 'response_name': explicit.response_name if explicit else f'最终取回-{index:03d}.json'})
    return result


def validate(data):
    plan = data.segment_plan
    if data.task_type not in ('video-first-pass', 'video-second-pass'):
        raise ValueError('分段计划仅用于原生H3一采／二采')
    if sum(node['class_type'] == 'MiniMaxH3Director' for node in data.workflow.values()) != 1:
        raise ValueError('分段取回需要一个明确的原生导演台节点')
    director = data.workflow[plan.director_node]
    if director['class_type'] != 'MiniMaxH3Director' or plan.report_node not in data.workflow:
        raise ValueError('分段计划必须绑定实际导演台及报告节点')
    # Require the report node's input to be this director's report output (slot 5).
    if [plan.director_node, 5] not in data.workflow[plan.report_node]['inputs'].values():
        raise ValueError('报告节点未连接该导演台report输出')
    timeline = json.loads(director['inputs']['timeline_data'])
    if timeline['output'].get('exportMode') != 'segments':
        raise ValueError('分段取回需要原生segments导出')
    mapping = json.loads((Path(data.record_dir) / '输入映射.json').read_text('utf-8-sig'))
    selected = sorted(timeline['runSelection']) if timeline.get('runSelectEnabled', False) else list(range(len(timeline['segments'])))
    if not selected or mapping['selected_indices'] != selected or len(mapping['segments']) != len(timeline['segments']):
        raise ValueError('分段计划与实际执行组序不一致')
    project = Path(data.project).resolve()
    explicit = plan.targets
    if explicit and (len(explicit) != len(selected) or {item.index for item in explicit} != set(selected)):
        raise ValueError('本机成果目标必须逐一对应实际执行分段')
    if len({Path(item.path).resolve() for item in explicit}) != len(explicit):
        raise ValueError('分段目标路径不能重复')
    for target in explicit:
        if not Path(target.path).is_absolute() or not Path(target.path).resolve().is_relative_to(project):
            raise ValueError('分段成果目标必须使用项目内绝对路径')
        if Path(target.path).resolve().is_relative_to(Path(data.record_dir).resolve()):
            raise ValueError('成果不能保存在共同执行附件内')
        if Path(target.response_name).name != target.response_name:
            raise ValueError('分段下载凭据必须是文件名')
    for item in targets(data):
        if (not re.fullmatch(re.escape(mapping['scene']) + r'-P\d{3,}-R\d{3,}-(一采|二采)', item['identity'])
                or not item['record'].is_relative_to(project)
                or item['record'].name != item['identity'] and item['record'].parent.name != item['identity']):
            raise ValueError('分段身份或执行附件目录不正确')
        if item['candidate'].exists():
            raise ValueError('本轮候选已存在；核对原任务，不得重复提交')
    remote_file(plan.output_root, plan.output_root.rstrip('/\\') + '/minimax_seg_export/validation/seg_0000.mp4')


async def finish(store, key, result):
    data, state = store.rows[key]['input'], store.rows[key]['state']
    outputs = result['history'].get('outputs', {}).get(data.segment_plan.report_node, {})
    text = '\n'.join(value for values in outputs.values() if isinstance(values, list)
                     for value in values if isinstance(value, str))
    paths = {}
    for match in REPORT.finditer(text):
        if (match[2] == '一采 mp4') == (data.task_type == 'video-first-pass'):
            paths[int(match[1]) - 1] = match[4].strip()
    problems, collected = [], 0
    state.setdefault('segments', {})
    expected_targets = targets(data)
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
            if receipt_path.exists():
                receipt = store.client.strict_json(receipt_path.read_bytes())
                downloaded = receipt['data']
                if (receipt['prompt_id'] != state['prompt_id'] or downloaded['remote'] != source
                        or downloaded['path'] != str(candidate) or not candidate.is_file()
                        or candidate.stat().st_size != downloaded['bytes']):
                    raise ValueError('已有最终下载凭据与文件不一致，不覆盖文件')
            else:
                downloaded = await asyncio.to_thread(store.client.download, store.client_for(data), argparse.Namespace(
                    filename=source['filename'], subfolder=source['subfolder'], type='output', output=str(candidate), sha256=None))
                store.client.write_new(receipt_path, {'time': store.client.now(), 'prompt_id': state['prompt_id'],
                                                     'identity': target['identity'], 'data': downloaded})
            item.update(remote=source, path=str(candidate), check='已取回', error=None)
            collected += 1
            store.record(key, 'download', 'success', path=str(candidate), remote=source, receipt=str(receipt_path))
        except (store.client.ClientError, OSError, ValueError, KeyError) as error:
            item.update(error=str(error), check='取回失败')
            problems.append(target['identity'] + '：' + str(error))
            store.record(key, 'download', 'failed', identity=target['identity'], error=str(error))
        store.save(key, collected=collected)
    return problems
