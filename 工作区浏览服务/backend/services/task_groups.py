"""Explicit submission membership; remote execution remains task-by-task."""
import asyncio
import json
from pathlib import Path
import uuid


class TaskGroups:
    def task_issue(self, key):
        state = self.rows[key]['state']
        closeout = state.get('closeout') or {}
        stage = state.get('failure_stage') or closeout.get('status') or state['status']
        error = state.get('error') or closeout.get('error') or state['status']
        # Local diagnostics put the varying file/field after a full-width colon.
        # Keep the full error on each member; only the group heading is shared.
        return [stage, error.split('\n', 1)[0].split('：', 1)[0]]

    def groups_init(self):
        self.db.execute('CREATE TABLE IF NOT EXISTS task_groups (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.commit()
        self.groups = {key: json.loads(value) for key, value in self.db.execute('SELECT id, payload FROM task_groups')}

    def save_group(self, group_id):
        self.db.execute('INSERT INTO task_groups VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                        (group_id, json.dumps(self.groups[group_id], ensure_ascii=False)))

    async def enqueue_group(self, inputs, title):
        if not inputs or not isinstance(title, str) or not title.strip():
            raise ValueError('任务组须有名称和至少一个任务')
        for data in inputs:
            self.resolve_input(data)
        if len({(data.project, data.thread_id) for data in inputs}) != 1:
            raise ValueError('同一任务组须属于同一项目和来源会话')
        if len({data.record_dir for data in inputs}) != len(inputs):
            raise ValueError('任务组内执行目录不能重复')
        existing = [next((key for key, row in self.rows.items() if row['input'].record_dir == data.record_dir), None)
                    for data in inputs]
        if any(existing):
            group_id = self.rows[next(key for key in existing if key)]['state'].get('group_id')
            if not group_id or self.groups[group_id]['task_ids'] != existing:
                raise ValueError('执行目录已登记，不能更改原任务组成员或重新分组；请按原ID接续')
            # Validate the whole request before refreshing any connection.
            for key, data in zip(existing, inputs):
                self.check_duplicate(key, data)
            results = [await self.enqueue(data) for data in inputs]
            return {'group_id': group_id, 'group': self.group_status(group_id), 'tasks': results, 'reused': True}
        for data in inputs:
            self.validate_registration(data)
        group_id = str(uuid.uuid4())
        ids = [str(uuid.uuid4()) for _ in inputs]
        group = dict(id=group_id, title=title.strip(), project=Path(inputs[0].project).name,
                     thread_id=inputs[0].thread_id, task_ids=ids, created_at=self.client.now())
        # No await until all members and the group are committed. The scheduler
        # cannot see a partial group, including after an HTTP interruption/restart.
        self.groups[group_id] = group
        committed = False
        try:
            with self.db:
                for key, data in zip(ids, inputs):
                    self.rows[key] = self.new_queue_row(key, data)
                    self.rows[key]['state']['group_id'] = group_id
                    self.persist(key)
                self.save_group(group_id)
            committed = True
        finally:
            if not committed:
                self.groups.pop(group_id)
                for key in ids:
                    self.rows.pop(key, None)
        for key in ids:
            self.record(key, 'enqueue', 'accepted', group_id=group_id)
            self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
        return {'group_id': group_id, 'group': self.group_status(group_id),
                'tasks': [dict(local_task_id=key, monitor_id=key, monitor='browser',
                               status=self.rows[key]['state']['status']) for key in ids]}

    def group_status(self, group_id):
        if group_id not in self.groups:
            raise ValueError('任务组不存在')
        group = self.groups[group_id]
        members = []
        for key in group['task_ids']:
            row = self.rows[key]
            state = row['state']
            closeout = state.get('closeout') or {}
            complete = state['status'] == 'completed' and closeout.get('status') == 'completed'
            terminal = complete or state['status'] in ('failed', 'rejected', 'cancelled', 'resolved') or (
                state['status'] == 'collection_failed' and bool(state.get('collection_retry_stop'))) or bool(state.get('closeout_retry_stop') and not complete)
            attention = not complete and (state['status'] in ('failed', 'rejected', 'collection_failed', 'needs_attention', 'submission_unknown')
                                         or state.get('error') and state['status'] != 'resolved' or bool(state.get('closeout_retry_stop')))
            members.append(dict(task_id=key, title=row['input'].title, status=state['status'],
                                completed=complete, terminal=terminal, needs_attention=bool(attention),
                                closeout_status=closeout.get('status'), error=state.get('error') or closeout.get('error'),
                                collected=state.get('collected', 0), expected=state.get('expected', 0),
                                failure_stage=state.get('failure_stage')))
        completed = sum(item['completed'] for item in members)
        issues = {}
        for member in members:
            if member['needs_attention']:
                stage, reason = self.task_issue(member['task_id'])
                issue = issues.setdefault((stage, reason), dict(stage=stage, reason=reason, task_ids=[]))
                issue['task_ids'].append(member['task_id'])
        terminal = all(item['terminal'] for item in members)
        status = ('completed' if completed == len(members) else 'terminal_partial' if terminal else
                  'needs_attention' if any(item['needs_attention'] for item in members) else 'running')
        return dict(id=group_id, title=group['title'], project=self.rows[group['task_ids'][0]]['state']['project'],
                    thread_id=group['thread_id'], status=status,
                    updated_at=max(self.rows[key]['state'].get('updated_at') or self.rows[key]['state']['created_at'] for key in group['task_ids']),
                    expected_tasks=len(members), completed_tasks=completed,
                    collected_outputs=sum(item['collected'] for item in members), expected_outputs=sum(item['expected'] for item in members),
                    terminal=terminal, review_ready=status == 'completed',
                    missing_task_ids=[item['task_id'] for item in members if not item['completed']],
                    issues=list(issues.values()), tasks=members)

    def group_members(self, key):
        group_id = self.rows[key]['state'].get('group_id')
        return self.groups[group_id]['task_ids'] if group_id else [key]

    def group_waiting(self, key):
        group_id = self.rows[key]['state'].get('group_id')
        if not group_id:
            return self.image_batch_waiting(key)
        group = self.group_status(group_id)
        member = next(item for item in group['tasks'] if item['task_id'] == key)
        return not group['terminal'] and not member['needs_attention']

    def wake_group(self, key):
        """A repaired closeout may finish a group whose exception was already read."""
        group_id = self.rows[key]['state'].get('group_id')
        if not group_id or not self.group_status(group_id)['terminal']:
            return
        ids = self.groups[group_id]['task_ids']
        if self.group_status(group_id)['status'] == 'completed' and all(self.rows[member]['input'].task_type == 'image-upscale' for member in ids):
            return
        outcomes = [self.notice_outcome(member) for member in ids]
        if outcomes == self.groups[group_id].get('notified_terminal'):
            return
        if any(notice['delivery'] == 'pending' for member in ids for notice in self.rows[member]['state'].get('notices', [])):
            return
        self.queue_notice(key, 'group-terminal-' + str(uuid.uuid4()), 'terminal', '任务组已结束')
