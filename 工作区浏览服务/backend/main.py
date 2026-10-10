from pathlib import Path
from contextlib import asynccontextmanager
from collections.abc import AsyncIterable
import asyncio
import secrets
from typing import Annotated, Any, Literal
import json
import re
import os
from ipaddress import ip_address, ip_network
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from backend.parsers import project as parser
from backend.services.projects import ProjectStore
from backend.services.episode_downloads import KINDS, resources as episode_resources, zip_response
from backend.services import krea2
from backend.services.comfy_tasks import TaskInput, TaskStore, client as comfy_client
from websockets.exceptions import WebSocketException
from backend.services.revision_notes import Episode, Scene, NoteInput, RevisionNote, SceneNotes, RevisionNotes

TOOL = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.environ.get('NORA_WORKSPACE', TOOL.parent)).resolve()
ENVIRONMENT = os.environ.get('NORA_SERVICE_ENV', 'production')
store = ProjectStore(WORKSPACE / 'projects')
revision_notes = RevisionNotes()
VERSION = json.loads((TOOL / 'frontend/package.json').read_text('utf-8'))['version']
FRONTEND_RELEASE = TOOL / 'frontend/dist/release.json'
@asynccontextmanager
async def lifespan(app):
    tasks = TaskStore(TOOL / 'runtime', WORKSPACE)
    app.state.comfy_tasks = tasks
    config_path = TOOL / 'runtime/service.json'
    config = json.loads(config_path.read_text('utf-8-sig')) if config_path.is_file() else {}
    port = int(os.environ.get('NORA_SERVICE_PORT', config.get('port', 8782)))
    (TOOL / 'runtime/task-service.json').write_text(
        json.dumps({'url': f'http://127.0.0.1:{port}', 'token': tasks.token}), encoding='utf-8')
    await tasks.start()
    await tasks.remote_queues.start()
    try:
        yield
    finally:
        await tasks.close()


app = FastAPI(title='Nora工作区浏览服务', version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get('/api/comfy/tasks')
async def comfy_tasks(request: Request) -> dict[str, Any]:
    return request.app.state.comfy_tasks.public()


@app.get('/api/comfy/events', response_class=EventSourceResponse)
async def comfy_events(request: Request) -> AsyncIterable[ServerSentEvent]:
    tasks = request.app.state.comfy_tasks
    event = asyncio.Event()
    tasks.subscribers.add(event)
    try:
        yield ServerSentEvent(data=tasks.public(), event='tasks')
        while True:
            await event.wait()
            event.clear()
            yield ServerSentEvent(data=tasks.public(), event='tasks')
    finally:
        tasks.subscribers.remove(event)


@app.post('/api/internal/comfy/submit')
async def comfy_submit(request: Request, data: TaskInput) -> dict[str, Any]:
    tasks = request.app.state.comfy_tasks
    # Local agent only. No token/connection metadata is returned to browser readers.
    if (request.client.host not in ('127.0.0.1', '::1') or request.headers.get('origin') is not None
            or not secrets.compare_digest(request.headers.get('x-nora-task-token', ''), tasks.token)):
        raise HTTPException(403, '仅允许本机Agent通过专用凭证提交')
    try:
        result = await tasks.enqueue(data)
    except (ValueError, OSError, RuntimeError, WebSocketException) as error:
        raise HTTPException(409, str(error)) from error
    except comfy_client.ClientError as error:
        raise HTTPException(409, {'code': error.code, 'message': str(error), **error.details}) from error
    return result


class QueueAction(BaseModel):
    action: Literal['immediate', 'insert', 'pause', 'resume', 'cancel']


class QueueOrder(BaseModel):
    ids: list[str]
    token: str


class DragInput(BaseModel):
    token: str | None = None
    release: bool = False
    url: str | None = None


class TransferInput(BaseModel):
    url: str


def queue_write(request: Request):
    if not local_write_request(request):
        raise HTTPException(403, '仅允许工作台同源管理操作')


def agent_request(request: Request):
    tasks = request.app.state.comfy_tasks
    if (request.client.host not in ('127.0.0.1', '::1') or request.headers.get('origin') is not None
            or not secrets.compare_digest(request.headers.get('x-nora-task-token', ''), tasks.token)):
        raise HTTPException(403, '仅允许本机Agent通过专用凭证调用')
    return tasks


@app.post('/api/comfy/tasks/{key}/action')
async def local_task_action(key: str, data: QueueAction, request: Request) -> dict[str, Any]:
    queue_write(request)
    try:
        return request.app.state.comfy_tasks.task_action(key, data.action)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post('/api/comfy/tasks/{key}/transfer')
async def local_task_transfer(key: str, data: TransferInput, request: Request) -> dict[str, Any]:
    queue_write(request)
    try:
        return request.app.state.comfy_tasks.transfer(key, data.url)
    except (ValueError, comfy_client.ClientError) as error:
        raise HTTPException(409, str(error)) from error


@app.post('/api/comfy/drag')
async def local_queue_drag(data: DragInput, request: Request) -> dict[str, Any]:
    queue_write(request)
    try:
        return request.app.state.comfy_tasks.drag(data.token, data.release, data.url)
    except (ValueError, comfy_client.ClientError) as error:
        raise HTTPException(409, str(error)) from error


@app.put('/api/comfy/order')
async def local_queue_order(data: QueueOrder, request: Request) -> dict[str, Any]:
    queue_write(request)
    try:
        request.app.state.comfy_tasks.reorder(data.ids, data.token)
        return request.app.state.comfy_tasks.public()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get('/api/internal/comfy/tasks/{key}')
async def agent_task_status(key: str, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    if key not in tasks.rows:
        raise HTTPException(404, '任务不存在')
    return next(item for item in tasks.public()['tasks'] if item['id'] == key) | {
        'record_dir': tasks.rows[key]['input'].record_dir}


@app.post('/api/internal/comfy/tasks/{key}/retry-collection')
async def agent_retry_collection(key: str, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        return await tasks.retry_collection(key)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


class NoticeReceipt(BaseModel):
    thread_id: str


@app.post('/api/internal/comfy/notifications/{batch_id}/ack')
async def agent_notice_ack(batch_id: str, data: NoticeReceipt, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        return tasks.acknowledge(batch_id, data.thread_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    elif response.headers.get('content-type', '').startswith('text/html'):
        response.headers['Cache-Control'] = 'no-cache'
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


def local_write_request(request: Request) -> bool:
    expected = str(request.base_url).rstrip('/')
    origin = request.headers.get('origin')
    referer = urlsplit(request.headers.get('referer', ''))
    port_stripped_origin = origin == request.url.scheme + '://' + request.url.hostname and request.headers.get('sec-fetch-site') == 'same-origin' and (
        referer.scheme + '://' + referer.netloc == expected)
    return management_request(request) and (origin == expected or port_stripped_origin)


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
    ready = FRONTEND_RELEASE.is_file() and json.loads(FRONTEND_RELEASE.read_text('utf-8'))['version'] == VERSION
    return {'app': 'nora-workspace-browser', 'version': app.version, 'pid': os.getpid(), 'workspace': str(WORKSPACE),
            'tool': str(TOOL), 'environment': ENVIRONMENT, 'ready': ready}


@app.get('/api/projects/{name}/status')
def project_status(name: str) -> dict[str, Any]:
    entry(name)
    return store.status(name)


@app.get('/api/projects/{name}/overview')
def overview(name: str) -> dict[str, Any]:
    data = entry(name)['data']
    return view({k: data[k] for k in ('project', 'positionTitle', 'builtAt', 'progressUpdated', 'active', 'directories', 'warnings')}, name)


@app.get('/api/projects/{name}/sections/{section}')
def section(name: str, section: str) -> dict[str, Any]:
    data = entry(name)['data']
    if section == '00-项目定位':
        result = {'exists': data['positionExists'], 'title': data['positionTitle'], 'meta': data['meta'], 'confirmationHtml': data['confirmationHtml'],
                  'introHtml': data['introHtml'], 'summaryHtml': data['summaryHtml'], 'headerHtml': data['headerHtml'], 'bodyHtml': data['positionHtml'], 'groups': data['groups'],
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
            {'statusHtml': item['card']['confirmationHtml'], 'formalCount': sum(
                bool(asset['media']) and asset['approved'] for asset in item['formal'] + item.get('auxiliary', [])),
             'candidateCount': len(item['candidates'])} |
            ({'voice': item['voice']} if key == 'people' else {}) for item in data[key]]}
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


@app.get('/api/projects/{name}/episodes/{episode}/downloads')
def episode_download_list(name: str, episode: Episode) -> dict[str, Any]:
    try:
        files = episode_resources(store, name, episode, entry(name)['data'])
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    prefix = '/api/projects/' + quote(name, safe='') + '/episodes/' + episode + '/downloads/'
    return {stage: {kind: {'count': len(items), 'url': prefix + quote(stage, safe='') + '/' + kind if items else None}
                    for kind, items in groups.items()} for stage, groups in files.items()}


@app.get('/api/projects/{name}/episodes/{episode}/downloads/{stage}/{kind}')
def episode_download(name: str, episode: Episode, stage: Literal['一采', '二采', '后处理'],
                     kind: Literal['videos', 'director', 'canvas']):
    try:
        files = episode_resources(store, name, episode, entry(name)['data'])[stage][kind]
        if not files:
            raise FileNotFoundError('本集该阶段没有可下载的' + KINDS[kind])
        return zip_response(files, name + '-' + episode + '-' + stage + '-' + KINDS[kind] + '.zip')
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@app.get('/api/projects/{name}/document')
def document(name: str, path: Annotated[str, Query()]) -> dict[str, Any]:
    data = entry(name)['data']
    if path in data['documents']:
        return view(data['documents'][path], name)
    if path in data['textPreviews']:
        return data['textPreviews'][path]
    raise HTTPException(404, '没有可用的文档预览，请打开原文件')


@app.get('/api/projects/{name}/files/{path:path}')
def project_file(name: str, path: str, v: str | None = None):
    try:
        target = store.file(name, path, v)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(target)


@app.get('/api/projects/{name}/revision-notes/{episode}/{scene}')
def scene_revision_notes(name: str, episode: Episode, scene: Scene) -> SceneNotes:
    try:
        return revision_notes.read(store.project(name), episode, scene)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, ValueError, UnicodeError) as error:
        raise HTTPException(503, '修改意见读取失败：' + str(error)) from error


@app.put('/api/projects/{name}/revision-notes/{episode}/{scene}')
def save_revision_note(name: str, episode: Episode, scene: Scene, value: NoteInput, request: Request) -> RevisionNote:
    if not local_write_request(request):
        raise HTTPException(403, '修改意见仅限本机或局域网地址，并要求同源请求')
    try:
        return revision_notes.save(store.project(name), episode, scene, value)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, ValueError, UnicodeError) as error:
        raise HTTPException(503, '修改意见未保存：' + str(error)) from error


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
    if not local_write_request(request):
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
