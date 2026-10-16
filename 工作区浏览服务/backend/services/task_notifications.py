"""Coalesce pending outcomes per source conversation, with durable delivery receipts."""
import asyncio
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
        self.record(key, 'notification', 'pending', message=message, _changes={'notification': 'waiting_idle'})
        if key not in self.notifiers or self.notifiers[key].done():
            self.notifiers[key] = asyncio.create_task(self.notify(key))

    def notification_pending(self, thread_id):
        return [(key, notice) for key, row in self.rows.items() if row['input'].thread_id == thread_id
                for notice in row['state'].get('notices', []) if notice['delivery'] == 'pending']

    def acknowledge(self, batch_id, thread_id):
        ids, delivery = batch_tasks(self, batch_id, thread_id)
        if delivery == 'acknowledged':
            return {'notification_id': batch_id, 'status': 'acknowledged',
                    'tasks': [summary(self, key) for key in ids], 'reused': True}
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
        return {'notification_id': batch_id, 'status': 'acknowledged', 'tasks': [summary(self, key) for key in ids]}

    def notification_text(self, key):
        row = self.rows[key]
        state, data = row['state'], row['input']
        return (f'本地任务ID：{key}；项目：{state["project"]}；任务：{data.title}\n'
                f'当前状态：{state["status"]}；远端ID：{state.get("prompt_id")}；'
                f'成果：{state["collected"]}/{state["expected"]}\n'
                f'失败阶段：{state.get("failure_stage") or "无"}；原因：{state.get("error") or "预期成果已保存"}\n'
                + (f'取回累计尝试：{state["collection_attempt"]}轮；本轮自动重试：{state.get("collection_auto_retry", 0)}/3；'
                   f'停止原因：{state.get("collection_retry_stop") or "无"}\n' if state.get('collection_attempt') else '')
                + f'结果摘要与凭据入口：确认通知时一次返回。记录位置：{data.record_dir}\n'
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
        while self.notification_pending(data.thread_id):
            data = max((row for row in self.rows.values() if row['input'].thread_id == data.thread_id),
                       key=lambda row: row['state']['created_at'])['input']
            # macOS uses Codex's durable message queue, which schedules the turn itself.
            # Do not gate it on the private Desktop pipe that rejects background callers.
            if not self.queue_notifications:
                try:
                    result = await self.desktop_call(data, 'read')
                    response = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
                    status = response['thread']['status']['type']
                except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, IndexError, StopIteration) as error:
                    for task, _ in self.notification_pending(data.thread_id):
                        if self.rows[task]['state'].get('notification') != 'waiting_connection':
                            self.record(task, 'notification', 'waiting_connection', _changes={'notification': 'waiting_connection'})
                    await asyncio.sleep(30)
                    continue
                if status not in ('idle', 'notLoaded'):
                    for task, _ in self.notification_pending(data.thread_id):
                        if self.rows[task]['state'].get('notice_wait_reason') != 'busy':
                            self.record(task, 'notification', 'waiting_idle', _changes={'notification': 'waiting_idle',
                                        'notice_wait_reason': 'busy'})
                    await asyncio.sleep(15)
                    continue
            pending = self.notification_pending(data.thread_id)
            if not pending:
                return
            ids = list(dict.fromkeys(task for task, _ in pending))
            batch_id = str(uuid.uuid4())
            prompt = (f'后台任务结果通知。通知ID：{batch_id}；来源会话：{data.thread_id}。\n'
                      '请先调用 browser_tasks.py ack --notification-id 上述ID，一次确认并取得本批摘要；正常成功不展开完整日志。\n'
                      + '\n'.join(self.notification_text(task) for task in ids)
                      + '\n正常视频调用 browser_tasks.py register-results --notification-id 上述ID 批量登记待审并核验网页；成功后仅汇报数量与审核入口。图片继续原图片审核与展示流程。成果保存不等于内容获批。'
                      '失败请从记录中的失败阶段复查；未知任务不自动重新生成。')
            self.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)',
                            (batch_id, data.thread_id, json.dumps(ids), prompt, 'sending'))
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
