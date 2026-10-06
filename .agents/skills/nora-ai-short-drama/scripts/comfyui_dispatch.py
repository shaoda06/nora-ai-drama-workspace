#!/usr/bin/env python3
"""Submit one authorized Nora task using the project's ordered ComfyUI endpoints."""
import argparse
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'references' / 'comfyui-scripts'))
import comfyui_client as client
from generation_context import prepare_generation_context

TASK_TYPES = ('image', 'image-upscale', 'video-first-pass', 'video-second-pass', 'video-postprocess')
VIDEO_TASK_TYPES = ('video-first-pass', 'video-second-pass')
DEFAULT_ONLY_TASK_TYPES = (*VIDEO_TASK_TYPES, 'video-postprocess')
VIDEO_GENERATION_NODES = {'MiniMaxH3Director', 'MiniMaxH3ReferenceToVideo'}
LOCK_PATH = Path(__file__).resolve().parents[1] / 'state' / 'comfyui-dispatch.lock'


def load_config(project, timeout):
    data = client.strict_json((Path(project) / 'comfyui-config.json').read_bytes())
    if not isinstance(data, dict):
        raise client.ClientError('invalid_config', 'Configuration must be a JSON object')
    if set(data) == {'remote-url'}:
        data = {'enable-multi-remote': False, 'remote-urls': [data['remote-url']],
                'busy-pending-threshold': 2, 'default-only-task-types': list(DEFAULT_ONLY_TASK_TYPES)}
    required = {'enable-multi-remote', 'remote-urls', 'busy-pending-threshold', 'default-only-task-types'}
    if set(data) != required:
        raise client.ClientError('invalid_config', 'Expected the four project dispatch fields')
    urls, threshold, pinned = data['remote-urls'], data['busy-pending-threshold'], data['default-only-task-types']
    if (type(data['enable-multi-remote']) is not bool or not isinstance(urls, list) or not urls or
            any(not isinstance(url, str) for url in urls) or type(threshold) is not int or threshold < 1 or
            not isinstance(pinned, list) or any(kind not in TASK_TYPES for kind in pinned)):
        raise client.ClientError('invalid_config', 'Invalid endpoint list, switch, threshold or task types')
    data['remote-urls'] = [client.Client(url, timeout).url for url in urls]
    if len(set(data['remote-urls'])) != len(urls):
        raise client.ClientError('invalid_config', 'Endpoint list contains duplicate addresses')
    data['default-only-task-types'] = list(dict.fromkeys([*DEFAULT_ONLY_TASK_TYPES, *pinned]))
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


def video_job_count(queue):
    count = 0
    for item in queue['queue_pending'] + queue['queue_running']:
        # ComfyUI queue entries: [number, prompt_id, prompt, extra_data, outputs...].
        if (not isinstance(item, list) or len(item) < 3 or not isinstance(item[2], dict) or
                not item[2] or any(not isinstance(node, dict) or
                    not isinstance(node.get('class_type'), str) for node in item[2].values())):
            raise client.ClientError('invalid_response', 'Queue entry lacks a readable API prompt')
        if any(node['class_type'] in VIDEO_GENERATION_NODES for node in item[2].values()):
            count += 1
    return count


def dispatch(args):
    workflow = client.strict_json(Path(args.workflow).read_bytes())
    client.validate_workflow(workflow)
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
        eligible = {client.Client(url, args.timeout).url for url in args.eligible_url}
        if not eligible <= set(config['remote-urls']):
            raise client.ClientError('invalid_eligibility', 'Eligible addresses must come from this project')
        urls = config['remote-urls']
        if args.target_url:
            target = client.Client(args.target_url, args.timeout).url
            if target not in urls or target not in eligible:
                raise client.ClientError('invalid_target', 'User-selected endpoint must be configured and verified eligible')
            urls = [target]
        elif not config['enable-multi-remote'] or args.task_type in config['default-only-task-types']:
            urls = urls[:1]
        checks = []
        for url in urls:
            if url not in eligible:
                checks.append({'url': url, 'state': 'not_eligible'})
                continue
            remote = client.Client(url, args.timeout)
            try:
                queue = remote.json('/queue')
                if (not isinstance(queue, dict) or
                        not all(isinstance(queue.get(k), list) for k in ('queue_pending', 'queue_running'))):
                    raise client.ClientError('invalid_response', 'Queue response lacks pending/running arrays')
                videos = video_job_count(queue)
            except client.ClientError as exc:
                checks.append({'url': url, 'state': 'unknown', 'error': str(exc)})
                continue
            check = {'url': url, 'pending': len(queue['queue_pending']),
                     'running': len(queue['queue_running']), 'video_jobs': videos}
            if videos or check['pending'] >= config['busy-pending-threshold']:
                checks.append({**check, 'state': 'busy',
                               'reason': 'video_generation' if videos else 'pending_threshold'})
                continue
            checks.append({**check, 'state': 'selected'})
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
            if args.task_type in DEFAULT_ONLY_TASK_TYPES:
                try:
                    prepare_generation_context(args.project, record, workflow, args.task_type)
                except KeyError as exc:
                    raise ValueError('生成资料输入映射或API缺少字段：' + str(exc)) from exc
            # Once a POST is attempted, errors propagate: never try the next endpoint.
            result = client.submit(remote, args, workflow=workflow)
            return {'dispatch_state': 'accepted', 'url': url, 'checks': checks, **result}
        return {'dispatch_state': 'deferred', 'reason': 'no_eligible_available_endpoint', 'checks': checks}


def parser():
    p = client.Parser(description=__doc__)
    p.add_argument('--project', required=True, help='Project root containing comfyui-config.json; relative to cwd')
    p.add_argument('--task-type', required=True, choices=TASK_TYPES, help='Authorized task stage; video passes and postprocessing default to the first endpoint')
    p.add_argument('--target-url', help='Use only this endpoint when explicitly selected by the user; no fallback, still checks eligibility and queue')
    p.add_argument('--workflow', required=True, help='Prepared API JSON; unchanged except declared uploaded input paths')
    p.add_argument('--eligible-url', action='append', required=True, help='Repeat for each endpoint whose nodes/models and existing inputs were verified')
    p.add_argument('--uploads', help='Optional JSON array of local files and loader bindings; paths relative to cwd')
    p.add_argument('--record-dir', required=True, help='Existing business evidence directory; video tasks require 输入映射.json and automatically save generation inputs before POST')
    p.add_argument('--attempt-name', default='submit-attempt.json', help='Exclusive attempt evidence filename')
    p.add_argument('--request-name', default='request.json', help='Actual request evidence filename')
    p.add_argument('--response-name', default='response.json', help='Actual submission response filename')
    p.add_argument('--timeout', type=float, default=30, help='Seconds per network operation, not task duration; no retries')
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
