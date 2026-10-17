"""Edit the one workspace configuration without changing task records."""
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, SecretStr
from backend.services.comfy_tasks import config


class NodeEdit(BaseModel):
    url: str
    original_url: str | None = None
    auth_mode: Literal['keep', 'none', 'basic'] = 'none'
    username: SecretStr = SecretStr('')
    password: SecretStr = SecretStr('')


class ConfigEdit(BaseModel):
    revision: str | None
    nodes: list[NodeEdit]


class ConfigConflict(ValueError):
    pass


def file_revision(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return f'{stat.st_mtime_ns}:{stat.st_size}'


def read_config(store):
    path = store.workspace / 'comfyui-config.json'
    revision = file_revision(path)
    nodes = config.load_config(store.workspace, missing_ok=True)
    if file_revision(path) != revision:
        raise ConfigConflict('配置正在被修改，请重新载入')
    return nodes, revision


def protected_urls(store):
    statuses = ('local_queued', 'paused', 'preparing', 'submitting', 'queued', 'running',
                'collecting', 'collection_failed', 'needs_attention', 'submission_unknown')
    return {row['input'].url.rstrip('/') for row in store.rows.values() if row['state']['status'] in statuses} | {
        url for url, state in store.remote_queues.states.items() if state['queue']}


def snapshot(store, nodes, revision, *, credentials=False):
    protected = protected_urls(store)
    return {'revision': revision, 'nodes': [
        {'url': node['url'], 'has_auth': 'auth' in node, 'locked': node['url'] in protected,
         **({'username': node.get('auth', {}).get('username', ''),
             'password': node.get('auth', {}).get('password', '')} if credentials else {})} for node in nodes]}


def save_config(store, edit, *, credentials=False):
    current, revision = read_config(store)
    if edit.revision != revision:
        raise ConfigConflict('配置已被Agent或其他页面修改，请重新载入后再保存')
    originals = {node['url']: node for node in current}
    nodes = []
    for item in edit.nodes:
        url = config.client.Client(item.url.strip(), 30).url
        node = {'url': url}
        if item.auth_mode == 'keep':
            original = originals.get(item.original_url)
            if original is None or original['url'] != url or 'auth' not in original:
                raise ValueError('修改已认证节点的地址时，请重新填写认证信息或选择无需认证')
            node['auth'] = original['auth']
        elif item.auth_mode == 'basic':
            username, password = item.username.get_secret_value(), item.password.get_secret_value()
            if not username or not password:
                raise ValueError('Basic认证需要填写账号和密码')
            node['auth'] = {'type': 'basic', 'username': username, 'password': password}
        nodes.append(node)
    nodes = config.validate_config({'remote-nodes': nodes})
    removed = set(originals) - {node['url'] for node in nodes}
    if removed & protected_urls(store):
        raise ConfigConflict('该节点有未结束、取回待处理或待核对任务，暂不能删除或替换地址；可以调整排序')
    path = store.workspace / 'comfyui-config.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.comfyui-config-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'remote-nodes': nodes}, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if file_revision(path) != revision:
            raise ConfigConflict('配置已被Agent或其他页面修改，请重新载入后再保存')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    store.remote_queues.config_changed.set()
    store.publish()
    return snapshot(store, nodes, file_revision(path), credentials=credentials)
