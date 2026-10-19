"""Publish explicitly selected current workdraft sections, without adopting content."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit

from project_paths import PreparationPaths


def render_current(text, draft, target):
    """Keep fenced payloads intact; change only document headings and link bases."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').splitlines(keepends=True)
    current, fence, body = False, None, []
    for line in lines:
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            if current:
                body.append((line, True))
            continue
        if fence is not None:
            if current:
                body.append((line, True))
            continue
        if re.fullmatch(r'##\s+1\.\s*当前内容\s*', line.rstrip()):
            if current:
                raise ValueError('当前内容章节重复：' + str(draft))
            current = True
            continue
        if current:
            if re.match(r'^##\s+\d+\.', line):
                break
            heading = re.match(r'^(#{3,6})(\s+.*)', line)
            if heading:
                line = '#' * (len(heading[1]) - 2) + heading[2] + '\n'
            body.append((line, False))
    if not current or not any(line.strip() for line, _ in body):
        raise ValueError('缺少非空的“## 1. 当前内容”章节：' + str(draft))
    if fence is not None:
        raise ValueError('代码围栏未闭合：' + str(draft))
    # In-document shot/section anchors stay local. Review anchors outside the
    # published section must still lead to the full workdraft.
    anchors = set()
    for line, literal in body:
        if literal:
            continue
        heading = re.match(r'^#{1,6}\s+(.*)', line)
        if heading:
            label = re.sub(r'<[^>]*>|[*`]', '', heading[1]).strip().lower()
            label = re.sub(r'\s+', '-', label)
            anchors.add(re.sub(r'[^\w-]', '', label))
        anchors.update(re.findall(r'\bid=[\'"]([^\'"]+)[\'"]', line))

    def link(match):
        raw = match[1]
        spelling = re.fullmatch(r'(<[^>]+>|\S+)(.*)', raw)
        if spelling is None:
            return match[0]
        address, title = spelling.groups()
        address = address[1:-1] if address.startswith('<') else address
        parts = urlsplit(address)
        if parts.scheme or parts.netloc or address.startswith('//'):
            return match[0]
        if not parts.path and unquote(parts.fragment) in anchors:
            return match[0]
        source = (draft.parent / unquote(parts.path)).resolve() if parts.path else draft
        destination = os.path.relpath(source, target.parent).replace('\\', '/')
        if parts.query:
            destination += '?' + parts.query
        if parts.fragment:
            destination += '#' + parts.fragment
        if any(c.isspace() for c in destination):
            destination = '<' + destination + '>'
        return '](' + destination + title + ')'

    result = ''.join(line if literal else re.sub(r'\]\((<[^>]+>|[^)\n]+)\)', link, line)
                     for line, literal in body)
    return result.strip() + '\n'


def sync_documents(project, plan, archive_dir):
    """Resolve/read once, prepare the entire batch, then preserve and write changes."""
    paths = PreparationPaths(project)
    archive = paths.file(archive_dir)
    if '其他资料' not in archive.parts or '历史版本' not in archive.parts:
        raise ValueError('archive-dir须位于项目的其他资料/历史版本目录')
    if not isinstance(plan, list) or not plan:
        raise ValueError('同步计划须为非空JSON数组')
    contents, states, pending, destinations = {}, {}, [], set()

    def read(path, *, required):
        if path not in contents:
            actual = paths.io_file(path)
            try:
                state = actual.stat()
            except FileNotFoundError:
                if required:
                    raise
                state = None
            states[path] = state
            contents[path] = actual.read_bytes() if state is not None else None
        return contents[path]

    for entry in plan:
        draft, target = paths.file(entry['draft']), paths.file(entry['target'])
        if draft == target or target in destinations:
            raise ValueError('源目标相同或目标重复：' + str(target))
        if draft.suffix.lower() != '.md' or target.suffix.lower() != '.md':
            raise ValueError('仅同步Markdown资料，不操作媒体或执行凭据')
        destinations.add(target)
        original = read(draft, required=True)
        previous = read(target, required=False)
        rendered = render_current(original.decode('utf-8-sig'), draft, target).encode('utf-8')
        pending.append((target, rendered, previous))
    if destinations.intersection(paths.file(entry['draft']) for entry in plan):
        raise ValueError('同批目标不能同时作为工作稿来源')
    changes = [(target, data, old) for target, data, old in pending if data != old]
    backups = {}
    for target, _, old in changes:
        if old is not None:
            backup = paths.file(archive / target.relative_to(paths.project))
            if backup in contents or backup in destinations or paths.io_file(backup).exists():
                raise ValueError('归档位置已占用：' + str(backup))
            backups[target] = backup
    # Protect another writer's work without re-reading unchanged contents.
    for path, before in states.items():
        actual = paths.io_file(path)
        try:
            after = actual.stat()
        except FileNotFoundError:
            after = None
        signature = lambda s: None if s is None else (s.st_ino, s.st_size, s.st_mtime_ns)
        if signature(before) != signature(after):
            raise ValueError('同步期间资料发生变化：' + str(path))
    for target, data, old in changes:
        if target in backups:
            backup = paths.io_file(backups[target])
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open('xb') as stream:
                stream.write(old)
        target = paths.io_file(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return {'ok': True,
            'written': [p.relative_to(paths.project).as_posix() for p, _, _ in changes],
            'unchanged': [p.relative_to(paths.project).as_posix() for p, data, old in pending if data == old],
            'archives': [p.relative_to(paths.project).as_posix() for p in backups.values()]}


def main():
    parser = argparse.ArgumentParser(description='集中同步已编写好的工作稿当前正文；不批准内容、不联网、不提交生成。')
    parser.add_argument('--project', required=True, help='当前设备的项目根目录')
    parser.add_argument('--plan', required=True, help='UTF-8 JSON数组文件，文件地址相对当前目录；条目含draft、target')
    parser.add_argument('--archive-dir', required=True, help='本批独立的其他资料/历史版本目录；相对项目根或项目内绝对地址')
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
    print(json.dumps(sync_documents(args.project, plan, args.archive_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
