"""Deliver explicit task groups, with durable per-task execution and delivery receipts."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import uuid
from backend.services.result_summary import summary, batch_tasks, group_delivery
from backend.services.round_results import round_results


class NotificationNotStarted(OSError):
    """The sender did not start, so retrying cannot duplicate a delivered message."""


class TaskNotifications:
    def notice_outcome(self, key):
        state = self.rows[key]['state']
        closeout = state.get('closeout') or {}
        return {**{name: state.get(name) for name in ('prompt_id', 'status', 'error', 'failure_stage',
                                                     'collected', 'expected', 'collection_attempt',
                                                     'dispatch_attempt', 'preparation_attempt')},
                'closeout_status': closeout.get('status'), 'closeout_error': closeout.get('error')}

    def image_batch_members(self, key):
        data = self.rows[key]['input']
        return [member for member, item in self.rows.items()
                if item['input'].project == data.project and item['input'].thread_id == data.thread_id
                and item['input'].task_type == 'image' and item['input'].image_batch_id == data.image_batch_id]

    def image_batch_waiting(self, key):
        row = self.rows[key]
        data, state = row['input'], row['state']
        if (data.task_type != 'image' or not data.image_batch_id or state['status'] != 'completed'
                or state.get('closeout', {}).get('status') != 'completed'):
            return False
        members = [self.rows[member] for member in self.image_batch_members(key)]
        return len(members) != data.image_batch_size or any(
            item['state']['status'] not in ('cancelled', 'resolved') and (
                item['state']['status'] != 'completed' or item['state'].get('closeout', {}).get('status') != 'completed')
            for item in members)

    def ready_notices(self, thread_id):
        ready = []
        for key, notice in self.notification_pending(thread_id):
            row = self.rows[key]
            state, data = row['state'], row['input']
            group_id = state.get('group_id')
            if group_id and self.group_status(group_id)['terminal'] and self.groups[group_id].get('notified_terminal') == [self.notice_outcome(member) for member in self.group_members(key)]:
                notice['delivery'] = 'not_required'
                self.record(key, 'notification', 'already_notified',
                            _changes={'notification': 'not_required', 'notice_wait_reason': None})
            elif (data.task_type == 'image-upscale' and state['status'] == 'completed'
                    and state.get('closeout', {}).get('status') == 'completed'
                    and (not state.get('group_id') or self.group_status(state['group_id'])['status'] == 'completed'
                         and all(self.rows[member]['input'].task_type == 'image-upscale' for member in self.group_members(key)))):
                notice['delivery'] = 'not_required'
                self.record(key, 'notification', 'not_required', message='超分完成并正式保存，正常结果静默',
                            _changes={'notification': 'not_required', 'notice_wait_reason': None})
            elif (not state.get('group_id') and state.get('reported_outcome') == self.notice_outcome(key)):
                notice['delivery'] = 'acknowledged'
                self.record(key, 'notification', 'already_received', message='本次实际结果已通过report读取，不再发送',
                            _changes={'notification': 'acknowledged', 'notice_wait_reason': None})
            elif self.group_waiting(key):
                reason = 'task_group' if group_id else 'image_batch'
                if state.get('notice_wait_reason') != reason:
                    self.record(key, 'notification', 'waiting_batch',
                                _changes={'notice_wait_reason': reason})
            elif group_id and not self.group_status(group_id)['terminal'] and self.merge_unread_issue(key, notice):
                continue
            else:
                ready.append((key, notice))
        if not ready:
            return []
        group_id = self.rows[ready[0][0]]['state'].get('group_id')
        if group_id:
            return [(key, notice) for key, notice in ready if self.rows[key]['state'].get('group_id') == group_id]
        ready = [(key, notice) for key, notice in ready if not self.rows[key]['state'].get('group_id')]
        first = self.rows[ready[0][0]]['input']
        if first.task_type == 'image' and first.image_batch_id:
            return [(key, notice) for key, notice in ready
                    if self.rows[key]['input'].project == first.project
                    and self.rows[key]['input'].image_batch_id == first.image_batch_id]
        return [(key, notice) for key, notice in ready
                if not (self.rows[key]['input'].task_type == 'image' and self.rows[key]['input'].image_batch_id)]

    def merge_unread_issue(self, key, notice):
        issue = self.task_issue(key)
        for member in self.group_members(key):
            for previous in reversed(self.rows[member]['state'].get('notices', [])):
                if previous.get('issue') != issue or previous['delivery'] not in ('sent', 'sending', 'delivery_unknown'):
                    continue
                batch_id = previous['batch_id']
                delivery = self.db.execute('SELECT state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()[0]
                if delivery not in ('sent', 'sending', 'delivery_unknown'):
                    continue
                # The outstanding message points to a live group report. Merge
                # peers until read; after receipt a new fault must wake the agent.
                notice.update(delivery=delivery, batch_id=batch_id, issue=issue)
                self.record(key, 'notification', 'merged', notification_id=batch_id,
                            _changes={'notification': delivery, 'notice_wait_reason': None})
                self.refresh_reports([key])
                return True
        return False

    def queue_notice(self, key, event_id, kind, message):
        state = self.rows[key]['state']
        event_id = f'{event_id}:{state.get("collection_attempt", 1)}:{state.get("dispatch_attempt", 0)}:{state.get("preparation_attempt", 0)}'
        notices = state.setdefault('notices', [])
        if any(item.get('event') == event_id for item in notices):
            return
        # An unsent older outcome is superseded; detailed history remains in task_events.
        for item in notices:
            if item['delivery'] == 'pending':
                item['delivery'] = 'superseded'
        notices.append({'id': str(uuid.uuid4()), 'event': event_id, 'kind': kind,
                        'message': message, 'delivery': 'pending'})
        self.record(key, 'notification', 'pending', message=message,
                    _changes={'notification': 'waiting', 'notice_wait_reason': None})
        if key not in self.notifiers or self.notifiers[key].done():
            self.notifiers[key] = asyncio.create_task(self.notify(key))

    def notification_pending(self, thread_id):
        return [(key, notice) for key, row in self.rows.items() if row['input'].thread_id == thread_id
                for notice in row['state'].get('notices', []) if notice['delivery'] == 'pending']

    def acknowledge(self, batch_id, thread_id):
        ids, delivery = batch_tasks(self, batch_id, thread_id)
        reused = self.mark_received(batch_id, ids, delivery)
        return {'notification_id': batch_id, 'status': 'acknowledged',
                'tasks': [summary(self, key) for key in ids], **({'reused': True} if reused else {})}

    def mark_received(self, batch_id, ids, delivery):
        if delivery == 'acknowledged':
            return True
        self.db.execute('UPDATE notification_batches SET state=? WHERE id=?', ('acknowledged', batch_id))
        for key in ids:
            row = self.rows[key]
            matched = [item for item in row['state'].get('notices', []) if item.get('batch_id') == batch_id]
            if matched:
                for item in matched:
                    item['delivery'] = 'acknowledged'
                changes = ({'notification': 'acknowledged', 'notification_acknowledged_at': self.client.now()}
                           if row['state']['notices'][-1].get('batch_id') == batch_id else {})
                self.record(key, 'notification', 'acknowledged', notification_id=batch_id,
                            _changes=changes)
        self.db.commit()
        event = getattr(self, '_ack_events', {}).get(batch_id)
        if event is not None:
            event.set()
        return False

    def read_report(self, batch_id, thread_id):
        ids, delivery = batch_tasks(self, batch_id, thread_id)
        reused = self.mark_received(batch_id, ids, delivery)
        has_report = self.db.execute('SELECT 1 FROM notification_reports WHERE batch_id=?', (batch_id,)).fetchone()
        new_ids = []
        if has_report:
            current = self.result_report(ids)
            received_ids = list(dict.fromkeys([task['id'] for task in current['tasks']
                if not self.rows[task['id']]['state'].get('group_id') or task['status'] in (
                    'completed', 'failed', 'rejected', 'collection_failed', 'needs_attention', 'submission_unknown', 'cancelled', 'resolved') or task.get('error')] + [
                task['task_id'] for scope in current.get('rounds', []) for task in scope.get('tasks', [])
                if task['task_id'] and (task['terminal'] or task['error'])]))
            if any(key not in self.rows or self.rows[key]['input'].thread_id != thread_id for key in received_ids):
                raise ValueError('报告任务与来源会话不匹配')
            for key in received_ids:
                outcome = self.notice_outcome(key)
                if self.rows[key]['state'].get('reported_outcome') != outcome:
                    new_ids.append(key)
                    self.record(key, 'report', 'outcome_received', notification_id=batch_id,
                                _changes={'reported_outcome': outcome})
        elif not reused:
            new_ids = ids
        # Receipt writes change task timestamps. Persist only their final state,
        # so a repeated read does not repair a snapshot created before the receipt.
        self.refresh_reports(ids)
        saved = self.db.execute('SELECT report FROM notification_reports WHERE batch_id=?', (batch_id,)).fetchone()
        # Old delivered notices have no snapshot. Reading them never restarts collection/registration.
        report = json.loads(saved[0]) if saved else {
            'tasks': [summary(self, key) for key in ids], 'legacy_report': True,
            'user_message_ready': False, 'results': []}
        return {**report, 'notification_id': batch_id, 'status': 'acknowledged', 'reused': reused,
                'should_notify_user': bool(new_ids), 'new_task_ids': new_ids}

    def refresh_reports(self, ids):
        """Refresh existing reports from task state, without media work or a new notice."""
        affected = set(ids)
        threads = {self.rows[key]['input'].thread_id for key in ids}
        for thread in threads:
            batches = self.db.execute(
                'SELECT b.id, b.task_ids, r.report FROM notification_batches b '
                'JOIN notification_reports r ON r.batch_id=b.id WHERE b.thread_id=?', (thread,)).fetchall()
            for batch_id, task_ids, saved in batches:
                members = json.loads(task_ids)
                if not affected.intersection(members):
                    continue
                previous = json.loads(saved)
                report = self.result_report(members)
                if all(previous.get(name) == value for name, value in report.items() if name != 'reported_at'):
                    continue
                self.db.execute('UPDATE notification_reports SET report=? WHERE batch_id=?',
                                (json.dumps(report, ensure_ascii=False), batch_id))
        self.db.commit()

    async def prepare_report(self, ids):
        """Finish media before delivery; persist bounded retry progress across restarts."""
        from backend.services.result_registration import closeout_tasks
        completed = [key for key in ids if self.rows[key]['state']['status'] == 'completed']
        if completed and not hasattr(self, 'projects'):
            from backend.services.projects import ProjectStore
            self.projects = ProjectStore(self.workspace / 'projects')
        while True:
            active = []
            for key in completed:
                state = self.rows[key]['state']
                outcome = state.get('closeout', {})
                if outcome.get('status') == 'completed' or state.get('closeout_retry_stop'):
                    continue
                if state.get('closeout_attempts', 0) >= 4 or (
                        outcome.get('status') == 'registration_failed' and not outcome.get('retryable')):
                    self.record(key, 'closeout', 'stopped', _changes={
                        'closeout_retry_stop': 'exhausted' if state.get('closeout_attempts', 0) >= 4 else 'requires_attention'})
                    continue
                due = state.get('closeout_next_retry_at')
                if due:
                    remaining = (datetime.fromisoformat(due) - datetime.now(timezone.utc)).total_seconds()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                self.record(key, 'closeout', 'started', _changes={
                    'closeout_attempts': state.get('closeout_attempts', 0) + 1, 'closeout_next_retry_at': None})
                active.append(key)
            if not active:
                break
            await closeout_tasks(self, self.projects, active)
            for key in active:
                state = self.rows[key]['state']
                outcome = state['closeout']
                if outcome['status'] == 'completed':
                    continue
                retryable = outcome['status'] == 'browser_pending' or outcome.get('retryable', False)
                attempts = state['closeout_attempts']
                if not retryable or attempts >= 4:
                    self.record(key, 'closeout', 'stopped', _changes={
                        'closeout_retry_stop': 'exhausted' if retryable else 'requires_attention'})
                else:
                    delay = (2, 5, 10)[attempts - 1]
                    due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                    self.record(key, 'closeout', 'retry_scheduled', _changes={'closeout_next_retry_at': due}, delay_seconds=delay)
        return self.result_report(ids)

    def result_report(self, ids):
        # A terminal image batch must retain cancelled members even when their
        # earlier notice was already read. Never infer a batch from its title.
        if ids:
            first = self.rows[ids[0]]['input']
            if not self.rows[ids[0]]['state'].get('group_id') and first.task_type == 'image' and first.image_batch_id:
                members = self.image_batch_members(ids[0])
                if (set(ids) <= set(members) and len(members) == first.image_batch_size and all(
                        self.rows[key]['state']['status'] in ('cancelled', 'resolved') or (
                            self.rows[key]['state']['status'] == 'completed' and
                            self.rows[key]['state'].get('closeout', {}).get('status') == 'completed') for key in members)):
                    ids = members
        ids = list(dict.fromkeys(member for key in ids for member in self.group_members(key)))
        completed = [key for key in ids if self.rows[key]['state']['status'] == 'completed']
        tasks = [summary(self, key) for key in ids]
        for task in tasks:
            task['closeout'] = self.record_paths(task['id']).convert(task['closeout'], relative=True)
        results = [{'task_id': task['id'], **(task['closeout'] or {})}
                   for task in tasks if task['id'] in completed]
        report = {'tasks': tasks, 'results': results, 'reported_at': self.client.now(),
                'handoff': {'receipt_only': True, 'scope': 'notification',
                            'next_action': 'resume-round-delivery',
                            'record_dirs': [task['record_dir'] for task in tasks]},
                'user_message_ready': bool(tasks) and all(
                    task['status'] == 'completed' and
                    (task.get('closeout') or {}).get('status') == 'completed'
                    for task in tasks)}
        business_sync = [{'task_id': task['id'], **task['closeout']['business_sync']} for task in tasks
                         if (task.get('closeout') or {}).get('business_sync') is not None]
        if business_sync:
            report['business_sync'] = business_sync
        delivery = group_delivery(self, tasks)
        if delivery is not None:
            report['delivery'] = delivery
        group_ids = list(dict.fromkeys(self.rows[key]['state']['group_id'] for key in ids if self.rows[key]['state'].get('group_id')))
        if group_ids:
            report['groups'] = [self.group_status(group_id) for group_id in group_ids]
            report['handoff'].update(scope='task-group', next_action='resume-group-delivery')
            if any(group['issues'] for group in report['groups']):
                report['handoff'].update(next_action='repair-group-silently',
                    user_notification='decision-or-blocker-only')
        rounds = round_results(self, [key for key in ids if not self.rows[key]['state'].get('group_id')])
        if rounds:
            report['rounds'] = rounds
        return report

    def notification_prompt(self, notification_id, thread_id, report):
        if report.get('groups'):
            group = report['groups'][0]
            scope = f'项目：{group["project"]}\n任务组：{group["title"]}'
        else:
            scope = '任务：\n' + '\n'.join(
                f'- {self.rows[task["id"]]["state"]["project"]}：{self.rows[task["id"]]["input"].title}'
                for task in report['tasks'])
        script = self.workspace / '.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
        rules = self.workspace / '.agents/skills/nora-generation/references/ComfyUI-任务监控规范.md'
        return ('后台任务有更新\n\n'
                + scope + '\n\n'
                'Agent将读取最新结果并继续处理。需要你决定的事项，会单独说明。\n\n'
                'Agent接续信息\n'
                f'通知编号：{notification_id}\n来源会话：{thread_id}\n\n'
                '读取报告：\n```text\n'
                f'python "{script}" report --notification-id {notification_id}\n```\n\n'
                f'接续规范：[后台通知接续](<{rules}#后台通知接续>)\n'
                '先读取该章节，再静默读取报告并按规范接续；以本次报告为准。')

    async def notify(self, key):
        from backend.services.desktop_channel import DesktopChannel
        thread_id = self.rows[key]['input'].thread_id
        lock = self.notification_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            channels = self.__dict__.setdefault('_notification_channels', {})
            channel = channels[thread_id] = DesktopChannel()
            cancelled = False
            try:
                await self._notify_pending(key)
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                channels.pop(thread_id, None)
                await channel.close()
                # A new outcome may arrive while the old channel is closing.
                if not cancelled and any(task == key and not self.group_waiting(task)
                                         for task, _ in self.notification_pending(thread_id)):
                    self.notifiers[key] = asyncio.create_task(self.notify(key))

    async def _notify_pending(self, key):
        data = self.rows[key]['input']
        state = self.rows[key]['state']
        # Saved terminal tasks from before the queue still need their one final notice.
        if not state.get('notices') and state['notification'] in ('waiting', 'waiting_idle', 'waiting_connection'):
            state['notices'] = [{'id': str(uuid.uuid4()), 'event': 'legacy-terminal', 'kind': 'terminal',
                                 'message': state.get('error') or '任务已结束', 'delivery': 'pending'}]
            self.save(key)
        if not self.notification_pending(data.thread_id):
            return
        await asyncio.sleep(2)
        prepared_notices = None
        while self.notification_pending(data.thread_id):
            data = max((row for row in self.rows.values() if row['input'].thread_id == data.thread_id),
                       key=lambda row: row['state']['created_at'])['input']
            pending = self.notification_pending(data.thread_id)
            signature = tuple(notice['id'] for _, notice in pending)
            if signature != prepared_notices:
                await self.prepare_report(list(dict.fromkeys(task for task, _ in pending)))
                prepared_notices = signature
            pending = self.ready_notices(data.thread_id)
            if not pending:
                return
            signature = tuple(notice['id'] for _, notice in pending)
            # Probe Desktop connectivity before attempting a send, so an unavailable
            # adapter remains retryable without an ambiguous delivery. Conversation
            # status is not a delivery gate: Codex handles input to an active turn.
            # macOS uses the CLI queue and does not need this Desktop connection.
            if not self.queue_notifications:
                try:
                    await self.desktop_call(data, 'read')
                except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                    for task, _ in pending:
                        if self.rows[task]['state'].get('notification') != 'waiting_connection':
                            self.record(task, 'notification', 'waiting_connection', error=str(error),
                                        _changes={'notification': 'waiting_connection', 'notice_wait_reason': 'connection'})
                    await asyncio.sleep(30)
                    continue
            pending = self.ready_notices(data.thread_id)
            if not pending:
                return
            if tuple(notice['id'] for _, notice in pending) != signature:
                continue
            ids = list(dict.fromkeys(task for task, _ in pending))
            report = self.result_report(ids)
            ids = [task['id'] for task in report['tasks']]
            # Use the selected group's connection, never another group's latest caller.
            data = self.rows[ids[0]]['input']
            batch_id = str(uuid.uuid4())
            prompt = self.notification_prompt(batch_id, data.thread_id, report)
            self.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)',
                            (batch_id, data.thread_id, json.dumps(ids), prompt, 'sending'))
            self.db.execute('INSERT INTO notification_reports VALUES (?, ?)', (batch_id, json.dumps(report, ensure_ascii=False)))
            group_id = report.get('groups', [{}])[0].get('id')
            previous_terminal = self.groups[group_id].get('notified_terminal') if group_id else None
            if group_id and report['groups'][0]['terminal']:
                self.groups[group_id]['notified_terminal'] = [self.notice_outcome(task) for task in ids]
                self.save_group(group_id)
            for task, notice in pending:
                notice.update(delivery='sending', batch_id=batch_id)
                if group_id and not report['groups'][0]['terminal']:
                    notice['issue'] = self.task_issue(task)
                self.record(task, 'notification', 'sending', notification_id=batch_id,
                            _changes={'notification': 'sending', 'notice_wait_reason': None})
            receipt = {}
            try:
                receipt = await self.desktop_call(data, 'send', prompt)
            except NotificationNotStarted as error:
                delivery, detail = 'not_started', str(error)
            except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                delivery = 'delivery_unknown'
                detail = str(error)
            else:
                delivery, detail = 'sent', None
            # The receiver may acknowledge while the send response is still in flight.
            acknowledged = self.db.execute('SELECT state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()[0] == 'acknowledged'
            if acknowledged:
                delivery = 'acknowledged'
            self.db.execute('UPDATE notification_batches SET state=? WHERE id=?', (delivery, batch_id))
            if group_id and delivery == 'not_started':
                self.groups[group_id]['notified_terminal'] = previous_terminal
                self.save_group(group_id)
            for task, notice in pending:
                notice['delivery'] = 'pending' if delivery == 'not_started' else delivery
                if delivery == 'not_started':
                    notice.pop('batch_id', None)
                changes = {'notification': 'waiting_connection' if delivery == 'not_started' else delivery,
                           'notice_wait_reason': 'connection' if delivery == 'not_started' else None,
                           'notification_attempted_at': self.client.now()}
                if delivery in ('sent', 'acknowledged'):
                    changes['notification_sent_at'] = self.client.now()
                self.record(task, 'notification', 'delivery_confirmed' if acknowledged else delivery,
                            _changes=changes, notification_id=batch_id, error=detail, message=prompt,
                            delivery_receipt=receipt.get('receipt') if detail is None else None)
            if delivery == 'delivery_unknown':
                self.notifiers['ack:' + batch_id] = asyncio.create_task(self.wait_ack(batch_id))
            elif delivery == 'not_started':
                await asyncio.sleep(30)

    async def wait_ack(self, batch_id):
        events = self.__dict__.setdefault('_ack_events', {})
        event = events.setdefault(batch_id, asyncio.Event())
        try:
            while self.db.execute('SELECT state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()[0] != 'acknowledged':
                try:
                    await asyncio.wait_for(event.wait(), 30)
                except asyncio.TimeoutError:
                    pass  # No acknowledgement is not evidence of non-delivery.
        finally:
            events.pop(batch_id, None)
