"""Append one complete episode composition per editing batch; legacy scenes stay read-only."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re

from scene_rounds import manifest_key, production_scene_ids, snapshot_text, validate_manifest


def episode_manifest_key(episode):
    manifest_key(episode, 'C001')
    return f'09-剧集制作/{episode}/其他资料/工作稿/{episode}-修改轮次.json'


def validate_episode_manifest(data, episode):
    if data.get('episode') != episode:
        raise ValueError('修改轮次的集号归属不匹配')
    numbers = []
    for item in data['rounds']:
        number = item['number']
        if type(number) is not int or number < 1 or number in numbers:
            raise ValueError('修改轮次须使用唯一正整数')
        numbers.append(number)
        if not item['scenes'] or not isinstance(item['script'], dict):
            raise ValueError('修改轮次必须包含完整场次组合')
        for scene, value in item['scenes'].items():
            manifest_key(episode, scene)
            validate_manifest({'episode': episode, 'scene': scene, 'rounds': [
                {**value, 'number': number, 'script': item['script']}]}, episode, scene)
    if numbers != sorted(numbers):
        raise ValueError('修改轮次须按编号递增保存')
    return data


def scene_entries(project, episode, scene, read=None):
    """Project an episode round to a scene without rewriting historical records."""
    if read is None:
        def read(key):
            path = Path(project) / key
            return path.read_text('utf-8-sig') if path.exists() else None
    raw = read(manifest_key(episode, scene))
    entries = validate_manifest(json.loads(raw), episode, scene)['rounds'] if raw is not None else []
    raw = read(episode_manifest_key(episode))
    if raw is not None:
        data = validate_episode_manifest(json.loads(raw), episode)
        for item in data['rounds']:
            if scene in item['scenes']:
                entries.append({**item['scenes'][scene], 'number': item['number'],
                    'script': item['script'], 'created_at': item['created_at'],
                    'note': item.get('note', ''), 'episodeRound': True})
    if len({item['number'] for item in entries}) != len(entries):
        raise ValueError('旧场次轮次与单集轮次编号冲突')
    return sorted(entries, key=lambda item: item['number'])


def create_episode_round(project, episode, plan):
    project = Path(project).resolve()
    target = project / episode_manifest_key(episode)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_suffix('.lock')
    # Concurrent scene authors must not allocate the same episode number.
    lock.open('x', encoding='utf-8').close()
    try:
        return append_round(project, episode, plan, target)
    finally:
        lock.unlink()


def append_round(project, episode, plan, target):
    data = validate_episode_manifest(json.loads(target.read_text('utf-8-sig')), episode) if target.exists() else {'episode': episode, 'rounds': []}
    legacy = {}
    maximum = max((item['number'] for item in data['rounds']), default=0)
    for path in target.parent.glob(f'{episode}-C*-场次修改轮次.json'):
        scene = path.name[len(episode) + 1:].split('-')[0]
        values = validate_manifest(json.loads(path.read_text('utf-8-sig')), episode, scene)['rounds']
        maximum = max(maximum, max((item['number'] for item in values), default=0))
        if values:
            legacy[scene] = values[-1]
    previous = data['rounds'][-1] if data['rounds'] else None
    if 'base_round' in plan:
        previous = next((item for item in data['rounds'] if item['number'] == plan['base_round']), None)
        if previous is None:
            raise ValueError('指定的修改基轮不存在')
    scenes = deepcopy(previous['scenes'] if previous else {
        scene: {key: value for key, value in item.items() if key not in ('number', 'script', 'created_at')}
        for scene, item in sorted(legacy.items())})
    script = plan.get('script') or (previous['script'] if previous else None)
    changes = plan['scenes']
    if not changes:
        raise ValueError('本批没有需要登记的场次修改')
    for scene, change in changes.items():
        manifest_key(episode, scene)
        base = scenes.get(scene)
        if 'base_round' in change:
            from scene_rounds import referenced_round
            base = referenced_round(project, episode + '-' + scene, change['base_round'])
        if script is None:
            script = change.get('script') or (base.get('script') if base else None)
        if change.get('script') and change['script'] != script:
            raise ValueError('同一轮各场须引用相同的本集剧本版本')
        value = {**(base or {}), **change}
        if 'segment_changes' in change:
            if 'segments' in change or base is None or ('base_round' not in change and 'base_round' not in plan):
                raise ValueError('局部分段修改须明确base_round，且不能同时填写segments')
            replacements = {item['id']: item for item in change['segment_changes']}
            if len(replacements) != len(change['segment_changes']):
                raise ValueError('局部轮次修改分段重复')
            if replacements.keys() - {item['id'] for item in base['segments']}:
                raise ValueError('局部轮次不能增加或重排分段；请提供完整segments方案')
            value['segments'] = [replacements.get(item['id'], item) for item in base['segments']]
            value['changed_segments'] = list(replacements)
        elif 'segments' not in change:
            raise ValueError('修改场次须填写segments或segment_changes')
        scenes[scene] = {key: value for key, value in value.items()
                         if key not in ('number', 'script', 'created_at', 'base_round', 'segment_changes', 'episodeRound')}
    source, script_text = read_document(project, script)
    order = production_scene_ids(script_text, episode)
    if not order or set(order) - scenes.keys() or changes.keys() - set(order):
        raise ValueError('修改轮次必须覆盖本集剧本的全部场次，且修改场次须在剧本中定义')
    scenes = {scene: scenes[scene] for scene in order}
    number = maximum + 1
    item = {'number': number, 'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'note': plan.get('note', ''), 'script': script, 'scenes': scenes, 'changed_scenes': list(changes)}
    validate_episode_manifest({'episode': episode, 'rounds': [item]}, episode)
    sources = [('script', None, script, source, script_text)]
    for scene, value in scenes.items():
        source, text = read_document(project, value['storyboard'])
        sources.append(('storyboard', scene, value['storyboard'], source, text))
    archive = project / f'09-剧集制作/{episode}/其他资料/历史版本/{episode}-修改轮次-{number:03d}'
    for kind, scene, reference, source, text in sources:
        old = previous['script'] if previous and kind == 'script' else previous['scenes'].get(scene, {}).get(kind) if previous else None
        if old and old['version'] == reference['version'] and (project / old['file']).read_text('utf-8-sig') == snapshot_text(text, source, project / old['file']):
            saved = dict(old)
        else:
            archive.mkdir(parents=True, exist_ok=True)
            snapshot = archive / ('本集剧本.md' if kind == 'script' else scene + '-场次分镜.md')
            with snapshot.open('x', encoding='utf-8', newline='') as stream:
                stream.write(snapshot_text(text, source, snapshot))
            saved = {**reference, 'file': snapshot.relative_to(project).as_posix()}
        if kind == 'script':
            item['script'] = saved
        else:
            item['scenes'][scene][kind] = saved
    data['rounds'].append(item)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)
    return {'file': str(target), 'number': number, 'scenes': list(scenes),
            'segments': sum(len(value['segments']) for value in scenes.values())}


def read_document(project, reference):
    if not isinstance(reference, dict) or not reference.get('file') or not reference.get('version'):
        raise ValueError('轮次缺少剧本或分镜的准确文件与版本')
    source = (project / reference['file']).resolve()
    if Path(reference['file']).is_absolute() or not source.is_relative_to(project):
        raise ValueError('轮次文档越出项目')
    text = source.read_text('utf-8-sig')
    version = re.search(r'^- 文档版本[：:]\s*(\S+)', text, re.M)
    if not version or version[1].rstrip('。') != reference['version']:
        raise ValueError('轮次文档版本不匹配：' + reference['file'])
    return source, text
