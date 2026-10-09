"""Agent-side handoff to the workspace browser backend; no independent monitor."""
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request


def submit(args, workflow, url):
    project = Path(args.project).resolve()
    service = project.parent.parent / '工作区浏览服务'
    config = json.loads((service / 'runtime/task-service.json').read_text('utf-8'))
    # Use genuine caller context inherited from Desktop, never a fabricated caller.
    caller = os.environ.get('CODEX_THREAD_ID')
    pipe = os.environ.get('CODEX_APP_TOOLS_PIPE_PATH')
    if not caller or not pipe:
        raise ValueError('浏览服务监控缺少Codex真实连接上下文；未提交，请在Codex中调用或明确使用legacy模式')
    node = shutil.which('node')
    servers = list((Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) /
                    'plugins/cache/openai-bundled/codex-app-tools').glob('*/server.mjs'))
    if not node or not servers:
        raise ValueError('缺少Node或Codex桌面适配器；未提交')
    payload = {name: getattr(args, name) for name in
               ('project', 'task_type', 'record_dir', 'attempt_name', 'request_name', 'response_name', 'history_name', 'timeout')}
    payload.update(project=str(project), record_dir=str(Path(args.record_dir).resolve()),
        workflow=workflow, url=url, title=args.task_title or Path(args.record_dir).name,
        outputs=json.loads(Path(args.output_plan).read_text('utf-8')),
        segment_plan=json.loads(Path(args.segment_plan).read_text('utf-8')) if args.segment_plan else None,
        thread_id=args.thread_id or caller,
        desktop={'node': node, 'server': str(max(servers, key=lambda path: path.stat().st_mtime)),
                 'pipe': pipe, 'caller_thread': caller})
    request = urllib.request.Request(config['url'] + '/api/internal/comfy/submit',
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-nora-task-token': config['token']})
    # Bypass system proxies for local service. Never retry a possibly accepted POST.
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2 * args.timeout + 15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = json.load(error).get('detail')
        raise ValueError('浏览服务提交未成功，先检查原证据，禁止直接重试：' + str(detail)) from error
