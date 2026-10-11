"""Agent-side handoff to the workspace browser backend; no independent monitor."""
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request


def submit(args, workflow, url, uploads=None):
    from project_paths import project_file, relative_file
    project = Path(args.project).resolve()
    service = project.parent.parent / '工作区浏览服务'
    config = json.loads((service / 'runtime/task-service.json').read_text('utf-8'))
    # Use genuine caller context inherited from Desktop, never a fabricated caller.
    caller = os.environ.get('CODEX_THREAD_ID')
    pipe = os.environ.get('CODEX_APP_TOOLS_PIPE_PATH')
    if not caller or not pipe:
        raise ValueError('浏览服务监控缺少Codex真实连接上下文；未提交，请在Codex中调用')
    node = shutil.which('node')
    servers = list((Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) /
                    'plugins/cache/openai-bundled/codex-app-tools').glob('*/server.mjs'))
    if not node or not servers:
        raise ValueError('缺少Node或Codex桌面适配器；未提交')
    payload = {name: getattr(args, name) for name in
               ('project', 'task_type', 'record_dir', 'attempt_name', 'request_name', 'response_name', 'history_name', 'timeout')}
    payload.update(project=project.name, record_dir=relative_file(project, project_file(project, args.record_dir)),
        workflow=workflow, url=url, title=args.task_title, uploads=uploads or [], start_paused=args.start_paused,
        outputs=json.loads(Path(args.output_plan).read_text('utf-8')),
        segment_plan=json.loads(Path(args.segment_plan).read_text('utf-8')) if args.segment_plan else None,
        thread_id=args.thread_id or caller,
        desktop={'node': node, 'server': str(max(servers, key=lambda path: path.stat().st_mtime)),
                 'pipe': pipe, 'caller_thread': caller})
    for output in payload['outputs']:
        output['path'] = relative_file(project, output['path'])
    for upload in payload['uploads']:
        upload['file'] = relative_file(project, upload['file'])
    if payload['segment_plan']:
        for target in payload['segment_plan']['targets']:
            target['path'] = relative_file(project, target['path'])
    request = urllib.request.Request(config['url'] + '/api/internal/comfy/submit',
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-nora-task-token': config['token']})
    # Bypass system proxies for local service. Never retry a possibly accepted POST.
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2 * args.timeout + 15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = json.load(error).get('detail')
        raise ValueError('本地入队未成功，检查后台任务状态：' + str(detail)) from error


def service_call(route, payload=None):
    service = Path(__file__).resolve().parents[4] / '工作区浏览服务'
    config = json.loads((service / 'runtime/task-service.json').read_text('utf-8'))
    request = urllib.request.Request(config['url'] + '/api/internal/comfy/' + route,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None,
        headers={'Content-Type': 'application/json', 'x-nora-task-token': config['token']})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(str(json.load(error).get('detail'))) from error


def main():
    import argparse
    parser = argparse.ArgumentParser(description='查询后台任务、请求重试取回或确认收到通知；不会重新生成')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('status', 'retry-collection'):
        item = commands.add_parser(command)
        item.add_argument('--task-id', required=True, help='Backend local UUID, not remote prompt_id')
    item = commands.add_parser('ack')
    item.add_argument('--notification-id', required=True, help='Notification batch UUID from received message')
    args = parser.parse_args()
    if args.command == 'ack':
        thread = os.environ.get('CODEX_THREAD_ID')
        if not thread:
            raise ValueError('通知确认必须在真实来源会话内调用')
        result = service_call('notifications/' + args.notification_id + '/ack', {'thread_id': thread})
    else:
        result = service_call('tasks/' + args.task_id + ('/retry-collection' if args.command == 'retry-collection' else ''),
                              {} if args.command == 'retry-collection' else None)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
