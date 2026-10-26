"""Repair collection metadata without changing accepted generation inputs."""
from pathlib import Path

from pydantic import BaseModel, Field

from backend.services import comfy_segments as segments


class CollectionRepairInput(BaseModel):
    expected_prompt_id: str = Field(min_length=1)
    output_root: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


def repair_collection(store, key, request):
    if key not in store.rows:
        raise ValueError('后台任务不存在')
    row = store.rows[key]
    data, state = row['input'], row['state']
    if request.thread_id != data.thread_id or request.thread_id != data.desktop.caller_thread:
        raise ValueError('只能由原来源会话修复取回配置')
    if state['status'] != 'collection_failed' or data.segment_plan is None:
        raise ValueError('只能修复取回失败的原生H3分段任务')
    if state.get('prompt_id') != request.expected_prompt_id:
        raise ValueError('远端任务ID与原任务不一致')
    if not request.reason.strip():
        raise ValueError('须说明实际失败原因与修复范围')
    segments.validate_h3_stage(data.task_type)
    evidence = Path(data.record_dir) / data.history_name
    result = store.client.strict_json(evidence.read_bytes())['data']
    if result.get('state') != 'success' or result.get('prompt_id') != request.expected_prompt_id:
        raise ValueError('修复须有原任务生成成功的终态证据')
    paths, pre_refine = segments.export_paths(data, result)
    for target in segments.targets(data):
        index = target['index']
        if index not in paths:
            raise ValueError('原终态报告缺少选中分段的导出路径')
        source = segments.remote_file(request.output_root, paths[index])
        if source['filename'] != f"seg_{index:04d}{'_pre' if pre_refine[index] else ''}.mp4":
            raise ValueError('原终态报告路径与分段身份不一致')
    old_root = state.get('collection_output_root', data.segment_plan.output_root)
    if old_root == request.output_root:
        return {'local_task_id': key, 'status': 'repaired', 'duplicate': True}
    repair = {'prompt_id': state['prompt_id'], 'old_output_root': old_root,
              'output_root': request.output_root, 'reason': request.reason,
              'history_name': data.history_name, 'repaired_at': store.client.now()}
    # Persist only a collection override; the accepted workflow and input remain immutable.
    store.record(key, 'collection_repair', 'accepted',
                 _changes={'collection_output_root': request.output_root}, **repair)
    for name in ('_segment_result', '_segment_sources'):
        row.pop(name, None)
    return {'local_task_id': key, 'status': 'repaired', 'duplicate': False,
            'next_action': 'retry-collection'}
