"""Project-relative file identities; legacy evidence is read without rewriting it."""
from pathlib import Path, PureWindowsPath


def project_file(project, value, *, recorded=False):
    project = Path(project).resolve()
    return _project_file(project, value, recorded=recorded)


def _project_file(project, value, *, recorded=False):
    spelling = str(value).replace('\\', '/')
    path = Path(spelling)
    windows = PureWindowsPath(spelling)
    absolute = path.is_absolute() or windows.is_absolute()
    resolved = path.resolve() if absolute else None
    if recorded and absolute and not resolved.is_relative_to(project):
        marker = '/projects/' + project.name + '/'
        position = spelling.casefold().find(marker.casefold())
        if position >= 0:
            spelling = spelling[position + len(marker):]
            path = Path(spelling)
            absolute = False
            resolved = None
    path = resolved if resolved is not None else (path if absolute else project / path).resolve()
    if not path.is_relative_to(project):
        raise ValueError('文件路径越出项目：' + str(value))
    relative = path.relative_to(project)
    if not recorded and relative.parts and relative.parts[0].casefold() in ('projects', project.name.casefold()):
        raise ValueError('文件路径必须相对项目根目录，不得重复 projects/项目名 或项目名：' + str(value))
    return path


def relative_file(project, value, *, recorded=False):
    project = Path(project).resolve()
    return _project_file(project, value, recorded=recorded).relative_to(project).as_posix()


LOCAL_FIELDS = {'path', 'file', 'record_dir', 'receipt', 'history', 'evidence', 'local_file',
                'approval_record', 'upload_response', 'previous_upload_response', 'reuse_response',
                'local_execution_dir', 'common_evidence_directory', 'expected_local_candidate',
                'mapping', 'mapping_file', 'selected_path', 'original_file', 'source_file', 'source_path', 'saved_outputs'}


class RecordPaths:
    """Project-scoped spelling conversion for records, never a file-access authorization."""

    def __init__(self, project):
        self.project = Path(project).resolve()
        self._files = {}

    @classmethod
    def from_resolved(cls, project, files):
        """Seed only from canonical input paths already checked at the task boundary."""
        self = cls.__new__(cls)
        self.project = Path(project)
        self._files = {}
        if not self.project.is_absolute() or '..' in self.project.parts:
            raise ValueError('记录转换需要已解析的项目根目录')
        for value in files:
            path = Path(value)
            if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(self.project):
                raise ValueError('文件路径越出项目：' + str(value))
            self._remember(path)
        return self

    def _remember(self, path):
        self._files[path.as_posix()] = path
        self._files[path.relative_to(self.project).as_posix()] = path

    def file(self, value):
        spelling = str(value).replace('\\', '/')
        path = self._files.get(spelling)
        if path is None:
            path = _project_file(self.project, spelling, recorded=True)
            self._remember(path)
            self._files[spelling] = path
        return path

    def relative_file(self, value):
        return self.file(value).relative_to(self.project).as_posix()

    def convert(self, document, *, relative=False, field=''):
        if field == 'error_details':
            return document  # Opaque remote/client errors, never project file identities.
        if isinstance(document, dict):
            return {key: self.convert(value, relative=relative, field=key) for key, value in document.items()}
        if isinstance(document, list):
            return [self.convert(value, relative=relative, field=field) for value in document]
        if isinstance(document, str) and document and field in LOCAL_FIELDS:
            spelling = document.replace('\\', '/')
            if (Path(spelling).is_absolute() or PureWindowsPath(spelling).is_absolute()) and (
                    not spelling.casefold().startswith(self.project.as_posix().casefold() + '/')
                    and ('/projects/' + self.project.name + '/').casefold() not in spelling.casefold()):
                return document  # Preserve remote evidence and external tool paths.
            path = self.file(spelling)
            return path.relative_to(self.project).as_posix() if relative else str(path)
        return document


def recorded_paths(project, document, *, relative=False, field=''):
    """Translate local file fields only; remote paths and historical prose stay intact."""
    if field == 'error_details':
        return document
    return RecordPaths(project).convert(document, relative=relative, field=field)
