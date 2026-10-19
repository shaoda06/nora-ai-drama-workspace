"""Coalesce pending outcomes per source conversation, with durable delivery receipts."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import uuid
from backend.services.result_summary import summary, batch_tasks


class TaskNotifications:
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
        saved = self.db.execute('SELECT report FROM notification_reports WHERE batch_id=?', (batch_id,)).fetchone()
        # Old delivered notices have no snapshot. Reading them never restarts collection/registration.
        report = json.loads(saved[0]) if saved else {
            'tasks': [summary(self, key) for key in ids], 'legacy_report': True,
            'user_message_ready': False, 'results': []}
        reused = self.mark_received(batch_id, ids, delivery)
        return {**report, 'notification_id': batch_id, 'status': 'acknowledged', 'reused': reused}

    async def prepare_report(self, ids):
        """Finish normal videos before delivery; persist bounded retry progress across restarts."""
        from backend.services.result_registration import closeout_tasks
        videos = [key for key in ids if self.rows[key]['input'].task_type.startswith('video-')
                  and self.rows[key]['state']['status'] == 'completed']
        if videos and not hasattr(self, 'projects'):
            from backend.services.projects import ProjectStore
            self.projects = ProjectStore(self.workspace / 'projects')
        while True:
            active = []
            for key in videos:
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
        tasks = [summary(self, key) for key in ids]
        results = [{'task_id': key, **self.rows[key]['state']['closeout']} for key in videos]
        return {'tasks': tasks, 'results': results, 'reported_at': self.client.now(),
                'user_message_ready': bool(tasks) and all(
                    task['status'] == 'completed' and
                    (not task['task_type'].startswith('video-') or task.get('closeout', {}).get('status') == 'completed')
                    for task in tasks)}

    def notification_text(self, key):
        row = self.rows[key]
        state, data = row['state'], row['input']
        return (f'本地任务ID：{key}；项目：{state["project"]}；任务：{data.title}\n'
                f'当前状态：{state["status"]}；远端ID：{state.get("prompt_id")}；'
                f'成果：{state["collected"]}/{state["expected"]}\n'
                f'失败阶段：{state.get("failure_stage") or "无"}；原因：{state.get("error") or "预期成果已保存"}\n'
                + (f'取回累计尝试：{state["collection_attempt"]}轮；本轮自动重试：{state.get("collection_auto_retry", 0)}/3；'
                   f'停止原因：{state.get("collection_retry_stop") or "无"}\n' if state.get('collection_attempt') else '')
                + f'收尾结果：{state.get("closeout", {}).get("status", "不适用")}；'
                  f'原因：{state.get("closeout", {}).get("error") or "无"}\n'
                + f'最终报告与凭据入口：读取报告时一次返回。记录位置：{data.record_dir}\n'
                + ('此前问题通知已被最新结果替代，完整经过见过程记录。\n' if any(item['delivery'] == 'superseded' for item in state.get('notices', [])) else '')
                + ('可用本地任务ID请求重试取回，无需重新生成。\n' if state['status'] == 'collection_failed' else ''))

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
                if not cancelled and any(task == key for task, _ in self.notification_pending(thread_id)):
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
        prepared_notices, report = None, None
        while self.notification_pending(data.thread_id):
            data = max((row for row in self.rows.values() if row['input'].thread_id == data.thread_id),
                       key=lambda row: row['state']['created_at'])['input']
            pending = self.notification_pending(data.thread_id)
            signature = tuple(notice['id'] for _, notice in pending)
            if signature != prepared_notices:
                report = await self.prepare_report(list(dict.fromkeys(task for task, _ in pending)))
                prepared_notices = signature
            # Probe Desktop connectivity before attempting a send, so an unavailable
            # adapter remains retryable without an ambiguous delivery. Conversation
            # status is not a delivery gate: Codex handles input to an active turn.
            # macOS uses the CLI queue and does not need this Desktop connection.
            if not self.queue_notifications:
                try:
                    await self.desktop_call(data, 'read')
                except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                    for task, _ in self.notification_pending(data.thread_id):
                        if self.rows[task]['state'].get('notification') != 'waiting_connection':
                            self.record(task, 'notification', 'waiting_connection', error=str(error),
                                        _changes={'notification': 'waiting_connection', 'notice_wait_reason': 'connection'})
                    await asyncio.sleep(30)
                    continue
            pending = self.notification_pending(data.thread_id)
            if not pending:
                return
            if tuple(notice['id'] for _, notice in pending) != prepared_notices:
                continue
            ids = list(dict.fromkeys(task for task, _ in pending))
            batch_id = str(uuid.uuid4())
            prompt = (f'后台任务结果通知。通知ID：{batch_id}；来源会话：{data.thread_id}。\n'
                      '请调用 browser_tasks.py report --notification-id 上述ID，读取已保存的最终报告；读取同时自动确认收到。\n'
                      + '\n'.join(self.notification_text(task) for task in ids)
                      + '\n视频待审登记与网页核验已由后台执行，以报告结果为准；正常成功直接汇报数量与审核入口，不再调用ack或register-results。图片继续原图片审核与展示流程。成果保存不等于内容获批。'
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
