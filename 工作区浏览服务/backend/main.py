from pathlib import Path
from typing import Annotated, Any, Literal
import re
import os
from ipaddress import ip_address, ip_network
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.parsers import project as parser
from backend.services.projects import ProjectStore
from backend.services import krea2

TOOL = Path(__file__).resolve().parent.parent
WORKSPACE = TOOL.parent
store = ProjectStore(WORKSPACE / 'projects')
app = FastAPI(title='Nora工作区浏览服务', version='0.1.0', docs_url=None, redoc_url=None)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def entry(name):
    try:
        return store.get(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        raise HTTPException(503, '项目读取失败：' + str(error)) from error


MANAGEMENT_NETWORKS = tuple(ip_network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7', 'fe80::/10'))


def management_address(value: str) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return address.is_loopback or any(address in network for network in MANAGEMENT_NETWORKS)


def management_request(request: Request) -> bool:
    peer = request.client.host
    hostname = request.url.hostname
    return (management_address(peer) or peer == 'testclient') and (hostname == 'localhost' or management_address(hostname))


def view(value, name):
    """Rewrite generated project-relative links without changing record content."""
    prefix = '/api/projects/' + quote(name, safe='') + '/files/'
    if isinstance(value, dict):
        return {k: prefix + re.sub('%5c', '/', v, flags=re.I) if (k == 'url' or k.endswith('Url')) and isinstance(v, str) and not urlsplit(v).scheme and not v.startswith(('#', '/'))
                else view(v, name) for k, v in value.items()}
    if isinstance(value, list):
        return [view(v, name) for v in value]
    if isinstance(value, str) and ('href=' in value or 'src=' in value):
        return re.sub(r'(href|src)="([^"\n]+)"',
                      lambda m: m[0] if urlsplit(m[2]).scheme or m[2].startswith(('#', '/', '//'))
                      else m[1] + '="' + prefix + m[2] + '"', value)
    return value


@app.get('/api/projects')
def projects() -> list[dict[str, str]]:
    return store.discover()


@app.get('/api/service')
def service() -> dict[str, Any]:
    return {'app': 'nora-workspace-browser', 'version': app.version, 'pid': os.getpid(), 'workspace': str(WORKSPACE)}


@app.get('/api/projects/{name}/status')
def project_status(name: str) -> dict[str, Any]:
    entry(name)
    return store.status(name)


@app.get('/api/projects/{name}/overview')
def overview(name: str) -> dict[str, Any]:
    data = entry(name)['data']
    return view({k: data[k] for k in ('project', 'builtAt', 'progressUpdated', 'active', 'directories', 'warnings')}, name)


@app.get('/api/projects/{name}/sections/{section}')
def section(name: str, section: str) -> dict[str, Any]:
    data = entry(name)['data']
    if section == '00-项目定位':
        result = {'exists': data['positionExists'], 'title': data['positionTitle'], 'meta': data['meta'], 'confirmationHtml': data['confirmationHtml'],
                  'introHtml': '', 'bodyHtml': data['positionHtml'], 'groups': data['groups'],
                  'documentKey': parser.POSITION}
        if parser.POSITION in data['documents']:
            result['url'] = data['documents'][parser.POSITION]['url']
    elif section in ('01-主旨与简介', '02-故事大纲'):
        result = dict(data['story' if section.startswith('01') else 'outline'])
        result['documentKey'] = parser.STORY if section.startswith('01') else parser.OUTLINE
    elif section in ('03-人物资料', '04-场景资料', '05-道具资料'):
        key, groups, index = {'03-人物资料': ('people', 'peopleGroups', 'peopleIndex'),
                              '04-场景资料': ('scenes', 'sceneGroups', 'sceneIndex'),
                              '05-道具资料': ('props', 'propGroups', 'propIndex')}[section]
        result = {'kind': key, 'indexKey': data[index], 'groups': data[groups], 'items': [
            {k: item[k] for k in ('id', 'name', 'role', 'cover', 'pendingCount')} |
            {'statusHtml': item['card']['confirmationHtml'], 'formalCount': len(item['formal']) + len(item.get('auxiliary', [])),
             'candidateCount': len(item['candidates'])} for item in data[key]]}
    elif section in data['catalogues']:
        result = data['catalogues'][section]
    else:
        raise HTTPException(404, '栏目不存在')
    return view(result, name)


@app.get('/api/projects/{name}/assets/{kind}/{identity}')
def asset(name: str, kind: Literal['people', 'scenes', 'props'], identity: str) -> dict[str, Any]:
    for item in entry(name)['data'][kind]:
        if item['id'] == identity:
            return view(item, name)
    raise HTTPException(404, '资料卡不存在')


@app.get('/api/projects/{name}/document')
def document(name: str, path: Annotated[str, Query()]) -> dict[str, Any]:
    data = entry(name)['data']
    if path in data['documents']:
        return view(data['documents'][path], name)
    if path in data['textPreviews']:
        return data['textPreviews'][path]
    raise HTTPException(404, '没有可用的文档预览，请打开原文件')


@app.get('/api/projects/{name}/files/{path:path}')
def project_file(name: str, path: str):
    try:
        target = store.file(name, path)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(target)


@app.get('/api/krea2/catalog')
def styles(q: str = '', library: str = '', category: str = '', page: Annotated[int, Query(ge=1)] = 1) -> dict[str, Any]:
    data = krea2.updater.catalog()['styles']
    categories = sorted({s['category_name'] for s in data if not library or s['library'] == library})
    matched = [s for s in data if (not library or s['library'] == library) and (not category or s['category_name'] == category)
               and q.casefold() in ' '.join((s['name'], s.get('name_cn', ''), s['category_name'])).casefold()]
    items = [{k: s.get(k, '') for k in ('id', 'name', 'name_cn', 'category_name', 'library', 'image')}
             for s in matched[(page - 1) * 36:page * 36]]
    return {'items': items, 'total': len(matched), 'categories': categories, 'pageSize': 36,
            'revision': krea2.updater.versions()}


@app.get('/api/krea2/styles/{identity}')
def style(identity: str) -> dict[str, Any]:
    for item in krea2.updater.catalog()['styles']:
        if item['id'] == identity:
            return item
    raise HTTPException(404, '风格不存在')


@app.get('/api/krea2/files/{path:path}')
def style_file(path: str):
    target = (krea2.updater.RES / path).resolve()
    if (not any(target.is_relative_to(krea2.updater.RES / library) for library in krea2.updater.SOURCES.values())
            or not target.is_file()):
        raise HTTPException(404, '资源不存在')
    return FileResponse(target)


@app.get('/api/krea2/state')
def update_state(request: Request) -> dict[str, Any]:
    return krea2.state(management_request(request))


class UpdateAction(BaseModel):
    source: Literal['clio', 'ray']
    action: Literal['check', 'prepare', 'apply', 'restore', 'discard']


@app.post('/api/krea2/action', status_code=202)
def update_action(request: Request, action: UpdateAction) -> dict[str, bool]:
    expected = str(request.base_url).rstrip('/')
    origin = request.headers.get('origin')
    referer = urlsplit(request.headers.get('referer', ''))
    port_stripped_origin = origin == request.url.scheme + '://' + request.url.hostname and request.headers.get('sec-fetch-site') == 'same-origin' and (
        referer.scheme + '://' + referer.netloc == expected)
    if not management_request(request) or (origin != expected and not port_stripped_origin):
        raise HTTPException(403, '更新管理仅限本机或局域网地址，并要求同源请求')
    if request.headers.get('x-krea-token') != krea2.updater.TOKEN:
        raise HTTPException(403, '操作凭证失效，请重新打开更新管理')
    if int(request.headers.get('content-length', '0')) > 4096:
        raise HTTPException(413, '请求超过4096字节')
    try:
        krea2.updater.start_job(action.action, action.source)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {'ok': True}


@app.get('/api/history')
def history() -> list[dict[str, str]]:
    root = TOOL / 'docs'
    return [{'path': p.relative_to(root).as_posix(), 'name': p.stem} for p in sorted(root.rglob('*.md'))]


@app.get('/api/history/document')
def history_document(path: Annotated[str, Query()]) -> dict[str, str]:
    root = TOOL / 'docs'
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix != '.md' or not target.is_file():
        raise HTTPException(404, '记录不存在')
    return {'title': target.stem, 'html': parser.markdown(target.read_text('utf-8'), path)}


app.frontend('/', directory=TOOL / 'frontend/dist', fallback='index.html')
