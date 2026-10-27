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
from urllib.parse import unquote

import video_adopt as adopt
import scene_finalize as final
import project_progress


indexed_parts = final.indexed_parts
selected = final.selected
episode_missing = final.episode_missing


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


def adopted_source(root, identity, stage):
    """Resolve the exact adopted identity through its linked records, never latest-R scans."""
    part = identity.rsplit('-', 2)[0]
    episode, scene, _ = part.split('-')
    draft = root / '09-剧集制作' / episode / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
    text = draft.read_text('utf-8-sig')
    candidates = []
    headings = re.findall(r'^### (定稿留档-' + re.escape(episode + '-' + scene + '-' + stage) + r'[^\n]*)$', text, re.M)
    for heading in headings:
        start, end = adopt.section(text, heading)
        for reference in re.findall(r'\[留档记录\]\(([^)]+)\)', text[start:end]):
            record = adopt.load(adopt.local_path(root, draft.parent / unquote(reference)))
            if record['state'] != 'completed' or record['stage'] != stage:
                continue
            for source in record['sources']:
                if source['identity'] == identity:
                    item = {key: source[key] for key in ('identity', 'mapping', 'api', 'canvas', 'receipt')}
                    if item not in candidates:
                        candidates.append(item)
    if candidates:
        if len(candidates) != 1:
            raise ValueError('当前采用身份的留档来源不唯一：' + identity)
        return candidates[0]
    row = adopt.selected_row(text, stage)[2]
    anchor = re.findall(r'\]\(#([^)]*)\)', row.strip().strip('|').split('|')[-1])[0]
    heading = next(h for h in re.findall(r'^### (.+)$', text, re.M) if h.lower() == anchor.lower())
    start, end = adopt.section(text, heading)
    review = text[start:end]
    mappings = re.findall(r'^- 来源任务[^：\n]*：\[' + re.escape(identity) + r'\]\(([^)]+)\)', review, re.M)
    receipts = re.findall(r'^- agent取回及展示入口：\[实际输出凭据\]\(([^)]+)\)', review, re.M)
    if len(mappings) != 1 or len(receipts) != 1:
        raise ValueError('当前采用身份缺少明确的执行来源或取回凭据：' + identity)
    mapping = adopt.local_path(root, draft.parent / unquote(mappings[0]))
    return {'identity': identity, 'mapping': str(mapping),
            'receipt': str(adopt.local_path(root, draft.parent / unquote(receipts[0]))),
            'api': str(mapping.parent / '任务.api.json'), 'canvas': str(mapping.parent / '任务.workflow.json')}


def record_updates(root, episode, summary):
    """Adoption requires both business entrances; the final status is written below."""
    updates = []
    for path in (summary, root / '项目进度.md'):
        first = path.read_text('utf-8-sig').splitlines()[0]
        updates.append({'path': str(path), 'old': first, 'new': first})
    return updates


def update_business(root, episode, scene, stage, summary, identities, finalized, complete):
    text = summary.read_text('utf-8-sig')
    heading = '批准收尾-' + scene + '-' + stage
    retrospective = final.retrospective_status(summary)
    previous = re.search(r'^### ' + re.escape(heading) + r'\s*$.*?(?=^### |\Z)', text, re.M | re.S)
    previous_ids = re.search(r'^- 当前采用顺序：([^\n]*)', previous[0], re.M) if previous else None
    if retrospective['status'] == 'completed' and previous_ids and previous_ids[1].strip() != ' → '.join(identities):
        retrospective['status'] = 'pending'
        text = re.sub(r'^- 完集复盘状态：[^\n]*', '- 完集复盘状态：待完成', text, flags=re.M)
    status = (episode + '分段制作与交付已完成。' if complete else
              scene + '的' + stage + '已采用' + str(len(identities)) + '段；'
              + (('本场后处理采用已齐备。' if finalized else '本场后处理采用尚未齐备。') if stage == '后处理' else
                 ('本场该阶段定稿留档完成。' if finalized else '本场该阶段定稿尚未完成。')))
    if retrospective['status'] == 'completed':
        status += '完集复盘与经验归并已完成。'
    elif complete:
        status += '待完成本集复盘与经验归并。'
    if re.search(r'^- 当前状态及待办：', text, re.M):
        text = re.sub(r'^- 当前状态及待办：[^\n]*', '- 当前状态及待办：' + status, text, count=1, flags=re.M)
    else:
        first, _, rest = text.partition('\n')
        text = first + '\n\n- 当前状态及待办：' + status + '\n' + rest
    folder = root / '09-剧集制作' / episode / '06-阶段采用视频' / adopt.STAGES[stage] / (scene.split('-')[1] + '-场次')
    file_entry = '[阶段采用视频](' + adopt.link(summary, folder) + ')'
    if stage == '后处理':
        links = []
        for identity in identities:
            part = identity.rsplit('-', 2)[0]
            draft = root / '09-剧集制作' / episode / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
            output = adopt.selected_output(root, draft, draft.read_text('utf-8-sig'), part, stage)
            links.append('[' + identity + '](' + adopt.link(summary, output['path']) + ')')
        file_entry = '；'.join(links)
    body = '\n- 状态：' + status + '\n- 当前采用顺序：' + ' → '.join(identities) + '\n- 文件入口：' + file_entry + '\n'
    if re.search(r'^### ' + re.escape(heading) + r'\s*$', text, re.M):
        a, b = adopt.section(text, heading)
        text = text[:a] + body + '\n' + text[b:]
    else:
        text = text.rstrip() + '\n\n### ' + heading + '\n' + body
    final.replace_file(summary, text)
    final.update_progress(root, episode, scene, stage, summary)


def completion_handoff(result, summary):
    if result.get('episode_completed'):
        result['retrospective'] = final.retrospective_status(summary)
        result['next_action'] = ('deliver-completed' if result['retrospective']['status'] == 'completed'
                                 else 'episode-retrospective')
    return result


def browser_sync(root, episode, stage, identities, complete, timeout):
    config = adopt.load(root.parent.parent / '工作区浏览服务/runtime/task-service.json')
    base = config['url'].rstrip('/')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(route, *, text=False):
        with opener.open(base + route, timeout=timeout) as response:
            return response.read().decode("utf-8-sig") if text else json.load(response)

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
    served = get(route + '/files/' + urllib.parse.quote('项目进度.md', safe=''), text=True)
    _, actual = project_progress.phase_row(served, episode)
    _, expected = project_progress.phase_row((root / '项目进度.md').read_text('utf-8-sig'), episode)
    if actual != expected:
        raise ValueError('网页尚未同步本批阶段行的状态、成果、待决事项和下一步')
    data = get(route + '/episodes/' + urllib.parse.quote(episode, safe=''))
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
    project_progress.phase_row((root / '项目进度.md').read_text('utf-8-sig'), episode)
    scene = episode + '-' + scene_number
    expected = [p for s, p in indexed_parts(root, episode) if s == scene]
    if not expected or any(i.rsplit('-', 2)[0] not in expected for i in ids):
        raise ValueError('批准对象不属于正式分镜索引')
    available = source_items(root, plan, stage)
    if set(ids) - available.keys():
        raise ValueError('原提交清单未提供这些具体执行身份：' + ', '.join(sorted(set(ids) - available.keys())))
    items = [available[i] for i in ids]
    items.sort(key=lambda i: expected.index(i['identity'].rsplit('-', 2)[0]))
    deliveries = plan.get('postprocess_delivery', {})
    if request_path.parent != Path(items[0]['mapping']).parent:
        raise ValueError('批准收尾请求须保存到本批最前P的实际共同执行附件')
    summary = adopt.local_path(root, plan.get('summary', '09-剧集制作/' + episode + '/其他资料/工作稿/' + episode + '-生成说明-工作稿.md'))
    adoption_plan = {k: plan[k] for k in ('approval_text', 'approval_time') if k in plan}
    adoption_plan.update(items=[{**{k: i[k] for k in ('identity', 'mapping', 'receipt')},
                                 **({'approval_scope': plan['approval_scope']} if 'approval_scope' in plan else {}),
                                 **({'postprocess_delivery': deliveries.get(i['identity'])}
                                    if stage == '后处理' and isinstance(deliveries, dict) else {})}
                                for i in items],
                         summary=str(summary), record_updates=record_updates(root, episode, summary))
    result = {'state': 'ready', 'phase': 'adoption', 'identities': ids, 'timings_seconds': {}, 'episode_completed': False}
    report = request_path.with_name(request_path.stem + '-结果.json')
    if args.apply:
        result['report_file'] = str(report)
    previous = adopt.load(report) if report.exists() else {}
    if previous.get('request') and previous['request'] != plan:
        raise ValueError('已有批准收尾请求不同，请另存本次请求，保留原批准记录')
    if (stage == '后处理' and 'postprocess_delivery' not in plan and args.apply
            and previous.get('request') == plan and previous.get('state') in ('completed', 'adopted_partial')):
        # Historical completed requests are receipts, not authorization for new adoption.
        return {**previous, 'reused': True}
    if stage == '后处理' and (not isinstance(deliveries, dict) or set(deliveries) != set(ids)
                              or any(value not in ('workflow', 'products') for value in deliveries.values())):
        raise ValueError('后处理收尾须用postprocess_delivery逐身份声明workflow或products；未齐备不收尾')
    if stage == '后处理' and (previous.get('local_completed') or previous.get('state') in ('completed', 'adopted_partial')):
        for identity in ids:
            product = adopt.postprocess_product(root, identity)
            if (deliveries[identity] == 'products') != (product is not None):
                raise ValueError('后处理交付范围与原收尾不同，须核对并另存接续请求')
            part = identity.rsplit('-', 2)[0]
            draft = root / '09-剧集制作' / episode / '其他资料/工作稿' / (part + '-视频制作-工作稿.md')
            current = adopt.selected_output(root, draft, draft.read_text('utf-8-sig'), part, stage)
            recorded = next(item for item in previous['adoption']['items'] if item['identity'] == identity)
            if (current is None or not current['path'].is_file()
                    or current['path'] != adopt.local_path(root, recorded['selected_path'])):
                raise ValueError('后处理最终产物缺失或采用关联已变化，不能复用旧完成报告')
    if args.apply and previous.get('state') in ('completed', 'adopted_partial'):
        refreshed = completion_handoff(dict(previous), summary)
        if refreshed != previous:
            final.save_json(report, refreshed)
        return {**refreshed, 'reused': True}
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
            result['state'] = 'completed' if all(selected(root, p, stage) for p in expected) else 'adopted_partial'
            return completion_handoff(result, summary)
        result['adoption'] = adopt.adoption(args, plan=adoption_plan)
        result['timings_seconds']['adoption'] = round(time.monotonic() - start, 3)
        if not args.apply:
            return result
        chosen = [selected(root, p, stage) for p in expected]
        ready = all(chosen)
        result['phase'] = 'business_records'
        update_business(root, episode, scene, stage, summary, [i for i in chosen if i], False, False)
        if ready and stage in final.FINALIZATION_STAGES:
            result['phase'] = 'finalization'
            chosen_items = [dict(available[i]) if i in available else adopted_source(root, i, stage) for i in chosen]
            final_plan = {'episode': episode, 'scene': scene_number, 'stage': stage, 'items': chosen_items, 'summary': str(summary)}
            if plan.get('source_finalization'):
                origin = adopt.load(adopt.local_path(root, plan['source_finalization']))
                for key in ('configuration_batches', 'configuration_batch_authorization'):
                    if key in origin:
                        final_plan[key] = origin[key]
            for key in ('configuration_batches', 'configuration_batch_authorization', 'edition'):
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
        return completion_handoff(result, summary)
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
                   'report_file', 'timings_seconds', 'error', 'reused', 'next_action', 'retrospective') if k in result}
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
