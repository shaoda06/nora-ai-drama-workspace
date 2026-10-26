"""Register an episode composition; retain legacy scene readers and original media identities."""
import argparse
import json
import os
from urllib.parse import urlsplit, unquote
from pathlib import Path
import re

STAGES = ('一采', '二采', '后处理')


def production_scene_ids(text, episode):
    chapter = r"(?:3\.[ \t]*动画内容|1\.[ \t]*故事剧本正文)" if episode in ("片头", "片尾") else r"1\.[ \t]*故事剧本正文"
    body = re.search(r"^##[ \t]+" + chapter + r"[ \t]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
    return list(dict.fromkeys(re.findall(r"^###[ \t]+" + re.escape(episode) + r"-(C\d{3,})[ \t]*$",
                                        body[1] if body else "", re.M)))

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
    from episode_rounds import scene_entries
    item = next((item for item in scene_entries(project, episode, scene_number) if item['number'] == number), None)
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
    from episode_rounds import create_episode_round
    return create_episode_round(project, episode, {'script': plan.get('script'), 'scenes': {scene: plan},
                                                  'note': plan.get('note', '')})

def main():
    parser = argparse.ArgumentParser(description='每批登记一份单集完整修改组合并留存剧本分镜；不生成媒体、不修改旧轮次。')
    parser.add_argument('--project', required=True, help='项目根目录绝对路径')
    parser.add_argument('--episode', required=True, help='集号，例如EP003')
    parser.add_argument('--scene', help='仅改单场时可选，例如C001；多场同批省略此参数，plan填写scenes')
    parser.add_argument('--plan', required=True, help='UTF-8 JSON：script和scenes修改映射；局部分段指定base_round与segment_changes，见修改轮次模板')
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text('utf-8-sig'))
    from episode_rounds import create_episode_round
    result = create_round(args.project, args.episode, args.scene, plan) if args.scene else create_episode_round(args.project, args.episode, plan)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
