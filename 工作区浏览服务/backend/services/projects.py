from pathlib import Path
import logging
import json
import os
import re
import stat
import sys
import threading
import time

from backend.parsers.project import SourceChangedError, build_data, live_task_record, live_revision_notes, FORMAL_SECTIONS
from backend.parsers.generation import load_context

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts'))
from project_index import read_index

logger = logging.getLogger(__name__)

# Increment only when the parsed project data or interpretation becomes incompatible.
CACHE_SCHEMA = 21

class ProjectStore:
    """Parse on demand; keep the last complete result while a change is read."""

    def __init__(self, root: Path, *, cache_directory: Path | None = None, version: str = ''):
        self.root = root.resolve()
        self.cache_directory = cache_directory
        self.version = version
        if cache_directory is not None:
            cache_directory.mkdir(parents=True, exist_ok=True)
        self.entries = {}
        self.lock = threading.Lock()

    def project(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if path.parent != self.root or not path.is_dir() or name.startswith('.'):
            raise FileNotFoundError('项目不存在')
        return path

    def discover(self):
        projects = {p.name for p in self.root.iterdir()
                    if p.is_dir() and not p.name.startswith('.') and p.resolve().parent == self.root}
        _, indexed = read_index(self.root)
        names = dict.fromkeys([*indexed, *sorted(projects)])
        return [{'id': name, 'name': name} for name in names if name in projects]

    def snapshot(self, path: Path):
        # mtime and size detect edits, additions, removal and renames without reading media.
        path = path.resolve()
        result = {}
        pending = [(str(path), '')]
        while pending:
            directory, prefix = pending.pop()
            with os.scandir(directory) as files:
                for item in files:
                    if item.name.startswith('.') or not prefix and item.name == '99-综合资料':
                        continue
                    key = prefix + item.name
                    if live_revision_notes(key):
                        continue
                    if item.is_dir():
                        if item.is_symlink():
                            continue
                        # Ordinary entries inherit their checked parent boundary.
                        # Windows junctions/reparse points still need real-path validation.
                        if (os.name == 'nt' and item.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                                and not Path(item.path).resolve().is_relative_to(path)):
                            continue
                        if key == '98-发布成片' or key.startswith('98-发布成片/'):
                            result[key + '/'] = (0, 0)
                        pending.append((item.path, key + '/'))
                    elif item.name not in ('项目总览.html', 'index.html') and item.is_file():
                        if item.is_symlink() and not Path(item.path).resolve().is_relative_to(path):
                            continue
                        # These generated records are read live when opened. Their
                        # presence affects the file list, but progress writes do not
                        # change compiled project documents or the queue's own API.
                        if item.name in ('后台任务状态.json', '后台过程记录.json') and live_task_record(key):
                            result[key] = (0, 0)
                        else:
                            info = item.stat()
                            result[key] = (info.st_mtime_ns, info.st_size)
        return result

    def cache_snapshot(self, snapshot, part, data):
        episode = re.match(r'09-剧集制作--((?:EP\d{3,}|片头|片尾))--(?:playback|ending|context)(?:--|$)', part or '')
        if episode is None:
            return snapshot
        number = episode[1]
        prefix = '09-剧集制作/' + number + '/'
        dependencies = {'项目进度.md', '00-项目定位/项目基本定位.md', '06-分集大纲/分集索引.md',
                        '06-分集大纲/' + number + '-分集大纲.md', *data.get('sources', {}), *data.get('dependencies', [])}
        return {key: value for key, value in snapshot.items() if key.startswith(prefix) or key in dependencies}

    def load_cache(self, name, snapshot, part=None):
        if self.cache_directory is None:
            return None
        path = (self.cache_directory / name / (part + '.json') if part else self.cache_directory / (name + '.json'))
        if not path.is_file():
            return None
        saved = json.loads(path.read_text('utf-8'))
        if (saved['workspace'] == str(self.root) and saved.get('schema') == CACHE_SCHEMA
                and saved['snapshot'] == {key: list(value) for key, value in self.cache_snapshot(snapshot, part, saved['data']).items()}):
            return saved['data']
        return None

    def save_cache(self, name, snapshot, data, part=None):
        if self.cache_directory is None:
            return
        path = (self.cache_directory / name / (part + '.json') if part else self.cache_directory / (name + '.json'))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'workspace': str(self.root), 'schema': CACHE_SCHEMA,
                                        'snapshot': self.cache_snapshot(snapshot, part, data), 'data': data}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    def get(self, name: str, *, synchronize=False):
        path = self.project(name)
        with self.lock:
            entry = self.entries.get(name)
            if entry is None:
                entry = {'data': None, 'revision': 0, 'error': None, 'error_kind': None, 'updating': False,
                         'scanning': False, 'sections': {}, 'snapshot': None, 'checked': 0.0, 'retry_at': 0.0, 'retry_at_time': 0.0,
                         'lock': threading.Lock(), 'initialization_lock': threading.Lock(), 'section_locks': {}}
                self.entries[name] = entry
        initialized = False
        with entry['lock']:
            needs_initialization = entry['data'] is None
        if needs_initialization:
            # Only the first readers wait here. Directory reads and parsing must
            # never hold the short lock used by status and refresh publication.
            with entry['initialization_lock']:
                if entry['data'] is None:
                    snapshot = self.snapshot(path)
                    data = self.load_cache(name, snapshot)
                    if data is None:
                        data = build_data(path, web_episode_navigation=True, load_scope="overview")
                        self.save_cache(name, snapshot, data)
                    with entry['lock']:
                        entry.update(snapshot=snapshot, data=data, revision=1, checked=time.monotonic())
                    initialized = True
        if synchronize and not initialized:
            with entry['lock']:
                if entry['scanning']:
                    return entry
                entry['scanning'] = True
            self.scan(name, entry)
        return entry

    def status(self, name: str):
        entry = self.get(name)
        with entry['lock']:
            now = time.monotonic()
            retry_due = entry['error'] and now >= entry['retry_at']
            if not entry['scanning'] and not entry['updating'] and (now - entry['checked'] >= 3 or retry_due):
                entry['checked'] = now
                entry['scanning'] = True
                if retry_due:
                    entry['updating'] = True
                threading.Thread(target=self.scan, args=(name, entry), daemon=True).start()
            return {'revision': entry['revision'], 'updating': entry['updating'], 'checking': entry['scanning'],
                    'error': entry['error'], 'errorKind': entry['error_kind'],
                    'retryAt': entry['retry_at_time'], 'updated': entry['data']['builtAt']}

    def scan(self, name, entry):
        try:
            snapshot = self.snapshot(self.project(name))
            with entry['lock']:
                retry_due = entry['error'] and time.monotonic() >= entry['retry_at']
                changed = snapshot != entry['snapshot'] or retry_due
                if changed:
                    entry['updating'] = True
            if changed:
                self.refresh(name, entry, snapshot)
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            self.read_failed(name, entry, error)
        finally:
            with entry['lock']:
                entry['scanning'] = False
                entry['checked'] = time.monotonic()

    def read_failed(self, name, entry, error, snapshot=None):
        if isinstance(error, SourceChangedError):
            logger.info('Project source changed while reading: %s: %s', name, error)
        else:
            logger.exception('Project sync failed: %s', name)
        with entry['lock']:
            waiting_for_retry = entry['error'] and time.monotonic() < entry['retry_at']
            entry['error'] = str(error)
            entry['error_kind'] = 'source_changed' if isinstance(error, SourceChangedError) else 'read_failed'
            entry['updating'] = False
            if snapshot is not None:
                entry['snapshot'] = snapshot
            if snapshot is not None or not waiting_for_retry:
                entry['retry_at'] = time.monotonic() + 30
                entry['retry_at_time'] = (time.time() + 30) * 1000

    def refresh(self, name, entry, snapshot):
        try:
            data = build_data(self.project(name), web_episode_navigation=True, load_scope="overview")
            self.save_cache(name, snapshot, data)
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            self.read_failed(name, entry, error, snapshot)
            return
        with entry['lock']:
            sections = {key: data for key, data in entry['sections'].items()
                        if self.cache_snapshot(entry['snapshot'], key, data) == self.cache_snapshot(snapshot, key, data)}
            entry.update(data=data, snapshot=snapshot, revision=entry['revision'] + 1,
                         error=None, error_kind=None, updating=False, retry_at=0.0, retry_at_time=0.0, sections=sections)

    def section(self, name: str, scope: str, episode: str | None = None, mode='full', candidate=None):
        if scope not in FORMAL_SECTIONS or episode is not None and not re.fullmatch(r'(?:EP\d{3,}|片头|片尾)', episode):
            raise FileNotFoundError('栏目或剧集不存在')
        entry = self.get(name)
        if candidate is not None and not re.fullmatch(re.escape(episode) + r'-C\d{3,}-P\d{3,}-R\d{3,}-(一采|二采|后处理)', candidate):
            raise FileNotFoundError('候选版本不存在')
        key = scope + ('--' + episode if episode else '') + ('--context--' + candidate if candidate else '--' + mode if mode != 'full' else '')
        with entry['lock']:
            if key in entry['sections']:
                return entry['sections'][key]
            section_lock = entry['section_locks'].setdefault(key, threading.Lock())
        # Deduplicate the same section while allowing status, other sections,
        # and source-change discovery to proceed independently.
        with section_lock:
            try:
                playback = self.section(name, scope, episode, mode='playback') if candidate else None
                with entry['lock']:
                    if key in entry['sections']:
                        return entry['sections'][key]
                    if candidate and entry['sections'].get(scope + '--' + episode + '--playback') is not playback:
                        raise SourceChangedError('项目资料在候选关联读取期间发生变化：' + key)
                    snapshot = entry['snapshot']
                data = self.load_cache(name, snapshot, part=key)
                if data is None:
                    data = (load_context(self.project(name), candidate, playback['generationContexts']) if candidate else
                            build_data(self.project(name), web_episode_navigation=True, load_scope=scope, episode_id=episode, episode_mode=mode))
                    self.save_cache(name, snapshot, data, part=key)
                with entry['lock']:
                    if self.cache_snapshot(snapshot, key, data) != self.cache_snapshot(entry['snapshot'], key, data):
                        raise SourceChangedError('项目资料在栏目读取期间发生变化，请重新读取：' + key)
                    entry['sections'][key] = data
                return data
            except (OSError, ValueError, RuntimeError, UnicodeError) as error:
                self.read_failed(name, entry, error)
                raise

    def file(self, name: str, relative: str, revision: str | None = None):
        root = self.project(name)
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or any(p.startswith('.') for p in Path(relative).parts):
            raise FileNotFoundError('文件不存在或不在项目内')
        identity = re.fullmatch(r'((?:EP\d{3,}|片头|片尾))-C\d{3,}-P\d{3,}-R\d{3,}-(一采|二采|后处理)', path.stem)
        if revision and identity:
            if path.is_file():
                stat = path.stat()
                if revision == str(stat.st_mtime_ns) + '-' + str(stat.st_size):
                    return path
            history = root / '09-剧集制作' / identity[1] / '其他资料/历史版本'
            for archive in [*history.glob(path.stem + '-运行中取回-*' + path.suffix),
                            *history.glob(path.stem + '-替换前-*' + path.suffix)]:
                if archive.is_file() and archive.resolve().is_relative_to(root):
                    stat = archive.stat()
                    if revision == str(stat.st_mtime_ns) + '-' + str(stat.st_size):
                        return archive
            raise FileNotFoundError('该视频文件版本不可用，请加载新文件')
        if not path.is_file():
            raise FileNotFoundError('文件不存在或不在项目内')
        return path
