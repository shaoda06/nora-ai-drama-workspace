"""Workspace-wide ComfyUI endpoint configuration; never persist credentials in tasks."""
import hashlib
import importlib.util
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'references/comfyui-scripts'))
import comfyui_client as client


def workspace_for_project(project):
    project = Path(project).resolve()
    if project.parent.name != 'projects':
        raise ValueError('项目必须位于工作区的projects目录下')
    return project.parent.parent


def load_config(workspace, *, missing_ok=False):
    path = Path(workspace) / 'comfyui-config.json'
    try:
        data = client.strict_json(path.read_bytes())
    except FileNotFoundError:
        if missing_ok:
            return []
        raise client.ClientError('missing_config', '工作区根目录缺少comfyui-config.json') from None
    except (ValueError, UnicodeError):
        raise client.ClientError('invalid_config', '工作区ComfyUI配置不是有效JSON') from None
    if not isinstance(data, dict):
        raise client.ClientError('invalid_config', 'ComfyUI配置必须为对象')
    # Compatibility is restricted to the workspace file, never project overrides.
    if set(data) == {'remote-url'}:
        data = {'remote-urls': [data['remote-url']]}
    if set(data) == {'remote-urls'} and isinstance(data['remote-urls'], list):
        data = {'remote-nodes': [{'url': url} for url in data['remote-urls']]}
    if set(data) != {'remote-nodes'} or not isinstance(data['remote-nodes'], list) or not data['remote-nodes']:
        raise client.ClientError('invalid_config', '配置需要非空remote-nodes数组')
    nodes = []
    for item in data['remote-nodes']:
        if not isinstance(item, dict) or set(item) - {'url', 'auth'} or not isinstance(item.get('url'), str):
            raise client.ClientError('invalid_config', '节点只允许url和可选auth字段')
        url = client.Client(item['url'], 30).url
        auth = item.get('auth')
        if auth is not None:
            if (not isinstance(auth, dict) or set(auth) != {'type', 'username', 'password'}
                    or auth['type'] != 'basic' or not isinstance(auth['username'], str)
                    or not isinstance(auth['password'], str) or ':' in auth['username']
                    or any(ord(c) < 32 or ord(c) == 127 for c in auth['username'] + auth['password'])):
                raise client.ClientError('invalid_config', 'auth需要basic类型及有效username、password')
        nodes.append({'url': url, **({'auth': dict(auth)} if auth is not None else {})})
    if len({node['url'] for node in nodes}) != len(nodes):
        raise client.ClientError('invalid_config', 'ComfyUI节点地址重复')
    return nodes


def remote_urls(workspace, *, missing_ok=False):
    return [node['url'] for node in load_config(workspace, missing_ok=missing_ok)]


def endpoint(workspace, url):
    url = client.Client(url, 30).url
    return next((node for node in load_config(workspace, missing_ok=True) if node['url'] == url), {'url': url})


def client_for(workspace, url, timeout):
    auth = endpoint(workspace, url).get('auth')
    if auth is None:
        return client.Client(url, timeout)
    if not auth['username'] or not auth['password']:
        raise client.ClientError('missing_auth', '请在工作区comfyui-config.json填写该节点的username和password')
    return client.Client(url, timeout, basic_auth=(auth['username'], auth['password']))


def connection_key(workspace, url):
    """Private digest lets observers reconnect when only credentials change."""
    return hashlib.sha256(client.encoded(endpoint(workspace, url))).hexdigest()


def main(argv=None):
    """Authorized diagnostics and cache operations; generation uses comfyui_dispatch."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--workspace', required=True, help='Workspace root containing comfyui-config.json')
    args, remaining = parser.parse_known_args(argv)
    factory = lambda url, timeout: client_for(args.workspace, url, timeout)
    tool_paths = {
        'inventory': 'dependencies/comfyui-inventory/scripts/refresh_inventory.py',
        'cache-clone': 'references/comfyui-scripts/director_cache.py',
    }
    if remaining and remaining[0] in tool_paths:
        path = Path(__file__).resolve().parents[1] / tool_paths[remaining[0]]
        spec = importlib.util.spec_from_file_location('nora_' + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if remaining[0] == 'cache-clone':
            return module.main(remaining[1:], client_factory=factory)

        def authenticated_fetch(url, route, timeout):
            try:
                return factory(url, timeout).json(route)
            except client.ClientError as error:
                # The independent inventory callback reports network failures as OSError.
                raise OSError(str(error)) from error

        return module.main(remaining[1:], fetcher=authenticated_fetch, require_url=True)
    return client.main(remaining, client_factory=factory,
                       allowed_commands=('status', 'download', 'export-pack'), require_url=True)


if __name__ == '__main__':
    sys.exit(main())
