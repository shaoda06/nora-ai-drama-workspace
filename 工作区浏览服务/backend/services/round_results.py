"""Read an authorized submission's existing assembly and task facts; never execute work."""
import json
from pathlib import Path

from backend.services.result_summary import outputs, summary, video_delivery

STAGES = {'video-first-pass': '一采', 'video-second-pass': '二采', 'video-postprocess': '后处理'}


def submission_result(store, key):
    from project_paths import project_file
    data = store.rows[key]['input']
    if not data.submission_plan:
        raise ValueError('历史任务未保存原清单关联；沿原执行记录确认范围，不按会话或标题合批')
    root = Path(data.project)
    path = project_file(root, data.submission_plan, recorded=True)
    source = json.loads(path.read_text('utf-8-sig'))
    journal = json.loads(path.with_name(path.stem + '-装配结果.json').read_text('utf-8-sig'))
    if source != journal['source'] or journal['thread_id'] != data.thread_id:
        raise ValueError('原清单与装配来源或负责会话不一致')
    planned = journal['tasks']
    if not planned or len(planned) != len(source['tasks']):
        raise ValueError('原清单与装配任务数量不一致')
    members, identities, numbers, episodes, scenes = [], set(), set(), set(), set()
    directories = set()
    for spec, task in zip(source['tasks'], planned):
        record = project_file(root, task['record_dir'], recorded=True)
        if (task['task_type'] not in STAGES or task['task_type'] != spec['task_type']
                or record != project_file(root, spec['record_dir'], recorded=True) or record in directories):
            raise ValueError('整轮汇总须为同一原清单中唯一的视频执行目录及阶段')
        directories.add(record)
        mapping = json.loads((record / '输入映射.json').read_text('utf-8-sig'))
        stage = STAGES[task['task_type']]
        expected = [f"{mapping['segments'][i]['segment']}-{mapping['segments'][i]['round']}-{stage}"
                    for i in mapping['selected_indices']]
        if not expected or len(set(expected)) != len(expected) or identities.intersection(expected):
            raise ValueError('整轮存在空对象或重复执行身份')
        identities.update(expected)
        episodes.add(mapping['scene'].split('-')[0])
        scenes.add(mapping['scene'].split('-')[1])
        numbers.add(mapping['scene_modification_round'])
        matches = [(k, row) for k, row in store.rows.items()
                   if row['input'].project == data.project and Path(row['input'].record_dir) == record
                   and row['input'].thread_id == data.thread_id]
        if len(matches) > 1:
            raise ValueError('同一执行目录有多个任务，须先确认实际执行身份')
        item = dict(record_dir=record.relative_to(root).as_posix(), identities=expected,
                    task_id=None, status='not_submitted', collected=[], completed=[], terminal=False,
                    received=False, error=None)
        if matches:
            member, row = matches[0]
            actual, state = row['input'], row['state']
            if actual.task_type != task['task_type'] or actual.submission_plan != str(path):
                raise ValueError('已登记任务未绑定此原清单及阶段')
            actual_outputs = outputs(store, member)
            collected = {o['identity'] for o in actual_outputs if o.get('identity')}
            if collected - set(expected):
                raise ValueError('实际成果不属于原清单的预期身份')
            closeout = state.get('closeout') or {}
            registered = {o['identity'] for o in closeout.get('video_outputs', [])}
            complete = (state['status'] == 'completed' and closeout.get('status') == 'completed'
                        and registered == set(expected) and collected == set(expected))
            terminal = (complete or state['status'] in ('cancelled', 'resolved', 'failed', 'rejected')
                        or state['status'] == 'collection_failed' and bool(state.get('collection_retry_stop')))
            item.update(task_id=member, status=state['status'], collected=sorted(collected),
                        completed=expected if complete else [], terminal=terminal,
                        closeout_status=closeout.get('status'), error=state.get('error') or closeout.get('error'),
                        received=state.get('reported_outcome') == store.notice_outcome(member))
        members.append(item)
    if key not in {m['task_id'] for m in members} or len(episodes) != 1 or len(numbers) != 1:
        raise ValueError('原清单未包含当前任务或跨越不同剧集/修改轮次')
    episode, number = next(iter(episodes)), next(iter(numbers))
    if type(number) is not int:
        raise ValueError('原清单缺少有效修改轮次')
    scope = source.get('business_scope', {})
    if (scope.get('episode', episode) != episode or scope.get('episode_round', number) != number
            or scope.get('expected_video_count', len(identities)) != len(identities)
            or set(scope.get('scenes', scenes)) != scenes):
        raise ValueError('业务范围与原清单实际执行身份不一致')
    manifest = json.loads((root / f'09-剧集制作/{episode}/其他资料/工作稿/{episode}-修改轮次.json').read_text('utf-8-sig'))
    composition = next((r for r in manifest['rounds'] if r['number'] == number), None)
    if composition is None:
        raise ValueError('原清单引用的修改轮次不存在')
    combined = {f"{episode}-{scene}-{s['id']}-{s['run']}-{s['stage']}"
                for scene, value in composition['scenes'].items() for s in value['segments']}
    if identities - combined:
        raise ValueError('执行身份不属于所引用的整集组合')
    completed = {identity for item in members for identity in item['completed']}
    collected = {identity for item in members for identity in item['collected']}
    ready = identities == completed
    tasks = [summary(store, m['task_id']) for m in members if m['task_id']]
    return dict(status='complete' if ready else 'terminal_partial' if all(m['terminal'] for m in members) else 'incomplete',
                source=path.relative_to(root).as_posix(), project=root.name, episode=episode, episode_round=number,
                current_round=number == max(r['number'] for r in manifest['rounds']),
                expected_tasks=len(members), expected_video_count=len(identities),
                registered_tasks=sum(m['task_id'] is not None for m in members),
                completed_tasks=sum(bool(m['completed']) for m in members),
                collected_video_count=len(collected), completed_video_count=len(completed),
                missing_identities=sorted(identities - completed), retained_identities=sorted(combined - identities),
                failed_tasks=[m['task_id'] for m in members if m['status'] in ('failed', 'rejected', 'collection_failed')],
                cancelled_tasks=[m['task_id'] for m in members if m['status'] == 'cancelled'],
                stopped_tasks=[m['task_id'] for m in members if m['status'] == 'resolved'],
                terminal=all(m['terminal'] for m in members), review_ready=ready,
                next_action=('adopt-approved-postprocess' if ready and any(t['task_type'] == 'video-postprocess' for t in planned)
                             else 'deliver-for-review' if ready else 'resolve-incomplete'),
                received=all(m['received'] for m in members), delivered_to_user=None,
                delivery=video_delivery(store, tasks), tasks=members)


def round_results(store, ids):
    results, seen = [], set()
    for key in ids:
        data = store.rows[key]['input']
        if not data.task_type.startswith('video-'):
            continue
        identity = (data.project, data.submission_plan or key, data.thread_id)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            results.append(submission_result(store, key))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            results.append(dict(status='needs_attention', source=data.submission_plan, task_id=key,
                                reason=str(error), owner='Agent', review_ready=False, terminal=False,
                                delivered_to_user=None))
    return results
