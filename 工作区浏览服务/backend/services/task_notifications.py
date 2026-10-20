"""Coalesce pending outcomes per source conversation, with durable delivery receipts."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import uuid
from backend.services.result_summary import summary, batch_tasks, image_delivery, video_delivery


class TaskNotifications:
    def image_batch_waiting(self, key):
        row = self.rows[key]
        data, state = row['input'], row['state']
        if (data.task_type != 'image' or not data.image_batch_id or state['status'] != 'completed'
                or state.get('closeout', {}).get('status') != 'completed'):
            return False
        members = [item for item in self.rows.values()
                   if item['input'].project == data.project and item['input'].thread_id == data.thread_id
                   and item['input'].task_type == 'image' and item['input'].image_batch_id == data.image_batch_id]
        return len(members) != data.image_batch_size or any(
            item['state']['status'] != 'completed' or item['state'].get('closeout', {}).get('status') != 'completed'
            for item in members)

    def ready_notices(self, thread_id):
        ready = []
        for key, notice in self.notification_pending(thread_id):
            row = self.rows[key]
            state, data = row['state'], row['input']
            if (data.task_type == 'image-upscale' and state['status'] == 'completed'
                    and state.get('closeout', {}).get('status') == 'completed'):
                notice['delivery'] = 'not_required'
                self.record(key, 'notification', 'not_required', message='超分完成并正式保存，正常结果静默',
                            _changes={'notification': 'not_required', 'notice_wait_reason': None})
            elif self.image_batch_waiting(key):
                if state.get('notice_wait_reason') != 'image_batch':
                    self.record(key, 'notification', 'waiting_batch',
                                _changes={'notice_wait_reason': 'image_batch'})
            else:
                ready.append((key, notice))
        if not ready:
            return []
        first = self.rows[ready[0][0]]['input']
        if first.task_type == 'image' and first.image_batch_id:
            return [(key, notice) for key, notice in ready
                    if self.rows[key]['input'].project == first.project
                    and self.rows[key]['input'].image_batch_id == first.image_batch_id]
        return [(key, notice) for key, notice in ready
                if not (self.rows[key]['input'].task_type == 'image' and self.rows[key]['input'].image_batch_id)]

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
                self.record(key, 'notification', 'acknowledged', notification_id=batch_id,
                            _changes={'notification': 'acknowledged', 'notification_acknowledged_at': self.client.now()})
        self.db.commit()
        event = getattr(self, '_ack_events', {}).get(batch_id)
        if event is not None:
            event.set()
        return False

    def read_report(self, batch_id, thread_id):
        ids, delivery = batch_tasks(self, batch_id, thread_id)
        reused = self.mark_received(batch_id, ids, delivery)
        self.refresh_reports(ids)
        saved = self.db.execute('SELECT report FROM notification_reports WHERE batch_id=?', (batch_id,)).fetchone()
        # Old delivered notices have no snapshot. Reading them never restarts collection/registration.
        report = json.loads(saved[0]) if saved else {
            'tasks': [summary(self, key) for key in ids], 'legacy_report': True,
            'user_message_ready': False, 'results': []}
        return {**report, 'notification_id': batch_id, 'status': 'acknowledged', 'reused': reused}

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
        completed = [key for key in ids if self.rows[key]['state']['status'] == 'completed']
        tasks = [summary(self, key) for key in ids]
        for task in tasks:
            task['closeout'] = self.record_paths(task['id']).convert(task['closeout'], relative=True)
        results = [{'task_id': task['id'], **(task['closeout'] or {})}
                   for task in tasks if task['id'] in completed]
        report = {'tasks': tasks, 'results': results, 'reported_at': self.client.now(),
                'user_message_ready': bool(tasks) and all(
                    task['status'] == 'completed' and
                    (task.get('closeout') or {}).get('status') == 'completed'
                    for task in tasks)}
        delivery = image_delivery(self, tasks) or video_delivery(self, tasks)
        if delivery is not None:
            report['delivery'] = delivery
        return report

    def notification_text(self, key):
        row = self.rows[key]
        state, data = row['state'], row['input']
        return (f'本地任务ID：{key}；项目：{state["project"]}；任务：{data.title}\n'
                f'记录位置：{data.record_dir}\n')

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
                if not cancelled and any(task == key and not self.image_batch_waiting(task)
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
            batch_id = str(uuid.uuid4())
            prompt = (f'后台任务结果通知。通知ID：{batch_id}；来源会话：{data.thread_id}。\n'
                      '请调用 browser_tasks.py report --notification-id 上述ID，读取后台已保存的最新结果；读取同时自动确认收到。\n'
                      '通知可能延迟送达，当前状态、异常是否已修复及成果清单以本次report为准，历史经过保留在过程记录。\n'
                      + '\n'.join(self.notification_text(task) for task in ids)
                      + '\n图片、超分与视频的技术核验、记录更新及网页核验已由后台执行，以报告结果为准；正常成功只读取report，图片按本批完整清单集中展示成果和审核入口，视频汇报数量与审核入口。正常超分静默；历史已发出的正常超分通知只读确认，不发处理进度、完成回复或图片。不再调用ack、register-results或重复查文件／刷新网页。成果保存不等于内容获批。'
                      '失败请从记录中的失败阶段复查；未知任务不自动重新生成。')
            self.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)',
                            (batch_id, data.thread_id, json.dumps(ids), prompt, 'sending'))
            self.db.execute('INSERT INTO notification_reports VALUES (?, ?)', (batch_id, json.dumps(report, ensure_ascii=False)))
            for task, notice in pending:
                notice.update(delivery='sending', batch_id=batch_id)
                self.record(task, 'notification', 'sending', notification_id=batch_id,
                            _changes={'notification': 'sending', 'notice_wait_reason': None})
            try:
                receipt = await self.desktop_call(data, 'send', prompt)
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
            for task, notice in pending:
                notice['delivery'] = delivery
                changes = {'notification': delivery, 'notification_attempted_at': self.client.now()}
                if delivery in ('sent', 'acknowledged'):
                    changes['notification_sent_at'] = self.client.now()
                self.record(task, 'notification', 'delivery_confirmed' if acknowledged else delivery,
                            _changes=changes, notification_id=batch_id, error=detail, message=prompt,
                            receipt=receipt.get('receipt') if detail is None else None)
            if delivery == 'delivery_unknown':
                self.notifiers['ack:' + batch_id] = asyncio.create_task(self.wait_ack(batch_id))

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
