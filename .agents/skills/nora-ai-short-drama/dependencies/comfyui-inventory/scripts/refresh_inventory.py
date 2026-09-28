#!/usr/bin/env python3
"""Refresh a local ComfyUI inventory using read-only HTTP requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.client import HTTPException
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import urlopen


def fetch(base, endpoint, timeout):
    with urlopen(base + endpoint, timeout=timeout) as response:
        return json.load(response)


def collect(base, timeout):
    endpoints = {'system_stats': '/system_stats', 'nodes': '/object_info',
                 'categories': '/models'}
    core = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(fetch, base, ep, timeout): name
                   for name, ep in endpoints.items()}
        for future in as_completed(pending):
            core[pending[future]] = future.result()
    if not isinstance(core['system_stats'], dict) or not isinstance(core['nodes'], dict):
        raise ValueError('Unexpected system_stats or object_info response')
    categories = core['categories']
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise ValueError('Expected /models to return a list of category names')
    models, errors = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(fetch, base, '/models/' + quote(cat, safe=''), timeout): cat
                   for cat in sorted(set(categories))}
        for future in as_completed(pending):
            cat = pending[future]
            try:
                names = future.result()
                if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                    raise ValueError('Expected a list of filenames')
                models[cat] = sorted(set(names))
            except (OSError, ValueError, HTTPException) as error:
                errors.append({'endpoint': '/models/' + cat,
                               'error': type(error).__name__ + ': ' + str(error)})
    nodes = core['nodes']
    modules = sorted({n.get('python_module') for n in nodes.values()
                      if isinstance(n, dict) and isinstance(n.get('python_module'), str)})
    return {'schema_version': 1, 'last_updated': datetime.now().astimezone().isoformat(),
            'source_url': base, 'mode': 'online', 'complete': not errors,
            'errors': sorted(errors, key=lambda x: x['endpoint']),
            'system_stats': core['system_stats'], 'model_categories': sorted(set(categories)),
            'models': dict(sorted(models.items())), 'nodes': dict(sorted(nodes.items())),
            'node_modules': modules,
            'limitations': ['API-visible filenames and registered classes only; no file checksums or runtime compatibility validation.',
                            'Missing/failed category queries are unknown, not empty.',
                            'Node module names are not a full on-disk custom_nodes package inventory.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=os.environ.get('COMFYUI_URL') or 'http://127.0.0.1:8188', help='HTTP(S) server base URL; default: COMFYUI_URL or http://127.0.0.1:8188. No credentials, query or fragment.')
    parser.add_argument('--timeout', type=float, default=30, help='Positive seconds per blocking network operation; default: 30. Not a deadline for the entire refresh.')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'state/inventory.json', help='Local cache JSON to create or replace; default: state/inventory.json under this skill. Explicit relative paths use the current working directory.')
    args = parser.parse_args()
    base = args.url.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        parser.error('--url must be an HTTP(S) base URL without credentials, query or fragment')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    try:
        data = collect(base, args.timeout)
    except (OSError, ValueError, HTTPException) as error:
        print(json.dumps({'ok': False, 'cache_updated': False,
                          'error': type(error).__name__ + ': ' + str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=args.output.parent,
                                         prefix='.inventory-', suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        temp_path.replace(args.output)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    print(json.dumps({'ok': data['complete'], 'cache_updated': True,
                      'output': str(args.output.resolve()), 'nodes': len(data['nodes']),
                      'model_categories': len(data['models']),
                      'listed_files_across_categories': sum(map(len, data['models'].values())),
                      'errors': data['errors']}, ensure_ascii=False))
    return 0 if data['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
