"""Automatic, resumable closeout of downloaded candidates and approved image upscales."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, unquote

from backend.services.execution_checks import write_json
from backend.services.result_summary import batch_tasks, summary, outputs as collected_outputs
from project_paths import project_file
from video_adopt import field

REPORT = '结果收尾报告.json'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def relative(base, target):
    return os.path.relpath(target, base.parent).replace('\\', '/').replace(' ', '%20')


def register(store, key):
    data, state = store.rows[key]['input'], store.rows[key]['state']
    if state['status'] != 'completed' or state['collected'] != state['expected']:
        raise ValueError('只有全部成果取回的任务可以登记待审')
    if not data.task_type.startswith('video-'):
        from backend.services.image_closeout import register as register_image
        return register_image(store, key, collected_outputs(store, key), Path(data.record_dir) / REPORT)
    root, record = Path(data.project), Path(data.record_dir)
    report_file = record / REPORT
    previous = json.loads(report_file.read_text('utf-8')) if report_file.exists() else {}
    if previous and (previous.get('task_id') != key or previous.get('prompt_id') != state['prompt_id']):
        raise ValueError('收尾报告不属于本次执行，不覆盖')
    for name, info in previous.get('probes', {}).items():
        current = project_file(root, name).stat()
        if [current.st_size,current.st_mtime_ns] != info['stamp']:
            raise ValueError('已读取媒体信息的视频发生变化，不复用旧测量：'+name)
    if previous.get('status') == 'registered':
        return previous
    stamp = previous.get('recorded_at') or store.client.now()
    outputs = collected_outputs(store, key)
    if len(outputs) != state['expected']:
        raise ValueError('成果摘要不完整，先核对取回记录')
    from backend.services.comfy_tasks import SKILL
    template_file = SKILL / 'references/模板/视频人工审阅区模板.md'
    template = re.search(r'```markdown\n(.*?)\n```', template_file.read_text('utf-8-sig'), re.S)[1]
    edits, items = {}, []
    probes = previous.get('probes', {})
    for output in outputs:
        candidate = project_file(root, output['path'], recorded=True)
        identity = output['identity']
        if not output.get('review'):
            raise ValueError('取回记录没有可登记的分段身份：' + identity)
        ep, scene, part, revision, stage = (output['review'][name] for name in ('episode', 'scene', 'part', 'revision', 'stage'))
        receipt = project_file(root, output['receipt'], recorded=True)
        # Downloads already established technical identity. No rehash or remote query.
        if not candidate.is_file() or not receipt.is_file():
            raise ValueError('成果或取回凭据缺失：' + identity)
        metadata = None
        if data.video_plan is not None:
            from backend.services.video_records import probe
            if data.video_plan['metadata'] != 'ffprobe':
                raise ValueError('视频媒体信息计划必须使用ffprobe')
            if output['path'] not in probes:
                probes[output['path']] = probe(candidate)
                previous.update(task_id=key, prompt_id=state['prompt_id'], recorded_at=stamp, status='measuring', probes=probes)
                write_json(report_file, previous)
            metadata = probes[output['path']]
        draft = root / '09-剧集制作' / ep / '其他资料/工作稿' / f'{ep}-{scene}-{part}-视频制作-工作稿.md'
        if not draft.is_file():
            raise ValueError('缺少已准备的分段工作稿：' + identity)
        original = draft.read_text('utf-8-sig')
        text = original
        marker = '<!-- result:' + state['prompt_id'] + ':' + identity + ' -->'
        link = f'[{candidate.name}]({relative(draft, candidate)})'
        proof = f'[取回凭据]({relative(draft, receipt)})'
        if marker not in text:
            area = re.search(r'^### ' + re.escape(revision + '-' + stage) + r'\s*$.*?(?=^#{1,3} |\Z)', text, re.M | re.S)
            if not area or len(re.findall(r'^### ' + re.escape(revision + '-' + stage) + r'\s*$', text, re.M)) != 1:
                raise ValueError('缺少本轮执行章节：' + identity)
            body = area[0]
            body = field(body, '输出当前入口及取回／展示情况', link + '；网页集中审核。')
            body = field(body, '远端实际输出信息与本地输出的对应关系', proof)
            body = field(body, '取回核对状态', '已取回；内容由用户人工审核。')
            if metadata is not None:
                measured = '[媒体信息]('+relative(draft, report_file)+')'
                seconds = metadata['duration']
                duration = str(seconds)+'秒' if seconds is not None else '容器未提供'
                if seconds is not None and seconds > 60:
                    duration += '（'+str(int(seconds//60))+'分'+format(seconds%60,'.6f').rstrip('0').rstrip('.')+'秒）'
                body = field(body, '实测时长及数值来源', duration+'；'+measured)
                body = field(body, '实际尺寸及数值来源', f"{metadata['width']}×{metadata['height']}；"+measured)
                body = field(body, '实际帧率及数值来源', (str(metadata['frame_rate'])+'fps' if metadata['frame_rate'] is not None else '容器未提供帧率')+'；'+measured)
                body = field(body, '实际平均码率及数值来源', f"视频轨{metadata['video_mbps'] if metadata['video_mbps'] is not None else '未提供'}Mbps；文件总{metadata['total_mbps'] if metadata['total_mbps'] is not None else '未提供'}Mbps；"+measured)
                body = field(body, '音轨情况及信息来源', (f"{len(metadata['audio'])}条音轨" if metadata['audio'] else '无音轨')+'；'+measured)
            body = field(body, '共同任务证据与状态入口',
                         f'[后台共同状态]({relative(draft, record / "后台任务状态.json")})')
            if output is outputs[0]:
                body = field(body, '任务状态', 'completed；全部预期成果已保存；人工决定见审阅区。')
                body = field(body, '最近检查时间', stamp)
            else:
                body = re.sub(r'^- (任务状态|最近检查时间)：[^\n]*\n?', '', body, flags=re.M)
            body = body.rstrip() + '\n' + marker + '\n\n'
            text = text[:area.start()] + body + text[area.end():]
        reviews = [m[0] for m in re.finditer(r'^### 审阅-.*?(?=^#{1,3} |\Z)', text, re.M | re.S)]
        has_review = any(any(candidate.name in value for value in re.findall(
            r'^- (?:被审[^：\n]*|对应具体输出)：([^\n]*)', body, re.M)) for body in reviews)
        if not has_review:
            review = re.sub(r'^### .*', '### 审阅-' + revision + '-' + stage + '-001', template, count=1)
            values = {'所属分段／场次／整集': f'{ep}-{scene}-{part}', '处理阶段或成片类型': stage,
                      '被审具体输出文件及R编号／版本': link + '；' + revision,
                      '来源任务或执行记录入口': proof + '；远端任务：' + state['prompt_id'],
                      'agent取回及展示入口': '网页剧集制作集中审核；' + identity,
                      '决定': '待审核', '对应具体输出': link, '批准或要求修改的范围': '尚未决定',
                      '决定时间与依据': '未批准；登记时间：' + stamp,
                      '当前候选／选定入口': link, '用户要求的后续处理及授权范围': '按原授权；登记不授权新生成或后处理',
                      '移动或替代关系及对应记录入口': '未移动、未替换旧版本',
                      '受影响的分段、场次或整集版本及处理决定': identity,
                      '其他补充': '技术取回成功不代表内容获批'}
            for name, value in values.items():
                review = re.sub(r'^- ' + re.escape(name) + r'：[^\n]*', lambda _: '- ' + name + '：' + value, review, flags=re.M)
            text = text.rstrip() + '\n\n' + review + '\n'
        edits[draft] = (original, text)
        items.append({'identity': identity, 'path': output['path'], 'receipt': output['receipt'],
                      'draft': draft.relative_to(root).as_posix(), 'episode': ep, 'metadata': metadata})
    old_files = previous.get('files', {})
    files = {}
    for path, (before, after) in edits.items():
        before_digest = digest(before)
        files[path.relative_to(root).as_posix()] = {'before': before_digest,
            'after': digest(after) if after != before else before_digest}
    for path, (before, _) in edits.items():
        old = old_files.get(path.relative_to(root).as_posix())
        if old and files[path.relative_to(root).as_posix()]['before'] not in old.values():
            raise ValueError('登记期间源资料已被修改，请核对：' + str(path))
    report = {'task_id': key, 'prompt_id': state['prompt_id'], 'recorded_at': stamp,
              'status': 'registering', 'files': files, 'items': items, 'probes': probes}
    write_json(report_file, report)
    for path, (before, after) in edits.items():
        if before == after:
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent,
                                             prefix='.nora-result-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(after)
            if path.read_text('utf-8-sig') != before:
                raise ValueError('源资料并发变化，未覆盖：' + str(path))
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    report['status'] = 'registered'
    report['registered_at'] = store.client.now()
    write_json(report_file, report)
    return report


def verify(projects, store, key, report):
    data, state = store.rows[key]['input'], store.rows[key]['state']
    name = state['project']
    entry = projects.get(name, synchronize=True)
    status = projects.status(name)
    if status['updating'] or status['checking'] or status['error']:
        raise ValueError('源资料已登记，网页尚未同步：' + str(status['error']))
    images = [item for item in report['items'] if item.get('image')]
    image_groups = {}
    for item in images:
        parts = Path(item['draft']).parts
        image_groups.setdefault((parts[0], parts[1] if parts[0] == '09-剧集制作' else None), []).append(item)
    for (scope, episode), members in image_groups.items():
        parsed = projects.section(name, scope, episode)
        found = set()
        def image_entries(value):
            if isinstance(value, dict):
                if value.get('key'):
                    found.add(unquote(value['key']))
                for child in value.values(): image_entries(child)
            elif isinstance(value, list):
                for child in value: image_entries(child)
        if scope in ('03-人物资料', '04-场景资料', '05-道具资料'):
            # A loose file in the directory is not a registered review/formal asset.
            for collection in ('people', 'scenes', 'props'):
                for asset in parsed.get(collection, []):
                    if any(asset.get('recordKey') == item['draft'] for item in members):
                        image_entries(asset.get('candidates', []))
                        image_entries(asset.get('formal', []))
                        image_entries(asset.get('auxiliary', []))
        else:
            image_entries(parsed)
        for item in members:
            if item.get('display_path', item['path']) not in found:
                raise ValueError('源资料已登记，网页缺少本批图片：' + item['path'])
    for ep in dict.fromkeys(item['episode'] for item in report['items'] if not item.get('image')):
        parsed = projects.section(name, '09-剧集制作', ep, mode='playback')
        found = set()
        def walk(value):
            if isinstance(value, dict):
                if value.get('productionIssues'):
                    raise ValueError('源资料已登记，网页制作资料需要修正：' + '；'.join(
                        issue['key'] + '：' + issue['message'] for issue in value['productionIssues']))
                if value.get('run') and value.get('stage') and value.get('url'):
                    found.add(unquote(value['url']))
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(parsed)
        for item in report['items']:
            if item.get('episode') == ep and not any(item['path'] in path for path in found):
                raise ValueError('源资料已登记，网页缺少本批候选：' + item['identity'])
    return {'status': 'verified', 'verified_at': store.client.now(), 'revision': status['revision'], 'updated': status['updated'],
            'review_path': '/#/projects/' + quote(name, safe='')}


def apply_record_updates(store, key, updates, episodes, report=None):
    """Journal exact Agent wording in the existing report, resume only unfinished edits."""
    root = Path(store.rows[key]['input'].project)
    report_file = Path(store.rows[key]['input'].record_dir) / REPORT
    if report is None:
        report = json.loads(report_file.read_text('utf-8'))
    journal = report.get('record_updates', {})
    if not updates:
        if journal.get('status') != 'applying':
            return journal.get('fingerprint')
        updates = journal['updates']
    fingerprint = digest(json.dumps(updates, ensure_ascii=False, sort_keys=True))
    if journal.get('fingerprint') == fingerprint and journal.get('status') == 'completed':
        return fingerprint
    if journal.get('status') == 'applying' and journal.get('fingerprint') != fingerprint:
        raise ValueError('先恢复原业务更新，不接受另一份更新覆盖未完成记录')
    edits, before_digests = {}, {}
    for update in updates:
        if set(update) != {'path', 'old', 'new'} or not all(isinstance(value, str) and value for value in update.values()):
            raise ValueError('业务更新须提供 path、old、new，且不得为空')
        path = project_file(root, update['path'])
        if path == root / '项目进度.md':
            if not any(re.search(r'\b' + re.escape(ep) + r'\b', update['old']) for ep in episodes):
                raise ValueError('项目进度更新必须明确属于本批剧集')
        elif not any(path.is_relative_to(root / '09-剧集制作' / ep) for ep in episodes) or not (
                '01-制作前检查' in path.parts or path.name.endswith('生成说明-工作稿.md')):
            raise ValueError('业务更新仅用于本批项目进度、制作前检查及生成说明工作稿')
        if path not in edits:
            before = path.read_text('utf-8-sig')
            edits[path] = before, before
            before_digests[path] = digest(before)
        before, current = edits[path]
        saved = journal.get('files', {}).get(path.relative_to(root).as_posix()) if journal.get('fingerprint') == fingerprint else None
        if saved and before_digests[path] == saved['after']:
            continue
        if saved and before_digests[path] != saved['before']:
            raise ValueError('业务登记中断后源资料已变化：' + str(path))
        if current.count(update['old']) != 1:
            raise ValueError('业务更新原文不唯一或已变化：' + str(path))
        edits[path] = before, current.replace(update['old'], update['new'], 1)
    journal = {'fingerprint': fingerprint, 'status': 'applying', 'updates': updates,
               'files': {path.relative_to(root).as_posix(): {'before': before_digests[path], 'after': digest(after) if after != before else before_digests[path]}
                         for path, (before, after) in edits.items()}}
    report['record_updates'] = journal
    write_json(report_file, report)
    for path, (before, after) in edits.items():
        if before == after:
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent,
                                             prefix='.nora-result-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(after)
            if path.read_text('utf-8-sig') != before:
                raise ValueError('业务记录并发变化，未覆盖：' + str(path))
            temporary.replace(path)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
    journal['status'] = 'completed'
    write_json(report_file, report)
    return fingerprint


async def closeout(store, projects, batch_id, thread_id, record_updates=(), image_plans=None):
    ids, _ = batch_tasks(store, batch_id, thread_id)
    for key, plan in (image_plans or {}).items():
        if key not in ids or store.rows[key]['input'].task_type not in ('image', 'image-upscale'):
            raise ValueError('补充的图片关联必须属于本通知')
        row = store.rows[key]
        existing = row['input'].image_plan or row['state'].get('image_closeout_plan')
        if existing is not None and existing != plan:
            raise ValueError('不得改写已接受的图片收尾关联')
        from backend.services.image_closeout import validate_plan
        validate_plan(row['input'].model_copy(update={'image_plan': plan}))
        store.record(key, 'closeout', 'association_repaired', _changes={'image_closeout_plan': plan})
    return await closeout_tasks(store, projects, ids, record_updates, batch_id=batch_id)


async def closeout_tasks(store, projects, ids, record_updates=(), *, batch_id=None):
    """Internal completion worker; no Agent acknowledgement is required to register."""
    import asyncio
    if record_updates and len({store.rows[key]['state']['project'] for key in ids}) != 1:
        raise ValueError('跨项目通知的业务更新须分项目处理，不接受混合更新')
    reports, groups = [], {}
    for key in ids:
        try:
            report = await asyncio.to_thread(register, store, key)
        except (ValueError, OSError, KeyError, TypeError) as error:
            outcome = {'status': 'registration_failed', 'error': str(error), 'report': REPORT,
                       'retryable': isinstance(error, OSError) and not isinstance(error, (PermissionError, FileNotFoundError))}
            if store.rows[key]['state'].get('closeout') != outcome:
                store.record(key, 'closeout', 'registration_failed', _changes={'closeout': outcome}, error=str(error))
            reports.append({'task_id': key, **outcome})
            continue
        groups.setdefault(store.rows[key]['state']['project'], []).append((key, report))
    for group in groups.values():
        key, owner = group[0]
        combined = {'items': [item for _, report in group for item in report['items']]}
        journal = owner.get('record_updates', {})
        fingerprint = digest(json.dumps(record_updates, ensure_ascii=False, sort_keys=True)) if record_updates else journal.get('fingerprint')
        if journal.get('status') != 'applying' and all(
                store.rows[task]['state'].get('closeout', {}).get('status') == 'completed'
                and (not record_updates or store.rows[task]['state']['closeout'].get('record_updates') == fingerprint)
                for task, _ in group):
            reports.extend({**report, 'browser': store.rows[task]['state']['closeout']['browser'], 'reused': True}
                           for task, report in group)
            continue
        try:
            if record_updates or journal.get('status') == 'applying':
                fingerprint = await asyncio.to_thread(apply_record_updates, store, key, record_updates,
                                        {item['episode'] for item in combined['items'] if not item.get('image')}, owner)
        except (ValueError, OSError, KeyError, TypeError) as error:
            for task, report in group:
                outcome = {'status': 'registration_failed', 'report': REPORT, 'error': str(error)}
                if store.rows[task]['state'].get('closeout') != outcome:
                    store.record(task, 'closeout', 'registration_failed', _changes={'closeout': outcome}, error=str(error))
                reports.append({**report, 'status': 'registration_failed', 'error': str(error)})
            continue
        try:
            browser = await asyncio.to_thread(verify, projects, store, key, combined)
        except (ValueError, OSError, KeyError, RuntimeError) as error:
            for task, report in group:
                outcome = {'status': 'browser_pending', 'report': REPORT, 'error': str(error)}
                if store.rows[task]['state'].get('closeout') != outcome:
                    store.record(task, 'closeout', 'browser_pending', _changes={'closeout': outcome}, error=str(error))
                reports.append({**report, 'browser': {'status': 'pending', 'error': str(error)}})
            continue
        for task, report in group:
            outcome = {'status': 'completed', 'report': REPORT, 'browser': browser, 'record_updates': fingerprint}
            if any(item.get('image') for item in report['items']):
                outcome['display_outputs'] = report['items']
            else:
                outcome['video_outputs'] = report['items']
            store.record(task, 'closeout', 'completed', _changes={'closeout': outcome}, notification_id=batch_id, browser=browser)
            reports.append({**report, 'browser': browser})
    store.refresh_reports(ids)
    return {'notification_id': batch_id, 'results': reports, 'user_message_ready': bool(reports) and all(
        item.get('browser', {}).get('status') == 'verified' for item in reports)}
