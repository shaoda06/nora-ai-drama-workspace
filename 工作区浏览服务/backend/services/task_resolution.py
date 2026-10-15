"""Close investigated historical exceptions without inventing execution success."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResolutionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_prompt_id: str
    summary: str = Field(min_length=1)
    outcome: Literal['recovered', 'superseded', 'recovered_and_superseded']
    evidence: list[str] = Field(min_length=1)
    replacement_task_ids: list[str] = Field(default_factory=list)


def resolve_task(store, key, request):
    if key not in store.rows:
        raise ValueError('任务不存在')
    row = store.rows[key]
    data, state = row['input'], row['state']
    if not state.get('prompt_id') or state['prompt_id'] != request.expected_prompt_id:
        raise ValueError('原任务ID不匹配，不能结案')
    if not request.summary.strip():
        raise ValueError('结案说明不能为空')
    if request.outcome != 'recovered' and not request.replacement_task_ids:
        raise ValueError('补做结案必须关联已完成的替代任务')
    from backend.services.comfy_tasks import paths
    evidence = []
    for value in request.evidence:
        path = paths.project_file(data.project, value)
        if not path.is_file():
            raise ValueError('结案依据文件不存在：' + value)
        relative = path.relative_to(Path(data.project)).as_posix()
        if relative not in evidence:
            evidence.append(relative)
    replacements = list(dict.fromkeys(request.replacement_task_ids))
    for replacement in replacements:
        target = store.rows.get(replacement)
        if (replacement == key or target is None or target['state']['status'] != 'completed'
                or target['input'].project != data.project):
            raise ValueError('替代任务必须是本项目其他已完成的任务')
    decision = {'summary': request.summary.strip(), 'outcome': request.outcome,
                'evidence_files': evidence, 'replacement_task_ids': replacements}
    if state['status'] == 'resolved':
        if any(state.get('resolution', {}).get(field) != value for field, value in decision.items()):
            raise ValueError('任务已有不同的结案决定，不能覆盖')
        store.write_records(key)
        return {'local_task_id': key, 'status': 'resolved', 'duplicate': True}
    if state['status'] != 'needs_attention':
        raise ValueError('仅允许对已核查的状态待核对任务结案')
    resolution = {**decision, 'resolved_at': store.client.now(),
                  'original_status': state['status'], 'original_error': state.get('error'),
                  'original_error_details': state.get('error_details'),
                  'original_prompt_id': state['prompt_id'],
                  'original_collected': state.get('collected'), 'original_expected': state.get('expected')}
    # Keep prompt_id, error, collected/expected, original end time and notifications intact.
    store.record(key, 'resolution', 'resolved', _changes={'status': 'resolved', 'resolution': resolution},
                 summary=decision['summary'], outcome=decision['outcome'],
                 evidence_files=evidence, replacement_task_ids=replacements)
    return {'local_task_id': key, 'status': 'resolved', 'duplicate': False}
