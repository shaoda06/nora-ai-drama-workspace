"""Coalesce pending outcomes per source conversation, with durable delivery receipts."""
import asyncio
import json
from pathlib import Path
import subprocess
import uuid


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
        self.save(key, notification='waiting_idle')
        self.record(key, 'notification', 'pending', message=message)
        if key not in self.notifiers or self.notifiers[key].done():
            self.notifiers[key] = asyncio.create_task(self.notify(key))

    def notification_pending(self, thread_id):
        return [(key, notice) for key, row in self.rows.items() if row['input'].thread_id == thread_id
                for notice in row['state'].get('notices', []) if notice['delivery'] == 'pending']

    def acknowledge(self, batch_id, thread_id):
        batch = self.db.execute('SELECT thread_id, state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()
        if batch is None or batch[0] != thread_id:
            raise ValueError('通知不存在或不属于该会话')
        self.db.execute('UPDATE notification_batches SET state=? WHERE id=?', ('acknowledged', batch_id))
        for key, row in self.rows.items():
            if row['input'].thread_id != thread_id:
                continue
            matched = [item for item in row['state'].get('notices', []) if item.get('batch_id') == batch_id]
            if matched:
                for item in matched:
                    item['delivery'] = 'acknowledged'
                self.save(key, notification='acknowledged')
                self.record(key, 'notification', 'acknowledged', notification_id=batch_id)
        self.db.commit()
        return {'notification_id': batch_id, 'status': 'acknowledged'}

    def notification_text(self, key):
        row = self.rows[key]
        state, data = row['state'], row['input']
        paths = list(state.get('saved_outputs', []))
        if 'saved_outputs' not in state and state['status'] == 'completed':
            paths = [out.path for out in data.outputs if Path(out.path).is_file()
                     and (Path(data.record_dir) / out.response_name).is_file()]
        paths += [item['path'] for item in state.get('segments', {}).values() if item.get('path')]
        return (f'本地任务ID：{key}；项目：{state["project"]}；任务：{data.title}\n'
                f'当前状态：{state["status"]}；远端ID：{state.get("prompt_id")}；'
                f'成果：{state["collected"]}/{state["expected"]}\n'
                f'失败阶段：{state.get("failure_stage") or "无"}；原因：{state.get("error") or "预期成果已保存"}\n'
                + (f'取回累计尝试：{state["collection_attempt"]}轮；本轮自动重试：{state.get("collection_auto_retry", 0)}/3；'
                   f'停止原因：{state.get("collection_retry_stop") or "无"}\n' if state.get('collection_attempt') else '')
                + f'已保存成果：{json.dumps(paths, ensure_ascii=False)}\n'
                f'记录位置：{data.record_dir}（后台任务状态.json、后台过程记录.json）\n'
                + ('此前问题通知已被最新结果替代，完整经过见过程记录。\n' if any(item['delivery'] == 'superseded' for item in state.get('notices', [])) else '')
                + ('可用本地任务ID请求重试取回，无需重新生成。\n' if state['status'] == 'collection_failed' else ''))

    async def notify(self, key):
        data = self.rows[key]['input']
        state = self.rows[key]['state']
        # Saved terminal tasks from before the queue still need their one final notice.
        if not state.get('notices') and state['notification'] in ('waiting', 'waiting_idle', 'waiting_connection'):
            state['notices'] = [{'id': str(uuid.uuid4()), 'event': 'legacy-terminal', 'kind': 'terminal',
                                 'message': state.get('error') or '任务已结束', 'delivery': 'pending'}]
            self.save(key)
        lock = self.notification_locks.setdefault(data.thread_id, asyncio.Lock())
        async with lock:
            while self.notification_pending(data.thread_id):
                await asyncio.sleep(2)
                data = max((row for row in self.rows.values() if row['input'].thread_id == data.thread_id),
                           key=lambda row: row['state']['created_at'])['input']
                try:
                    result = await self.desktop_call(data, 'read')
                    response = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
                    status = response['thread']['status']['type']
                except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, StopIteration) as error:
                    for task, _ in self.notification_pending(data.thread_id):
                        self.save(task, notification='waiting_connection')
                    await asyncio.sleep(30)
                    continue
                if status not in ('idle', 'notLoaded'):
                    for task, _ in self.notification_pending(data.thread_id):
                        self.save(task, notification='waiting_idle')
                    await asyncio.sleep(15)
                    continue
                pending = self.notification_pending(data.thread_id)
                if not pending:
                    return
                ids = list(dict.fromkeys(task for task, _ in pending))
                batch_id = str(uuid.uuid4())
                prompt = (f'后台任务结果通知。通知ID：{batch_id}；来源会话：{data.thread_id}。\n'
                          '请先调用 browser_tasks.py ack --notification-id 上述ID 确认收到，再读取各任务摘要及过程记录。\n'
                          + '\n'.join(self.notification_text(task) for task in ids)
                          + '\n按现有授权维护业务记录并展示成果；成果保存不等于内容获批。'
                          '失败请从记录中的失败阶段复查；未知任务不自动重新生成。')
                self.db.execute('INSERT INTO notification_batches VALUES (?, ?, ?, ?, ?)',
                                (batch_id, data.thread_id, json.dumps(ids), prompt, 'sending'))
                for task, notice in pending:
                    notice.update(delivery='sending', batch_id=batch_id)
                    self.save(task, notification='sending')
                try:
                    await self.desktop_call(data, 'send', prompt)
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
                    self.save(task, notification=delivery)
                    self.record(task, 'notification', delivery, notification_id=batch_id, error=detail, message=prompt)
                if delivery == 'delivery_unknown':
                    self.notifiers['ack:' + batch_id] = asyncio.create_task(self.wait_ack(batch_id))

    async def wait_ack(self, batch_id):
        while True:
            try:
                await asyncio.wait_for(asyncio.Event().wait(), 30)
            except asyncio.TimeoutError:
                pass
            state = self.db.execute('SELECT state FROM notification_batches WHERE id=?', (batch_id,)).fetchone()[0]
            if state == 'acknowledged':
                return
            # No acknowledgement is not evidence of non-delivery; do not resend.
