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

    def notification_text(self, key):
        row = self.rows[key]
        state, data = row['state'], row['input']
        return (f'本地任务ID：{key}；项目：{state["project"]}；任务：{data.title}\n'
                f'任务类型：{data.task_type}\n'
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
            if report.get('groups'):
                group = report['groups'][0]
                prompt = (f'后台任务组交接。通知ID：{batch_id}；来源会话：{data.thread_id}。\n'
                          f'任务组ID：{group["id"]}；项目：{group["project"]}；任务组：{group["title"]}。\n'
                          '先静默调用 browser_tasks.py report --notification-id 上述ID，读取最新组报告并自动确认接收。\n'
                          '以groups固定成员及tasks/results/delivery为准；异常按子任务ID和failure_stage处理，正常项继续执行。'
                          '同组同类异常按groups[].issues合并处理，本消息是Agent交接，不是要求向用户逐条报错。'
                          '先沿原授权、原任务ID自行修复可处理的资料、取回和登记问题；过程及已修复异常静默记入原记录。'
                          '只有需要用户作决定、超出已有授权或现有工具内确实无法继续时，才合并说明影响、已完成范围和待决事项；'
                          '不要仅因收到异常、should_notify_user=true或组终态就要求用户确认内部命令。'
                          '处理完本次问题后查一次最新组状态，接续同类后到成员，不另建轮询或heartbeat。'
                          '正常完成按组一次汇总；最终无法恢复、取消或结案的部分列清成功与未完成范围及审核入口，不无限等待。'
                          '读取回执不代表内容批准或已交付用户；已读但未交付的整组仍须交付，已交付不重复。'
                          '正常成功不重复核验、刷新网页或登记；业务摘要仅按business_sync.actions接手。'
                          '正常超分静默；后处理按已有规则采用。不得自动重新生成、清缓存或重启远端。')
            else:
                prompt = (f'后台任务结果通知。通知ID：{batch_id}；来源会话：{data.thread_id}。\n'
                          '请调用 browser_tasks.py report --notification-id 上述ID，读取后台已保存的最新结果；读取同时自动确认收到。\n'
                          '先静默读取report；should_notify_user和new_task_ids只表示新增接收结果，读取回执不代表已交付用户。接收数量和任务清单复用rounds；沿既有共同工作记录核对实际交付范围及负责会话，不逐任务抄写已有事实或新建通知台账。若结果此前已读，仍核对本轮是否尚待交付；已经交付的结果不重复汇报。\n'
                          '同一次用户授权按整轮汇总：部分正常成功静默接收；优先使用rounds中的原清单范围、已完成、缺项和delivery，不重复拼路径或数文件。整轮全部预期成果及技术收尾齐备后，汇总此前已读与本次新增结果，一次交付数量和审核入口，不限于new_task_ids。单份user_message_ready=true不代表整轮齐备；多份清单按已明确授权范围分别核对，不靠会话或轮号猜测合并。review_ready不是内容批准或已交付，后处理仍按已有规则采用；delivered_to_user为null时沿原共同记录确认实际交付。阻塞整轮的异常及时处理；最终部分失败、取消或停止时列清成功和未完成范围，不能无限等待。用户明确要求先看部分时按该要求交付。\n'
                          '通知可能延迟送达，当前状态、异常是否已修复及成果清单以本次report为准，历史经过保留在过程记录。\n'
                          + '\n'.join(self.notification_text(task) for task in ids)
                          + '\n图片、超分与视频的技术核验、分段成果登记及网页候选核验由后台执行，以报告结果为准；业务摘要按business_sync处理，needs_attention时只接手actions列出的path/field/reason，旧报告无actions才按原原因定位。不例行重写三份摘要，不把技术登记完成当作内容批准。正常成功只读取report并按上述整轮规则交付；不重复技术核验。正常超分静默；历史已发出的正常超分通知只读确认，不发处理进度、完成回复或图片。正常成功时不再调用ack、register-results或重复查文件／刷新网页。成果保存不等于内容获批。'
                          '失败请从报告中的失败阶段复查；已授权范围内的登记修复由Agent直接处理，可使用register-results补完已有结果的登记，不重新生成、不扩大批准范围，也不让用户决定内部命令。超出既有授权或不能保留用户修改时，再说明实际影响并请求决定；未知任务不自动重新生成。')
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
