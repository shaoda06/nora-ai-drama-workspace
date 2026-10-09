"""Native H3 incremental files; only saved paths bound to this task are eligible."""
import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath, PurePosixPath
import re

from pydantic import BaseModel


class SegmentPlan(BaseModel):
    director_node: str
    report_node: str
    output_root: str


ANSI = re.compile(r'\x1b\[[0-9;]*m')
RUN = re.compile(r'MiniMax H3 Director segment mp4 run dir: (.+)')
COMPLETED = re.compile(r'^(?:\[\w+\] )?Prompt executed in (?:\d+(?:\.\d+)? seconds|\d+:\d{2}:\d{2})\s*$')
SAVED = re.compile(r'MiniMax H3 Director segment #(\d+) (first-pass )?mp4 saved: (.+)')
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
        candidate = project / '09-剧集制作' / episode / '其他资料/候选视频' / (identity + '.mp4')
        result.append({'index': index, 'identity': identity, 'record': record, 'candidate': candidate})
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
        raise ValueError('运行中取回仅支持原生segments导出')
    mapping = json.loads((Path(data.record_dir) / '输入映射.json').read_text('utf-8-sig'))
    selected = sorted(timeline['runSelection']) if timeline.get('runSelectEnabled', False) else list(range(len(timeline['segments'])))
    if not selected or mapping['selected_indices'] != selected or len(mapping['segments']) != len(timeline['segments']):
        raise ValueError('分段计划与实际执行组序不一致')
    project = Path(data.project).resolve()
    for item in targets(data):
        if (not re.fullmatch(re.escape(mapping['scene']) + r'-P\d{3,}-R\d{3,}-(一采|二采)', item['identity'])
                or not item['record'].is_relative_to(project)
                or item['record'].name != item['identity'] and item['record'].parent.name != item['identity']):
            raise ValueError('分段身份或执行附件目录不正确')
        if item['candidate'].exists():
            raise ValueError('本轮候选已存在；核对原任务，不得重复提交')
    remote_file(plan.output_root, plan.output_root.rstrip('/\\') + '/minimax_seg_export/validation/seg_0000.mp4')


async def baseline(store, data):
    logs = await asyncio.to_thread(store.client_for(data).json, '/internal/logs/raw')
    entries = logs['entries']
    for item in entries:
        datetime.fromisoformat(item['t'])
        if not isinstance(item['m'], str):
            raise ValueError('远端保存日志格式异常')
    return max((item['t'] for item in entries), default='')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


async def scan(store, key, *, begin=False, terminal=False):
    """Bind the serial worker's current run without skipping buffered start logs."""
    row = store.rows[key]
    data, state = row['input'], row['state']
    remote = store.client_for(data)
    if not terminal:
        queue = await asyncio.to_thread(remote.json, '/queue')
        if [item[1] for item in queue['queue_running']] != [state['prompt_id']]:
            return
    logs = await asyncio.to_thread(remote.json, '/internal/logs/raw')
    entries = logs['entries']
    runtime = state['segment_monitor']
    if not terminal and not runtime['run_dir']:
        # The queue can advance while GET logs is in flight. Never bind the next job.
        queue = await asyncio.to_thread(remote.json, '/queue')
        if [item[1] for item in queue['queue_running']] != [state['prompt_id']]:
            return
    if begin and not runtime['started']:
        runtime['started'] = True
        store.save(key)
    if not runtime['started']:
        return  # A missed start cannot safely identify a new run directory from global logs.
    fresh = [item for item in entries if item['t'] > runtime['cursor']]
    if not runtime['run_dir']:
        # ComfyUI logs this after task_done and before starting the next queued prompt.
        # Everything after the last completion belongs to the verified running job.
        # Unlike wall-clock conversion, this also works with remote naive timestamps.
        completed = [i for i, item in enumerate(entries) if COMPLETED.fullmatch(ANSI.sub('', item['m']).strip())]
        if completed:
            fresh = entries[completed[-1] + 1:]
    runs = [RUN.search(ANSI.sub('', item['m'])) for item in fresh]
    runs = list(dict.fromkeys(match[1].strip() for match in runs if match))
    if runs and not terminal:
        if len(runs) != 1 or runtime['run_dir'] and runtime['run_dir'] != runs[0]:
            raise ValueError('本轮出现多个无法区分的导演台运行目录，等待终态报告核对')
        # Validate the real directory using a placeholder only for containment, never download it.
        remote_file(data.segment_plan.output_root, runs[0].rstrip('/\\') + '/validation.mp4')
        runtime['run_dir'] = runs[0]
        runtime['run_evidence'] = next({'t': item['t'], 'm': ANSI.sub('', item['m'])}
            for item in fresh if RUN.search(ANSI.sub('', item['m'])))
    selected = {item['index']: item for item in targets(data)}
    for entry in fresh:
        match = SAVED.search(ANSI.sub('', entry['m']))
        if match and not runtime['run_dir']:
            raise ValueError('保存事件缺少可绑定的本轮运行目录，等待最终报告核对')
        if not match:
            continue
        index, pre, absolute = int(match[1]) - 1, bool(match[2]), match[3].strip()
        if index not in selected or pre != (data.task_type == 'video-first-pass'):
            continue
        identity = remote_file(data.segment_plan.output_root, absolute)
        run_identity = remote_file(data.segment_plan.output_root, runtime['run_dir'].rstrip('/\\') + '/validation.mp4')
        if identity['subfolder'] != run_identity['subfolder']:
            continue
        expected = f"seg_{index:04d}{'_pre' if pre else ''}.mp4"
        if identity['filename'] != expected:
            raise ValueError('保存日志的组序与真实文件名不一致')
        # Persist only the task's save evidence, never entire logs or other users' prompts.
        item = state['segments'][str(index)]
        item['remote'] = identity
        item['save_evidence'] = {'t': entry['t'], 'm': ANSI.sub('', entry['m'])}
        item['save_version'] = entry['t']
    if fresh:
        runtime['cursor'] = max(runtime['cursor'], max(item['t'] for item in fresh))
    store.save(key)
    for target in selected.values():
        item = state['segments'][str(target['index'])]
        if item.get('remote') and item.get('downloaded_version') != item['save_version']:
            try:
                await retrieve(store, key, target, final=False)
            except (store.client.ClientError, OSError, ValueError) as error:
                item['failures'] = item.get('failures', 0) + 1
                item['error'] = str(error)
                store.save(key)
                if item['failures'] >= 3:
                    store.queue_notice(key, 'download_issue:' + target['identity'], 'attention',
                        target['identity'] + '连续取回失败；已有候选保留，后台继续补查：' + str(error))
            else:
                item['failures'] = 0
                store.save(key)


async def retrieve(store, key, target, *, final):
    row = store.rows[key]
    data, state = row['input'], row['state']
    item = state['segments'][str(target['index'])]
    versions = item['versions']
    record = target['record']
    source = item['remote']
    if item.get('pending') and item['pending']['version'] != item['save_version']:
        number = item['pending']['number']
        previous_path = record / (source['filename'] if not versions else f'收尾取回-{number:03d}.mp4')
        if previous_path.exists() or (record / f'取回响应-{number:03d}.json').exists():
            raise ValueError('上次分段取回尚未核对，不能覆盖新的保存事件')
        item['pending'] = None  # A failed GET left neither complete media nor a receipt.
    if not item.get('pending'):
        item['retrievals'] = item.get('retrievals', 0) + 1
        item['pending'] = {'version': item['save_version'], 'number': item['retrievals']}
        store.save(key)
    revision = item['pending']['number']
    filename = source['filename'] if not versions else f"收尾取回-{revision:03d}.mp4"
    download_path = record / filename
    evidence_path = record / f'取回响应-{revision:03d}.json'
    evidence = {'source': item['save_evidence'], 'prompt_id': state['prompt_id'],
                'director_node': data.segment_plan.director_node, 'identity': target['identity'],
                'candidate_target': str(target['candidate']), 'final': final}
    # Durable evidence permits crash recovery between download and moving into candidates.
    if evidence_path.exists():
        receipt = store.client.strict_json(evidence_path.read_bytes())
        downloaded = receipt['data']
        if receipt['prompt_id'] != state['prompt_id'] or downloaded['remote'] != source:
            raise ValueError('已有分段取回凭据与本轮任务不一致')
    else:
        if download_path.exists():
            raise ValueError('分段文件存在但缺少下载凭据，需原会话核对，不覆盖文件')
        downloaded = await asyncio.to_thread(store.client.download, store.client_for(data), argparse.Namespace(
            filename=source['filename'], subfolder=source['subfolder'], type='output', output=str(download_path), sha256=None))
        store.client.write_new(evidence_path, {**evidence, 'time': store.client.now(), 'data': downloaded})
    local_unchanged = (versions and Path(versions[-1]['path']).is_file()
        and await asyncio.to_thread(digest, Path(versions[-1]['path'])) == versions[-1]['sha256'])
    if local_unchanged and versions[-1]['sha256'] == downloaded['sha256']:
        # A terminal verification GET may be necessary because the plugin overwrites the same path.
        # Identical bytes do not create a second candidate or notification.
        if download_path.exists():
            download_path.unlink()
        item.update(downloaded_version=item['save_version'], pending=None,
                    check='已核对不变' if final and item['check'] != '新文件已取回，待替换核对' else item['check'])
        store.save(key)
        return
    if not versions:
        candidate = target['candidate']
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if download_path.exists():
            # link fails rather than overwriting a file created by another session.
            if candidate.exists():
                if not os.path.samefile(download_path, candidate):
                    raise ValueError('候选入口已被其他文件占用，不覆盖文件')
            else:
                os.link(download_path, candidate)
            download_path.unlink()
        elif not candidate.is_file() or candidate.stat().st_size != downloaded['bytes'] or await asyncio.to_thread(
                digest, candidate) != downloaded['sha256']:
            raise ValueError('已移动分段与下载凭据不一致')
        path = str(candidate)
        check = '已核对不变' if final else '运行中已取回，待收尾核对'
        kind = 'segment'
    else:
        # The agent must clear old current approval/selection before replacing an approved file.
        path, check, kind = str(download_path), '新文件已取回，待替换核对', 'replacement'
    versions.append({'path': path, 'sha256': downloaded['sha256'], 'bytes': downloaded['bytes'],
                     'receipt': str(evidence_path), 'final': final})
    item.update(path=path, check=check, downloaded_version=item['save_version'], pending=None, error=None)
    store.save(key, collected=sum(bool(s['versions']) for s in state['segments'].values()))
    store.queue_notice(key, f"{kind}:{target['identity']}:{revision}", kind,
        f"{target['identity']}：{check}；文件：{path}；凭据：{evidence_path}")


async def finish(store, key, result):
    row = store.rows[key]
    data, state = row['input'], row['state']
    outputs = result['history'].get('outputs', {}).get(data.segment_plan.report_node, {})
    text = '\n'.join(value for values in outputs.values() if isinstance(values, list) for value in values if isinstance(value, str))
    paths = {}
    for match in REPORT.finditer(text):
        index = int(match[1]) - 1
        if (match[2] == '一采 mp4') == (data.task_type == 'video-first-pass'):
            paths[index] = match[4].strip()
    problems = []
    for target in targets(data):
        item = state['segments'][str(target['index'])]
        if target['index'] not in paths:
            item['check'] = '无法核对' if item['versions'] else '未取回'
            problems.append(target['identity'] + '缺少终态保存路径')
            continue
        try:
            source = remote_file(data.segment_plan.output_root, paths[target['index']])
            expected = f"seg_{target['index']:04d}{'_pre' if data.task_type == 'video-first-pass' else ''}.mp4"
            if source['filename'] != expected or item.get('remote') and item['remote'] != source:
                raise ValueError('终态路径与分段身份／提前取回来源不一致')
            item.update(remote=source, save_version='terminal', save_evidence={
                'history': str(Path(data.record_dir) / data.history_name), 'path': paths[target['index']]})
            if item.get('downloaded_version') != 'terminal':
                await retrieve(store, key, target, final=True)
        except (store.client.ClientError, OSError, ValueError) as error:
            item.update(error=str(error), check='无法核对')
            problems.append(target['identity'] + '取回或收尾核对失败')
    store.save(key)
    return problems
