"""Persistent ComfyUI monitoring; browser clients only receive public snapshots."""
import argparse
import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid

from pydantic import BaseModel, Field
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

logger = logging.getLogger(__name__)
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
        self.subscribers = set()
        self.token = secrets.token_urlsafe(32)

    def public(self):
        return {'tasks': sorted(({key: value for key, value in row['state'].items() if key != 'client_id'} for row in self.rows.values()),
                                key=lambda item: item['created_at'], reverse=True)}

    def save(self, key, **changes):
        row = self.rows[key]
        row['state'].update(changes, updated_at=client.now())
        self.db.execute('INSERT INTO tasks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET state=excluded.state',
                        (key, row['input'].model_dump_json(), json.dumps(row['state'], ensure_ascii=False)))
        self.db.commit()
        for event in self.subscribers:
            event.set()

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
        return project

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
        # The WebSocket is open before the only POST; fast/cached completions stay buffered.
        socket = await connect(self.ws_url(data, client_id), open_timeout=data.timeout, max_size=2**22)
        self.rows[key] = {'input': data, 'state': {
            'id': key, 'project': project.name, 'title': data.title, 'task_type': data.task_type,
            'prompt_id': None, 'client_id': client_id, 'status': 'submitting', 'connection': 'connected',
            'progress': None, 'node': None, 'error': None, 'notification': 'waiting',
            'created_at': client.now(), 'updated_at': client.now(), 'collected': 0, 'expected': len(data.outputs)}}
        self.save(key)
        try:
            result = await asyncio.to_thread(client.submit, client.Client(data.url, data.timeout),
                argparse.Namespace(**data.model_dump()), workflow=data.workflow, client_id=client_id)
        except (client.ClientError, OSError, ValueError) as error:
            rejected = isinstance(error, client.ClientError) and error.code == 'submission_rejected'
            self.save(key, status='rejected' if rejected else 'submission_unknown', error=str(error))
            await socket.close()
            raise
        self.save(key, prompt_id=result['prompt_id'], status='queued')
        self.workers[key] = asyncio.create_task(self.watch(key, socket))
        return {**result, 'monitor': 'browser', 'monitor_id': key}

    async def start(self):
        for key, row in self.rows.items():
            state = row['state']
            if state['status'] == 'rejected':
                continue
            if state['notification'] == 'sending':
                self.save(key, notification='delivery_unknown')
            if not state['prompt_id']:
                # A response may have been saved immediately before a service crash.
                response = Path(row['input'].record_dir) / row['input'].response_name
                if response.is_file():
                    result = client.strict_json(response.read_bytes())
                    if result.get('prompt_id'):
                        self.save(key, prompt_id=result['prompt_id'], status='queued')
                if not state['prompt_id']:
                    self.save(key, status='submission_unknown', error='提交未确认；核对原提交证据，不自动重提')
                    continue
            if state['status'] in ('completed', 'failed', 'needs_attention', 'collection_failed'):
                if state['notification'] in ('waiting', 'waiting_connection', 'waiting_idle'):
                    self.workers[key] = asyncio.create_task(self.notify(key))
            else:
                self.workers[key] = asyncio.create_task(self.watch(key))

    async def close(self):
        for task in self.workers.values():
            task.cancel()
        await asyncio.gather(*self.workers.values(), return_exceptions=True)
        self.db.close()

    async def reconcile(self, key):
        row = self.rows[key]
        data, state = row['input'], row['state']
        result = await asyncio.to_thread(client.status, client.Client(data.url, data.timeout),
                                         argparse.Namespace(prompt_id=state['prompt_id']))
        remote_state = result['state']
        if remote_state in ('success', 'failed'):
            history = Path(data.record_dir) / data.history_name
            if not history.exists():
                client.write_new(history, {'time': client.now(), 'data': result})
            if remote_state == 'failed':
                self.save(key, status='failed', error='ComfyUI确认执行失败；详情见终态附件', progress=None)
            else:
                self.save(key, status='collecting', error=None, progress=None)
                try:
                    await self.collect(key, result)
                except (client.ClientError, OSError, ValueError) as error:
                    logger.warning('ComfyUI task %s collection failed: %s', key, error)
                    self.save(key, status='collection_failed', error=str(error))
            return True
        if remote_state == 'unknown':
            self.save(key, status='needs_attention', error='history及queue均无法确认任务；停止自动处理，请核对原任务')
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
        try:
            while True:
                try:
                    if socket is None:
                        socket = await connect(self.ws_url(data, state['client_id']), open_timeout=data.timeout, max_size=2**22)
                    self.save(key, connection='connected')
                    if await self.reconcile(key):
                        break
                    while True:
                        try:
                            raw = await asyncio.wait_for(socket.recv(), 300)
                        except asyncio.TimeoutError:
                            if await self.reconcile(key):
                                break
                            continue
                        if not isinstance(raw, str):
                            continue  # Binary preview frames are not task completion evidence.
                        message = json.loads(raw)
                        event, payload = message['type'], message['data']
                        if payload.get('prompt_id') != state['prompt_id']:
                            continue
                        if event == 'progress':
                            self.save(key, status='running', progress={'value': payload['value'], 'max': payload['max']})
                        elif event == 'executing' and payload.get('node') is not None:
                            self.save(key, status='running', node=str(payload['node']), progress=None)
                        elif event in ('execution_success', 'execution_error', 'execution_interrupted') or (
                                event == 'executing' and payload.get('node') is None):
                            if await self.reconcile(key):
                                break
                    if state['status'] in ('completed', 'failed', 'needs_attention', 'collection_failed'):
                        break
                except (OSError, WebSocketException, client.ClientError, asyncio.TimeoutError) as error:
                    logger.warning('ComfyUI task %s connection interrupted: %s', key, type(error).__name__)
                    self.save(key, connection='reconnecting', error='连接中断，正在恢复；不代表生成失败')
                    if socket is not None:
                        await socket.close()
                        socket = None
                    await asyncio.sleep(5)
        except (ValueError, KeyError, TypeError) as error:
            logger.exception('ComfyUI task %s protocol error', key)
            self.save(key, status='needs_attention', error='远端消息或证据格式异常：' + str(error))
        finally:
            if socket is not None:
                await socket.close()
        self.save(key, connection='closed')
        await self.notify(key)

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
        row = self.rows[key]
        data, state = row['input'], row['state']
        if state['notification'] in ('sent', 'sending', 'delivery_unknown'):
            return
        while True:
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
            break
        outputs = '\n'.join(output.path for output in data.outputs)
        prompt = (f'ComfyUI任务通知。事件ID：{key}；项目：{state["project"]}；任务：{data.title}；'
                  f'prompt_id：{state["prompt_id"]}；状态：{state["status"]}。\n'
                  f'执行附件：{data.record_dir}\n登记的成果路径（以下载证据为准）：\n{outputs}\n'
                  '请先核对该事件是否已处理、现有授权和执行附件，再按主技能的任务监控规范维护原业务记录并汇报。'
                  '传输成功不代表素材获批；不得因此提交新任务、启动下一阶段或重提状态不明任务。')
        self.save(key, notification='sending')
        try:
            await self.desktop_call(data, 'send', prompt)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.save(key, notification='delivery_unknown')
        else:
            self.save(key, notification='sent')
