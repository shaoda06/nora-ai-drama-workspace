from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import secrets
from typing import Annotated, Any, Literal
import json
import re
import os
from ipaddress import ip_address, ip_network
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ValidationError

from backend.parsers import project as parser
from backend.services.projects import ProjectStore
from project_index import INDEX_NAME
from backend.services.request_diagnostics import RequestDiagnostics, RequestDiagnosticsMiddleware
from backend.services.episode_downloads import KINDS, resources as episode_resources, completed_episode_videos, zip_response, clear_downloads, video_archive_name
from backend.services import krea2
from backend.services.comfy_tasks import DesktopConnection, TaskInput, TaskStore, client as comfy_client
from backend.services.workflows import catalogue as workflow_catalogue
from workflow_paths import workflow_directories, workflow_root
from backend.services.task_details import task_detail
from backend.services.task_history import task_history
from backend.services import node_config
from backend.services.prompts import WorkspacePromptLibrary
from backend.routes.prompts import create_router as prompt_router
from backend.services.assets import AssetLibrary
from backend.routes.assets import create_router as asset_router
from backend.services.task_resolution import ResolutionInput, resolve_task
from backend.services.result_summary import summary as result_summary
from backend.services.result_registration import closeout as result_closeout
from websockets.exceptions import WebSocketException
from backend.services.revision_notes import Episode, Scene, NoteInput, RevisionNote, SceneNotes, RevisionNotes, ExportChanges, NotesChangedError

TOOL = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.environ.get('NORA_WORKSPACE', TOOL.parent)).resolve()
WORKFLOWS = workflow_root(WORKSPACE / '.agents/skills/nora-ai-short-drama')
ENVIRONMENT = os.environ.get('NORA_SERVICE_ENV', 'production')
revision_notes = RevisionNotes()
prompt_library = WorkspacePromptLibrary(WORKSPACE / '提示词管理', WORKSPACE / '共享提示词')
VERSION = json.loads((TOOL / 'frontend/package.json').read_text('utf-8'))['version']
FRONTEND_RELEASE = TOOL / 'frontend/dist/release.json'
store = ProjectStore(WORKSPACE / 'projects', cache_directory=TOOL / 'runtime/project-cache', version=VERSION)
@asynccontextmanager
async def lifespan(app):
    clear_downloads()
    prompt_library.initialize()
    tasks = TaskStore(TOOL / 'runtime', WORKSPACE)
    tasks.projects = store
    app.state.comfy_tasks = tasks
    config_path = TOOL / 'runtime/service.json'
    config = json.loads(config_path.read_text('utf-8-sig')) if config_path.is_file() else {}
    port = int(os.environ.get('NORA_SERVICE_PORT', config.get('port', 8782)))
    (TOOL / 'runtime/task-service.json').write_text(
        json.dumps({'url': f'http://127.0.0.1:{port}', 'token': tasks.token}), encoding='utf-8')
    await tasks.start()
    await tasks.remote_queues.start()
    diagnostics = app.state.request_diagnostics = RequestDiagnostics(TOOL / 'runtime')
    diagnostics.start()
    try:
        yield
    finally:
        await diagnostics.close()
        await tasks.close()


app = FastAPI(title='Nora工作区浏览服务', version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(RequestDiagnosticsMiddleware)


@app.get('/api/comfy/tasks')
async def comfy_tasks(request: Request, include_history: bool = True) -> dict[str, Any]:
    return request.app.state.comfy_tasks.public(include_history=include_history)


@app.get('/api/comfy/config')
async def comfy_config(request: Request, response: Response) -> dict[str, Any]:
    if not management_request(request):
        raise HTTPException(403, '仅允许工作台管理操作')
    return node_config_response(request, response)


@app.post('/api/comfy/config/read')
async def read_comfy_config(request: Request, response: Response) -> dict[str, Any]:
    queue_write(request)
    return node_config_response(request, response, credentials=True)


def node_config_response(request: Request, response: Response, *, credentials=False):
    response.headers['Cache-Control'] = 'no-store'
    tasks = request.app.state.comfy_tasks
    try:
        return node_config.snapshot(tasks, *node_config.read_config(tasks), credentials=credentials)
    except node_config.ConfigConflict as error:
        raise HTTPException(409, str(error)) from error
    except (comfy_client.ClientError, OSError, ValueError) as error:
        raise HTTPException(503, '节点配置读取失败，请核对工作区配置文件') from error


@app.put('/api/comfy/config')
async def save_comfy_config(request: Request, response: Response) -> dict[str, Any]:
    queue_write(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        edit = node_config.ConfigEdit.model_validate(await request.json())
    except (ValidationError, json.JSONDecodeError) as error:
        # Validation responses must not echo a submitted credential-bearing object.
        raise HTTPException(422, '节点配置请求格式不正确') from error
    try:
        return node_config.save_config(request.app.state.comfy_tasks, edit, credentials=True)
    except node_config.ConfigConflict as error:
        raise HTTPException(409, str(error)) from error
    except comfy_client.ClientError as error:
        raise HTTPException(422, '节点地址或认证格式不正确；地址须为HTTP或HTTPS，不能包含账号密码、查询参数或片段，且不能重复') from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        raise HTTPException(503, '节点配置保存失败，原配置保留，请检查文件写入权限后重试') from error


@app.get('/api/comfy/history')
async def comfy_history(request: Request, url: str | None = None, q: str = '',
                        result: Literal['all', 'completed', 'abnormal', 'cancelled', 'resolved'] = 'all',
                        offset: Annotated[int, Query(ge=0)] = 0,
                        limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict[str, Any]:
    return task_history(request.app.state.comfy_tasks, url, q, result, offset, limit)


@app.get('/api/comfy/tasks/{key}/detail')
async def comfy_task_detail(key: str, request: Request) -> dict[str, Any]:
    if key not in request.app.state.comfy_tasks.rows:
        raise HTTPException(404, '任务不存在')
    try:
        return await task_detail(request.app.state.comfy_tasks, key)
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(503, '任务详情读取失败：' + str(error)) from error


@app.get('/api/comfy/events')
async def comfy_events() -> Response:
    # HTTP 204 stops EventSource reconnection in pages from older releases,
    # freeing their sockets so version detection can load the new frontend.
    return Response(status_code=204)


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


@app.post('/api/internal/comfy/prepare')
async def comfy_prepare(request: Request, data: TaskInput) -> dict[str, Any]:
    tasks = request.app.state.comfy_tasks
    if (request.client.host not in ('127.0.0.1', '::1') or request.headers.get('origin') is not None
            or not secrets.compare_digest(request.headers.get('x-nora-task-token', ''), tasks.token)):
        raise HTTPException(403, '仅允许本机Agent通过专用凭证检查')
    try:
        return await tasks.prepare_only(data)
    except (ValueError, OSError, RuntimeError, comfy_client.ClientError) as error:
        raise HTTPException(409, str(error)) from error


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


app.include_router(prompt_router(prompt_library, queue_write))
app.include_router(asset_router(AssetLibrary(WORKSPACE / '综合资料/资产管理'), queue_write))


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
    return result_summary(tasks, key) | {
        'record_dir': tasks.rows[key]['input'].record_dir,
        'error_details': tasks.rows[key]['state'].get('error_details', {})}


@app.post('/api/internal/comfy/tasks/{key}/retry-collection')
async def agent_retry_collection(key: str, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        return await tasks.retry_collection(key)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post('/api/internal/comfy/tasks/{key}/resolve')
async def agent_resolve_task(key: str, data: ResolutionInput, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        return resolve_task(tasks, key, data)
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from error


class SubmissionPlanInput(BaseModel):
    project: str
    plan_file: str
    timeout: float = 30
    thread_id: str
    desktop: DesktopConnection
    prepare_only: bool = False
    reprepare: bool = False
    start_paused: bool = False


@app.post('/api/internal/comfy/submit-plan')
async def agent_submit_plan(request: Request, data: SubmissionPlanInput) -> dict[str, Any]:
    tasks = agent_request(request)
    from backend.services.submission_plans import execute
    try:
        return await execute(tasks, data)
    except (ValueError, OSError, KeyError, TypeError, AssertionError, comfy_client.ClientError) as error:
        raise HTTPException(409, str(error)) from error


class NoticeReceipt(BaseModel):
    thread_id: str


class ResultRegistrationInput(NoticeReceipt):
    record_updates: list[dict[str, str]] = []
    image_plans: dict[str, dict] = {}


@app.post('/api/internal/comfy/notifications/{batch_id}/ack')
async def agent_notice_ack(batch_id: str, data: NoticeReceipt, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        return tasks.acknowledge(batch_id, data.thread_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post('/api/internal/comfy/notifications/{batch_id}/report')
async def agent_result_report(batch_id: str, data: NoticeReceipt, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        return tasks.read_report(batch_id, data.thread_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post('/api/internal/comfy/notifications/{batch_id}/register-results')
async def agent_register_results(batch_id: str, data: ResultRegistrationInput, request: Request) -> dict[str, Any]:
    tasks = agent_request(request)
    try:
        locks = tasks.__dict__.setdefault('_closeout_locks', {})
        async with locks.setdefault(batch_id, asyncio.Lock()):
            return await result_closeout(tasks, store, batch_id, data.thread_id, data.record_updates, data.image_plans)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise HTTPException(409, str(error)) from error


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'no-store')
    elif response.headers.get('content-type', '').startswith('text/html'):
        response.headers['Cache-Control'] = 'no-cache'
    return response


def entry(name, scope=None, episode=None, mode='full', candidate=None):
    try:
        return {'data': store.section(name, scope, episode, mode=mode, candidate=candidate)} if scope else store.get(name)
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
        return {k: prefix + re.sub('%5c', '/', v, flags=re.I) if (k == 'url' or k.endswith('Url')) and isinstance(v, str) and v and not urlsplit(v).scheme and not v.startswith(('#', '/'))
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


@app.get('/api/project-index')
def project_index() -> dict[str, str]:
    path = store.root / INDEX_NAME
    if not path.is_file():
        raise HTTPException(404, '项目总索引尚未建立')
    return {'title': path.stem, 'html': parser.markdown(path.read_text('utf-8-sig'), INDEX_NAME)}


@app.get('/api/workflows')
def workflows() -> list[dict]:
    return workflow_catalogue(WORKFLOWS)


@app.get('/api/workflows/files/{filename:path}')
def workflow_file(filename: str) -> FileResponse:
    path = (WORKFLOWS / filename).resolve()
    if (not path.is_relative_to(WORKFLOWS.resolve())
            or path.parent not in tuple(folder.resolve() for folder, _ in workflow_directories(WORKFLOWS)) or not path.is_file()
            or not filename.endswith(('.workflow.json', '.api.json'))):
        raise HTTPException(404, '工作流文件不存在')
    return FileResponse(path, media_type='application/json', filename=path.name)


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
    data = entry(name, section)['data']
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
    return view(dict(result, warnings=data['warnings']), name)


@app.get('/api/projects/{name}/assets/{kind}/{identity}')
def asset(name: str, kind: Literal['people', 'scenes', 'props'], identity: str) -> dict[str, Any]:
    for item in entry(name, {'people': parser.PEOPLE, 'scenes': parser.SCENES, 'props': parser.PROPS}[kind])['data'][kind]:
        if item['id'] == identity:
            return view(item, name)
    raise HTTPException(404, '资料卡不存在')


@app.get('/api/projects/{name}/episodes/{episode}')
def episode_detail(name: str, episode: Episode, detail: Annotated[Literal['playback', 'full'], Query(alias='view')] = 'playback') -> dict[str, Any]:
    data = entry(name, '09-剧集制作', episode, mode=detail)['data']
    current = next((item for item in data['catalogues']['09-剧集制作']['children'] if item['name'] == episode), None)
    if current is None:
        raise HTTPException(404, '剧集不存在')
    previous = None
    if episode.startswith('EP') and int(episode[2:]) > 1:
        previous_id = 'EP' + str(int(episode[2:]) - 1).zfill(len(episode) - 2)
        prior = entry(name, '09-剧集制作', previous_id, mode='ending' if detail == 'playback' else 'full')['data']['catalogues']['09-剧集制作']['children']
        if prior:
            item = prior[0]
            scene = next(reversed(item.get('scenes', [])), '')
            previous = {'name': previous_id, 'scenes': [scene] if scene else [],
                        'segments': {scene: item['segments'][scene]} if scene else {}}
    return view({**current, 'previousEpisode': previous, 'warnings': data['warnings']}, name)


@app.get('/api/projects/{name}/episodes/{episode}/contexts/{candidate}')
def generation_context(name: str, episode: Episode, candidate: str) -> dict[str, Any]:
    return view(entry(name, '09-剧集制作', episode, candidate=candidate)['data']['context'], name)


@app.get('/api/projects/{name}/episodes/{episode}/download')
def completed_episode_download(name: str, episode: Episode):
    try:
        files = completed_episode_videos(store, name, episode, entry(name, '09-剧集制作', episode, mode='playback')['data'])
        return zip_response(files, video_archive_name(name, episode))
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get('/api/projects/{name}/episodes/{episode}/downloads')
def episode_download_list(name: str, episode: Episode, scene: Scene | None = None) -> dict[str, Any]:
    try:
        files = episode_resources(store, name, episode, entry(name, '09-剧集制作', episode, mode='playback')['data'], scene)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    prefix = '/api/projects/' + quote(name, safe='') + '/episodes/' + episode + '/downloads/'
    file_prefix = '/api/projects/' + quote(name, safe='') + '/files/'
    return {stage: {kind: {'count': len(items),
                         'url': prefix + quote(stage, safe='') + '/videos' + ('?scene=' + scene if scene else '') if kind == 'videos' and items else None,
                         'files': [] if kind == 'videos' else [
                             {'name': path.name, 'url': file_prefix + quote(path.relative_to(store.project(name)).as_posix(), safe='/') + '?download=true'}
                             for path, _ in items]}
                    for kind, items in groups.items()} for stage, groups in files.items()}


@app.get('/api/projects/{name}/episodes/{episode}/downloads/{stage}/{kind}')
def episode_download(name: str, episode: Episode, stage: Literal['一采', '二采', '后处理'],
                     kind: Literal['videos'], scene: Scene | None = None):
    try:
        files = episode_resources(store, name, episode, entry(name, '09-剧集制作', episode, mode='playback')['data'], scene)[stage][kind]
        if not files:
            raise FileNotFoundError(('本场' if scene else '本集') + '该阶段没有可下载的' + KINDS[kind])
        label = episode if episode in ('片头', '片尾') else f'第{int(episode[2:])}集'
        filename = f'{name}-{label}-{scene}-{stage}-已采用视频.zip' if scene else video_archive_name(name, episode)
        return zip_response(files, filename)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get('/api/projects/{name}/document')
def document(name: str, path: Annotated[str, Query()]) -> dict[str, Any]:
    try:
        target = store.file(name, path)
        if target.suffix.lower() == '.md':
            return view(parser.document_preview(target.read_text('utf-8-sig'), path), name)
        if target.suffix.lower() in ('.json', '.txt', '.log'):
            return parser.plain_text_preview(target)[0]
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    raise HTTPException(404, '没有可用的文档预览，请打开原文件')


@app.get('/api/projects/{name}/files/{path:path}')
def project_file(name: str, path: str, request: Request, v: str | None = None, download: bool = False):
    try:
        target = store.file(name, path, v)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    response = FileResponse(target, filename=target.name if download else None,
                            media_type='application/octet-stream' if download else None)
    if v and not download and target.suffix.lower() in {'.mp4', '.webm', '.mov'}:
        stat = target.stat()
        if v == f'{stat.st_mtime_ns}-{stat.st_size}':
            response.stat_result = stat
            response.set_stat_headers(stat)
            response.headers['Cache-Control'] = 'private, no-cache'
            tags = [tag.strip().removeprefix('W/') for tag in request.headers.get('if-none-match', '').split(',')]
            if response.headers['etag'] in tags or '*' in tags:
                return Response(status_code=304, headers={key: response.headers[key] for key in ('cache-control', 'etag', 'last-modified')})
    return response


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


@app.put('/api/projects/{name}/revision-notes/{episode}/{scene}/export')
def save_revision_export(name: str, episode: Episode, scene: Scene, value: ExportChanges, request: Request) -> SceneNotes:
    if not local_write_request(request):
        raise HTTPException(403, '修改意见仅限本机或局域网地址，并要求同源请求')
    try:
        return revision_notes.save_export(store.project(name), episode, scene, value)
    except NotesChangedError as error:
        raise HTTPException(409, str(error)) from error
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


@app.get('/api/component-samples/file')
def component_sample_file(download: bool = False) -> Response:
    return Response('公共组件下载示例。此文件不包含项目资料。\n', media_type='text/plain',
                    headers={'Content-Disposition': ('attachment' if download else 'inline') + '; filename="component-sample.txt"'})


@app.get('/api/history')
def history() -> list[dict[str, str]]:
    root = TOOL / 'docs'
    return [{'path': p.relative_to(root).as_posix(), 'name': p.stem}
            for p in sorted(root.rglob('*.md')) if not p.is_relative_to(root / '归档')]


@app.get('/api/history/document')
def history_document(path: Annotated[str, Query()], page: Annotated[int, Query(ge=1)] = 1) -> dict[str, str | int]:
    root = TOOL / 'docs'
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix != '.md' or not target.is_file():
        raise HTTPException(404, '记录不存在')
    text = target.read_text('utf-8')
    if path == '版本记录.md':
        introduction, *entries = re.split(r'(?m)(?=^### )', text)
        page_size = 10
        total = len(entries)
        page = min(page, max(1, (total + page_size - 1) // page_size))
        start = (page - 1) * page_size
        return {'title': target.stem, 'html': parser.markdown(introduction + ''.join(entries[start:start + page_size]), path),
                'page': page, 'pageSize': page_size, 'total': total}
    return {'title': target.stem, 'html': parser.markdown(text, path)}


app.frontend('/', directory=TOOL / 'frontend/dist', fallback='index.html')
