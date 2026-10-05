from pathlib import Path
import threading

from backend.parsers.project import build_data


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
                entry = {'data': None, 'revision': 0, 'error': None, 'updating': False,
                         'snapshot': None, 'checked': 0.0, 'lock': threading.Lock()}
                self.entries[name] = entry
        with entry['lock']:
            if entry['data'] is None and not entry['updating']:
                entry['snapshot'] = self.snapshot(path)
                entry['data'] = build_data(path)
                entry['revision'] = 1
        return entry

    def status(self, name: str):
        import time
        entry = self.get(name)
        with entry['lock']:
            if time.monotonic() - entry['checked'] >= 3 and not entry['updating']:
                entry['checked'] = time.monotonic()
                snapshot = self.snapshot(self.project(name))
                if snapshot != entry['snapshot']:
                    entry['updating'] = True
                    threading.Thread(target=self.refresh, args=(name, entry, snapshot), daemon=True).start()
            return {'revision': entry['revision'], 'updating': entry['updating'],
                    'error': entry['error'], 'updated': entry['data']['builtAt']}

    def refresh(self, name, entry, snapshot):
        try:
            data = build_data(self.project(name))
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            with entry['lock']:
                entry['error'] = str(error)
                entry['updating'] = False
                entry['snapshot'] = snapshot
            return
        with entry['lock']:
            entry.update(data=data, snapshot=snapshot, revision=entry['revision'] + 1,
                         error=None, updating=False)

    def file(self, name: str, relative: str):
        root = self.project(name)
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or any(p.startswith('.') for p in Path(relative).parts):
            raise FileNotFoundError('文件不存在或不在项目内')
        return path
