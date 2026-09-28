#!/usr/bin/env python3
"""Krea local gallery and two-source updater. Python 3.9+, standard library only."""
import argparse
import errno
import json
import mimetypes
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import tempfile
import threading
import traceback
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / 'Krea2_风格资源'
WORK = ROOT / 'Krea2_更新工具' / 'work'
HTML = ROOT / 'Krea2_风格浏览.html'
SOURCES = {'clio': 'krea2_styles', 'ray': 'Krea2_moodboard'}
RAY = 'https://civitai.com/models/2856809/ray-style-switching-extension'
REPO = 'https://github.com/lumenastrum/clio-style-preview'
MAX_ZIP = 300 * 1024 * 1024
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
JOB = {'running': False, 'message': '就绪', 'error': None, 'source': None}
SOURCE_STATUS = {source: {'running': False, 'message': '就绪', 'error': None} for source in SOURCES}
REMOTE = {}
PLANS = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 KreaLocalGallery/1.0'}), timeout=60)


def remote_json(url):
    with request(url) as response:
        return json.load(response)


def versions():
    p = RES / 'versions.json'
    return read_json(p) if p.exists() else {}


def catalog():
    return read_json(RES / 'catalog.json')


def fetch_meta(source):
    if source == 'clio':
        data = remote_json('https://api.github.com/repos/lumenastrum/clio-style-preview/commits/main')
        return {'revision': data['sha'], 'label': data['sha'][:8], 'date': data['commit']['committer']['date'],
                'note': data['commit']['message'].splitlines()[0], 'url': REPO,
                'download': 'https://codeload.github.com/lumenastrum/clio-style-preview/zip/' + data['sha']}
    with request(RAY) as response:
        html = response.read().decode('utf-8')
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        raise ValueError('Civitai 页面数据格式已变化，暂时无法读取更新信息。')
    data = json.loads(match.group(1))
    models = [q['state']['data'] for q in data['props']['pageProps']['trpcState']['json']['queries']
              if isinstance(q['state'].get('data'), dict) and q['state']['data'].get('id') == 2856809
              and 'modelVersions' in q['state']['data']]
    if len(models) != 1:
        raise ValueError('未能识别 Ray 发布信息。')
    model = models[0]
    candidates = [(v, f) for v in model['modelVersions'] if 'moodboard' in v['name'].lower()
                  for f in v['files'] if 'local' in f['name'].lower() and f['name'].lower().endswith('.zip')]
    if not candidates:
        raise ValueError('发布页没有可识别的 Moodboard 带图 ZIP。')
    version, file = max(candidates, key=lambda pair: pair[1]['id'])
    return {'revision': str(file['id']), 'label': file['name'], 'date': model['updatedAt'],
            'note': '日期为作者发布页最后修改时间；更新按资源文件 ID 识别。', 'url': RAY,
            'download': f"https://civitai.com/api/download/models/{version['id']}?type=Archive&format=Other&fileId={file['id']}"}


def check(source):
    JOB['message'] = '正在检查 ' + source + ' 上游版本…'
    REMOTE[source] = fetch_meta(source)
    JOB['message'] = '检查完成。可下载资源并查看具体变化。'


def safe_part(value):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', value).strip(' .')[:180] or 'style'


def image_ok(data):
    return data.startswith((b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n')) or (data[:4] == b'RIFF' and data[8:12] == b'WEBP')


def build_library(source, archive, stage, meta):
    lib = SOURCES[source]
    old_styles = {s['name']: s for s in catalog()['styles'] if s['library'] == lib}
    entries, cats, seen_folders = [], {}, set()
    changes = {k: [] for k in ['added', 'prompts', 'images', 'metadata', 'removed', 'missing']}
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > 20000 or sum(i.file_size for i in infos) > 600 * 1024 * 1024:
            raise ValueError('ZIP 内容过大，超过风格资源包限制。')
        for i in infos:
            p = PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename:
                raise ValueError('ZIP 包含不安全的路径。')
        names = z.namelist()
        rows = []
        if source == 'clio':
            roots = [n for n in names if n.count('/') == 1 and n.endswith('/styles.json')]
            if len(roots) != 1:
                raise ValueError('无法识别 Clio styles.json。')
            base = roots[0].rsplit('/', 1)[0] + '/'
            manifest = json.loads(z.read(base + 'gallery/manifest.json'))['sections']['krea2']
            images = {i['style']: i['file'] for i in manifest['images']}
            cn = {'Anime': '动漫', '3D Render': '3D渲染', 'Cartoon': '卡通', 'Comics': '漫画', 'Cover Art': '封面艺术',
                  'Design': '设计', 'Digital Painting': '数字绘画', 'Drawing': '素描', 'Painting': '绘画', 'Photography': '摄影'}
            for s in json.loads(z.read(roots[0])):
                prompt = manifest['template'].replace('{name}', s['name']).replace('{style}', s['prompt'])
                image = base + 'gallery/' + images[s['name']]
                rows.append((dict(s, prompt=prompt, negative_prompt=''), 'clio_' + s['section'], cn.get(s['section'], s['section']), image))
        else:
            files = sorted(n for n in names if PurePosixPath(n).name.startswith('Krea2_moodboard_') and n.endswith('.json'))
            if not files:
                raise ValueError('没有找到 Krea2_moodboard_*.json，请选择 Ray 的 Moodboard ZIP。')
            for file in files:
                cat = PurePosixPath(file).stem
                data = json.loads(z.read(file))
                if not isinstance(data, list) or not data:
                    raise ValueError('风格 JSON 必须是非空列表：' + file)
                for s in data:
                    thumb = s.get('thumbnail', '')
                    image = str(PurePosixPath(file).parent / thumb) if thumb and not thumb.startswith(('http:', 'https:', '/')) else ''
                    rows.append((s, cat, cat.rsplit('_', 1)[-1], image))
        if not rows:
            raise ValueError('资源包没有风格。')
        seen_names = set()
        for index, (s, cat, cat_cn, member) in enumerate(rows):
            if not isinstance(s.get('name'), str) or not s['name'].strip() or not isinstance(s.get('prompt'), str) or not s['prompt'].strip():
                raise ValueError('风格名称或提示词为空。')
            name = s['name']
            if name in seen_names:
                raise ValueError('风格名称重复：' + name)
            seen_names.add(name)
            old = old_styles.get(name)
            name_cn = old['name_cn'] if old else s.get('name_cn', name)
            folder = old['folder'] if old else lib + '/' + safe_part(name_cn + '__' + name)
            if folder in seen_folders:
                raise ValueError('风格目录重名：' + folder)
            seen_folders.add(folder)
            dest = stage / folder
            dest.mkdir(parents=True)
            image_path = None
            if member in names:
                data = z.read(member)
                if not image_ok(data):
                    raise ValueError('无效图片：' + member)
                ext = PurePosixPath(member).suffix.lower()
                if ext not in ('.jpg', '.jpeg', '.webp', '.png'):
                    raise ValueError('不支持的图片格式：' + member)
                image_path = folder + '/preview' + ext
                (stage / image_path).write_bytes(data)
            elif old and old['image']:
                # Some upstream packages omit an image. Preserve the known local asset explicitly.
                image_path = folder + '/' + Path(old['image']).name
                shutil.copy2(RES / old['image'], stage / image_path)
                changes['missing'].append(name + '（包内缺图，保留本地图片）')
            else:
                changes['missing'].append(name + '（包内缺图）')
            entry = {'id': old['id'] if old else lib + ':' + name, 'library': lib, 'category': cat,
                     'category_name': cat_cn, 'name_cn': name_cn, 'name': name, 'prompt': s['prompt'],
                     'negative_prompt': s.get('negative_prompt', ''), 'image': image_path, 'folder': folder,
                     'source': meta['url'], 'source_revision': meta['revision']}
            if image_path and member not in names:
                previous_info = read_json(RES / old['folder'] / 'style.json')
                entry['image_source'] = previous_info.get('image_source', previous_info.get('download_source', previous_info.get('source')))
                entry['image_note'] = '当前上游包缺图，保留此前本地图片。'
            if not image_path:
                entry['image_error'] = '上游包内没有此风格的图片。'
                (dest / '图片缺失说明.txt').write_text(entry['image_error'], encoding='utf-8')
            (dest / 'positive.txt').write_text(entry['prompt'], encoding='utf-8')
            (dest / 'negative.txt').write_text(entry['negative_prompt'], encoding='utf-8')
            write_json(dest / 'style.json', entry)
            entries.append(entry)
            cats.setdefault(cat, {'id': cat, 'name': cat_cn, 'library': lib, 'count': 0})['count'] += 1
            if old is None:
                changes['added'].append(name)
            else:
                if (old['prompt'], old['negative_prompt']) != (entry['prompt'], entry['negative_prompt']):
                    changes['prompts'].append(name)
                if (old['name_cn'], old['category_name']) != (name_cn, cat_cn):
                    changes['metadata'].append(name)
                old_bytes = (RES / old['image']).read_bytes() if old['image'] else None
                new_bytes = (stage / image_path).read_bytes() if image_path else None
                if old_bytes != new_bytes:
                    changes['images'].append(name)
            if index % 150 == 0:
                JOB['message'] = f'正在整理 {index + 1} / {len(rows)} 个风格…'
        changes['removed'] = sorted(old_styles.keys() - seen_names)
    write_json(stage / 'library.json', {'styles': entries, 'categories': list(cats.values()), 'version': meta})
    return {'count': len(entries), 'image_count': sum(bool(s['image']) for s in entries), 'changes': changes, 'version': meta}


def prepare(source):
    stage = Path(tempfile.mkdtemp(prefix='prepare-', dir=WORK))
    try:
        meta = fetch_meta(source)
        REMOTE[source] = meta
        archive = stage / 'download.zip'
        JOB['message'] = '正在下载 ' + meta['label'] + '…'
        with request(meta['download']) as response, archive.open('wb') as out:
            downloaded = 0
            while chunk := response.read(1024 * 1024):
                downloaded += len(chunk)
                if downloaded > MAX_ZIP:
                    raise ValueError('资源包超过 300 MB 限制。')
                out.write(chunk)
                JOB['message'] = f'正在下载 {meta["label"]} · {downloaded // (1024 * 1024)} MB'
        plan = build_library(source, archive, stage, meta)
        archive.unlink()
        if source in PLANS:
            shutil.rmtree(PLANS[source]['stage'])
        PLANS[source] = dict(plan, stage=str(stage))
        JOB['message'] = '资源已准备好。查看变化后点击“应用更新”。'
    except Exception:
        shutil.rmtree(stage)
        raise


def commit_library(source, incoming, info):
    lib = SOURCES[source]
    current = catalog()
    state = versions()
    previous = WORK / ('previous-' + source)
    backup = Path(tempfile.mkdtemp(prefix='backup-', dir=WORK))
    # Only this source is backed up/restored; the other library keeps its current version.
    shutil.copytree(RES / lib, backup / lib)
    write_json(backup / 'library.json', {'styles': [s for s in current['styles'] if s['library'] == lib],
               'categories': [c for c in current['categories'] if c['library'] == lib], 'version': state.get(source)})
    originals = {name: (RES / name).read_bytes() if (RES / name).exists() else None
                 for name in ['catalog.json', 'catalog.js', 'versions.json']}
    retired = WORK / ('retired-' + secrets.token_hex(6))
    moved = False
    try:
        (RES / lib).rename(retired)
        moved = True
        shutil.move(str(incoming / lib), str(RES / lib))
        current['styles'] = [s for s in current['styles'] if s['library'] != lib] + info['styles']
        current['categories'] = [c for c in current['categories'] if c['library'] != lib] + info['categories']
        if info['version'] is None:
            state.pop(source, None)
        else:
            state[source] = dict(info['version'], installed_at=now(), count=len(info['styles']))
        write_json(RES / 'catalog.json', current)
        (RES / 'catalog.js.tmp').write_text('window.STYLE_CATALOG = ' + json.dumps(current, ensure_ascii=False) + ';\n', encoding='utf-8')
        (RES / 'catalog.js.tmp').replace(RES / 'catalog.js')
        write_json(RES / 'versions.json', state)
    except Exception:
        if moved:
            if (RES / lib).exists():
                (RES / lib).rename(incoming / lib)
            retired.rename(RES / lib)
        for name, data in originals.items():
            if data is None:
                (RES / name).unlink(missing_ok=True)
            else:
                (RES / name).write_bytes(data)
        shutil.rmtree(backup)
        raise
    shutil.rmtree(retired)
    if previous.exists():
        shutil.rmtree(previous)
    backup.rename(previous)


def apply(source):
    if source not in PLANS:
        raise ValueError('请先下载资源并查看变化。')
    JOB['message'] = '正在保存上一版并应用更新…'
    stage = Path(PLANS[source]['stage'])
    commit_library(source, stage, read_json(stage / 'library.json'))
    shutil.rmtree(stage)
    del PLANS[source]
    JOB['message'] = '更新完成，浏览索引已刷新。'


def restore(source):
    previous = WORK / ('previous-' + source)
    if not previous.exists():
        raise ValueError('还没有可恢复的上一版。')
    stage = Path(tempfile.mkdtemp(prefix='restore-', dir=WORK))
    try:
        shutil.copytree(previous, stage, dirs_exist_ok=True)
        JOB['message'] = '正在恢复上一版…'
        commit_library(source, stage, read_json(stage / 'library.json'))
        if source in PLANS:
            shutil.rmtree(PLANS.pop(source)['stage'])
        JOB['message'] = '已恢复上一版，浏览索引已刷新。'
    finally:
        shutil.rmtree(stage)


def start_job(action, source):
    if source not in SOURCES:
        raise ValueError('未知资源库。')
    if not LOCK.acquire(blocking=False):
        raise ValueError('另一个更新操作正在进行，请等待完成。')
    JOB.update(running=True, error=None, message='正在开始…', source=source)
    def run():
        try:
            if action == 'check': check(source)
            elif action == 'prepare': prepare(source)
            elif action == 'apply': apply(source)
            elif action == 'restore': restore(source)
            elif action == 'discard':
                if source in PLANS:
                    shutil.rmtree(PLANS.pop(source)['stage'])
                JOB['message'] = '已取消准备，当前资源未改变。'
            else: raise ValueError('未知操作。')
        except Exception as error:
            traceback.print_exc()
            JOB.update(error=str(error), message='操作失败；请查看错误信息。')
        finally:
            JOB['running'] = False
            SOURCE_STATUS[source] = JOB.copy()
            LOCK.release()
    threading.Thread(target=run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if len(args) < 2 or str(args[1]) != '200':
            super().log_message(fmt, *args)

    def send_data(self, code, data, content_type='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def json(self, data, code=200):
        self.send_data(code, json.dumps(data, ensure_ascii=False).encode())

    def valid_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.valid_host():
            return self.json({'error': '仅允许本机地址'}, 403)
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == '/api/state':
            data = catalog()
            state = versions()
            self.json({'app': 'krea-local-gallery', 'token': TOKEN, 'job': JOB.copy(), 'sources': {s: {
                'status': JOB.copy() if JOB['source'] == s else SOURCE_STATUS[s].copy(),
                'local': state.get(s), 'count': sum(x['library'] == lib for x in data['styles']),
                'remote': REMOTE.get(s), 'plan': {k: v for k, v in PLANS.get(s, {}).items() if k != 'stage'},
                'restore': (WORK / ('previous-' + s)).exists()} for s, lib in SOURCES.items()}})
            return
        target = HTML if path in ('/', '/' + HTML.name) else (ROOT / path.lstrip('/')).resolve()
        allowed = target == HTML or target in (RES / 'catalog.js', RES / 'catalog.json')
        allowed = allowed or any((RES / lib) in target.parents for lib in SOURCES.values())
        if not allowed or not target.is_file():
            return self.json({'error': '找不到文件'}, 404)
        self.send_data(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

    def do_POST(self):
        expected = f'http://127.0.0.1:{self.server.server_port}'
        if not self.valid_host():
            return self.json({'error': '访问地址不匹配，请使用 ' + expected}, 403)
        origin = self.headers.get('Origin')
        # This browser sends a loopback Origin without its port. Accept that
        # specific form only with an exact Referer origin and same-origin fetch.
        referer = urllib.parse.urlsplit(self.headers.get('Referer', ''))
        port_stripped_local = (
            origin == 'http://127.0.0.1'
            and self.headers.get('Sec-Fetch-Site') == 'same-origin'
            and (referer.scheme, referer.netloc) == ('http', f'127.0.0.1:{self.server.server_port}')
        )
        if origin != expected and not port_stripped_local:
            return self.json({'error': '浏览器请求来源不匹配，请从 ' + expected + ' 打开页面'}, 403)
        if self.headers.get('X-Krea-Token') != TOKEN:
            return self.json({'error': '页面操作凭证已失效，请关闭更新面板后重新打开'}, 403)
        try:
            path = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get('Content-Length', '0'))
            if path.path == '/api/action':
                if length <= 0 or length > 4096:
                    raise ValueError('请求为空或超过 4096 字节。')
                data = json.loads(self.rfile.read(length))
                if data.get('action') not in ('check', 'prepare', 'apply', 'restore', 'discard'):
                    raise ValueError('未知操作。')
                start_job(data['action'], data['source'])
            else:
                return self.json({'error': '找不到接口'}, 404)
            self.json({'ok': True}, 202)
        except (ValueError, KeyError) as error:
            self.json({'error': str(error)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8876)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    url = f'http://127.0.0.1:{args.port}/'
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        if remote_json(url + 'api/state').get('app') != 'krea-local-gallery':
            raise RuntimeError('端口已被其他程序占用。') from error
        print('风格库服务已运行：' + url)
        if not args.no_browser:
            webbrowser.open(url)
        return
    print('Krea2 风格库：' + url + '\n保持此窗口开启；按 Ctrl+C 停止服务。', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if JOB['running']:
            print('等待当前资源操作完成后关闭…', flush=True)
            with LOCK:
                pass
        server.server_close()


if __name__ == '__main__':
    main()
