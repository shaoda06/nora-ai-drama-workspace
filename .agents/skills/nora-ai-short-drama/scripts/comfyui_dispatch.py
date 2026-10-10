#!/usr/bin/env python3
"""Submit one authorized Nora task using the project's primary ComfyUI endpoint."""
import argparse
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'references' / 'comfyui-scripts'))
import comfyui_client as client
from generation_context import prepare_generation_context
import browser_tasks

TASK_TYPES = ('image', 'image-upscale', 'video-first-pass', 'video-second-pass', 'video-postprocess')
VIDEO_TASK_TYPES = ('video-first-pass', 'video-second-pass')
VIDEO_CONTEXT_TASK_TYPES = (*VIDEO_TASK_TYPES, 'video-postprocess')
VIDEO_GENERATION_NODES = {'MiniMaxH3Director', 'MiniMaxH3ReferenceToVideo'}
LOCK_PATH = Path(__file__).resolve().parents[1] / 'state' / 'comfyui-dispatch.lock'


def load_config(project, timeout):
    data = client.strict_json((Path(project) / 'comfyui-config.json').read_bytes())
    if not isinstance(data, dict):
        raise client.ClientError('invalid_config', 'Configuration must be a JSON object')
    if set(data) == {'remote-url'}:
        data = {'remote-urls': [data['remote-url']]}
    if set(data) != {'remote-urls'}:
        raise client.ClientError('invalid_config', 'Expected only remote-urls')
    urls = data['remote-urls']
    if not isinstance(urls, list) or not urls or any(not isinstance(url, str) for url in urls):
        raise client.ClientError('invalid_config', 'Invalid endpoint list')
    data['remote-urls'] = [client.Client(url, timeout).url for url in urls]
    if len(set(data['remote-urls'])) != len(urls):
        raise client.ClientError('invalid_config', 'Endpoint list contains duplicate addresses')
    return data


@contextmanager
def submission_lock():
    # Coordinates local sessions using this skill; no queue deletion or remote locks.
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            acquire = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise client.ClientError('dispatcher_busy', 'Another local submission is in progress; try later') from exc
            raise
        try:
            yield
        finally:
            stream.seek(0)
            release()


def dispatch(args):
    if args.monitor == 'browser' and not args.output_plan:
        raise ValueError('浏览服务监控需要--output-plan；无可自动取回输出时显式提供空数组JSON')
    workflow = client.strict_json(Path(args.workflow).read_bytes())
    client.validate_workflow(workflow)
    if args.segment_plan and args.monitor != 'browser':
        raise ValueError('--segment-plan由浏览服务统一处理，不用于legacy模式')
    if args.monitor == 'browser' and any(node['class_type'] == 'MiniMaxH3Director'
            and client.strict_json(node['inputs']['timeline_data']).get('output', {}).get('exportMode') == 'segments'
            for node in workflow.values()) and not args.segment_plan:
        raise ValueError('原生H3分段任务需要--segment-plan；由浏览服务逐段取回，不另开旧监控')
    if (any(node['class_type'] in VIDEO_GENERATION_NODES for node in workflow.values()) and
            args.task_type not in VIDEO_TASK_TYPES):
        raise client.ClientError('invalid_task_type', 'H3 generation requires a first-pass or second-pass task type')
    uploads = client.strict_json(Path(args.uploads).read_bytes()) if args.uploads else []
    if not isinstance(uploads, list):
        raise client.ClientError('invalid_uploads', 'Upload map must be an array')
    record = Path(args.record_dir).resolve()
    names = (args.attempt_name, args.request_name, args.response_name)
    for name in names:
        client.remote_path(name, filename=True)
    if len(set(names)) != 3:
        raise client.ClientError('path_collision', 'Submission filenames must be distinct')
    # Check before uploading; generic submit repeats its own exclusive evidence check.
    if any(os.path.lexists(record / name) for name in names):
        raise client.ClientError('submission_guard', 'Existing evidence: follow the original task, do not dispatch again')
    for item in uploads:
        if (not isinstance(item, dict) or set(item) != {'file', 'node', 'input', 'subfolder', 'response-name'} or
                item['node'] not in workflow or item['input'] not in workflow[item['node']]['inputs']):
            raise client.ClientError('invalid_uploads', 'Each upload must target an existing node input')
        Path(item['file']).resolve(strict=True)
        client.remote_path(item['subfolder'])
        client.remote_path(item['response-name'], filename=True)
    evidence_names = list(names) + [item['response-name'] for item in uploads]
    if len(evidence_names) != len(set(evidence_names)):
        raise client.ClientError('path_collision', 'Upload and submission evidence must have distinct names')
    with submission_lock():
        config = load_config(args.project, args.timeout)
        url = config['remote-urls'][0]
        if client.Client(args.eligible_url, args.timeout).url != url:
            raise client.ClientError('invalid_eligibility', 'Verify the project primary endpoint before submission')
        remote = client.Client(url, args.timeout)
        for item in uploads:
            response_path = record / item['response-name']
            # Reserve the response before upload; never re-upload an ambiguous attempt.
            if response_path.exists():
                evidence = client.strict_json(response_path.read_bytes())
                if evidence.get('url') != url or evidence.get('ok') is not True:
                    raise client.ClientError('upload_guard', 'Reconcile existing upload evidence before continuing')
                uploaded = evidence['data']
            else:
                response_path.parent.mkdir(parents=True, exist_ok=True)
                with response_path.open('xb') as stream:
                    try:
                        uploaded = client.upload(remote, argparse.Namespace(file=item['file'], subfolder=item['subfolder']))
                    except client.ClientError as exc:
                        stream.write(client.encoded({'ok': False, 'url': url, 'time': client.now(), 'error': str(exc)}))
                        raise
                    stream.write(client.encoded({'ok': True, 'url': url, 'time': client.now(), 'data': uploaded}))
            workflow[item['node']]['inputs'][item['input']] = uploaded['input_path']
        if args.task_type in VIDEO_CONTEXT_TASK_TYPES:
            try:
                prepare_generation_context(args.project, record, workflow, args.task_type)
            except KeyError as exc:
                raise ValueError('生成资料输入映射或API缺少字段：' + str(exc)) from exc
        # Once a POST is attempted, errors propagate: never retry or change endpoints.
        result = (browser_tasks.submit(args, workflow, url) if args.monitor == 'browser'
                  else client.submit(remote, args, workflow=workflow))
        return {'dispatch_state': 'accepted', 'url': url, **result}


def parser():
    p = client.Parser(description=__doc__)
    p.add_argument('--project', required=True, help='Project root containing comfyui-config.json; relative to cwd')
    p.add_argument('--task-type', required=True, choices=TASK_TYPES, help='Authorized task stage; all tasks use the project primary endpoint')
    p.add_argument('--workflow', required=True, help='Prepared API JSON; unchanged except declared uploaded input paths')
    p.add_argument('--eligible-url', required=True, help='Verified primary endpoint; must match the first project address')
    p.add_argument('--uploads', help='Optional JSON array of local files and loader bindings; paths relative to cwd')
    p.add_argument('--record-dir', required=True, help='Existing business evidence directory; video tasks require 输入映射.json and automatically save generation inputs before POST')
    p.add_argument('--attempt-name', default='submit-attempt.json', help='Exclusive attempt evidence filename')
    p.add_argument('--request-name', default='request.json', help='Actual request evidence filename')
    p.add_argument('--response-name', default='response.json', help='Actual submission response filename')
    p.add_argument('--timeout', type=float, default=30, help='Seconds per network operation, not task duration; no retries')
    p.add_argument('--monitor', choices=('browser', 'legacy'), default='browser', help='browser: hand off submit/monitor/download to running workspace service (default); legacy: explicit original polling/heartbeat path')
    p.add_argument('--output-plan', help='JSON array of explicit output selectors and absolute local targets; required for browser mode; H3 segments use [] plus --segment-plan')
    p.add_argument('--segment-plan', help='Native H3 segments JSON with director_node, report_node and verified output_root; per-segment targets come from 输入映射.json')
    p.add_argument('--history-name', default='执行结果.json', help='Terminal history evidence filename inside record-dir; use the project-required prefix for image tasks')
    p.add_argument('--task-title', help='Human-readable title shown in the global read-only task sidebar; defaults to record directory name')
    p.add_argument('--thread-id', help='Authorized destination Codex thread; defaults to genuine CODEX_THREAD_ID; never changes model settings')
    return p


def main(argv=None):
    try:
        data = dispatch(parser().parse_args(argv))
        result = {'ok': True, 'time': client.now(), 'data': data}
        code = 0
    except (client.ClientError, OSError, ValueError) as exc:
        result = {'ok': False, 'time': client.now(), 'error': {
            'code': exc.code if isinstance(exc, client.ClientError) else type(exc).__name__,
            'message': str(exc), **(exc.details if isinstance(exc, client.ClientError) else {})}}
        code = 1
    sys.stdout.buffer.write(client.encoded(result))
    return code


if __name__ == '__main__':
    sys.exit(main())
