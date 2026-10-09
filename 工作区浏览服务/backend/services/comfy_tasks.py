"""Persistent ComfyUI monitoring; browser clients only receive public snapshots."""
import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import time
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid

from pydantic import BaseModel, Field
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException
from backend.services import comfy_segments as segments
from backend.services.comfy_nodes import RemoteQueues, initial_state

logger = logging.getLogger(__name__)
SEGMENT_CHECK_INTERVAL = 30
SKILL = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama'
spec = importlib.util.spec_from_file_location('nora_comfy_client', SKILL / 'references/comfyui-scripts/comfyui_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


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


class TaskInput(BaseModel):
    project: str
    title: str
    task_type: str
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


class TaskStore:
    def __init__(self, runtime: Path, workspace: Path):
        self.runtime, self.workspace = runtime, workspace.resolve()
        runtime.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(runtime / 'comfy-tasks.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL)')
        self.db.commit()
        self.rows = {key: {'input': TaskInput.model_validate_json(payload), 'state': json.loads(state)}
                     for key, payload, state in self.db.execute('SELECT id, payload, state FROM tasks')}
        self.workers = {}
        self.notifiers = {}
        self.session_readers = {}
        self.notification_locks = {}
        self.client = client
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

    def public(self):
        return {'tasks': sorted(({**{key: ([{field: item.get(field) for field in ('identity', 'index', 'check', 'path', 'error')}
                                        for item in value.values()] if key == 'segments' else value) for key, value in row['state'].items()
                                 if key not in ('client_id', 'segment_monitor', 'notices')},
                                 'remote_url': client.Client(row['input'].url, row['input'].timeout).url,
                                 'notification_unknown': sum(item['delivery'] == 'delivery_unknown' for item in row['state'].get('notices', []))}
                                for row in self.rows.values()),
                                key=lambda item: item['created_at'], reverse=True),
                'remote_nodes': [{'url': url, 'name': '默认节点' if index == 0 else f'备用{index}',
                                  **self.remote_queues.states.get(url, initial_state())}
                                 for index, url in enumerate(self.remote_urls())]}

    def publish(self):
        for event in self.subscribers:
            event.set()

    def save(self, key, **changes):
        row = self.rows[key]
        row['state'].update(changes, updated_at=client.now())
        self.db.execute('INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET state=excluded.state',
                        (key, row['input'].model_dump_json(), json.dumps(row['state'], ensure_ascii=False)))
        self.db.commit()
        self.publish()

    def validate(self, data):
        project = Path(data.project).resolve(strict=True)
        if project.parent != self.workspace / 'projects':
            raise ValueError('任务必须属于当前工作区projects下的项目')
        config = client.strict_json((project / 'comfyui-config.json').read_bytes())
        configured = config.get('remote-urls', [config.get('remote-url')])
        if data.url not in [client.Client(url, data.timeout).url for url in configured]:
            raise ValueError('服务地址不在项目配置中')
        record = Path(data.record_dir).resolve()
        if not record.is_relative_to(project):
            raise ValueError('执行附件必须位于所属项目内')
        names = [data.attempt_name, data.request_name, data.response_name, data.history_name]
        names += [output.response_name for output in data.outputs]
        for name in names:
            client.remote_path(name, filename=True)
        if len(names) != len(set(names)):
            raise ValueError('证据文件名不能重复')
        if any((record / name).exists() for name in names):
            raise client.ClientError('submission_guard', '已有任务证据；核对原任务，不得再次提交')
        targets = [Path(output.path).resolve() for output in data.outputs]
        if any(not Path(output.path).is_absolute() for output in data.outputs):
            raise ValueError('成果保存路径必须是绝对路径')
        if any(not path.is_relative_to(project) or path.is_relative_to(record) for path in targets):
            raise ValueError('成果必须位于所属项目内，且不得写入执行附件目录')
        if len(targets) != len(set(targets)):
            raise ValueError('成果保存路径不能重复')
        selectors = [(out.node_id, out.output_key, out.index) for out in data.outputs]
        if any(output.node_id not in data.workflow for output in data.outputs):
            raise ValueError('预期输出节点不在工作流中')
        if len(selectors) != len(set(selectors)):
            raise ValueError('输出身份不能重复')
        if not data.thread_id or not data.desktop.caller_thread:
            raise ValueError('缺少真实会话身份')
        client.validate_workflow(data.workflow)
        native_segments = [node for node in data.workflow.values() if node['class_type'] == 'MiniMaxH3Director'
            and json.loads(node['inputs']['timeline_data']).get('output', {}).get('exportMode') == 'segments']
        if native_segments and not data.segment_plan:
            raise ValueError('原生H3分段任务必须登记segment-plan，不能仅等终态处理')
        if data.segment_plan:
            try:
                segments.validate(data)
            except (KeyError, IndexError, TypeError) as error:
                raise ValueError('分段计划或输入映射字段不完整：' + str(error)) from error
            if data.outputs:
                raise ValueError('原生分段任务使用segment-plan，不混用末段保存节点作为全组输出')
        return project

    def client_for(self, data):
        return client.Client(data.url, data.timeout)

    def queue_notice(self, key, event_id, kind, message):
        state = self.rows[key]['state']
        notices = state.setdefault('notices', [])
        if any(item['id'] == event_id for item in notices):
            return
        notices.append({'id': event_id, 'kind': kind, 'message': message, 'delivery': 'pending'})
        self.save(key, notification='waiting_idle')
        if key not in self.notifiers or self.notifiers[key].done():
            self.notifiers[key] = asyncio.create_task(self.notify(key))

    def ws_url(self, data, client_id):
        parts = urlsplit(data.url)
        return urlunsplit(('wss' if parts.scheme == 'https' else 'ws', parts.netloc,
                           parts.path + '/ws', urlencode({'clientId': client_id}), ''))

    async def submit(self, data):
        project = self.validate(data)
        record = Path(data.record_dir)
        if any((record / name).exists() for name in (data.attempt_name, data.request_name, data.response_name)):
            raise client.ClientError('submission_guard', '已有提交证据，不得再次提交')
        client_id, key = str(uuid.uuid4()), str(uuid.uuid4())
        log_cursor = await segments.baseline(self, data) if data.segment_plan else None
        # The WebSocket is open before the only POST; fast/cached completions stay buffered.
        socket = await connect(self.ws_url(data, client_id), open_timeout=data.timeout, max_size=2**22)
        self.rows[key] = {'input': data, 'state': {
            'id': key, 'project': project.name, 'title': data.title, 'task_type': data.task_type,
            'prompt_id': None, 'client_id': client_id, 'status': 'submitting', 'connection': 'connected',
            'progress': None, 'node': None, 'error': None, 'notification': 'waiting',
            'created_at': client.now(), 'started_at': None, 'updated_at': client.now(), 'collected': 0, 'expected': len(data.outputs)}}
        self.save(key)
        if data.segment_plan:
            self.save(key, expected=len(segments.targets(data)), segments={str(item['index']): {
                'identity': item['identity'], 'index': item['index'], 'check': '未取回', 'versions': [], 'error': None}
                for item in segments.targets(data)}, segment_monitor={
                    'cursor': log_cursor, 'started': False, 'run_dir': None, 'last_probe': 0, 'failures': 0})
        try:
            result = await asyncio.to_thread(client.submit, client.Client(data.url, data.timeout),
                argparse.Namespace(**data.model_dump()), workflow=data.workflow, client_id=client_id)
        except (client.ClientError, OSError, ValueError) as error:
            rejected = isinstance(error, client.ClientError) and error.code == 'submission_rejected'
            self.save(key, status='rejected' if rejected else 'submission_unknown', error=str(error))
            if not rejected:
                self.queue_notice(key, 'submission_unknown', 'attention', '提交结果未确认；核对原提交证据，不自动重新提交')
            await socket.close()
            raise
        self.save(key, prompt_id=result['prompt_id'], status='queued')
        self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
        self.workers[key] = asyncio.create_task(self.watch(key, socket))
        return {**result, 'monitor': 'browser', 'monitor_id': key}

    async def start(self):
        for key, row in self.rows.items():
            state = row['state']
            if state['status'] == 'rejected':
                continue
            if state['notification'] == 'sending':
                self.save(key, notification='delivery_unknown')
            for notice in state.get('notices', []):
                if notice['delivery'] == 'sending':
                    notice['delivery'] = 'delivery_unknown'
            self.save(key)
            if any(notice['delivery'] == 'pending' for notice in state.get('notices', [])):
                self.notifiers[key] = asyncio.create_task(self.notify(key))
            if not state['prompt_id']:
                # A response may have been saved immediately before a service crash.
                response = Path(row['input'].record_dir) / row['input'].response_name
                if response.is_file():
                    result = client.strict_json(response.read_bytes())
                    if result.get('prompt_id'):
                        self.save(key, prompt_id=result['prompt_id'], status='queued')
                if not state['prompt_id']:
                    self.save(key, status='submission_unknown', error='提交未确认；核对原提交证据，不自动重提')
                    self.queue_notice(key, 'submission_unknown', 'attention', state['error'])
                    continue
            if state['status'] in ('completed', 'failed', 'needs_attention', 'collection_failed'):
                if state['notification'] in ('waiting', 'waiting_connection', 'waiting_idle'):
                    self.workers[key] = asyncio.create_task(self.notify(key))
            else:
                if not state.get('source_session_name'):
                    self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
                self.workers[key] = asyncio.create_task(self.watch(key))

    async def close(self):
        await self.remote_queues.close()
        tasks = [*self.workers.values(), *self.notifiers.values(), *self.session_readers.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.db.close()

    async def reconcile(self, key):
        row = self.rows[key]
        data, state = row['input'], row['state']
        result = await asyncio.to_thread(client.status, client.Client(data.url, data.timeout),
                                         argparse.Namespace(prompt_id=state['prompt_id']))
        remote_state = result['state']
        if not state.get('started_at'):
            for event, payload in (result.get('history') or {}).get('status', {}).get('messages', []):
                if event == 'execution_start' and payload.get('prompt_id') == state['prompt_id'] and 'timestamp' in payload:
                    self.record_start(key, payload)
                    break
        if remote_state in ('success', 'failed'):
            history = Path(data.record_dir) / data.history_name
            if not history.exists():
                client.write_new(history, {'time': client.now(), 'data': result})
            if data.segment_plan:
                if state['segment_monitor']['run_dir']:
                    try:
                        await segments.scan(self, key, terminal=True)
                    except (client.ClientError, OSError, ValueError, KeyError, TypeError) as error:
                        self.save(key, segment_warning='收尾日志补查不可用，按最终报告核对：' + str(error))
                problems = await segments.finish(self, key, result)
                if remote_state == 'failed':
                    self.save(key, status='failed', error='ComfyUI确认执行失败；已取回分段保留，缺项见分段状态', progress=None)
                elif problems:
                    self.save(key, status='collection_failed', error='；'.join(problems), progress=None)
                elif any(item['check'] == '新文件已取回，待替换核对' for item in state['segments'].values()):
                    self.save(key, status='needs_attention', error='改写后的新文件已取回，需原会话按旧批准关系完成留存与替换', progress=None)
                else:
                    self.save(key, status='completed', error=None, progress=None)
            elif remote_state == 'failed':
                self.save(key, status='failed', error='ComfyUI确认执行失败；详情见终态附件', progress=None)
            else:
                self.save(key, status='collecting', error=None, progress=None)
                try:
                    await self.collect(key, result)
                except (client.ClientError, OSError, ValueError) as error:
                    logger.warning('ComfyUI task %s collection failed: %s', key, error)
                    self.save(key, status='collection_failed', error=str(error))
            self.queue_notice(key, 'terminal', 'terminal', f'整轮状态：{state["status"]}；{state.get("error") or "预期成果已取回"}')
            return True
        if remote_state == 'unknown':
            self.save(key, status='needs_attention', error='history及queue均无法确认任务；停止自动处理，请核对原任务')
            self.queue_notice(key, 'terminal', 'terminal', state['error'])
            return True
        self.save(key, status=remote_state, error=None)
        return False

    async def collect(self, key, result):
        row = self.rows[key]
        data = row['input']
        if not data.outputs:
            self.save(key, status='needs_attention', error='生成已成功；未配置自动取回映射，需原会话按专项规则核对输出')
            return
        for output in data.outputs:
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
                        or previous['path'] != str(Path(output.path).absolute())
                        or not Path(output.path).is_file()
                        or Path(output.path).stat().st_size != previous['bytes']):
                    raise ValueError('已有下载证据与当前文件不一致，需原会话核对')
                continue
            downloaded = await asyncio.to_thread(client.download, client.Client(data.url, data.timeout),
                argparse.Namespace(filename=identity['filename'], subfolder=identity['subfolder'],
                                   type=identity['type'], output=output.path, sha256=None))
            client.write_new(response, {'time': client.now(), 'data': downloaded})
            self.save(key, collected=self.rows[key]['state']['collected'] + 1)
        self.save(key, status='completed', collected=len(data.outputs), error=None)

    async def watch(self, key, socket=None):
        row = self.rows[key]
        data, state = row['input'], row['state']
        disconnected_since = None
        try:
            while True:
                try:
                    if socket is None:
                        socket = await connect(self.ws_url(data, state['client_id']), open_timeout=data.timeout, max_size=2**22)
                    self.save(key, connection='connected')
                    if await self.reconcile(key):
                        break
                    disconnected_since = None
                    if data.segment_plan:
                        await self.probe_segments(key, force=True)
                    last_reconcile = time.monotonic()
                    while True:
                        if data.segment_plan:
                            await self.probe_segments(key)
                        if time.monotonic() - last_reconcile >= 300:
                            if await self.reconcile(key):
                                break
                            last_reconcile = time.monotonic()
                        try:
                            delay = max(.01, SEGMENT_CHECK_INTERVAL - (time.monotonic() - state['segment_monitor']['last_probe'])) if data.segment_plan else 300
                            raw = await asyncio.wait_for(socket.recv(), delay)
                        except asyncio.TimeoutError:
                            if data.segment_plan:
                                await self.probe_segments(key)
                            if not data.segment_plan or time.monotonic() - last_reconcile >= 300:
                                if await self.reconcile(key):
                                    break
                                last_reconcile = time.monotonic()
                            continue
                        if not isinstance(raw, str):
                            continue  # Binary preview frames are not task completion evidence.
                        message = json.loads(raw)
                        event, payload = message['type'], message['data']
                        if event == 'minimax_director_progress' and data.segment_plan:
                            if (payload.get('prompt_id', state['prompt_id']) == state['prompt_id']
                                    and str(payload.get('node_id')) == data.segment_plan.director_node
                                    and state.get('node') == data.segment_plan.director_node
                                    and state['segment_monitor']['started']):
                                previous = state.get('director_progress')
                                current = {field: payload[field] for field in ('segment', 'segment_total', 'timeline_segment', 'phase', 'phase_label')}
                                self.save(key, director_progress=current)
                                if previous != current:
                                    await self.probe_segments(key)
                            continue
                        if payload.get('prompt_id') != state['prompt_id']:
                            continue
                        if event == 'execution_start':
                            self.record_start(key, payload)
                            self.save(key, status='running')
                            if data.segment_plan:
                                await self.probe_segments(key, begin=True, force=True)
                        elif event == 'progress':
                            self.save(key, status='running', progress={'value': payload['value'], 'max': payload['max']})
                        elif event == 'executing' and payload.get('node') is not None:
                            self.save(key, status='running', node=str(payload['node']), progress=None)
                        elif event in ('execution_success', 'execution_error', 'execution_interrupted') or (
                                event == 'executing' and payload.get('node') is None):
                            if await self.reconcile(key):
                                break
                        if data.segment_plan:
                            await self.probe_segments(key)
                        if time.monotonic() - last_reconcile >= 300:
                            if await self.reconcile(key):
                                break
                            last_reconcile = time.monotonic()
                    if state['status'] in ('completed', 'failed', 'needs_attention', 'collection_failed'):
                        break
                except (OSError, WebSocketException, client.ClientError, asyncio.TimeoutError) as error:
                    logger.warning('ComfyUI task %s connection interrupted: %s', key, type(error).__name__)
                    self.save(key, connection='reconnecting', error='连接中断，正在恢复；不代表生成失败')
                    if disconnected_since is None:
                        disconnected_since = time.monotonic()
                    elif time.monotonic() - disconnected_since >= 300:
                        self.queue_notice(key, 'connection_issue', 'attention', '连接持续无法恢复，请核对原任务；后台仍在重连，不重新提交')
                    if socket is not None:
                        await socket.close()
                        socket = None
                    await asyncio.sleep(5)
        except (ValueError, KeyError, TypeError) as error:
            logger.exception('ComfyUI task %s protocol error', key)
            self.save(key, status='needs_attention', error='远端消息或证据格式异常：' + str(error))
            self.queue_notice(key, 'terminal', 'attention', state['error'])
        finally:
            if socket is not None:
                await socket.close()
        self.save(key, connection='closed')
        if key in self.notifiers:
            await self.notifiers[key]
        else:
            await self.notify(key)

    async def probe_segments(self, key, *, begin=False, force=False):
        state = self.rows[key]['state']
        runtime = state['segment_monitor']
        if not force and time.monotonic() - runtime['last_probe'] < SEGMENT_CHECK_INTERVAL:
            return
        runtime['last_probe'] = time.monotonic()
        try:
            await segments.scan(self, key, begin=begin)
        except (client.ClientError, OSError, ValueError, KeyError, TypeError) as error:
            runtime['failures'] += 1
            self.save(key, segment_warning='逐段查询或取回未完成，保留已有成果并等待补查：' + str(error))
            if runtime['failures'] >= 3:
                self.queue_notice(key, 'segment_issue', 'attention', state['segment_warning'])
        else:
            runtime['failures'] = 0
            self.save(key, segment_warning=None)

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

    async def notify(self, key):
        # A task can report several collected segments while its monitor keeps running.
        lock = self.notification_locks.setdefault(key, asyncio.Lock())
        async with lock:
            row = self.rows[key]
            data, state = row['input'], row['state']
            if not state.get('notices'):
                if state['notification'] in ('sent', 'sending', 'delivery_unknown'):
                    return
                state['notices'] = [{'id': 'terminal', 'kind': 'terminal',
                    'message': f"整轮状态：{state['status']}；执行附件：{data.record_dir}", 'delivery': 'pending'}]
                self.save(key)
            while any(item['delivery'] == 'pending' for item in state['notices']):
                # Briefly coalesce adjacent saves, including the final segment and terminal result.
                await asyncio.sleep(2)
                try:
                    result = await self.desktop_call(data, 'read')
                    response = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
                    status = response['thread']['status']['type']
                except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, StopIteration):
                    self.save(key, notification='waiting_connection')
                    await asyncio.sleep(30)
                    continue
                if status not in ('idle', 'notLoaded'):
                    self.save(key, notification='waiting_idle')
                    await asyncio.sleep(15)
                    continue
                pending = [item for item in state['notices'] if item['delivery'] == 'pending']
                details = '\n'.join(f"事件 {item['id']}：{item['message']}" for item in pending)
                prompt = (f'ComfyUI任务通知。任务ID：{key}；项目：{state["project"]}；任务：{data.title}；'
                    f'prompt_id：{state["prompt_id"]}；当前状态：{state["status"]}。\n'
                    f'共同执行附件：{data.record_dir}\n{details}\n'
                    '请核对事件是否已处理、现有授权和下载凭据，再按主技能监控及目录规范维护原业务记录并展示。'
                    '运行中取回不代表整轮完成；新改写文件先核对旧批准、当前选定及下游影响，按专项规则留旧换新，不能沿用旧批准。'
                    '传输成功不代表素材获批；不得因此提交新任务、启动下一阶段、重提未知任务或创建重复监控。')
                for item in pending:
                    item['delivery'] = 'sending'
                self.save(key, notification='sending')
                try:
                    await self.desktop_call(data, 'send', prompt)
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    delivery = 'delivery_unknown'
                else:
                    delivery = 'sent'
                for item in pending:
                    item['delivery'] = delivery
                self.save(key, notification=delivery)
