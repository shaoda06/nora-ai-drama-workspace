from pathlib import Path
import logging
import re
import threading
import time

from backend.parsers.project import SourceChangedError, build_data

logger = logging.getLogger(__name__)

class ProjectStore:
    """Parse on demand; keep the last complete result while a change is read."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.entries = {}
        self.lock = threading.Lock()

    def project(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if path.parent != self.root or not path.is_dir() or name.startswith('.'):
            raise FileNotFoundError('项目不存在')
        return path

    def discover(self):
        return [{'id': p.name, 'name': p.name} for p in sorted(self.root.iterdir())
                if p.is_dir() and not p.name.startswith('.') and p.resolve().parent == self.root]

    def snapshot(self, path: Path):
        # mtime and size detect edits, additions, removal and renames without reading media.
        return {p.relative_to(path).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
                for p in path.rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(path).parts)
                and p.relative_to(path).parts[0] != '99-综合资料'
                and p.name not in ('项目总览.html', 'index.html') and p.resolve().is_relative_to(path)}

    def get(self, name: str):
        path = self.project(name)
        with self.lock:
            entry = self.entries.get(name)
            if entry is None:
                entry = {'data': None, 'revision': 0, 'error': None, 'error_kind': None, 'updating': False,
                         'snapshot': None, 'checked': 0.0, 'retry_at': 0.0, 'retry_at_time': 0.0, 'lock': threading.Lock()}
                self.entries[name] = entry
        with entry['lock']:
            if entry['data'] is None and not entry['updating']:
                entry['snapshot'] = self.snapshot(path)
                entry['data'] = build_data(path, web_episode_navigation=True)
                entry['revision'] = 1
        return entry

    def status(self, name: str):
        entry = self.get(name)
        with entry['lock']:
            now = time.monotonic()
            retry_due = entry['error'] and now >= entry['retry_at']
            if not entry['updating'] and (now - entry['checked'] >= 3 or retry_due):
                entry['checked'] = now
                snapshot = self.snapshot(self.project(name))
                if snapshot != entry['snapshot'] or retry_due:
                    entry['updating'] = True
                    threading.Thread(target=self.refresh, args=(name, entry, snapshot), daemon=True).start()
            return {'revision': entry['revision'], 'updating': entry['updating'],
                    'error': entry['error'], 'errorKind': entry['error_kind'],
                    'retryAt': entry['retry_at_time'], 'updated': entry['data']['builtAt']}

    def refresh(self, name, entry, snapshot):
        try:
            data = build_data(self.project(name), web_episode_navigation=True)
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            if isinstance(error, SourceChangedError):
                logger.info('Project source changed while reading: %s: %s', name, error)
            else:
                logger.exception('Project sync failed: %s', name)
            with entry['lock']:
                entry['error'] = str(error)
                entry['error_kind'] = 'source_changed' if isinstance(error, SourceChangedError) else 'read_failed'
                entry['updating'] = False
                entry['snapshot'] = snapshot
                entry['retry_at'] = time.monotonic() + 30
                entry['retry_at_time'] = (time.time() + 30) * 1000
            return
        with entry['lock']:
            entry.update(data=data, snapshot=snapshot, revision=entry['revision'] + 1,
                         error=None, error_kind=None, updating=False, retry_at=0.0, retry_at_time=0.0)

    def file(self, name: str, relative: str, revision: str | None = None):
        root = self.project(name)
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or any(p.startswith('.') for p in Path(relative).parts):
            raise FileNotFoundError('文件不存在或不在项目内')
        identity = re.fullmatch(r'(EP\d{3,})-C\d{3,}-P\d{3,}-R\d{3,}-(一采|二采|后处理)', path.stem)
        if revision and identity:
            if path.is_file():
                stat = path.stat()
                if revision == str(stat.st_mtime_ns) + '-' + str(stat.st_size):
                    return path
            history = root / '09-剧集制作' / identity[1] / '其他资料/历史版本'
            for archive in history.glob(path.stem + '-运行中取回-*' + path.suffix):
                if archive.is_file() and archive.resolve().is_relative_to(root):
                    stat = archive.stat()
                    if revision == str(stat.st_mtime_ns) + '-' + str(stat.st_size):
                        return archive
            raise FileNotFoundError('该视频文件版本不可用，请加载新文件')
        if not path.is_file():
            raise FileNotFoundError('文件不存在或不在项目内')
        return path
