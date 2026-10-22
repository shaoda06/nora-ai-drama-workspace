"""File-backed prompt library. All public paths are relative to its root."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import RLock
import unicodedata
from uuid import uuid4

from markdown_it import MarkdownIt


class PromptError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


is_junction = getattr(os.path, 'isjunction', lambda path: False)


MARKDOWN = MarkdownIt('commonmark', {'html': False}).enable('table')


def revision(path):
    stat = path.stat()
    return f'{stat.st_ino}:{stat.st_mtime_ns}:{stat.st_ctime_ns}:{stat.st_size}'


def read_body(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return handle.read()


def validate_name(name):
    if (not name or name != name.strip() or name.startswith('.') or name.endswith('.')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name)):
        raise PromptError('名称不能为空、以点开头或结尾，也不能包含跨平台文件名禁用字符。')
    return name


def folded(name):
    return unicodedata.normalize('NFC', name).casefold()


class PromptLibrary:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.lock = RLock()

    def path(self, relative='', *, internal=False):
        if self.root.is_symlink() or is_junction(self.root):
            raise PromptError('提示词管理目录不能是链接。')
        if not isinstance(relative, str) or '\\' in relative or relative.startswith('/'):
            raise PromptError('路径必须位于提示词管理目录内。')
        parts = relative.split('/') if relative else []
        current = self.root
        for part in parts:
            if internal:
                if not part or part in ('.', '..'):
                    raise PromptError('无效的管理路径。')
            else:
                validate_name(part)
            current = current / part
            if current.is_symlink() or is_junction(current):
                raise PromptError('不支持符号链接或目录联接。')
        if not current.resolve().is_relative_to(self.root.resolve()):
            raise PromptError('路径超出提示词管理目录。')
        return current

    def folder(self, relative):
        path = self.path(relative)
        if not path.is_dir():
            raise PromptError('分类已不存在，请刷新列表。', 404)
        return path

    def file(self, relative):
        path = self.path(relative)
        if path.suffix.lower() != '.md' or not path.is_file():
            raise PromptError('提示词已不存在，请刷新列表。', 404)
        return path

    def check(self, path, expected):
        if not path.exists() or revision(path) != expected:
            raise PromptError('内容已被其他页面或外部程序修改，请重新载入后再操作；当前输入仍保留。', 409)

    def vacant(self, target, source=None):
        for entry in target.parent.iterdir():
            if folded(entry.name) == folded(target.name) and entry != source:
                raise PromptError('目标分类已存在同名文件或分类，请更换名称。', 409)

    def entries(self, folder):
        for entry in sorted(folder.iterdir(), key=lambda p: folded(p.name)):
            if entry.name.startswith('.') or entry.is_symlink() or is_junction(entry):
                continue
            yield entry

    def metadata(self, path):
        return {'path': path.relative_to(self.root).as_posix(), 'title': path.stem,
                'category': '' if path.parent == self.root else path.parent.relative_to(self.root).as_posix(),
                'modified': path.stat().st_mtime, 'revision': revision(path)}

    def snapshot(self):
        with self.lock:
            self.path()
            categories, prompts = [], []
            if not self.root.exists():
                return {'categories': [], 'prompts': []}
            def visit(folder):
                for entry in self.entries(folder):
                    if entry.is_dir():
                        categories.append({'path': entry.relative_to(self.root).as_posix(), 'revision': revision(entry)})
                        visit(entry)
                    elif entry.is_file() and entry.suffix.lower() == '.md':
                        prompts.append(self.metadata(entry))
            visit(self.root)
            prompts.sort(key=lambda item: (-item['modified'], folded(item['path'])))
            return {'categories': categories, 'prompts': prompts}

    def read(self, relative):
        with self.lock:
            path = self.file(relative)
            info = self.metadata(path)
            body = read_body(path)
            self.check(path, info['revision'])
            return {**info, 'body': body}

    def search(self, query, category=''):
        with self.lock:
            if category:
                self.folder(category)
            result = []
            needle = query.casefold()
            for info in self.snapshot()['prompts']:
                if category and not info['path'].startswith(category + '/'):
                    continue
                data = self.read(info['path'])
                index = data['body'].casefold().find(needle)
                if needle in data['title'].casefold() or index >= 0:
                    start = max(0, index - 35)
                    result.append({**info, 'snippet': data['body'][start:start + 160]})
            return result

    @contextmanager
    def temporary(self, parent, body):
        with NamedTemporaryFile(mode='w', encoding='utf-8', newline='', prefix='.prompt-', suffix='.tmp', dir=parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                handle.close()
                temporary.unlink()
                raise
        try:
            yield temporary
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, category, title, body, source=None, expected=None):
        with self.lock:
            self.path().mkdir(parents=True, exist_ok=True)
            parent = self.folder(category)
            title = validate_name(title)
            original = self.file(source) if source is not None else None
            suffix = original.suffix if original else '.md'
            target = self.path('/'.join(filter(None, [category, title + suffix])))
            if original:
                self.check(original, expected)
            self.vacant(target, original)
            # Case-only renames have different behavior on macOS and Windows.
            if original and original != target and folded(original.name) == folded(target.name) and original.parent == parent:
                raise PromptError('仅大小写或 Unicode 写法不同的改名，请先改为一个不同的名称。')
            with self.temporary(parent, body) as temp:
                if original:
                    self.check(original, expected)
                if original == target:
                    os.replace(temp, target)
                else:
                    os.link(temp, target)  # Atomic, never replaces an existing destination.
                    if original:
                        original.unlink()
            return self.read(target.relative_to(self.root).as_posix())

    def create_category(self, parent, name):
        with self.lock:
            self.path().mkdir(parents=True, exist_ok=True)
            folder = self.folder(parent)
            target = folder / validate_name(name)
            self.vacant(target)
            target.mkdir()
            return {'path': target.relative_to(self.root).as_posix(), 'revision': revision(target)}

    def update_category(self, source, parent, name, expected):
        with self.lock:
            if not source:
                raise PromptError('主目录不能改名或移动。')
            original = self.folder(source)
            self.check(original, expected)
            target = self.folder(parent) / validate_name(name)
            if target == original:
                return {'path': source, 'revision': revision(original)}
            if target.is_relative_to(original):
                raise PromptError('分类不能移动到自身或自己的子分类。')
            self.vacant(target)
            original.rename(target)
            return {'path': target.relative_to(self.root).as_posix(), 'revision': revision(target)}

    def delete_category(self, source, expected):
        with self.lock:
            if not source:
                raise PromptError('主目录不能删除。')
            path = self.folder(source)
            self.check(path, expected)
            if any(path.iterdir()):
                raise PromptError('只能删除空分类，请先移动或删除其中的文件和子分类。', 409)
            path.rmdir()

    def trash_path(self, identity):
        if not re.fullmatch('[0-9a-f]{32}', identity):
            raise PromptError('无效的回收站记录。')
        return self.path('.trash/' + identity, internal=True)

    def discard(self, source, expected):
        with self.lock:
            path = self.file(source)
            self.check(path, expected)
            identity = uuid4().hex
            trash = self.trash_path(identity)
            trash.mkdir(parents=True)
            record = {'id': identity, 'original': source, 'deleted': datetime.now(timezone.utc).isoformat()}
            try:
                (trash / 'record.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
                self.check(path, expected)
                os.link(path, trash / 'content.md')
                path.unlink()
            except BaseException:
                (trash / 'record.json').unlink(missing_ok=True)
                (trash / 'content.md').unlink(missing_ok=True)
                trash.rmdir()
                raise
            return record

    def trash_read(self, identity):
        with self.lock:
            trash = self.trash_path(identity)
            content = self.path(f'.trash/{identity}/content.md', internal=True)
            record_path = self.path(f'.trash/{identity}/record.json', internal=True)
            if not trash.is_dir():
                raise PromptError('回收站记录已不存在。', 404)
            record = json.loads(record_path.read_text(encoding='utf-8'))
            stamp = revision(content)
            body = read_body(content)
            self.check(content, stamp)
            return {**record, 'body': body, 'revision': stamp}

    def trash_list(self):
        with self.lock:
            root = self.path('.trash', internal=True)
            if not root.exists():
                return []
            result = []
            for folder in self.entries(root):
                item = self.trash_read(folder.name)
                result.append({key: value for key, value in item.items() if key != 'body'})
            return sorted(result, key=lambda item: item['deleted'], reverse=True)

    def restore(self, identity, category, title, expected):
        with self.lock:
            trash = self.trash_path(identity)
            content = self.path(f'.trash/{identity}/content.md', internal=True)
            self.trash_read(identity)
            self.check(content, expected)
            parent = self.path(category)
            validate_name(title)
            parent.mkdir(parents=True, exist_ok=True)
            target = parent / (title + '.md')
            self.vacant(target)
            os.link(content, target)
            self.purge(identity, revision(content))
            return self.read(target.relative_to(self.root).as_posix())

    def purge(self, identity, expected):
        with self.lock:
            trash = self.trash_path(identity)
            self.trash_read(identity)
            content = self.path(f'.trash/{identity}/content.md', internal=True)
            self.check(content, expected)
            content.unlink()
            self.path(f'.trash/{identity}/record.json', internal=True).unlink()
            trash.rmdir()
