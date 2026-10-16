"""Small task/batch results, without rebuilding the global queue or inspecting media."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote


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
    outputs = deepcopy(state.get('result_items', []))
    if data.segment_plan:
        outputs = [deepcopy(item) for item in state.get('segments', {}).values() if item.get('check') == '已取回']
        for item in outputs:
            if not item.get('receipt'):
                target = next((target for target in data.segment_plan.targets if target.index == item['index']), None)
                item['receipt'] = str(Path(data.record_dir) / (target.response_name if target else f"最终取回-{item['index']:03d}.json"))
    elif not outputs:
        outputs = [{'path': path, 'receipt': str(Path(data.record_dir) / target.response_name)}
                   for path in state.get('saved_outputs', []) for target in data.outputs if path == target.path]
    result.update(remote_url=data.url, outputs=store.record_paths(key).convert(outputs, relative=True),
                  record_dir=store.portable_input(data)['record_dir'],
                  review_path='/#/projects/' + quote(state['project'], safe=''),
                  next_action=('register-results' if data.task_type.startswith('video-') else 'image-review-workflow')
                  if state['status'] == 'completed' else 'inspect-failure')
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
