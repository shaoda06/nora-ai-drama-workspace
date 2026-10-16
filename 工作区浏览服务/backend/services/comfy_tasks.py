"""Persistent ComfyUI monitoring; browser clients only receive public snapshots."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import logging
import os
from pathlib import Path, PureWindowsPath
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException
from backend.services import comfy_segments as segments
from backend.services.comfy_nodes import RemoteQueues, initial_state
from backend.services.local_queue import LocalQueue, LOCAL, TERMINAL
from backend.services.task_notifications import TaskNotifications
from backend.services.collection_retry import DELAYS, failure, saved_stamp

logger = logging.getLogger(__name__)
SKILL = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama'
sys.path.insert(0, str(SKILL / 'scripts'))
import project_paths as paths
import comfyui_config as config
client = config.client
context_spec = importlib.util.spec_from_file_location('nora_generation_context', SKILL / 'scripts/generation_context.py')
generation_context = importlib.util.module_from_spec(context_spec)
context_spec.loader.exec_module(generation_context)


class OutputTarget(BaseModel):
    node_id: str
    output_key: str
    index: int = Field(ge=0)
    path: str
    response_name: str


class DesktopConnection(BaseModel):
    node: str
    server: str
    pipe: str
    caller_thread: str
    cli: str | None = None


class TaskInput(BaseModel):
    project: str
    title: str
    task_type: Literal['image', 'image-upscale', 'video-first-pass', 'video-second-pass', 'video-postprocess']
    url: str
    workflow: dict
    record_dir: str
    attempt_name: str
    request_name: str
    response_name: str
    history_name: str = '执行结果.json'
    timeout: float = Field(default=30, gt=0, le=120)
    outputs: list[OutputTarget]
    thread_id: str
    desktop: DesktopConnection
    segment_plan: segments.SegmentPlan | None = None
    uploads: list[dict] = Field(default_factory=list)
    source_session_name: str = ''
    start_paused: bool = False


class TaskStore(LocalQueue, TaskNotifications):
    queue_notifications = sys.platform == 'darwin'

    def __init__(self, runtime: Path, workspace: Path):
        self.runtime, self.workspace = runtime, workspace.resolve()
        runtime.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(runtime / 'comfy-tasks.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, event TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS notification_batches (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, task_ids TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL)')
        self.db.commit()
        self.rows = {}
        for key, payload, state in self.db.execute('SELECT id, payload, state FROM tasks'):
            data = TaskInput.model_validate_json(payload)
            self.resolve_input(data, recorded=True)
            self.rows[key] = {'input': data, 'state': json.loads(state)}
            self.rows[key]['state'] = self.record_paths(key).convert(self.rows[key]['state'])
        self.workers = {}
        self.notifiers = {}
        self.session_readers = {}
        self.notification_locks = {}
        self.reconcile_locks = {}
        self.reconcile_queries = {}
        self.client = client
        self.generation_context = generation_context
        self.queue_init()
        self.subscribers = set()
        self.token = secrets.token_urlsafe(32)
        self.remote_queues = RemoteQueues(client, self.remote_urls, self.publish,
                                         client_for=self.remote_client, connection_key=self.connection_key)

    def remote_urls(self):
        return config.remote_urls(self.workspace, missing_ok=True)

    def remote_client(self, url, timeout):
        return config.client_for(self.workspace, url, timeout)

    def connection_key(self, url):
        return config.connection_key(self.workspace, url)

    def public(self, include_history=True):
        configured_urls = self.remote_urls()
        historical_urls = sorted({row['input'].url.rstrip('/') for row in self.rows.values()} - set(configured_urls))
        snapshot = {'tasks': sorted(({**{key: ([{field: item.get(field) for field in ('identity', 'index', 'check', 'path', 'error')}
                                        for item in value.values()] if key == 'segments' else value) for key, value in row['state'].items()
                                 if key not in ('client_id', 'segment_monitor', 'notices', 'prepared_files')},
                                 'remote_url': row['input'].url.rstrip('/'),
                                 'notification_unknown': sum(item['delivery'] == 'delivery_unknown' for item in row['state'].get('notices', []))}
                                for row in self.rows.values()),
                                key=lambda item: item['created_at'], reverse=True),
                'remote_nodes': [{'url': url, 'name': '默认节点' if index == 0 else f'备用{index}',
                                  **self.remote_queues.states.get(url, initial_state())}
                                 for index, url in enumerate(configured_urls)] + [
                    {'url': url, 'name': f'旧节点{index + 1}', **initial_state(), 'connection': 'unconfigured',
                     'error': '该地址已退出工作区配置；保留原任务及历史，新任务请使用已配置节点'}
                    for index, url in enumerate(historical_urls)]}
        local = []
        orders = {node['url']: self.ordered(node['url']) for node in snapshot['remote_nodes']}
        for task in snapshot['tasks']:
            status = task['status']
            if status in LOCAL or status in ('preparing', 'submitting'):
                category = 'paused' if status == 'paused' else 'queued'
            elif status in TERMINAL or status == 'collecting':
                category = 'history'
            else:
                continue
            row = self.rows[task['id']]
            order = orders.get(task['remote_url'], [])
            local.append({**task, 'queue': 'local', 'category': category,
                          'can_transfer': self.can_transfer(task['id']),
                          'transfer_targets': [{'url': url, 'name': '默认节点' if index == 0 else f'备用{index}'}
                                               for index, url in enumerate(configured_urls) if url != task['remote_url']],
                          'queue_position': order.index(task['id']) + 1 if task['id'] in order else None})
        snapshot['local_tasks'] = sorted(local, key=lambda task: (task['category'] != 'queued', task.get('queue_order', 0)))
        if not include_history:
            snapshot['local_counts'] = {node['url']: {category: sum(task['remote_url'] == node['url'] and task['category'] == category
                                                                   for task in local)
                                                     for category in ('queued', 'paused', 'history')}
                                        for node in snapshot['remote_nodes']}
            snapshot['history_updated_at'] = {node['url']: max((task.get('updated_at') or task['created_at'] for task in local
                                                               if task['remote_url'] == node['url'] and task['category'] == 'history'), default=None)
                                             for node in snapshot['remote_nodes']}
            snapshot['tasks'] = [task for task in snapshot['tasks'] if task['status'] not in TERMINAL and task['status'] != 'collecting']
            snapshot['local_tasks'] = [task for task in snapshot['local_tasks'] if task['category'] != 'history']
        return snapshot

    def publish(self):
        self.dispatch_event.set()
        for event in self.dispatch_events.values():
            event.set()
        for event in self.subscribers:
            event.set()

    def save(self, key, **changes):
        row = self.rows[key]
        row['state'].update(changes, updated_at=client.now())
        self.persist(key)
        self.db.commit()
        if self.db.execute('SELECT 1 FROM task_events WHERE task_id=? LIMIT 1', (key,)).fetchone():
            self.write_records(key)
        self.publish()

    def persist(self, key):
        row = self.rows[key]
        payload = json.dumps(self.portable_input(row['input']), ensure_ascii=False)
        state = json.dumps(self.record_paths(key).convert(row['state'], relative=True), ensure_ascii=False)
        if row.get('_persisted_payload') == payload:
            self.db.execute('UPDATE tasks SET state=? WHERE id=?', (state, key))
        else:
            self.db.execute('INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,state=excluded.state',
                            (key, payload, state))
            row['_persisted_payload'] = payload

    def record_paths(self, key):
        row = self.rows[key]
        if '_record_paths' not in row:
            data = row['input']
            files = [data.record_dir, *(item.path for item in data.outputs)]
            if data.segment_plan:
                files.extend(item.path for item in data.segment_plan.targets)
            files.extend(item['file'] for item in data.uploads if isinstance(item.get('file'), str))
            row['_record_paths'] = paths.RecordPaths.from_resolved(data.project, files)
        return row['_record_paths']

    def resolve_input(self, data, *, recorded=False):
        if not recorded and not Path(data.project).is_absolute() and PureWindowsPath(data.project).name != data.project:
            raise ValueError('项目必须是当前工作区内的项目名或绝对路径')
        project = (self.workspace / 'projects' / PureWindowsPath(data.project).name
                   if recorded or not Path(data.project).is_absolute() else Path(data.project)).resolve()
        if project.parent != self.workspace / 'projects':
            raise ValueError('任务必须属于当前工作区projects下的项目')
        data.project = str(project)
        resolved = {}
        def local(value):
            if value not in resolved:
                resolved[value] = str(paths.project_file(project, value, recorded=recorded))
            return resolved[value]
        data.record_dir = local(data.record_dir)
        for target in [*data.outputs, *(data.segment_plan.targets if data.segment_plan else [])]:
            target.path = local(target.path)
            if Path(target.path).is_relative_to(data.record_dir):
                raise ValueError('成果必须位于所属项目内，且不得写入执行附件目录')
        for upload in data.uploads:
            if isinstance(upload.get('file'), str):
                upload['file'] = local(upload['file'])

    def portable_input(self, data):
        # Input paths have already crossed the authenticated boundary once.
        project = Path(data.project)
        def relative(value):
            path = Path(value)
            return path.relative_to(project).as_posix() if path.is_relative_to(project) else str(path)
        payload = data.model_dump()
        payload['project'] = project.name
        payload['record_dir'] = relative(data.record_dir)
        for target in [*payload['outputs'], *((payload['segment_plan'] or {}).get('targets', []))]:
            target['path'] = relative(target['path'])
        for upload in payload['uploads']:
            if isinstance(upload.get('file'), str):
                upload['file'] = relative(upload['file'])
        return payload

    def validate_registration(self, data):
        project = Path(data.project)
        configured = self.remote_urls()
        if client.Client(data.url, data.timeout).url != configured[0]:
            raise ValueError('新任务只允许提交到工作区主节点')
        record = Path(data.record_dir)
        if any((record / name).exists() for name in ('后台任务状态.json', '后台过程记录.json')):
            raise client.ClientError('registration_guard', '执行目录已有后台登记记录；请核对原任务')
        if not data.thread_id or not data.desktop.caller_thread:
            raise ValueError('缺少真实会话身份')
        return project

    async def prepare_only(self, data):
        from backend.services.execution_checks import prepare_report
        self.resolve_input(data)
        existing = next((key for key, row in self.rows.items() if row['input'].record_dir == data.record_dir), None)
        if existing is None:
            self.validate_registration(data)
        else:
            row = self.rows[existing]
            old = row['input']
            if (row['state']['status'] not in LOCAL or row['state'].get('prompt_id')
                    or old.thread_id != data.thread_id or old.desktop.caller_thread != data.desktop.caller_thread
                    or old.task_type != data.task_type or old.url != data.url
                    or old.outputs != data.outputs or old.segment_plan != data.segment_plan):
                raise ValueError('只能为同一来源、同一阶段且尚未提交的本地任务重新准备')
            record = Path(data.record_dir)
            evidence = [old.attempt_name, old.request_name, old.response_name, old.history_name,
                        *(item.response_name for item in old.outputs)]
            if old.segment_plan:
                evidence.extend(item.response_name for item in old.segment_plan.targets)
            if any((record / name).exists() for name in evidence):
                raise ValueError('已有提交或成果证据，不允许修改原执行资料')
            # Repreparation must not race an idle scheduler after a successful await.
            self.save(existing, status='paused', immediate=False)
        result = await asyncio.to_thread(prepare_report, self, data)
        if existing is not None:
            row['input'] = data
            for name in ('_prepared_run', '_source_digests', '_collection_ok', '_record_paths'):
                row.pop(name, None)
            self.record(existing, 'preparation', 'updated', _changes={'error': None, 'uploads_bound': False, 'prepared_files': {}})
            result['local_task_id'] = existing
        return result

    def client_for(self, data):
        return self.remote_client(data.url, data.timeout)

    def ws_url(self, data, client_id):
        parts = urlsplit(data.url)
        return urlunsplit(('wss' if parts.scheme == 'https' else 'ws', parts.netloc,
                           parts.path + '/ws', urlencode({'clientId': client_id}), ''))

    async def submit(self, data, *, key=None, workflow=None):
        registered = key is not None
        if key is None:
            self.resolve_input(data)
            project = self.validate_registration(data)
            from backend.services import execution_checks as checks
            checks.check_prepared(self, data)
            key = str(uuid.uuid4())
            self.rows[key] = {'input': data, 'state': {
                'id': key, 'project': project.name, 'title': data.title, 'task_type': data.task_type,
                'prompt_id': None, 'client_id': str(uuid.uuid4()), 'status': 'submitting',
                'preparation_required': True,
                'connection': 'connecting', 'progress': None, 'node': None, 'error': None,
                'notification': 'waiting', 'created_at': client.now(), 'started_at': None,
                'collected': 0, 'expected': len(data.outputs)}}
        state = self.rows[key]['state']
        if state.get('prompt_id'):
            raise ValueError('任务已有远端ID，不能重新提交')
        record = Path(data.record_dir)
        result_names = [data.history_name, *(item.response_name for item in data.outputs)]
        if data.segment_plan:
            result_names.extend(item.response_name for item in data.segment_plan.targets)
        if any((record / name).exists() for name in result_names):
            error = client.ClientError('execution_guard', '已有终态或取回凭据；请核对原执行，不发送新任务', submission_state='not_sent')
            if state['status'] in ('local_queued', 'paused', 'preparing', 'submitting'):
                self.save(key, status='paused', phase='submit', failure_stage='submit', error=str(error), error_details=error.details)
            self.record(key, 'submit', 'blocked', error=str(error), error_details=error.details)
            raise error
        if registered and workflow is None and state.get('preparation_required', False):
            from backend.services.execution_checks import check_prepared
            check_prepared(self, data, bound=state.get('uploads_bound', False),
                           transferred=data.url.rstrip('/') != state.get('enqueued_url', data.url).rstrip('/'))
        previous = state.copy()
        socket = await connect(self.ws_url(data, state['client_id']), open_timeout=data.timeout,
                               additional_headers=self.client_for(data).headers,
                               ping_interval=20, ping_timeout=20, max_size=2**22)
        self.record(key, 'submit', 'started', _changes={'status': 'submitting', 'phase': 'submit', 'failure_stage': None, 'dispatch_attempt': state.get('dispatch_attempt', 0) + 1})
        try:
            result = await asyncio.to_thread(client.submit, self.client_for(data),
                argparse.Namespace(**data.model_dump()), workflow=workflow or data.workflow, client_id=state['client_id'])
        except (client.ClientError, OSError, ValueError) as error:
            details = getattr(error, 'details', {})
            if isinstance(error, client.ClientError) and error.code in ('submission_guard', 'submission_not_sent'):
                state.clear()
                state.update(previous)
                if state['status'] in ('local_queued', 'paused', 'preparing', 'submitting'):
                    self.save(key, status='paused', phase='submit', failure_stage='submit', error=str(error), error_details=details)
                else:
                    self.save(key)
                self.record(key, 'submit', 'blocked', error=str(error), error_details=details)
            else:
                rejected = isinstance(error, client.ClientError) and error.code == 'submission_rejected'
                self.record(key, 'submit', 'rejected' if rejected else 'unknown', _changes={'status': 'rejected' if rejected else 'submission_unknown', 'error': str(error), 'error_details': details, 'failure_stage': 'submit'}, error=str(error), error_details=details)
                self.queue_notice(key, 'submission_issue', 'attention', str(error))
            await socket.close()
            raise
        self.record(key, 'submit', 'accepted', _changes={'prompt_id': result['prompt_id'], 'status': 'queued', 'submitted_at': client.now(), 'connection': 'connected', 'immediate': False}, prompt_id=result['prompt_id'])
        self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
        self.workers[key] = asyncio.create_task(self.watch(key, socket))
        return {**result, 'monitor': 'browser', 'monitor_id': key, 'local_task_id': key}

    async def start(self):
        for key, row in self.rows.items():
            state = row['state']
            if state['status'] == 'resolved':
                continue
            for notice in state.get('notices', []):
                if notice['delivery'] == 'sending':
                    notice['delivery'] = 'delivery_unknown'
            if state['notification'] == 'sending':
                self.save(key, notification='delivery_unknown')
            if any(item['delivery'] == 'pending' for item in state.get('notices', [])):
                self.notifiers[key] = asyncio.create_task(self.notify(key))
            if state['status'] in LOCAL or state['status'] == 'cancelled':
                continue
            if state['status'] == 'preparing':
                self.record(key, 'restart', 'resume_local', _changes={'status': 'local_queued'})
                continue
            if not state.get('prompt_id'):
                response = Path(row['input'].record_dir) / row['input'].response_name
                if response.is_file():
                    result = client.strict_json(response.read_bytes())
                    if result.get('prompt_id'):
                        self.save(key, prompt_id=result['prompt_id'], status='queued')
                if not state.get('prompt_id'):
                    if state['status'] not in TERMINAL:
                        self.save(key, status='submission_unknown', error='提交未确认；保留原证据，不自动重提')
                        self.queue_notice(key, 'submission_issue', 'attention', state['error'])
                    continue
            if state['status'] in TERMINAL:
                if not state.get('notices') and state['notification'] in ('waiting', 'waiting_idle', 'waiting_connection'):
                    self.notifiers[key] = asyncio.create_task(self.notify(key))
                continue
            if state['status'] == 'collecting':
                self.workers[key] = asyncio.create_task(self.collect_saved(key))
            else:
                self.workers[key] = asyncio.create_task(self.watch(key))
            if not state.get('source_session_name'):
                self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
        for batch_id, in self.db.execute("SELECT id FROM notification_batches WHERE state IN ('sending','delivery_unknown')"):
            self.db.execute('UPDATE notification_batches SET state=? WHERE id=?', ('delivery_unknown', batch_id))
            self.notifiers['ack:' + batch_id] = asyncio.create_task(self.wait_ack(batch_id))
        self.db.commit()
        self.scheduler = asyncio.create_task(self.schedule())

    async def close(self):
        await self.remote_queues.close()
        tasks = [*self.reconcile_queries.values(), *self.workers.values(), *self.notifiers.values(), *self.session_readers.values(), *self.dispatch_workers.values()]
        if self.scheduler is not None:
            tasks.append(self.scheduler)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.db.close()

    async def reconcile(self, key, *, background_collection=False):
        if self.rows[key]['state']['status'] in (*TERMINAL, 'collecting'):
            return True
        query = self.reconcile_queries.get(key)
        if query is None:
            query = self.reconcile_queries[key] = asyncio.create_task(self.remote_result(key))
        try:
            result = await asyncio.shield(query)
        finally:
            if query.done() and self.reconcile_queries.get(key) is query:
                del self.reconcile_queries[key]
        lock = self.reconcile_locks.setdefault(key, asyncio.Lock())
        if background_collection and lock.locked():
            return False
        async with lock:
            if self.rows[key]['state']['status'] in (*TERMINAL, 'collecting'):
                return True
            return await self.reconcile_remote(key, result, background_collection=background_collection)

    async def remote_result(self, key):
        row = self.rows[key]
        data, state = row['input'], row['state']
        history = Path(data.record_dir) / data.history_name
        try:
            saved = client.strict_json(history.read_bytes())['data'] if history.is_file() else None
            if saved is not None and not isinstance(saved, dict):
                raise ValueError('终态凭据必须包含结果对象')
        except (OSError, client.ClientError, ValueError, KeyError, TypeError) as error:
            from backend.services.collection_retry import EvidenceError
            raise EvidenceError('本地终态凭据不可读取：' + str(error)) from error
        result = saved if saved and saved.get('state') in ('success', 'failed') else await asyncio.to_thread(
            client.status, self.client_for(data), argparse.Namespace(prompt_id=state['prompt_id']))
        if result['state'] == 'unknown':
            # One additional read avoids treating a queue-to-history transition as disappearance.
            result = await asyncio.to_thread(client.status, self.client_for(data), argparse.Namespace(prompt_id=state['prompt_id']))
        return result

    async def reconcile_remote(self, key, result, *, background_collection=False):
        row = self.rows[key]
        data, state = row['input'], row['state']
        history = Path(data.record_dir) / data.history_name
        remote_state = result['state']
        if not state.get('started_at'):
            for event, payload in (result.get('history') or {}).get('status', {}).get('messages', []):
                if event == 'execution_start' and payload.get('prompt_id') == state['prompt_id'] and 'timestamp' in payload:
                    self.record_start(key, payload)
                    break
        if remote_state in ('success', 'failed'):
            if not history.exists():
                client.write_new(history, {'time': client.now(), 'data': result})
            self.record(key, 'execution', remote_state, evidence=str(history))
            if background_collection:
                self.save(key, status='collecting')
                self.workers[key] = asyncio.create_task(self.collect_saved(key, result))
            else:
                await self.finish_collection(key, result)
                self.queue_notice(key, 'terminal', 'terminal', state.get('error') or '预期成果已保存')
            return True
        if remote_state == 'unknown':
            self.record(key, 'reconcile', 'unknown', _changes={'status': 'needs_attention', 'error': '队列与历史均无法确认任务；状态待核对，不自动重提'}, prompt_id=state['prompt_id'])
            self.queue_notice(key, 'terminal', 'attention', state['error'])
            return True
        if state['status'] != remote_state:
            self.record(key, 'execution', remote_state)
        self.save(key, status=remote_state, error=None)
        return False

    async def finish_collection(self, key, result):
        data, state = self.rows[key]['input'], self.rows[key]['state']
        if not isinstance(result, dict) or result.get('state') not in ('success', 'failed'):
            raise ValueError('取回必须使用已确认的终态结果')
        if result['state'] == 'failed':
            messages = (result.get('history') or {}).get('status', {}).get('messages', [])
            details = next((payload for event, payload in messages
                            if event in ('execution_error', 'execution_interrupted')), {})
            error = json.dumps(details, ensure_ascii=False) if details else 'ComfyUI确认执行失败；详情见执行结果.json'
            self.save(key, status='failed', error=error, error_details=details, ended_at=client.now(), progress=None, failure_stage='execution')
            return
        self.save(key, status='collecting', progress=None, ended_at=state.get('ended_at') or client.now(), phase='collection',
                  collection_attempt=state.get('collection_attempt', 1), collection_auto_retry=state.get('collection_auto_retry', 0))
        while True:
            if state.get('collection_next_retry_at'):
                remaining = (datetime.fromisoformat(state['collection_next_retry_at']) - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                self.record(key, 'collection_retry', 'started', _changes={'collection_next_retry_at': None, 'collection_auto_retry': state['collection_auto_retry'] + 1, 'collection_attempt': state['collection_attempt'] + 1}, attempt=state['collection_attempt'] + 1, auto_retry=state['collection_auto_retry'] + 1)
            self.record(key, 'collection', 'started', _changes={'error': None, 'failure_stage': None}, attempt=state['collection_attempt'])
            try:
                problems = await segments.finish(self, key, result) if data.segment_plan else await self.collect(key, result)
            except (client.ClientError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
                problems = [failure(error, client.ClientError)]
            if not problems:
                self.record(key, 'collection', 'completed', _changes={'status': 'completed', 'error': None, 'failure_stage': None, 'collection_errors': [], 'collection_next_retry_at': None, 'collection_retry_stop': None, 'collected_at': client.now()}, collected=state['collected'], attempt=state['collection_attempt'])
                return
            message = '；'.join((item.get('path') or item.get('identity') or '成果取回') + '：' + item['error'] for item in problems)
            self.record(key, 'collection', 'attempt_failed', error=message, failures=problems,
                        collected=state['collected'], attempt=state['collection_attempt'])
            retries = state['collection_auto_retry']
            retryable = all(item['retryable'] for item in problems)
            if not retryable or retries == len(DELAYS):
                self.record(key, 'collection', 'collection_failed', _changes={'status': 'collection_failed', 'error': message, 'failure_stage': 'collection', 'collection_errors': problems, 'collection_next_retry_at': None, 'collection_retry_stop': 'exhausted' if retryable else 'requires_attention'}, error=message, attempt=state['collection_attempt'], auto_retry=retries, stop='exhausted' if retryable else 'requires_attention')
                return
            delay = max([DELAYS[retries], *(item.get('retry_after_seconds', 0) for item in problems)])
            due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            self.record(key, 'collection_retry', 'scheduled', _changes={'error': message, 'failure_stage': 'collection', 'collection_errors': problems, 'collection_next_retry_at': due, 'collection_retry_stop': None}, error=message, auto_retry=retries + 1, delay_seconds=delay, next_retry_at=due, attempt=state['collection_attempt'])

    async def collect(self, key, result):
        data, state = self.rows[key]['input'], self.rows[key]['state']
        if not data.outputs:
            raise ValueError('生成成功但没有配置成果取回映射')
        problems = []
        collected = 0
        saved_outputs = []
        verified = self.rows[key].setdefault('_collection_ok', {})
        row = self.rows[key]
        if row.get('_output_result') is not result:
            index = {}
            for item in result['files']:
                index.setdefault((item['node_id'], item['output_key'], item['index']), []).append(item['file'])
            row['_output_index'], row['_output_result'] = index, result
        saved_items = []
        for output in data.outputs:
            try:
                matching = row['_output_index'].get((output.node_id, output.output_key, output.index), [])
                if len(matching) != 1:
                    raise ValueError(f'预期输出未确认：节点{output.node_id}/{output.output_key}/{output.index}')
                identity = matching[0]
                response = Path(data.record_dir) / output.response_name
                proof = (identity, saved_stamp(response, Path(output.path)))
                fresh = False
                if proof[1] is not None and verified.get(str(response)) == proof:
                    pass
                elif response.exists():
                    previous = client.strict_json(response.read_bytes())['data']
                    if (previous['remote'] != {name: identity[name] for name in ('filename', 'subfolder', 'type')}
                            or paths.project_file(data.project, previous['path'], recorded=True) != Path(output.path)
                            or proof[1] is None or proof[1][1][0] != previous['bytes']):
                        raise ValueError('已有下载证据与当前文件不一致，不覆盖文件')
                else:
                    downloaded = await asyncio.to_thread(client.download, self.client_for(data),
                        argparse.Namespace(filename=identity['filename'], subfolder=identity['subfolder'],
                                           type=identity['type'], output=output.path, sha256=None))
                    downloaded['path'] = self.record_paths(key).relative_file(downloaded['path'])
                    client.write_new(response, {'time': client.now(), 'data': downloaded})
                    proof = (identity, saved_stamp(response, Path(output.path)))
                    fresh = True
                verified[str(response)] = proof
                collected += 1
                saved_outputs.append(output.path)
                saved_items.append({'path': output.path, 'receipt': str(response), 'remote': identity,
                                    'bytes': proof[1][1][0]})
                if fresh:
                    self.record(key, 'download', 'success', path=output.path, remote=identity, receipt=str(response),
                                attempt=state.get('collection_attempt', 1), _changes={'collected': collected,
                                'saved_outputs': saved_outputs.copy(), 'result_items': saved_items.copy()})
            except (client.ClientError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
                issue = failure(error, client.ClientError, path=output.path)
                problems.append(issue)
                self.record(key, 'download', 'failed', **issue, attempt=state.get('collection_attempt', 1))
        if any(state.get(name) != value for name, value in {'collected': collected, 'saved_outputs': saved_outputs,
                                                          'result_items': saved_items}.items()):
            self.save(key, collected=collected, saved_outputs=saved_outputs, result_items=saved_items)
        return problems

    async def watch(self, key, socket=None):
        data, state = self.rows[key]['input'], self.rows[key]['state']
        try:
            while state['status'] not in TERMINAL:
                try:
                    if socket is None:
                        socket = await connect(self.ws_url(data, state['client_id']), open_timeout=data.timeout,
                                               additional_headers=self.client_for(data).headers,
                                               ping_interval=20, ping_timeout=20, max_size=2**22)
                    self.save(key, connection='connected')
                    if await self.reconcile(key):
                        break
                    while state['status'] not in TERMINAL:
                        try:
                            raw = await asyncio.wait_for(socket.recv(), 30)
                        except asyncio.TimeoutError:
                            if await self.reconcile(key):
                                break
                            continue
                        if not isinstance(raw, str):
                            continue
                        message = json.loads(raw)
                        event, payload = message['type'], message['data']
                        director_event = (event == 'minimax_director_progress' and data.segment_plan
                                          and str(payload.get('node_id')) == data.segment_plan.director_node
                                          and state.get('node') == data.segment_plan.director_node)
                        if payload.get('prompt_id') != state['prompt_id'] and not (director_event and not payload.get('prompt_id')):
                            continue
                        if event == 'execution_start':
                            self.record_start(key, payload)
                            self.record(key, 'execution', 'running', _changes={'status': 'running'})
                        elif event == 'progress':
                            self.save(key, status='running', progress={'value': payload['value'], 'max': payload['max']})
                        elif event == 'executing' and payload.get('node') is not None:
                            self.save(key, status='running', node=str(payload['node']), progress=None)
                        elif event == 'minimax_director_progress' and data.segment_plan:
                            current = {field: payload[field] for field in ('segment', 'segment_total', 'phase_label')}
                            if current != state.get('director_progress'):
                                self.record(key, 'director', 'progress', _changes={'director_progress': current}, **current)
                        elif event in ('execution_success', 'execution_error', 'execution_interrupted') or (
                                event == 'executing' and payload.get('node') is None):
                            if await self.reconcile(key):
                                break
                except (OSError, WebSocketException, client.ClientError, asyncio.TimeoutError) as error:
                    self.record(key, 'connection', 'reconnecting', _changes={'connection': 'reconnecting', 'error': '连接中断，后台正在重连核对，不代表生成失败'}, error=str(error))
                    if socket is not None:
                        await socket.close()
                        socket = None
                    await asyncio.sleep(5)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            logger.exception('ComfyUI task %s protocol error', key)
            from backend.services.collection_retry import EvidenceError
            phase = 'collection' if isinstance(error, EvidenceError) else 'execution'
            self.record(key, phase, 'protocol_error', _changes={'status': 'needs_attention', 'failure_stage': phase,
                        'error': '远端消息或证据格式异常：' + str(error)}, error=str(error))
            self.queue_notice(key, 'terminal', 'attention', state['error'])
        finally:
            if socket is not None:
                await socket.close()
        self.save(key, connection='closed')
        if state['status'] in TERMINAL:
            if key in self.notifiers:
                await self.notifiers[key]
            else:
                await self.notify(key)

    def record_start(self, key, payload):
        if not self.rows[key]['state'].get('started_at'):
            started_at = (datetime.fromtimestamp(payload['timestamp'] / 1000, timezone.utc).isoformat()
                          if 'timestamp' in payload else client.now())
            self.save(key, started_at=started_at)

    async def read_session_name(self, key):
        try:
            result = await self.desktop_call(self.rows[key]['input'], 'read')
            response = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
            title = response['thread']['title']
            if not isinstance(title, str) or not title.strip():
                raise ValueError('来源会话没有有效标题')
            self.save(key, source_session_name=title)
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, StopIteration) as error:
            logger.warning('ComfyUI task %s source session lookup failed: %s', key, error)

    async def desktop_call(self, data, operation, prompt=''):
        channel = getattr(self, '_notification_channels', {}).get(data.thread_id)
        if channel is not None and not self.queue_notifications:
            return await channel.call(data, operation, prompt)
        if self.queue_notifications and operation == 'send':
            cli = data.desktop.cli or os.environ.get('CODEX_CLI_PATH') or shutil.which('codex')
            if not cli:
                raise OSError('找不到Codex CLI，无法投递后台通知')
            def queue():
                completed = subprocess.run([cli, 'queue', '--thread', data.thread_id, '--message', prompt],
                    encoding='utf-8', capture_output=True, timeout=40)
                if completed.returncode:
                    raise OSError(f'Codex queue退出{completed.returncode}：{completed.stderr.strip()}')
                return {'receipt': completed.stdout.strip()}
            return await asyncio.to_thread(queue)
        bridge = Path(__file__).resolve().parents[2] / 'scripts/codex_task_bridge.mjs'
        environment = {**os.environ, 'CODEX_APP_TOOLS_PIPE_PATH': data.desktop.pipe}
        payload = {'server': data.desktop.server, 'caller': data.desktop.caller_thread,
                   'threadId': data.thread_id, 'operation': operation, 'prompt': prompt}
        def call():
            completed = subprocess.run([data.desktop.node, str(bridge)], input=json.dumps(payload),
                encoding='utf-8', capture_output=True, timeout=40, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if completed.returncode:
                raise OSError('Codex连接不可用')
            result = json.loads(completed.stdout)
            if result.get('isError'):
                raise OSError('Codex拒绝本次会话操作')
            return result
        return await asyncio.to_thread(call)
