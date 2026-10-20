"""Agent-side handoff to the workspace browser backend; no independent monitor."""
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request


def connection(args):
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
    desktop = {'node': node, 'server': str(max(servers, key=lambda path: path.stat().st_mtime)),
               'pipe': pipe, 'caller_thread': caller, 'cli': os.environ.get('CODEX_CLI_PATH') or shutil.which('codex')}
    return project, config, args.thread_id or caller, desktop


def submit_plan(args):
    project, config, thread, desktop = connection(args)
    plan = Path(args.plan)
    # The one plan parameter is project-relative, like all files inside its task entries.
    plan = plan.resolve() if plan.is_absolute() else (project / plan).resolve()
    payload = dict(project=project.name, plan_file=plan.relative_to(project).as_posix(), thread_id=thread,
                   desktop=desktop, timeout=args.timeout, prepare_only=args.prepare_only,
                   reprepare=getattr(args, 'reprepare', False), start_paused=args.start_paused)
    return local_post(config, '/submit-plan', payload, args.timeout)


def submit(args, workflow, url, uploads=None):
    project, config, thread, desktop = connection(args)
    payload = {name: getattr(args, name) for name in
               ('project', 'task_type', 'record_dir', 'attempt_name', 'request_name', 'response_name', 'history_name', 'timeout')}
    payload.update(project=project.name, record_dir=args.record_dir,
        workflow=workflow, url=url, title=args.task_title, uploads=[] if uploads is None else uploads, start_paused=args.start_paused,
        outputs=json.loads(Path(args.output_plan).read_text('utf-8')),
        segment_plan=json.loads(Path(args.segment_plan).read_text('utf-8')) if args.segment_plan else None,
        thread_id=thread, desktop=desktop)
    if getattr(args, 'image_plan', None):
        payload['image_plan'] = json.loads(Path(args.image_plan).read_text('utf-8-sig'))
    preparing = getattr(args, 'prepare_only', False)
    route = '/prepare' if preparing else '/submit'
    return local_post(config, route, payload, args.timeout)


def local_post(config, route, payload, timeout):
    request = urllib.request.Request(config['url'] + '/api/internal/comfy' + route,
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-nora-task-token': config['token']})
    # Bypass system proxies for local service. Never retry a possibly accepted POST.
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2 * timeout + 15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = json.load(error).get('detail')
        raise ValueError(('准备检查失败：' if route == '/prepare' else '本地入队未成功，检查后台任务状态：') + str(detail)) from error


def service_call(route, payload=None):
    service = Path(__file__).resolve().parents[4] / '工作区浏览服务'
    config = json.loads((service / 'runtime/task-service.json').read_text('utf-8'))
    request = urllib.request.Request(config['url'] + '/api/internal/comfy/' + route,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None,
        headers={'Content-Type': 'application/json', 'x-nora-task-token': config['token']})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as response:
            result = json.load(response)
        for item in result.get('delivery', {}).get('tasks', []):
            item['review_url'] = config['url'] + item['review_path']
        return result
    except urllib.error.HTTPError as error:
        raise ValueError(str(json.load(error).get('detail'))) from error


def main():
    import argparse
    parser = argparse.ArgumentParser(description='读取后台最终报告并自动确认收到、查询异常或重试原任务取回；不会重新生成')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('status', 'retry-collection'):
        item = commands.add_parser(command)
        item.add_argument('--task-id', required=True, help='Backend local UUID, not remote prompt_id')
    for name in ('report', 'ack', 'register-results'):
        item = commands.add_parser(name, help={'report': '读取现成报告并自动确认收到；正常完成只需此命令',
            'ack': '兼容旧通知的独立确认；正常完成不用', 'register-results': '显式修复待审登记或兼容旧任务；正常完成由后台自动执行'}[name])
        item.add_argument('--notification-id', required=True, help='Notification batch UUID from received message')
        if name == 'register-results':
            item.add_argument('--image-plans', help='Explicit legacy repair only: JSON object from local task UUID to its image closeout plan; cannot replace an accepted association')
            item.add_argument('--record-updates', help='UTF-8 JSON array of exact path/old/new updates for this batch progress or production checks; paths relative to the project')
    commands.choices['report'].add_argument('--details', action='store_true', help='显式读取完整报告；正常图片／视频报告只返回成果、数量和审核入口，异常自动保留完整报告')
    item = commands.add_parser('resolve', help='Close an investigated needs_attention task; preserve its original exception')
    item.add_argument('--task-id', required=True, help='Backend local UUID, not remote prompt_id')
    item.add_argument('--resolution', required=True, help='UTF-8 JSON resolution file with original prompt ID, evidence and replacement IDs')
    args = parser.parse_args()
    if args.command in ('report', 'ack', 'register-results'):
        thread = os.environ.get('CODEX_THREAD_ID')
        if not thread:
            raise ValueError('通知确认必须在真实来源会话内调用')
        payload = {'thread_id': thread}
        if args.command == 'register-results' and args.record_updates:
            payload['record_updates'] = json.loads(Path(args.record_updates).read_text('utf-8-sig'))
        if args.command == 'register-results' and args.image_plans:
            payload['image_plans'] = json.loads(Path(args.image_plans).read_text('utf-8-sig'))
        result = service_call('notifications/' + args.notification_id + '/' + args.command, payload)
        if args.command == 'report' and not args.details and result.get('user_message_ready') and result.get('delivery') is not None:
            result = {name: result[name] for name in ('notification_id', 'status', 'reused', 'user_message_ready', 'delivery')}
    elif args.command == 'resolve':
        result = service_call('tasks/' + args.task_id + '/resolve',
                              json.loads(Path(args.resolution).read_text('utf-8-sig')))
    else:
        result = service_call('tasks/' + args.task_id + ('/retry-collection' if args.command == 'retry-collection' else ''),
                              {} if args.command == 'retry-collection' else None)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
