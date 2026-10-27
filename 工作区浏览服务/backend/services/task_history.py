"""History search and pagination over the existing task records."""
from datetime import datetime
from backend.services.comfy_tasks import TERMINAL


def task_history(store, url=None, search='', result='all', offset=0, limit=20):
    needle = search.strip().casefold()
    rows = []
    for row in store.rows.values():
        state = row['state']
        status = state['status']
        if url is not None and row['input'].url.rstrip('/') != url.rstrip('/'):
            continue
        if status not in TERMINAL and status != 'collecting':
            continue
        if result == 'completed' and status != 'completed' or result == 'cancelled' and status != 'cancelled':
            continue
        if result == 'resolved' and status != 'resolved':
            continue
        closeout_failed = state.get('closeout', {}).get('status') in ('registration_failed', 'browser_pending')
        if result == 'abnormal' and status in ('completed', 'cancelled', 'collecting', 'resolved') and not (status == 'completed' and closeout_failed):
            continue
        if needle and not any(needle in (state.get(field) or '').casefold() for field in ('title', 'source_session_name')):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (datetime.fromisoformat(row['state'].get('ended_at') or row['state']['created_at']).timestamp(),
                               row['state']['created_at'], row['state']['id']), reverse=True)
    fields = ('id', 'project', 'title', 'task_type', 'status', 'source_session_name', 'created_at', 'updated_at',
              'started_at', 'ended_at', 'error', 'notification', 'collected', 'expected',
              'collection_auto_retry', 'collection_next_retry_at', 'resolution')
    items = [{**{field: row['state'][field] for field in fields if field in row['state']},
              'closeout': {field: row['state'].get('closeout', {})[field] for field in ('status', 'error')
                           if field in row['state'].get('closeout', {})},
              'remote_url': row['input'].url.rstrip('/'), 'queue': 'local', 'category': 'history'}
             for row in rows[offset:offset + limit]]
    next_offset = offset + len(items)
    return {'items': items, 'total': len(rows), 'next_offset': next_offset if next_offset < len(rows) else None}
