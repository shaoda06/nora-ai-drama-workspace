"""Read-only task details from the existing task store and recorded evidence."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import quote


async def task_detail(store, key):
    row = store.rows[key]
    data, state = row['input'].model_copy(deep=True), deepcopy(row['state'])
    events = [dict(id=event_id, **json.loads(value)) for event_id, value in store.db.execute(
        'SELECT id, event FROM task_events WHERE task_id=? ORDER BY id', (key,))]
    batches = []
    for batch_id in dict.fromkeys(event['notification_id'] for event in events if event.get('notification_id')):
        batch = store.db.execute('SELECT task_ids, state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()
        if batch:
            batches.append({'id': batch_id, 'task_count': len(json.loads(batch[0])), 'status': batch[1]})
    files = await asyncio.to_thread(task_files, data, state, events)
    fields = ('id', 'project', 'title', 'task_type', 'status', 'source_session_name', 'created_at',
              'submitted_at', 'started_at', 'ended_at', 'updated_at', 'prompt_id', 'failure_stage',
              'error', 'collected', 'expected', 'notification', 'dispatch_attempt', 'preparation_attempt')
    summary = {field: state.get(field) for field in fields}
    summary.update(enqueued_url=state.get('enqueued_url', data.url), remote_url=data.url)
    collection = [event['time'] for event in events if event['stage'] == 'collection' and event['result'] == 'completed']
    summary['collected_at'] = collection[-1] if collection else None
    public_fields = ('id', 'time', 'stage', 'result', 'error', 'source_url', 'target_url', 'url',
                     'position', 'path', 'file', 'identity', 'collected', 'notification_id')
    timeline = [{field: event[field] for field in public_fields if field in event}
                for event in events if not (event['stage'] == 'director' and event['result'] == 'progress')]
    return {'summary': summary, 'events': timeline, 'outputs': files['outputs'],
            'records': files['records'], 'notification_batches': batches}


def task_files(data, state, events):
    project = Path(data.project).resolve()

    def file_info(value):
        path = Path(value).resolve()
        if not path.is_relative_to(project) or any(part.startswith('.') for part in path.relative_to(project).parts):
            return {'available': False, 'bytes': None, 'url': None}
        available = path.is_file()
        return {'available': available, 'bytes': path.stat().st_size if available else None,
                'url': '/api/projects/' + quote(project.name, safe='') + '/files/'
                       + quote(path.relative_to(project).as_posix(), safe='/') if available else None}

    targets = [{'path': item.path, 'identity': None} for item in data.outputs]
    if data.segment_plan:
        mapping = Path(data.record_dir) / '输入映射.json'
        if mapping.is_file():
            from backend.services.comfy_segments import targets as segment_targets
            targets += [{'path': str(item['candidate']), 'identity': item['identity']} for item in segment_targets(data)]
        else:
            targets += [{'path': item.path, 'identity': state.get('segments', {}).get(str(item.index), {}).get('identity')}
                        for item in data.segment_plan.targets]
            targets += [{'path': item['path'], 'identity': item.get('identity')}
                        for item in state.get('segments', {}).values() if item.get('path')]
    outputs = []
    for target in targets:
        if any(item['path'] == target['path'] for item in outputs):
            continue
        info = file_info(target['path'])
        downloads = [event for event in events if event['stage'] == 'download' and
                     (event.get('path') == target['path'] or target['identity'] and event.get('identity') == target['identity'])]
        latest = downloads[-1] if downloads else None
        segment = next((item for item in state.get('segments', {}).values() if item.get('path') == target['path'] or
                        target['identity'] and item.get('identity') == target['identity']), None)
        error = latest.get('error') if latest and latest['result'] == 'failed' else (
            segment.get('error') if not latest and segment and segment.get('check') == '取回失败' else None)
        saved = target['path'] in state.get('saved_outputs', []) or any(
            item.get('path') == target['path'] and item.get('check') == '已取回' for item in state.get('segments', {}).values())
        saved = saved or bool(latest and latest['result'] == 'success')
        status = 'failed' if latest and latest['result'] == 'failed' or error else (
            'saved' if saved and info['available'] else 'missing' if saved else 'pending')
        outputs.append({**target, **info, 'name': Path(target['path']).name, 'status': status,
                        'downloaded_at': latest['time'] if latest and latest['result'] == 'success' else None,
                        'error': error})
    records = []
    for label, name in (('任务摘要', '后台任务状态.json'), ('完整过程记录', '后台过程记录.json'),
                        ('远端执行结果', data.history_name)):
        info = file_info(Path(data.record_dir) / name)
        if info['available']:
            records.append({'name': label, **info})
    return {'outputs': outputs, 'records': records}
