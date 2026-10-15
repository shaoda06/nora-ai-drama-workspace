"""Clone explicitly named H3 cache slots to an empty director identity, without sampling."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode

import comfyui_client as c


def cache_folder(cache_name, node):
    if (not cache_name or re.search(r'[<>:"/\\|?*\x00-\x1f]', cache_name)
            or cache_name != cache_name.strip(' .') or not re.fullmatch(r'[0-9]+', node)):
        raise ValueError('Use the actual normalized cache name and numeric director ID')
    return 'minimax_seg_cache/' + cache_name + '_' + node


def probe(client, folder, name):
    try:
        with client.open('/view?' + urlencode({'filename': name, 'subfolder': folder, 'type': 'output'}),
                         headers={'Range': 'bytes=0-0'}) as response:
            size = response.headers.get('Content-Range')
            size = int(size.rsplit('/', 1)[1]) if size else int(response.headers['Content-Length'])
            return {'bytes': size, 'modified': response.headers.get('Last-Modified')}
    except c.ClientError as error:
        if error.details.get('http_status') == 404:
            return None
        raise


def slot_files(client, folder, index):
    stem = f'seg_{index:04d}'
    required = [stem + suffix for suffix in (
        '.meta.json', '.av.pt', '.audio.pt', '.pre.meta.json', '.pre.av.pt')]
    optional = [stem + suffix for suffix in ('.handoff.json', '.pre.handoff.json', '.pre.low.pt')]
    found = {}
    for name in required + optional:
        state = probe(client, folder, name)
        if state is None and name in required:
            raise ValueError('Required source cache file missing: ' + name)
        if state is not None:
            found[name] = state
    for prefix in (stem, stem + '.pre'):
        frames = {prefix + suffix: probe(client, folder, prefix + suffix)
                  for suffix in ('.frames.mkv', '.pt')}
        frames = {name: state for name, state in frames.items() if state is not None}
        if not frames:
            raise ValueError('Required source frame cache missing: ' + prefix)
        found.update(frames)
    return found


def idle(client):
    queue = client.json('/queue')
    if queue['queue_running'] or queue['queue_pending']:
        raise ValueError('Cache cloning requires an idle remote queue; no task was interrupted')


def clone(client, args):
    if args.source_node == args.target_node:
        raise ValueError('Source and target director IDs must differ')
    source = cache_folder(args.cache_name, args.source_node)
    target = cache_folder(args.cache_name, args.target_node)
    indices = [int(value) for value in args.indices.split(',')]
    if not indices or len(set(indices)) != len(indices) or any(value < 0 or value >= args.segment_count for value in indices):
        raise ValueError('Indices must be unique original slots within segment-count')
    record = Path(args.record_dir).resolve()
    receipt = record / '缓存隔离结果.json'
    if receipt.exists():
        raise ValueError('Existing clone receipt; reconcile it instead of copying again')
    idle(client)
    # Inspect every original slot, not only copied ones; never overwrite another cache identity.
    for index in range(args.segment_count):
        for suffix in ('.meta.json', '.pre.meta.json'):
            if probe(client, target, f'seg_{index:04d}' + suffix) is not None:
                raise ValueError('Target director cache is not empty')
    files = {}
    for index in indices:
        files.update(slot_files(client, source, index))
    plan = {'source': source, 'target': target, 'indices': indices, 'files': files}
    if not args.apply:
        return {'state': 'preview', **plan}
    record.mkdir(parents=True, exist_ok=True)
    evidence = {'state': 'copying', 'time': c.now(), 'url': client.url, **plan, 'copied': []}
    c.write_new(receipt, evidence)
    local = record / '接续来源缓存'
    # Publish metadata last, so interrupted copies do not appear ready for generation.
    for name in sorted(files, key=lambda value: (value.endswith('.meta.json'), value)):
        destination = local / name
        downloaded = c.download(client, argparse.Namespace(filename=name, subfolder=source, type='output',
                                                           output=str(destination), sha256=None))
        if downloaded['bytes'] != files[name]['bytes']:
            raise ValueError('Source cache changed during download: ' + name)
        idle(client)
        uploaded = c.upload(client, argparse.Namespace(file=str(destination), subfolder=target), storage_type='output')
        remote = uploaded['remote']
        if remote['name'] != name or remote['subfolder'] != target:
            raise ValueError('Server changed target cache identity; do not submit generation')
        digest = hashlib.sha256()
        count = 0
        with client.open('/view?' + urlencode({'filename': name, 'subfolder': target, 'type': 'output'})) as response:
            while block := response.read(c.CHUNK):
                digest.update(block)
                count += len(block)
        if count != downloaded['bytes'] or digest.hexdigest() != downloaded['sha256']:
            raise ValueError('Cloned cache bytes differ: ' + name)
        evidence['copied'].append({'filename': name, 'bytes': count, 'sha256': digest.hexdigest()})
        receipt.write_bytes(c.encoded(evidence))
        print(json.dumps({'copied': len(evidence['copied']), 'total': len(files), 'filename': name}), flush=True)
    idle(client)
    for name, state in files.items():
        if probe(client, source, name) != state:
            raise ValueError('Source cache changed during cloning: ' + name)
    evidence['state'] = 'cloned'
    evidence['completed_at'] = c.now()
    receipt.write_bytes(c.encoded(evidence))
    return {'state': 'cloned', 'files': len(files), 'source': source, 'target': target, 'receipt': str(receipt)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True, help='Actual ComfyUI service used for both cache identities')
    p.add_argument('--cache-name', required=True, help='Actual normalized scene cache name; not a path')
    p.add_argument('--source-node', required=True, help='Original director numeric ID; source remains unchanged')
    p.add_argument('--target-node', required=True, help='Different, unused director numeric ID')
    p.add_argument('--indices', required=True, help='Comma-separated original zero-based slots')
    p.add_argument('--segment-count', type=int, required=True, help='Full original slot count, including unselected slots')
    p.add_argument('--record-dir', required=True, help='Evidence directory, relative to cwd or absolute')
    p.add_argument('--timeout', type=float, default=120, help='Seconds per network operation; default 120')
    p.add_argument('--apply', action='store_true', help='Copy bytes to the empty target; default only previews')
    args = p.parse_args()
    try:
        print(json.dumps(clone(c.Client(args.url, args.timeout), args), ensure_ascii=False))
    except (c.ClientError, OSError, ValueError) as error:
        failure = {'ok': False, 'error': str(error),
                   'details': error.details if isinstance(error, c.ClientError) else {}}
        receipt = Path(args.record_dir) / '缓存隔离结果.json'
        if receipt.exists():
            evidence = json.loads(receipt.read_text('utf-8'))
            if evidence.get('state') == 'copying':
                evidence.update(state='failed', failure=failure)
                receipt.write_bytes(c.encoded(evidence))
        print(json.dumps(failure, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
