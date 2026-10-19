"""Small task/batch results, without rebuilding the global queue or inspecting media."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import quote


def prepared_identities(store, key):
    """Read an existing checked association once; do not infer it from a save name."""
    row = store.rows[key]
    if '_review_identities' not in row:
        data = row['input']
        record = Path(data.record_dir)
        identities = set()
        try:
            report = json.loads((record / '执行检查报告.json').read_text('utf-8-sig'))
        except FileNotFoundError:
            # Legacy registrations can lack preparation reports. Fill only this missing link.
            if not row['state'].get('preparation_required'):
                try:
                    mapping = json.loads((record / '输入映射.json').read_text('utf-8-sig'))
                    identities = {item['identity'] for item in mapping.get('generation_contexts', [])}
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        except (OSError, ValueError):
            pass
        else:
            try:
                if report.get('ok'):
                    mapping = report.get('prepared_input', {}).get('mapping', {})
                    stage = {'video-first-pass': '一采', 'video-second-pass': '二采', 'video-postprocess': '后处理'}[data.task_type]
                    identities = {f"{mapping['segments'][index]['segment']}-{mapping['segments'][index]['round']}-{stage}"
                                  for index in mapping.get('selected_indices', [])}
            except (KeyError, TypeError, AttributeError, IndexError):
                pass
        if identities:
            row['_review_identities'] = identities
        return identities
    return row['_review_identities']


def outputs(store, key):
    """Reuse collected entries and their prepared identities; never reload frozen input."""
    row = store.rows[key]
    state, data = row['state'], row['input']
    source = state.get('result_items', [])
    if data.segment_plan:
        source = [item for item in state.get('segments', {}).values() if item.get('check') == '已取回']
    elif not source:
        source = [{'path': path, 'receipt': str(Path(data.record_dir) / target.response_name)}
                  for path in state.get('saved_outputs', []) for target in data.outputs if path == target.path]
    signature = (state.get('prompt_id'), data.task_type, tuple(tuple(item.get(name) for name in (
        'identity', 'index', 'path', 'receipt', 'bytes', 'check', 'error')) + tuple(
        item.get('remote', {}).get(name) for name in ('filename', 'subfolder', 'type')) for item in source))
    cached = row.get('_result_outputs')
    if cached is not None and cached[0] == signature:
        return cached[1]
    items = deepcopy(source)
    if data.segment_plan:
        for item in items:
            if not item.get('receipt'):
                target = next((target for target in data.segment_plan.targets if target.index == item['index']), None)
                item['receipt'] = str(Path(data.record_dir) / (target.response_name if target else f"最终取回-{item['index']:03d}.json"))
    items = store.record_paths(key).convert(items, relative=True)
    if data.task_type.startswith('video-'):
        for item in items:
            trusted = bool(item.get('identity'))
            identity = item['identity'] = item.get('identity') or Path(item['path']).stem
            parts = identity.split('-')
            if len(parts) == 5 and (trusted or identity in prepared_identities(store, key)):
                item['review'] = dict(zip(('episode', 'scene', 'part', 'revision', 'stage'), parts))
    if not data.task_type.startswith('video-') or all(item.get('review') for item in items):
        row['_result_outputs'] = signature, items
    else:
        row.pop('_result_outputs', None)  # Missing proof can be repaired before an explicit retry.
    return items


def summary(store, key):
    row = store.rows[key]
    state, data = row['state'], row['input']
    fields = ('id', 'project', 'title', 'task_type', 'status', 'prompt_id', 'collected', 'expected',
              'created_at', 'updated_at', 'started_at', 'ended_at', 'progress', 'node', 'connection',
              'notification', 'director_progress', 'collection_next_retry_at', 'collection_errors',
              'error', 'error_details', 'failure_stage', 'collection_attempt', 'collection_auto_retry',
              'collection_retry_stop', 'closeout', 'collected_at', 'notification_sent_at',
              'notification_acknowledged_at', 'notification_attempted_at')
    result = {name: deepcopy(state.get(name)) for name in fields}
    result['title'], result['task_type'] = data.title, data.task_type
    result.update(remote_url=data.url, outputs=deepcopy(outputs(store, key)),
                  record_dir=store.record_paths(key).relative_file(data.record_dir),
                  review_path='/#/projects/' + quote(state['project'], safe=''),
                  next_action=('report-user' if state.get('closeout', {}).get('status') == 'completed' else 'inspect-closeout')
                  if data.task_type.startswith('video-') else
                  ('display-image' if state.get('closeout', {}).get('status') == 'completed' else 'inspect-closeout'))
    if state['status'] != 'completed':
        result['next_action'] = 'inspect-failure'
    return result


def batch_tasks(store, batch_id, thread_id):
    batch = store.db.execute('SELECT thread_id, task_ids, state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()
    if batch is None or batch[0] != thread_id:
        raise ValueError('通知不存在或不属于该会话')
    import json
    ids = json.loads(batch[1])
    if any(key not in store.rows or store.rows[key]['input'].thread_id != thread_id for key in ids):
        raise ValueError('通知任务与来源会话不匹配')
    return ids, batch[2]
