"""Durable local FIFO; only the service performs uploads and remote submission."""
import argparse
import asyncio
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import time
import uuid
from websockets.exceptions import WebSocketException

LOCAL = ('local_queued', 'paused')
TERMINAL = ('completed', 'failed', 'rejected', 'collection_failed', 'needs_attention', 'submission_unknown', 'cancelled', 'resolved')


class LocalQueue:
    def queue_init(self):
        self.dispatch_locks = {}
        self.dispatch_workers = {}
        self.dispatch_events = {}
        self.dispatch_event = asyncio.Event()
        self.scheduler = None
        self.drag_leases = {}

    def ordered(self, url=None):
        return sorted((key for key, row in self.rows.items() if row['state']['status'] == 'local_queued'
                       and (url is None or row['input'].url.rstrip('/') == url)),
                      key=lambda key: self.rows[key]['state']['queue_order'])

    def next_order(self, url):
        return max((row['state'].get('queue_order', 0) for row in self.rows.values()
                    if row['input'].url.rstrip('/') == url), default=0) + 1

    def record(self, key, stage, result, *, _changes=None, **details):
        row = self.rows[key]
        if _changes is not None:
            row['state'].update(_changes, updated_at=self.client.now())
            self.persist(key)
        event = {'time': self.client.now(), 'stage': stage, 'result': result, **details}
        event = self.record_paths(key).convert(event, relative=True)
        self.db.execute('INSERT INTO task_events(task_id, event) VALUES (?, ?)',
                        (key, json.dumps(event, ensure_ascii=False)))
        self.db.commit()
        self.write_records(key)
        self.publish()

    def write_records(self, key):
        row = self.rows[key]
        directory = Path(row['input'].record_dir)
        directory.mkdir(parents=True, exist_ok=True)
        prepared = self.completion_input(key)
        if prepared:
            history = directory / '后台过程记录.json'
            checkpoint = row.get('_completion_events') if history.is_file() else None
            last = checkpoint[0] if checkpoint else 0
            added = self.db.execute('SELECT id, event FROM task_events WHERE task_id=? AND id>? ORDER BY id', (key, last)).fetchall()
            if checkpoint is None:
                rendered = json.dumps([json.loads(value) for _, value in added], ensure_ascii=False, indent=2)
                history.write_text(rendered, 'utf-8', newline='')
                raw = rendered.encode('utf-8')
                offset = len(raw) - (2 if added else 1)
                row['_completion_events'] = (added[-1][0] if added else 0, offset)
            elif added:
                # SQLite is authoritative. A restart reconstructs once after an interrupted tail write.
                tail = json.dumps([json.loads(value) for _, value in added], ensure_ascii=False, indent=2)[1:-1].rstrip()
                with history.open('r+b') as stream:
                    stream.seek(checkpoint[1])
                    stream.write(((',' if last else '') + tail + '\n]').encode('utf-8'))
                    stream.truncate()
                    offset = stream.tell() - 2
                row['_completion_events'] = (added[-1][0], offset)
        else:
            events = [json.loads(value) for value, in self.db.execute(
                'SELECT event FROM task_events WHERE task_id=? ORDER BY id', (key,))]
            (directory / '后台过程记录.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), 'utf-8')
        converter = self.record_paths(key)
        summary = {**{name: value for name, value in converter.convert(row['state'], relative=True).items()
                      if name not in ('client_id', 'notices', 'segment_monitor')},
                   'record_dir': converter.relative_file(directory), 'remote_url': row['input'].url,
                   'outputs': (prepared[0] if prepared else self.portable_input(row['input']))['outputs']}
        (directory / '后台任务状态.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')

    async def enqueue(self, data):
        self.resolve_input(data)
        # Registration has no await before saving, so duplicate HTTP arrivals share one durable ID.
        existing = next((key for key, row in self.rows.items()
                         if row['input'].record_dir == data.record_dir), None)
        if existing is not None:
            row = self.rows[existing]
            registered = row['input'].model_copy(update={'url': row['state'].get('enqueued_url', row['input'].url)})
            if registered.model_dump(exclude={'desktop', 'source_session_name'}) != data.model_dump(exclude={'desktop', 'source_session_name'}):
                raise ValueError('执行附件目录已有不同任务，不能重复登记')
            row['input'].desktop = data.desktop
            if data.source_session_name:
                row['state']['source_session_name'] = data.source_session_name
            self.save(existing)
            return {'local_task_id': existing, 'monitor_id': existing, 'monitor': 'browser',
                    'status': row['state']['status'], 'duplicate': True}
        project = self.validate_registration(data)
        key = str(uuid.uuid4())
        now = self.client.now()
        self.rows[key] = {'input': data, 'state': {
            'id': key, 'project': project.name, 'title': data.title, 'task_type': data.task_type,
            'prompt_id': None, 'client_id': str(uuid.uuid4()), 'status': 'paused' if data.start_paused else 'local_queued',
            'preparation_required': True,
            'content_review_required': True,
            'scene_round_required': data.task_type.startswith('video-'),
            'queue_order': self.next_order(data.url.rstrip('/')), 'enqueued_url': data.url,
            'connection': 'waiting', 'progress': None, 'node': None,
            'error': None, 'notification': 'waiting', 'created_at': now, 'started_at': None,
            'collected': 0, 'expected': len(data.segment_plan.targets) if data.segment_plan else len(data.outputs),
            'source_session_name': data.source_session_name}}
        self.record(key, 'enqueue', 'accepted', _changes={})
        self.session_readers[key] = asyncio.create_task(self.read_session_name(key))
        return {'local_task_id': key, 'monitor_id': key, 'monitor': 'browser', 'status': self.rows[key]['state']['status']}

    def active_drag(self, url=None):
        now = time.monotonic()
        self.drag_leases = {key: lease for key, lease in self.drag_leases.items() if lease['expires'] > now}
        return any(url is None or lease['url'] == url for lease in self.drag_leases.values())

    def drag(self, token=None, release=False, url=None):
        self.active_drag()
        if token is None:
            if url is None:
                urls = self.remote_urls()
                if not urls:
                    raise ValueError('尚未配置节点')
                url = urls[0]
            url = self.client.Client(url, 30).url
            if url not in self.remote_urls():
                raise ValueError('节点未配置')
            token = str(uuid.uuid4())
        elif token not in self.drag_leases:
            raise ValueError('拖拽已结束或超时，请重新抓取')
        if release:
            del self.drag_leases[token]
        else:
            node = self.drag_leases[token]['url'] if token in self.drag_leases else url
            self.drag_leases[token] = {'url': node, 'expires': time.monotonic() + 15}
        self.publish()
        return {'token': token}

    def reorder(self, ids, token):
        self.active_drag()
        if token not in self.drag_leases:
            raise ValueError('请先暂停调度再排序')
        url = self.drag_leases[token]['url']
        if len(ids) != len(set(ids)) or set(ids) != set(self.ordered(url)):
            raise ValueError('队列已变化，请刷新后重新排序')
        for position, key in enumerate(ids, 1):
            self.rows[key]['state']['queue_order'] = position
            self.persist(key)
        self.db.commit()
        for key in ids:
            self.record(key, 'reorder', 'saved', position=ids.index(key) + 1)
        self.publish()

    def task_action(self, key, action):
        if key not in self.rows:
            raise ValueError('任务不存在')
        state = self.rows[key]['state']
        if state['status'] not in LOCAL:
            raise ValueError('任务已经提交或结束，不能操作本地排队')
        url = self.rows[key]['input'].url.rstrip('/')
        if self.active_drag(url):
            raise ValueError('正在排序，请放下卡片后再操作')
        if action == 'pause' and state['status'] == 'local_queued':
            self.save(key, status='paused', immediate=False)
        elif action == 'resume' and state['status'] == 'paused':
            self.save(key, status='local_queued', queue_order=self.next_order(url), error=None, immediate=False)
        elif action == 'insert':
            first = min((self.rows[item]['state']['queue_order'] for item in self.ordered(url)), default=1)
            self.save(key, status='local_queued', queue_order=first - 1, error=None, immediate=False)
        elif action == 'immediate':
            self.save(key, status='local_queued', immediate=True, queue_order=self.next_order(url), error=None)
        elif action == 'cancel':
            self.save(key, status='cancelled', ended_at=self.client.now(), error=None)
        else:
            raise ValueError('该状态不支持此操作')
        if action in ('resume', 'insert', 'immediate', 'cancel'):
            for notice in state.get('notices', []):
                if notice['delivery'] == 'pending':
                    notice['delivery'] = 'superseded'
            self.save(key, notification='not_required')
        self.record(key, action, 'accepted')
        return {'local_task_id': key, 'status': state['status']}

    def can_transfer(self, key):
        state = self.rows[key]['state']
        return state['status'] in LOCAL and not state.get('prompt_id') and not state.get('preparation_attempt', 0)

    def transfer(self, key, url):
        if key not in self.rows:
            raise ValueError('任务不存在')
        if not self.can_transfer(key):
            raise ValueError('任务已开始准备、提交或结束，不能转移')
        row = self.rows[key]
        target = self.client.Client(url, row['input'].timeout).url
        if target not in self.remote_urls():
            raise ValueError('目标节点不属于工作区配置')
        source = row['input'].url.rstrip('/')
        if source == target:
            raise ValueError('任务已在该节点队列中')
        if self.active_drag(source) or self.active_drag(target):
            raise ValueError('源节点或目标节点正在排序，请放下卡片后再转移')
        order = self.next_order(target)
        row['state'].setdefault('enqueued_url', row['input'].url)
        row['input'].url = target
        self.record(key, 'transfer', 'accepted', _changes={'queue_order': order, 'immediate': False}, source_url=source, target_url=target, status=row['state']['status'], queue_order=order)
        return {'local_task_id': key, 'status': row['state']['status'], 'remote_url': target}

    async def prepare(self, key):
        row = self.rows[key]
        data = row['input']
        self.record(key, 'preflight', 'started', _changes={'status': 'preparing', 'phase': 'preflight', 'preparation_attempt': row['state'].get('preparation_attempt', 0) + 1})
        # Re-check the endpoint and files at the moment of execution, not just at enqueue time.
        if self.client.Client(data.url, data.timeout).url not in self.remote_urls():
            raise ValueError('节点配置已改变，请核对任务地址')
        workflow = deepcopy(data.workflow)
        transferred = data.url.rstrip('/') != row['state'].get('enqueued_url', data.url).rstrip('/')
        from backend.services import execution_checks as checks
        # Share this opening observation across report, phase and upload baselines.
        # Later transfer/end checks still read fresh states at their own checkpoints.
        checked_files = {}
        report = checks.check_prepared(self, data, bound=row['state'].get('uploads_bound', False), transferred=transferred,
                                       legacy=not row['state'].get('preparation_required', False),
                                       require_content_review=row['state'].get('content_review_required', False),
                                       require_scene_round=row['state'].get('scene_round_required', False), file_stamps=checked_files)
        if report is None:
            result = await asyncio.to_thread(checks.prepare_report, self, data, at_execution=True, previous=None)
            report = {'sources': result['sources']}
            checked_files.update((Path(data.project) / name, tuple(stamp)) for name, stamp in report['sources'].items())
            self.record(key, 'preparation', 'execution_checks', segments=result['checks']['segments'], remote_capabilities='not_queried')
        else:
            self.record(key, 'preparation', 'reused', remote_capabilities='not_queried')
        prepared = row.get('_prepared_run')
        if not prepared:
            for name, stamp in row['state'].get('prepared_files', {}).items():
                path = Path(data.project) / name
                current = checks._file_stamp(path, checked_files)
                if list(current) != stamp:
                    raise ValueError('已保存执行资料发生变化：' + name + '；请核对原执行')
        if prepared:
            for path, stamp in prepared['files'].items():
                current = checks._file_stamp(Path(path), checked_files)
                if current != stamp:
                    raise ValueError('准备资料已变化：' + path + '；请返回准备阶段')
            await self.check_target_cache(key, prepared['workflow'])
            return prepared['workflow']
        uploaded_materials = {}
        upload_cache = {}
        saved_uploads = {}
        upload_bindings = []
        binding_results = []
        remote_url = self.client_for(data).url
        source_digests = row.setdefault('_source_digests', {})
        source_stamps = {}
        documents = {}

        def checked_source(source, uploaded):
            if not isinstance(uploaded, dict) or not {'input_path', 'sha256'}.issubset(uploaded):
                raise ValueError('已有上传凭据缺少文件路径或传输校验信息')
            stamp = source_stamps[source]
            if source not in source_digests:
                with source.open('rb') as stream:
                    source_digests[source] = (stamp, hashlib.file_digest(stream, 'sha256').hexdigest())
            previous, digest = source_digests[source]
            if previous != stamp or digest != uploaded['sha256']:
                raise ValueError('本机素材已不同于原上传凭据，请核对素材版本后创建新的执行')
            return uploaded

        # Recover all completed transfers first, including receipts for later slots.
        # This cache belongs only to this preparation, never another task or endpoint.
        for item in data.uploads:
            source = Path(item['file'])
            if source not in source_stamps:
                source_stamps[source] = checks._file_stamp(source, checked_files)
            receipt = Path(data.record_dir) / item['response-name']
            upload_key = (remote_url, source, item['subfolder'])
            upload_bindings.append((item, source, receipt, upload_key))
            if receipt.exists():
                evidence = self.client.strict_json(receipt.read_bytes())
                if evidence.get('url') != remote_url or evidence.get('ok') is not True:
                    raise ValueError('已有上传凭据不完整，需核对后恢复')
                uploaded = checked_source(source, evidence.get('data'))
                saved_uploads[receipt] = uploaded
                upload_cache.setdefault(upload_key, (uploaded, receipt))

        for item, source, receipt, upload_key in upload_bindings:
            if receipt in saved_uploads:
                uploaded = saved_uploads[receipt]
            elif upload_key in upload_cache:
                uploaded, original_receipt = upload_cache[upload_key]
                self.client.write_new(receipt, {'ok': True, 'url': remote_url, 'time': self.client.now(),
                                                'data': uploaded, 'reused_from': original_receipt.name})
                self.record(key, 'upload', 'reused', file=str(source), remote=uploaded,
                            receipt=str(receipt), reused_from=str(original_receipt))
            else:
                self.record(key, 'upload', 'started', _changes={'phase': 'upload'}, file=str(source), receipt=str(receipt))
                stamp = source_stamps[source]
                uploaded = await asyncio.to_thread(self.client.upload, self.client_for(data),
                                                   argparse.Namespace(file=str(source), subfolder=item['subfolder']), source=source)
                self.client.write_new(receipt, {'ok': True, 'url': self.client_for(data).url,
                                               'time': self.client.now(), 'data': uploaded})
                self.record(key, 'upload', 'success', file=str(source), remote=uploaded)
                current = source.stat()
                if stamp != (current.st_size, current.st_mtime_ns):
                    raise ValueError('本机素材已不同于上传开始时，请核对素材版本后创建新的执行')
                source_digests[source] = (stamp, uploaded['sha256'])
                upload_cache[upload_key] = (uploaded, receipt)
            inputs = workflow[item['node']]['inputs']
            if 'json-path' in item:
                document_key = (item['node'], item['input'])
                if document_key not in documents:
                    documents[document_key] = self.client.strict_json(inputs[item['input']].encode('utf-8'))
                document = documents[document_key]
                parent = document
                try:
                    for part in item['json-path'][:-1]:
                        parent = parent[part]
                    parent[item['json-path'][-1]] = uploaded['input_path']
                    if (workflow[item['node']]['class_type'] == 'MiniMaxH3Director'
                            and item['input'] == 'timeline_data'
                            and item['json-path'][0] in ('global', 'segments')):
                        path = item['json-path']
                        workspace = document['batchWorkspaces']['r2v']
                        editor = workspace['globalCommon'] if path[0] == 'global' else workspace['segments'][path[1]]
                        for part in path[1:-1] if path[0] == 'global' else path[2:-1]:
                            editor = editor[part]
                        editor[path[-1]] = uploaded['input_path']
                        remote = uploaded['remote']
                        for media in (parent, editor):
                            media.update(fileName=remote['name'], subfolder=remote['subfolder'], type=remote['type'])
                except (KeyError, IndexError, TypeError) as error:
                    raise ValueError('素材JSON字段路径不匹配：' + str(item['json-path'])) from error
            else:
                inputs[item['input']] = uploaded['input_path']
            uploaded_materials[uploaded['input_path']] = {'input_path': uploaded['input_path'], 'file': str(source)}
            binding_results.append((item, uploaded))
        for (node, field), document in documents.items():
            workflow[node]['inputs'][field] = json.dumps(document, ensure_ascii=False, allow_nan=False)
        await self.check_target_cache(key, workflow)
        if data.task_type.startswith('video-') or (data.image_plan is not None and list(Path(data.record_dir).glob('*.api.json'))):
            from backend.services.director_uploads import save_uploaded_workflow
            from project_paths import PreparationPaths
            # Address reuse belongs to this save phase; each IO still checks scope.
            path_scope = PreparationPaths.from_resolved(data.project,
                            [data.record_dir, *(item['file'] for item in data.uploads)])
            self.save(key, phase='upload_binding')
            await asyncio.to_thread(save_uploaded_workflow, data.project, Path(data.record_dir), data.workflow, workflow,
                                    uploaded_materials, binding_results, path_scope=path_scope)
            self.record(key, 'upload_binding', 'success', _changes={'uploads_bound': True})
        if data.task_type.startswith('video-'):
            self.save(key, phase='generation_context')
            await asyncio.to_thread(self.generation_context.prepare_generation_context,
                                    data.project, Path(data.record_dir), workflow, data.task_type, uploaded_materials,
                                    fixed_checked=True, path_scope=path_scope)
        # This checkpoint is process-local; a restart verifies durable receipts once.
        files = {Path(item['file']) for item in data.uploads}
        record = Path(data.record_dir)
        files.update(record.glob('*.api.json'))
        files.update(record.glob('*.workflow.json'))
        mapping_file = record / '输入映射.json'
        if mapping_file.exists():
            files.add(mapping_file)
            mapping = json.loads(mapping_file.read_text('utf-8-sig'))
            for context in mapping.get('generation_contexts', []):
                files.update(Path(data.project) / name for name in context.get('prompts', {}).values())
                if context.get('storyboard'):
                    files.add(Path(data.project) / context['storyboard']['file'])
                files.update(Path(data.project) / ref['file'] for refs in context.get('references', {}).values() for ref in refs)
        final_stamps = {str(path): (stamp.st_size, stamp.st_mtime_ns) for path in files for stamp in [path.stat()]}
        for source, stamp in source_stamps.items():
            if final_stamps[str(source)] != stamp:
                raise ValueError('本机素材已不同于上传／核验时，请返回准备阶段')
        phase_files = {name: stamp for name, stamp in final_stamps.items()
                       if Path(name).relative_to(data.project).as_posix() not in report['sources']
                       or name.endswith(('.api.json', '.workflow.json'))}
        row['_prepared_run'] = {'workflow': workflow, 'files': phase_files}
        self.record(key, 'preflight', 'success', _changes={'prepared_files': {
            Path(name).relative_to(data.project).as_posix(): list(stamp) for name, stamp in phase_files.items()}})
        return workflow

    async def check_target_cache(self, key, workflow):
        data = self.rows[key]['input']
        if data.task_type in ('video-first-pass', 'video-second-pass'):
            self.save(key, phase='target_cache')
            for node_id, node in workflow.items():
                if node['class_type'] != 'MiniMaxH3Director':
                    continue
                inputs = node['inputs']
                payload = {name: inputs[name] for name in (
                    'timeline_data', 'task_type', 'global_prompt', 'total_frames', 'frame_rate', 'width', 'height',
                    'ref_max_size', 'seed', 'cfg', 'steps', 'sampler', 'scheduler', 'shift_video', 'shift_audio') if name in inputs}
                payload.update(node_id=node_id, cache_name=inputs.get('cache_name', ''), sigmas_linked='sigmas' in inputs)
                for name in ('refine', 'selflift', 'semantic_bridge'):
                    if name in inputs:
                        pack = workflow[inputs[name][0]]['inputs']
                        payload[name] = {field: value for field, value in pack.items() if not isinstance(value, list)}
                        payload[name]['has_sigmas_tensor'] = 'sigmas' in pack
                result = await asyncio.to_thread(self.client_for(data).json, '/minimax/director/first_pass_cache_status',
                    json.dumps(payload, ensure_ascii=False).encode('utf8'), {'Content-Type': 'application/json'})
                self.record(key, 'target_cache', 'checked', url=data.url, response=result)
                if type(result.get('can_confirm_refine')) is not bool:
                    raise ValueError('阶段缓存状态不明确；未提交生成，请核对原任务')
                if data.task_type == 'video-second-pass' and result.get('can_confirm_refine') is not True:
                    raise ValueError('目标节点的一采缓存缺失或不匹配，不能执行二采；请核对来源缓存后处理，不会自动重做一采')
                if data.task_type == 'video-first-pass' and (result.get('can_confirm_refine') is True
                        or result.get('selected_matched', 0) > 0):
                    raise ValueError('目标节点已有匹配的一采缓存，当前工作流会进入二采；请先核对目标节点缓存与任务阶段')
                timeline = json.loads(inputs['timeline_data'])
                if timeline.get('runSelectEnabled'):
                    selected = set(timeline['runSelection'])
                    cached = {item['index']: item for item in result['segments']}
                    for index in selected:
                        if index and index - 1 not in selected and timeline['segments'][index].get('continuityFromPrev'):
                            previous = cached.get(index - 1, {})
                            matches = previous.get('final_matches') is True
                            if data.task_type == 'video-first-pass' and not matches:
                                differences = previous.get('final_diff_keys', [])
                                # First-pass guide uses the matching pre-refine source. A change
                                # confined to Refine settings does not invalidate that source.
                                matches = (previous.get('exists') is True and previous.get('matches') is True
                                           and previous.get('final_exists') is True and bool(differences)
                                           and all(name.startswith('refine_') for name in differences))
                            if not matches:
                                raise ValueError('目标节点缺少匹配的前段衔接缓存：组序 ' + str(index - 1))

    async def dispatch_once(self):
        await asyncio.gather(*(self.dispatch_node(url) for url in self.remote_urls()))

    async def dispatch_node(self, url):
        async with self.dispatch_locks.setdefault(url, asyncio.Lock()):
            if self.active_drag(url):
                return
            ids = self.ordered(url)
            ids.sort(key=lambda key: not self.rows[key]['state'].get('immediate', False))
            for key in ids:
                row = self.rows[key]
                node = self.remote_queues.states.get(url)
                if not node or node['connection'] != 'connected' or node['queue_error'] or not node['updated_at']:
                    continue
                immediate = row['state'].get('immediate', False)
                if not immediate and (node['running_count'] or node['queued_count']):
                    continue
                # Recovery/monitoring of accepted IDs precedes another automatic submission.
                active = [other for other, item in self.rows.items() if other != key
                          and self.client_for(item['input']).url == url and item['state'].get('prompt_id')
                          and item['state']['status'] in ('queued', 'running')]
                if not immediate:
                    for other in active:
                        await self.reconcile(other, background_collection=True)
                try:
                    workflow = await self.prepare(key)
                    await self.remote_queues.refresh(url)
                    fresh = self.remote_queues.states[url]
                    if (fresh['connection'] != 'connected' or fresh['queue_error']
                            or not immediate and (fresh['running_count'] or fresh['queued_count'])):
                        self.record(key, 'dispatch', 'waiting_remote', _changes={'status': 'local_queued'})
                        return
                    await self.submit(row['input'], key=key, workflow=workflow)
                except (self.client.ClientError, OSError, ValueError, RuntimeError, WebSocketException) as error:
                    phase = row['state'].get('phase', 'dispatch')
                    if row['state']['status'] not in ('rejected', 'submission_unknown'):
                        self.save(key, status='paused', error=str(error), immediate=False, failure_stage=phase)
                    if phase != 'submit':
                        self.record(key, phase, 'failed', error=str(error))
                    if row['state']['status'] not in ('rejected', 'submission_unknown'):
                        self.queue_notice(key, 'dispatch_issue', 'attention', str(error))
                return

    async def schedule(self):
        while True:
            self.dispatch_event.clear()
            for url in self.remote_urls():
                if url not in self.dispatch_workers:
                    self.dispatch_events[url] = asyncio.Event()
                    self.dispatch_workers[url] = asyncio.create_task(self.schedule_node(url))
            try:
                await asyncio.wait_for(self.dispatch_event.wait(), 30)
            except asyncio.TimeoutError:
                continue

    async def schedule_node(self, url):
        event = self.dispatch_events[url]
        while True:
            event.clear()
            try:
                await self.dispatch_node(url)
            except (self.client.ClientError, OSError, ValueError) as error:
                import logging
                logging.getLogger(__name__).warning('Local dispatch postponed for %s: %s', url, error)
            try:
                await asyncio.wait_for(event.wait(), 5 if self.active_drag(url) else 30)
            except asyncio.TimeoutError:
                continue

    async def retry_collection(self, key):
        if key not in self.rows or self.rows[key]['state']['status'] != 'collection_failed':
            raise ValueError('只有取回失败的任务可以重试取回')
        state = self.rows[key]['state']
        self.record(key, 'collection_retry', 'accepted', _changes={'status': 'collecting', 'error': None, 'collection_attempt': state.get('collection_attempt', 1) + 1, 'collection_auto_retry': 0, 'collection_next_retry_at': None, 'collection_retry_stop': None, 'collection_errors': []})
        self.workers[key] = asyncio.create_task(self.collect_saved(key))
        return {'local_task_id': key, 'status': 'collecting'}

    async def collect_saved(self, key, result=None):
        data = self.rows[key]['input']
        try:
            if result is None:
                result = self.client.strict_json((Path(data.record_dir) / data.history_name).read_bytes())['data']
            await self.finish_collection(key, result)
        except (self.client.ClientError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            self.record(key, 'collection', 'failed', _changes={'status': 'collection_failed', 'error': str(error),
                        'failure_stage': 'collection', 'collection_retry_stop': 'requires_attention'}, error=str(error))
        self.queue_notice(key, 'terminal', 'terminal', self.rows[key]['state'].get('error') or '预期成果已保存')
