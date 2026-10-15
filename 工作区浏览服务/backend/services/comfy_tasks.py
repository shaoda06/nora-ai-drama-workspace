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
from backend.services.collection_retry import DELAYS, failure

logger = logging.getLogger(__name__)
SKILL = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama'
sys.path.insert(0, str(SKILL / 'scripts'))
import project_paths as paths
spec = importlib.util.spec_from_file_location('nora_comfy_client', SKILL / 'references/comfyui-scripts/comfyui_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
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
            self.rows[key] = {'input': data, 'state': paths.recorded_paths(data.project, json.loads(state))}
        for key in self.rows:
            self.persist(key)
        self.db.commit()
        self.workers = {}
        self.notifiers = {}
        self.session_readers = {}
        self.notification_locks = {}
        self.reconcile_locks = {}
        self.client = client
        self.generation_context = generation_context
        self.queue_init()
        self.subscribers = set()
        self.token = secrets.token_urlsafe(32)
        self.remote_queues = RemoteQueues(client, self.remote_urls, self.publish)

    def remote_urls(self):
        remote_urls = []
        for path in sorted((self.workspace / 'projects').glob('*/comfyui-config.json')):
            config = client.strict_json(path.read_bytes())
            for url in config.get('remote-urls', [config.get('remote-url')]):
                remote_url = client.Client(url, 30).url
                if remote_url not in remote_urls:
                    remote_urls.append(remote_url)
        return remote_urls

    def project_urls(self, data):
        config = client.strict_json((Path(data.project) / 'comfyui-config.json').read_bytes())
        return [client.Client(url, data.timeout).url for url in config.get('remote-urls', [config.get('remote-url')])]

    def public(self, include_history=True):
        snapshot = {'tasks': sorted(({**{key: ([{field: item.get(field) for field in ('identity', 'index', 'check', 'path', 'error')}
                                        for item in value.values()] if key == 'segments' else value) for key, value in row['state'].items()
                                 if key not in ('client_id', 'segment_monitor', 'notices')},
                                 'remote_url': row['input'].url.rstrip('/'),
                                 'notification_unknown': sum(item['delivery'] == 'delivery_unknown' for item in row['state'].get('notices', []))}
                                for row in self.rows.values()),
                                key=lambda item: item['created_at'], reverse=True),
                'remote_nodes': [{'url': url, 'name': '默认节点' if index == 0 else f'备用{index}',
                                  **self.remote_queues.states.get(url, initial_state())}
                                 for index, url in enumerate(self.remote_urls())]}
        local = []
        orders = {node['url']: self.ordered(node['url']) for node in snapshot['remote_nodes']}
        projects = {}
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
            if row['input'].project not in projects:
                projects[row['input'].project] = self.project_urls(row['input'])
            local.append({**task, 'queue': 'local', 'category': category,
                          'can_transfer': self.can_transfer(task['id']),
                          'transfer_targets': [{'url': url, 'name': '默认节点' if index == 0 else f'备用{index}'}
                                               for index, url in enumerate(projects[row['input'].project]) if url != task['remote_url']],
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
        self.db.execute('INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,state=excluded.state',
                        (key, json.dumps(self.portable_input(row['input']), ensure_ascii=False),
                         json.dumps(paths.recorded_paths(row['input'].project, row['state'], relative=True), ensure_ascii=False)))

    def resolve_input(self, data, *, recorded=False):
        if not recorded and not Path(data.project).is_absolute() and PureWindowsPath(data.project).name != data.project:
            raise ValueError('项目必须是当前工作区内的项目名或绝对路径')
        project = self.workspace / 'projects' / PureWindowsPath(data.project).name if recorded or not Path(data.project).is_absolute() else Path(data.project)
        if project.resolve().parent != self.workspace / 'projects':
            raise ValueError('任务必须属于当前工作区projects下的项目')
        data.project = str(project.resolve())
        data.record_dir = str(paths.project_file(project, data.record_dir, recorded=recorded))
        for output in data.outputs:
            output.path = str(paths.project_file(project, output.path, recorded=recorded))
        for upload in data.uploads:
            if isinstance(upload.get('file'), str):
                upload['file'] = str(paths.project_file(project, upload['file'], recorded=recorded))
        if data.segment_plan:
            for target in data.segment_plan.targets:
                target.path = str(paths.project_file(project, target.path, recorded=recorded))

    def portable_input(self, data):
        payload = data.model_dump()
        payload['project'] = Path(data.project).name
        payload['record_dir'] = paths.relative_file(data.project, data.record_dir, recorded=True)
        for output in payload['outputs']:
            output['path'] = paths.recorded_paths(data.project, output['path'], relative=True, field='path')
        for upload in payload['uploads']:
            if isinstance(upload.get('file'), str):
                upload['file'] = paths.relative_file(data.project, upload['file'], recorded=True)
        if payload['segment_plan']:
            for target in payload['segment_plan']['targets']:
                target['path'] = paths.relative_file(data.project, target['path'], recorded=True)
        return payload

    def validate_registration(self, data):
        self.resolve_input(data)
        if not data.title.strip():
            raise ValueError('任务标题不能为空')
        project = Path(data.project).resolve(strict=True)
        if project.parent != self.workspace / 'projects':
            raise ValueError('任务必须属于当前工作区projects下的项目')
        config = client.strict_json((project / 'comfyui-config.json').read_bytes())
        configured = config.get('remote-urls', [config.get('remote-url')])
        if client.Client(data.url, data.timeout).url != client.Client(configured[0], data.timeout).url:
            raise ValueError('新任务只允许提交到项目主节点')
        record = Path(data.record_dir).resolve()
        if not record.is_relative_to(project):
            raise ValueError('执行附件必须位于所属项目内')
        if any((record / name).exists() for name in ('后台任务状态.json', '后台过程记录.json')):
            raise client.ClientError('registration_guard', '执行目录已有后台登记记录；请核对原任务')
        targets = [Path(output.path).resolve() for output in data.outputs]
        if any(not Path(output.path).is_absolute() for output in data.outputs):
            raise ValueError('成果保存路径必须是绝对路径')
        if any(not path.is_relative_to(project) or path.is_relative_to(record) for path in targets):
            raise ValueError('成果必须位于所属项目内，且不得写入执行附件目录')
        if not data.thread_id or not data.desktop.caller_thread:
            raise ValueError('缺少真实会话身份')
        if data.segment_plan:
            for target in data.segment_plan.targets:
                path = Path(target.path).resolve()
                if not path.is_relative_to(project) or path.is_relative_to(record):
                    raise ValueError('分段成果必须位于所属项目内，且不得写入执行附件目录')
        return project

    async def prepare_only(self, data):
        from backend.services.execution_checks import prepare_report
        self.validate_registration(data)
        return await asyncio.to_thread(prepare_report, self, data)

    def client_for(self, data):
        return client.Client(data.url, data.timeout)

    def ws_url(self, data, client_id):
        parts = urlsplit(data.url)
        return urlunsplit(('wss' if parts.scheme == 'https' else 'ws', parts.netloc,
                           parts.path + '/ws', urlencode({'clientId': client_id}), ''))

    async def submit(self, data, *, key=None, workflow=None):
        if key is None:
            project = self.validate_registration(data)
            from backend.services import execution_checks as checks
            if checks.check_prepared(self, data) is None:
                await asyncio.to_thread(checks.prepare_report, self, data, at_execution=True)
            key = str(uuid.uuid4())
            self.rows[key] = {'input': data, 'state': {
                'id': key, 'project': project.name, 'title': data.title, 'task_type': data.task_type,
                'prompt_id': None, 'client_id': str(uuid.uuid4()), 'status': 'submitting',
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
        previous = state.copy()
        socket = await connect(self.ws_url(data, state['client_id']), open_timeout=data.timeout,
                               ping_interval=20, ping_timeout=20, max_size=2**22)
        self.save(key, status='submitting', phase='submit', failure_stage=None, dispatch_attempt=state.get('dispatch_attempt', 0) + 1)
        self.record(key, 'submit', 'started')
        try:
            result = await asyncio.to_thread(client.submit, self.client_for(data),
                argparse.Namespace(**data.model_dump()), workflow=workflow or data.workflow, client_id=state['client_id'])
        except (client.ClientError, OSError, ValueError) as error:
            details = getattr(error, 'details', {})
            if isinstance(error, client.ClientError) and error.code == 'submission_guard':
                state.clear()
                state.update(previous)
                if state['status'] in ('local_queued', 'paused', 'preparing', 'submitting'):
                    self.save(key, status='paused', phase='submit', failure_stage='submit', error=str(error), error_details=details)
                else:
                    self.save(key)
                self.record(key, 'submit', 'blocked', error=str(error), error_details=details)
            else:
                rejected = isinstance(error, client.ClientError) and error.code == 'submission_rejected'
                self.save(key, status='rejected' if rejected else 'submission_unknown', error=str(error), error_details=details, failure_stage='submit')
                self.record(key, 'submit', 'rejected' if rejected else 'unknown', error=str(error), error_details=details)
                self.queue_notice(key, 'submission_issue', 'attention', str(error))
            await socket.close()
            raise
        self.save(key, prompt_id=result['prompt_id'], status='queued', submitted_at=client.now(), connection='connected', immediate=False)
        self.record(key, 'submit', 'accepted', prompt_id=result['prompt_id'])
        self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
        self.workers[key] = asyncio.create_task(self.watch(key, socket))
        return {**result, 'monitor': 'browser', 'monitor_id': key, 'local_task_id': key}

    async def start(self):
        for key, row in self.rows.items():
            state = row['state']
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
                self.save(key, status='local_queued')
                self.record(key, 'restart', 'resume_local')
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
        tasks = [*self.workers.values(), *self.notifiers.values(), *self.session_readers.values(), *self.dispatch_workers.values()]
        if self.scheduler is not None:
            tasks.append(self.scheduler)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.db.close()

    async def reconcile(self, key):
        async with self.reconcile_locks.setdefault(key, asyncio.Lock()):
            if self.rows[key]['state']['status'] in TERMINAL:
                return True
            return await self.reconcile_remote(key)

    async def reconcile_remote(self, key):
        row = self.rows[key]
        data, state = row['input'], row['state']
        history = Path(data.record_dir) / data.history_name
        saved = client.strict_json(history.read_bytes())['data'] if history.is_file() else None
        result = saved if saved and saved.get('state') in ('success', 'failed') else await asyncio.to_thread(
            client.status, self.client_for(data), argparse.Namespace(prompt_id=state['prompt_id']))
        if result['state'] == 'unknown':
            # One additional read avoids treating a queue-to-history transition as disappearance.
            result = await asyncio.to_thread(client.status, self.client_for(data), argparse.Namespace(prompt_id=state['prompt_id']))
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
            await self.finish_collection(key, result)
            self.queue_notice(key, 'terminal', 'terminal', state.get('error') or '预期成果已保存')
            return True
        if remote_state == 'unknown':
            self.save(key, status='needs_attention', error='队列与历史均无法确认任务；状态待核对，不自动重提')
            self.record(key, 'reconcile', 'unknown', prompt_id=state['prompt_id'])
            self.queue_notice(key, 'terminal', 'attention', state['error'])
            return True
        if state['status'] != remote_state:
            self.record(key, 'execution', remote_state)
        self.save(key, status=remote_state, error=None)
        return False

    async def finish_collection(self, key, result):
        data, state = self.rows[key]['input'], self.rows[key]['state']
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
                self.save(key, collection_next_retry_at=None, collection_auto_retry=state['collection_auto_retry'] + 1,
                          collection_attempt=state['collection_attempt'] + 1)
                self.record(key, 'collection_retry', 'started', attempt=state['collection_attempt'],
                            auto_retry=state['collection_auto_retry'])
            self.save(key, error=None, failure_stage=None)
            self.record(key, 'collection', 'started', attempt=state['collection_attempt'])
            try:
                problems = await segments.finish(self, key, result) if data.segment_plan else await self.collect(key, result)
            except (client.ClientError, OSError, ValueError, KeyError) as error:
                problems = [failure(error, client.ClientError)]
            if not problems:
                self.save(key, status='completed', error=None, failure_stage=None, collection_errors=[],
                          collection_next_retry_at=None, collection_retry_stop=None)
                self.record(key, 'collection', 'completed', collected=state['collected'], attempt=state['collection_attempt'])
                return
            message = '；'.join((item.get('path') or item.get('identity') or '成果取回') + '：' + item['error'] for item in problems)
            self.record(key, 'collection', 'attempt_failed', error=message, failures=problems,
                        collected=state['collected'], attempt=state['collection_attempt'])
            retries = state['collection_auto_retry']
            retryable = all(item['retryable'] for item in problems)
            if not retryable or retries == len(DELAYS):
                self.save(key, status='collection_failed', error=message, failure_stage='collection', collection_errors=problems,
                          collection_next_retry_at=None, collection_retry_stop='exhausted' if retryable else 'requires_attention')
                self.record(key, 'collection', 'collection_failed', error=message, attempt=state['collection_attempt'],
                            auto_retry=retries, stop=state['collection_retry_stop'])
                return
            delay = max([DELAYS[retries], *(item.get('retry_after_seconds', 0) for item in problems)])
            due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            self.save(key, error=message, failure_stage='collection', collection_errors=problems,
                      collection_next_retry_at=due, collection_retry_stop=None)
            self.record(key, 'collection_retry', 'scheduled', error=message, auto_retry=retries + 1,
                        delay_seconds=delay, next_retry_at=due, attempt=state['collection_attempt'])

    async def collect(self, key, result):
        data, state = self.rows[key]['input'], self.rows[key]['state']
        if not data.outputs:
            raise ValueError('生成成功但没有配置成果取回映射')
        problems = []
        collected = 0
        saved_outputs = []
        for output in data.outputs:
            try:
                matching = [item['file'] for item in result['files'] if
                            (item['node_id'], item['output_key'], item['index']) ==
                            (output.node_id, output.output_key, output.index)]
                if len(matching) != 1:
                    raise ValueError(f'预期输出未确认：节点{output.node_id}/{output.output_key}/{output.index}')
                identity = matching[0]
                response = Path(data.record_dir) / output.response_name
                if response.exists():
                    previous = client.strict_json(response.read_bytes())['data']
                    if (previous['remote'] != {name: identity[name] for name in ('filename', 'subfolder', 'type')}
                            or paths.project_file(data.project, previous['path'], recorded=True) != Path(output.path)
                            or not Path(output.path).is_file() or Path(output.path).stat().st_size != previous['bytes']):
                        raise ValueError('已有下载证据与当前文件不一致，不覆盖文件')
                else:
                    downloaded = await asyncio.to_thread(client.download, self.client_for(data),
                        argparse.Namespace(filename=identity['filename'], subfolder=identity['subfolder'],
                                           type=identity['type'], output=output.path, sha256=None))
                    downloaded['path'] = paths.relative_file(data.project, downloaded['path'])
                    client.write_new(response, {'time': client.now(), 'data': downloaded})
                    self.record(key, 'download', 'success', path=output.path, remote=identity, receipt=str(response),
                                attempt=state.get('collection_attempt', 1))
                collected += 1
                saved_outputs.append(output.path)
                self.save(key, collected=collected, saved_outputs=saved_outputs.copy())
            except (client.ClientError, OSError, ValueError, KeyError) as error:
                issue = failure(error, client.ClientError, path=output.path)
                problems.append(issue)
                self.record(key, 'download', 'failed', **issue, attempt=state.get('collection_attempt', 1))
        self.save(key, collected=collected, saved_outputs=saved_outputs)
        return problems

    async def watch(self, key, socket=None):
        data, state = self.rows[key]['input'], self.rows[key]['state']
        try:
            while state['status'] not in TERMINAL:
                try:
                    if socket is None:
                        socket = await connect(self.ws_url(data, state['client_id']), open_timeout=data.timeout,
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
                            self.save(key, status='running')
                            self.record(key, 'execution', 'running')
                        elif event == 'progress':
                            self.save(key, status='running', progress={'value': payload['value'], 'max': payload['max']})
                        elif event == 'executing' and payload.get('node') is not None:
                            self.save(key, status='running', node=str(payload['node']), progress=None)
                        elif event == 'minimax_director_progress' and data.segment_plan:
                            current = {field: payload[field] for field in ('segment', 'segment_total', 'phase_label')}
                            if current != state.get('director_progress'):
                                self.save(key, director_progress=current)
                                self.record(key, 'director', 'progress', **current)
                        elif event in ('execution_success', 'execution_error', 'execution_interrupted') or (
                                event == 'executing' and payload.get('node') is None):
                            if await self.reconcile(key):
                                break
                except (OSError, WebSocketException, client.ClientError, asyncio.TimeoutError) as error:
                    self.save(key, connection='reconnecting', error='连接中断，后台正在重连核对，不代表生成失败')
                    self.record(key, 'connection', 'reconnecting', error=str(error))
                    if socket is not None:
                        await socket.close()
                        socket = None
                    await asyncio.sleep(5)
        except (ValueError, KeyError, TypeError) as error:
            logger.exception('ComfyUI task %s protocol error', key)
            self.save(key, status='needs_attention', error='远端消息或证据格式异常：' + str(error))
            self.record(key, 'execution', 'protocol_error', error=str(error))
            self.queue_notice(key, 'terminal', 'attention', state['error'])
        finally:
            if socket is not None:
                await socket.close()
        self.save(key, connection='closed')
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
