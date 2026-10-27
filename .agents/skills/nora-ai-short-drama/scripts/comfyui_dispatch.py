#!/usr/bin/env python3
"""Submit authorized tasks as one group with --plan; remote execution remains per task."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'references' / 'comfyui-scripts'))
import comfyui_client as client
import browser_tasks
import comfyui_config as config

TASK_TYPES = ('image', 'image-upscale', 'video-first-pass', 'video-second-pass', 'video-postprocess')
VIDEO_TASK_TYPES = ('video-first-pass', 'video-second-pass')
VIDEO_CONTEXT_TASK_TYPES = (*VIDEO_TASK_TYPES, 'video-postprocess')


def load_config(project, timeout):
    return {'remote-urls': config.remote_urls(config.workspace_for_project(project))}


def dispatch(args):
    if getattr(args, 'record_repairs', None) and (not args.plan or args.prepare_only or args.reprepare or args.start_paused):
        raise ValueError('--record-repairs只与原--plan合用，仅接续本地成果登记，不准备或生成')
    if getattr(args, 'reprepare', False) and (not args.plan or not args.prepare_only):
        raise ValueError('--reprepare必须与--plan和--prepare-only一起使用；只重新准备，不入队')
    if getattr(args, 'plan', None):
        return browser_tasks.submit_plan(args)
    for name in ('task_type', 'workflow', 'record_dir', 'task_title'):
        if not getattr(args, name, None):
            raise ValueError('旧式参数入口缺少--' + name.replace('_', '-'))
    if not args.output_plan:
        raise ValueError('入队需要--output-plan；导演台提供空数组及--segment-plan')
    if args.task_type in ('image', 'image-upscale') and not getattr(args, 'image_plan', None):
        raise ValueError('图片及超分入队需要--image-plan，先明确后台收尾关联')
    workflow = client.strict_json(Path(args.workflow).read_bytes())
    uploads = client.strict_json(Path(args.uploads).read_bytes()) if args.uploads else []
    url = load_config(args.project, args.timeout)['remote-urls'][0]
    if args.eligible_url and client.Client(args.eligible_url, args.timeout).url != url:
        raise ValueError('指定的地址不是工作区主节点')
    result = browser_tasks.submit(args, workflow, url, uploads=uploads)
    return {'dispatch_state': 'prepared' if getattr(args, 'prepare_only', False) else 'enqueued', 'url': url, **result}


def parser():
    p = client.Parser(description=__doc__)
    p.add_argument('--project', required=True, help='Project root under workspace/projects; relative to cwd; uses workspace comfyui-config.json')
    p.add_argument('--plan', help='Default submission: one task-group JSON for all ready tasks in this authorization, not one call per scene/segment; project-relative or absolute: optional group_title plus tasks (one or more); checks all members, atomically registers one group, returns group_id and child IDs; --prepare-only never registers')
    p.add_argument('--record-repairs', help='Existing local image results only: JSON object from record_dir to reason/expected_updates/updates; never runs image processing or queues tasks')
    p.add_argument('--task-type', choices=TASK_TYPES, help='Compatibility for existing tasks or an explicitly independent single task; use --plan for grouped submissions')
    p.add_argument('--workflow', help='Legacy prepared-input mode only: prepared API JSON')
    p.add_argument('--eligible-url', help='Optional expected primary address; identity check only, no capability probe')
    p.add_argument('--uploads', help='Optional upload bindings; file paths relative to the project root')
    p.add_argument('--prepare-only', action='store_true', help='Tool checks and writes 执行检查报告.json; no upload, queue entry or generation POST')
    p.add_argument('--reprepare', action='store_true', help='With --plan --prepare-only: archive and rebuild an unregistered local preparation in place; registered tasks and concurrent edits are rejected; no upload or generation')
    p.add_argument('--record-dir', help='Legacy prepared-input mode: evidence directory relative to project; video tasks require 输入映射.json')
    p.add_argument('--attempt-name', default='submit-attempt.json', help='Exclusive attempt evidence filename')
    p.add_argument('--request-name', default='request.json', help='Actual request evidence filename')
    p.add_argument('--response-name', default='response.json', help='Actual submission response filename')
    p.add_argument('--timeout', type=float, default=30, help='Seconds per network operation, not task duration; no retries')
    p.add_argument('--monitor', choices=('browser',), default='browser', help='Persistent backend queue; Agent does not upload or submit remotely')
    p.add_argument('--start-paused', action='store_true', help='Register paused for an authorized manual transfer; default is automatic local queueing, with no remote submission until resumed')
    p.add_argument('--output-plan', help='JSON output selectors and project-relative local targets; H3 segments use [] plus --segment-plan')
    p.add_argument('--image-plan', help='Image/image-upscale closeout JSON: draft, generation, review, kind, formal, images; formal binds candidate identity (style samples declare image_type instead). Approved processing also supplies source, approval, formal and record_updates. Paths relative to project; backend finishes before notification')
    p.add_argument('--segment-plan', help='Native H3 plan; targets specify index, project-relative path and response_name; output_root belongs to the remote server')
    p.add_argument('--history-name', default='执行结果.json', help='Terminal history evidence filename inside record-dir; use the project-required prefix for image tasks')
    p.add_argument('--task-title', help='Legacy prepared-input mode: object number plus short description')
    p.add_argument('--thread-id', help='Authorized destination Codex thread; defaults to genuine CODEX_THREAD_ID; never changes model settings')
    return p


def main(argv=None):
    try:
        data = dispatch(parser().parse_args(argv))
        success = data.get('status') not in ('partial', 'failed')
        result = {'ok': success, 'time': client.now(), 'data': data}
        code = 0 if success else 1
    except (client.ClientError, OSError, ValueError) as exc:
        result = {'ok': False, 'time': client.now(), 'error': {
            'code': exc.code if isinstance(exc, client.ClientError) else type(exc).__name__,
            'message': str(exc), **(exc.details if isinstance(exc, client.ClientError) else {})}}
        code = 1
    sys.stdout.buffer.write(client.encoded(result))
    return code


if __name__ == '__main__':
    sys.exit(main())
