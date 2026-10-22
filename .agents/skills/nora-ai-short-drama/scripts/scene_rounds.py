"""Persist a scene revision composition; media and review records remain at their original identities."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from urllib.parse import urlsplit, unquote
from pathlib import Path
import re

STAGES = ('一采', '二采', '后处理')

def manifest_key(episode, scene):
    if not re.fullmatch(r'(?:EP\d{3,}|片头|片尾)', episode) or not re.fullmatch(r'C\d{3,}', scene):
        raise ValueError('集号或场次号不正确')
    return f'09-剧集制作/{episode}/其他资料/工作稿/{episode}-{scene}-场次修改轮次.json'

def validate_manifest(data, episode, scene):
    if data.get('episode') != episode or data.get('scene') != scene:
        raise ValueError('场次修改轮次的归属不匹配')
    numbers = []
    for item in data['rounds']:
        number = item['number']
        if type(number) is not int or number < 1 or number in numbers:
            raise ValueError('场次修改轮次须使用唯一正整数')
        numbers.append(number)
        for kind in ('script', 'storyboard'):
            if not item[kind].get('file') or not item[kind].get('version'):
                raise ValueError('轮次缺少剧本或分镜的准确文件与版本')
        ids = []
        for entry in item['segments']:
            if not re.fullmatch(r'P\d{3,}', entry['id']) or entry['id'] in ids:
                raise ValueError('轮次分段编号无效或重复')
            ids.append(entry['id'])
            if entry['stage'] not in STAGES or not re.fullmatch(r'R\d{3,}', entry['run']) or int(entry['run'][1:]) < 1:
                raise ValueError('轮次中的阶段或R编号无效')
            if not isinstance(entry['duration'], (int, float)) or entry['duration'] <= 0:
                raise ValueError('轮次分段计划时长须为正数秒')
        if not ids:
            raise ValueError('轮次必须明确完整分段顺序')
    if numbers != sorted(numbers):
        raise ValueError('场次修改轮次须按编号递增保存')
    return data


def referenced_round(project, scene, number):
    """Read only the referenced composition; appending other rounds does not change it."""
    if type(number) is not int or number < 1:
        raise ValueError('场次修改轮次引用须为正整数')
    episode, scene_number = scene.split('-')
    data = validate_manifest(json.loads((Path(project) / manifest_key(episode, scene_number)).read_text('utf-8-sig')), episode, scene_number)
    item = next((item for item in data['rounds'] if item['number'] == number), None)
    if item is None:
        raise ValueError('输入映射引用的场次修改轮次不存在')
    return {key: item[key] for key in ('number', 'script', 'storyboard', 'segments')}

def snapshot_text(text, source, target):
    """Preserve document text while keeping relative links usable after archiving."""
    def link(match):
        address = match[1].strip('<>')
        parts = urlsplit(address)
        if parts.scheme or parts.netloc or not parts.path:
            return match[0]
        destination = os.path.relpath((source.parent / unquote(parts.path)).resolve(), target.parent).replace('\\', '/')
        if parts.query:
            destination += '?' + parts.query
        if parts.fragment:
            destination += '#' + parts.fragment
        return '](' + ('<' + destination + '>' if ' ' in destination else destination) + ')'
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            fence = token if fence is None else None if token[0] == fence[0] and len(token) >= len(fence) else fence
            lines.append(line)
        else:
            lines.append(line if fence else re.sub(r'\]\((<[^>]+>|[^)\n]+)\)', link, line))
    return ''.join(lines)

def create_round(project, episode, scene, plan):
    project = Path(project).resolve()
    target = project / manifest_key(episode, scene)
    data = validate_manifest(json.loads(target.read_text('utf-8-sig')), episode, scene) if target.exists() else {'episode': episode, 'scene': scene, 'rounds': []}
    if 'base_round' in plan:
        if 'segments' in plan or 'segment_changes' not in plan:
            raise ValueError('局部轮次须用base_round与segment_changes；重新分段请提供完整segments')
        base = referenced_round(project, episode + '-' + scene, plan['base_round'])
        changes = {item['id']: item for item in plan['segment_changes']}
        if len(changes) != len(plan['segment_changes']):
            raise ValueError('局部轮次修改分段重复')
        if changes.keys() - {item['id'] for item in base['segments']}:
            raise ValueError('局部轮次不能增加或重排分段；请提供完整segments方案')
        plan = {**plan, 'script': plan.get('script', base['script']), 'storyboard': plan.get('storyboard', base['storyboard']),
                'segments': [changes.get(item['id'], item) for item in base['segments']]}
        plan.pop('segment_changes')
        plan['changed_segments'] = list(changes)
    elif 'segment_changes' in plan:
        raise ValueError('局部轮次必须明确base_round，不自动选择最新或推算R')
    number = max((item['number'] for item in data['rounds']), default=0) + 1
    item = {**plan, 'number': number, 'created_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')}
    validate_manifest({**data, 'rounds': [*data['rounds'], item]}, episode, scene)
    documents = {}
    for kind in ('script', 'storyboard'):
        source = (project / item[kind]['file']).resolve()
        if Path(item[kind]['file']).is_absolute() or not source.is_relative_to(project):
            raise ValueError('轮次文档越出项目')
        text = source.read_text('utf-8-sig')
        version = re.search(r'^- 文档版本[：:]\s*(\S+)', text, re.M)
        if not version or version[1].rstrip('。') != item[kind]['version']:
            raise ValueError('轮次文档版本不匹配：' + kind)
        documents[kind] = (source, text)
    archive = project / f'09-剧集制作/{episode}/其他资料/历史版本/{episode}-{scene}-场次修改轮次-{number:03d}'
    previous = data['rounds'][-1] if data['rounds'] else None
    for kind, (source, text) in documents.items():
        old = previous[kind] if previous else None
        if old and old['version'] == item[kind]['version'] and (project / old['file']).read_text('utf-8-sig') == snapshot_text(text, source, project / old['file']):
            item[kind] = dict(old)
            continue
        archive.mkdir(parents=True, exist_ok=True)
        snapshot = archive / ('本集剧本.md' if kind == 'script' else '场次分镜.md')
        with snapshot.open('x', encoding='utf-8', newline='') as stream:
            stream.write(snapshot_text(text, source, snapshot))
        item[kind] = {**item[kind], 'file': snapshot.relative_to(project).as_posix()}
    data['rounds'].append(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)
    return {'file': str(target), 'number': number, 'segments': len(item['segments'])}

def main():
    parser = argparse.ArgumentParser(description='保存场次完整版本组合并留存剧本分镜副本；不生成媒体、不改变审核记录。')
    parser.add_argument('--project', required=True, help='项目根目录绝对路径')
    parser.add_argument('--episode', required=True, help='集号，例如EP003')
    parser.add_argument('--scene', required=True, help='场次号，例如C001')
    parser.add_argument('--plan', required=True, help='UTF-8 JSON：完整segments，或明确base_round与segment_changes的局部方案；字段见场次修改轮次模板')
    args = parser.parse_args()
    print(json.dumps(create_round(args.project, args.episode, args.scene, json.loads(Path(args.plan).read_text('utf-8-sig'))), ensure_ascii=False))

if __name__ == '__main__':
    main()
