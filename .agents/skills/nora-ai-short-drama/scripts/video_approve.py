#!/usr/bin/env python3
"""一次落实明确的视频批准、阶段留档、业务进度及网页核对；不生成媒体。"""
import argparse
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import video_adopt as adopt
import scene_finalize as final


def indexed_parts(root, episode):
    path = root / '09-剧集制作' / episode / '03-分镜脚本' / (episode + '-分镜索引.md')
    return re.findall(r'^\| (' + re.escape(episode) + r'-C\d{3}) \|[^\n]*?\| ('
                      + re.escape(episode) + r'-C\d{3}-P\d{3}) \|', path.read_text('utf-8-sig'), re.M)


def selected(root, part, stage):
    draft = root / '09-剧集制作' / part.split('-')[0] / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
    text = draft.read_text('utf-8-sig')
    _, _, row = adopt.selected_row(text, stage)
    names = re.findall(re.escape(part) + r'-R\d{3}-' + stage + r'\.\w+', row)
    anchors = re.findall(r'\]\(#([^)]*)\)', row.strip().strip('|').split('|')[-1])
    approved = names and len(anchors) == 1 and adopt.approved_row(text, names[0] + ' [审核](#' + anchors[0] + ')', names[0])
    return Path(names[0]).stem if approved else None


def source_items(root, plan, stage):
    """Only use the explicitly supplied submission plans, never latest-R scans."""
    found = {}
    task_type = {'一采': 'video-first-pass', '二采': 'video-second-pass', '后处理': 'video-postprocess'}[stage]
    for name in plan['submission_plans']:
        for task in adopt.load(adopt.local_path(root, name))['tasks']:
            if task['task_type'] != task_type:
                continue
            record = adopt.local_path(root, task['record_dir'])
            mapping_path = record / '输入映射.json'
            mapping = adopt.load(mapping_path)
            execution = adopt.execution_metadata(root, mapping_path, mapping)
            for index in mapping['selected_indices']:
                entry = mapping['segments'][index]
                identity = entry['segment'] + '-' + entry['round'] + '-' + stage
                if identity not in {c['identity'] for c in mapping['generation_contexts']}:
                    raise ValueError('提交清单的实际执行阶段与本次批准阶段不符：' + identity)
                output = next(o for o in execution['outputs'] if o['identity'] == identity)
                item = {'identity': identity, 'mapping': str(mapping_path), 'receipt': output['receipt'],
                        'api': str(record / '任务.api.json'), 'canvas': str(record / '任务.workflow.json')}
                if identity in found and found[identity] != item:
                    raise ValueError('同一批准身份存在不同执行来源：' + identity)
                found[identity] = item
    return found


def record_updates(root, episode, summary):
    """Adoption requires both business entrances; the final status is written below."""
    updates = []
    for path in (summary, root / '项目进度.md'):
        first = path.read_text('utf-8-sig').splitlines()[0]
        updates.append({'path': str(path), 'old': first, 'new': first})
    return updates


def episode_missing(root, episode):
    """Check current approvals against existing finalization records, not newest files."""
    missing, records = [], {}
    for scene, part in indexed_parts(root, episode):
        draft = root / '09-剧集制作' / episode / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
        text = draft.read_text('utf-8-sig')
        for stage in adopt.STAGES:
            identity = selected(root, part, stage)
            if identity is None:
                missing.append(part + ' ' + stage + '未采用')
                continue
            headings = re.findall(r'^### (定稿留档-' + re.escape(scene + '-' + stage) + r'[^\n]*)$', text, re.M)
            covered = False
            for heading in headings:
                a, b = adopt.section(text, heading)
                for link in re.findall(r'\[留档记录\]\(([^)]+)\)', text[a:b]):
                    path = adopt.local_path(root, draft.parent / urllib.parse.unquote(link))
                    if path not in records:
                        records[path] = adopt.load(path)
                    record = records[path]
                    if (record['state'] == 'completed' and identity in {s['identity'] for s in record['sources']}
                            and all(adopt.local_path(root, record[k]).is_file() for k in ('pack', 'canvas'))):
                        covered = True
            if not covered:
                missing.append(identity + '缺少当前版本定稿留档')
    return missing


def update_business(root, episode, scene, stage, summary, identities, finalized, complete):
    status = (episode + '分段制作与交付已完成。' if complete else
              scene + '的' + stage + '已采用' + str(len(identities)) + '段；'
              + ('本场该阶段定稿留档完成。' if finalized else '本场该阶段定稿尚未完成。'))
    text = summary.read_text('utf-8-sig')
    if re.search(r'^- 当前状态及待办：', text, re.M):
        text = re.sub(r'^- 当前状态及待办：[^\n]*', '- 当前状态及待办：' + status, text, count=1, flags=re.M)
    else:
        first, _, rest = text.partition('\n')
        text = first + '\n\n- 当前状态及待办：' + status + '\n' + rest
    heading = '批准收尾-' + scene + '-' + stage
    folder = root / '09-剧集制作' / episode / '06-阶段采用视频' / adopt.STAGES[stage] / (scene.split('-')[1] + '-场次')
    body = '\n- 状态：' + status + '\n- 当前采用顺序：' + ' → '.join(identities) + '\n- 文件入口：[阶段采用视频](' + adopt.link(summary, folder) + ')\n'
    if re.search(r'^### ' + re.escape(heading) + r'\s*$', text, re.M):
        a, b = adopt.section(text, heading)
        text = text[:a] + body + '\n' + text[b:]
    else:
        text = text.rstrip() + '\n\n### ' + heading + '\n' + body
    final.replace_file(summary, text)
    progress = root / '项目进度.md'
    text = progress.read_text('utf-8-sig')
    rows = re.findall(r'^\| ' + re.escape(episode) + r'制作 \|[^\n]*', text, re.M)
    if len(rows) != 1:
        raise ValueError('项目进度缺少唯一的' + episode + '制作行；采用和留档事实已保留')
    cells = rows[0].split('|')
    cells[3] = ' 已完成 ' if complete else ' 进行中 '
    cells[4] = ' - [' + scene + stage + '采用视频](' + adopt.link(progress, folder) + ') '
    cells[5] = ' - 分段制作与交付完成 ' if complete else ' - ' + status + ' '
    cells[6] = ' - 下一集等待用户安排 ' if complete else ' - 后续阶段按实际批准及执行授权安排 '
    final.replace_file(progress, text.replace(rows[0], '|'.join(cells), 1))


def browser_sync(root, episode, stage, identities, complete, timeout):
    config = adopt.load(root.parent.parent / '工作区浏览服务/runtime/task-service.json')
    base = config['url'].rstrip('/')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(route):
        with opener.open(base + route, timeout=timeout) as response:
            return json.load(response)

    service = get('/api/service')
    if not service['ready'] or Path(service['workspace']).resolve() != root.parent.parent:
        raise ValueError('浏览服务未就绪或读取了其他工作区')
    route = '/api/projects/' + urllib.parse.quote(root.name, safe='')
    deadline = time.monotonic() + timeout
    while True:
        status = get(route + '/status')
        if not status['updating'] and not status['checking']:
            if status.get('error'):
                raise ValueError('浏览入口同步失败：' + str(status['error']))
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('浏览入口仍在同步；只需恢复本次网页核对，不重复采用或导出')
        time.sleep(.5)
    data = get(route + '/episodes/' + episode)
    seen = set()
    for scene_name, rows in data['segments'].items():
        for row in rows:
            for video in row['videos']:
                identity = episode + '-' + scene_name + '-' + row['id'] + '-' + video['run'] + '-' + video['stage']
                if identity in identities and video['approved']:
                    seen.add(identity)
    if seen != set(identities):
        raise ValueError('网页未识别本次具体采用版本：' + ', '.join(sorted(set(identities) - seen)))
    if complete:
        catalogue = get(route + '/sections/' + urllib.parse.quote('09-剧集制作', safe=''))
        current = next(row for row in catalogue['children'] if row['name'] == episode)
        if current['productionComplete'] is not True:
            raise ValueError('网页尚未识别本集已完成状态')
    return {'state': 'verified', 'review_url': base + '/#/projects/' + urllib.parse.quote(root.name, safe='')}


def approve(args):
    root = Path(args.project).resolve(strict=True)
    request_path = adopt.local_path(root, args.plan)
    plan = adopt.load(request_path)
    ids = plan['identities']
    matches = [adopt.IDENTITY.fullmatch(i) for i in ids]
    if not ids or len(ids) != len(set(ids)) or not all(matches):
        raise ValueError('identities必须明确列出不重复的EP/C/P/R/阶段')
    if len({m[3] for m in matches}) != len(matches):
        raise ValueError('同一P段本次只能指定一个采用版本')
    scopes = {(m[1], m[2], m[5]) for m in matches}
    if len(scopes) != 1:
        raise ValueError('一次批准收尾限同一集、场次及处理阶段')
    episode, scene_number, stage = next(iter(scopes))
    scene = episode + '-' + scene_number
    expected = [p for s, p in indexed_parts(root, episode) if s == scene]
    if not expected or any(i.rsplit('-', 2)[0] not in expected for i in ids):
        raise ValueError('批准对象不属于正式分镜索引')
    available = source_items(root, plan, stage)
    if set(ids) - available.keys():
        raise ValueError('原提交清单未提供这些具体执行身份：' + ', '.join(sorted(set(ids) - available.keys())))
    items = [available[i] for i in ids]
    items.sort(key=lambda i: expected.index(i['identity'].rsplit('-', 2)[0]))
    if request_path.parent != Path(items[0]['mapping']).parent:
        raise ValueError('批准收尾请求须保存到本批最前P的实际共同执行附件')
    summary = adopt.local_path(root, plan.get('summary', '09-剧集制作/' + episode + '/其他资料/工作稿/' + episode + '-生成说明-工作稿.md'))
    adoption_plan = {k: plan[k] for k in ('approval_text', 'approval_time') if k in plan}
    adoption_plan.update(items=[{**{k: i[k] for k in ('identity', 'mapping', 'receipt')},
                                 **({'approval_scope': plan['approval_scope']} if 'approval_scope' in plan else {})}
                                for i in items],
                         summary=str(summary), record_updates=record_updates(root, episode, summary))
    result = {'state': 'ready', 'phase': 'adoption', 'identities': ids, 'timings_seconds': {}, 'episode_completed': False}
    report = request_path.with_name(request_path.stem + '-结果.json')
    if args.apply:
        result['report_file'] = str(report)
    previous = adopt.load(report) if report.exists() else {}
    if previous.get('request') and previous['request'] != plan:
        raise ValueError('已有批准收尾请求不同，请另存本次请求，保留原批准记录')
    if args.apply and previous.get('state') in ('completed', 'adopted_partial'):
        return {**previous, 'reused': True}
    result['request'] = plan
    result['previous_failures'] = list(previous.get('previous_failures', []))
    if previous.get('error'):
        result['previous_failures'].append({k: previous[k] for k in ('state', 'phase', 'error', 'timings_seconds')})
    start = time.monotonic()
    try:
        if args.apply and previous.get('local_completed'):
            result.update({k: previous[k] for k in ('adoption', 'episode_completed', 'episode_missing')})
            if 'finalization' in previous:
                result['finalization'] = previous['finalization']
            result.update(phase='browser', local_completed=True)
            result['browser'] = browser_sync(root, episode, stage, ids, result['episode_completed'], args.timeout)
            result['state'] = 'completed' if 'finalization' in result else 'adopted_partial'
            return result
        result['adoption'] = adopt.adoption(args, plan=adoption_plan)
        result['timings_seconds']['adoption'] = round(time.monotonic() - start, 3)
        if not args.apply:
            return result
        chosen = [selected(root, p, stage) for p in expected]
        ready = all(chosen)
        result['phase'] = 'business_records'
        update_business(root, episode, scene, stage, summary, [i for i in chosen if i], False, False)
        if ready:
            result['phase'] = 'finalization'
            chosen_items = [dict(available[i]) for i in chosen]
            final_plan = {'episode': episode, 'scene': scene_number, 'stage': stage, 'items': chosen_items, 'summary': str(summary)}
            if stage == '后处理' or plan.get('source_finalization'):
                origin = adopt.load(adopt.local_path(root, plan['source_finalization']))
                for key in ('configuration_batches', 'configuration_batch_authorization'):
                    if key in origin:
                        final_plan[key] = origin[key]
                if stage == '后处理':
                    content = {i['identity']: i for i in origin['items']}
                    for item in chosen_items:
                        mapping = adopt.load(Path(item['mapping']))
                        source = next(c['source'] for c in mapping['generation_contexts'] if c['identity'] == item['identity'])
                        item['content'] = {k: content[source][k] for k in ('identity', 'mapping', 'api', 'canvas')}
                        item['source_video'] = mapping['source_video']
            for key in ('configuration_batches', 'configuration_batch_authorization'):
                if key in plan:
                    final_plan[key] = plan[key]
            began = time.monotonic()
            result['finalization'] = final.finalize(args, plan=final_plan)
            result['timings_seconds']['finalization'] = round(time.monotonic() - began, 3)
        result['phase'] = 'business_records'
        missing = episode_missing(root, episode) if stage == '后处理' and ready else []
        complete = stage == '后处理' and ready and not missing
        result.update(episode_completed=complete, episode_missing=missing)
        chosen = [i for i in chosen if i]
        update_business(root, episode, scene, stage, summary, chosen, ready, complete)
        result.update(phase='browser', local_completed=True)
        began = time.monotonic()
        result['browser'] = browser_sync(root, episode, stage, ids, complete, args.timeout)
        result['timings_seconds']['browser'] = round(time.monotonic() - began, 3)
        result['state'] = 'completed' if ready else 'adopted_partial'
        return result
    except (ValueError, KeyError, OSError, TimeoutError, urllib.error.URLError, final.client.ClientError, final.zipfile.BadZipFile, AssertionError) as error:
        result.update(state='browser_pending' if result['phase'] == 'browser' else 'needs_attention', error=str(error))
        return result
    finally:
        if args.apply:
            result['timings_seconds']['total'] = round(time.monotonic() - start, 3)
            final.save_json(report, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='项目根目录；不扫描其他项目')
    parser.add_argument('--plan', required=True, help='项目内批准收尾请求；只填批准身份、用户原话及原提交清单')
    parser.add_argument('--apply', action='store_true', help='一次采用、齐备后定稿、进度更新及网页核对；默认只读预览')
    parser.add_argument('--timeout', type=float, default=30, help='导出和网页请求超时秒数；无生成、无自动重新导出')
    args = parser.parse_args()
    try:
        result = approve(args)
        compact = {k: result[k] for k in ('state', 'phase', 'episode_completed', 'episode_missing',
                   'report_file', 'timings_seconds', 'error', 'reused') if k in result}
        compact['identity_count'] = len(result['identities'])
        if 'browser' in result:
            compact['review_url'] = result['browser']['review_url']
        print(json.dumps(compact, ensure_ascii=False))
        return 1 if result['state'] in ('needs_attention', 'browser_pending') else 0
    except (ValueError, KeyError, OSError, urllib.error.URLError, final.client.ClientError, final.zipfile.BadZipFile, AssertionError) as error:
        print(json.dumps({'state': 'needs_attention', 'error': str(error), 'phase': 'inputs'}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
