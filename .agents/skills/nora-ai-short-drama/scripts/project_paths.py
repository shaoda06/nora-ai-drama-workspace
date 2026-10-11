"""Project-relative file identities; legacy evidence is read without rewriting it."""
from pathlib import Path, PureWindowsPath


def project_file(project, value, *, recorded=False):
    project = Path(project).resolve()
    spelling = str(value).replace('\\', '/')
    path = Path(spelling)
    windows = PureWindowsPath(spelling)
    absolute = path.is_absolute() or windows.is_absolute()
    if recorded and absolute and not path.resolve().is_relative_to(project):
        marker = '/projects/' + project.name + '/'
        position = spelling.casefold().find(marker.casefold())
        if position >= 0:
            spelling = spelling[position + len(marker):]
            path = Path(spelling)
            absolute = False
    path = (path if absolute else project / path).resolve()
    if not path.is_relative_to(project):
        raise ValueError('文件路径越出项目：' + str(value))
    return path


def relative_file(project, value):
    return project_file(project, value).relative_to(Path(project).resolve()).as_posix()


LOCAL_FIELDS = {'path', 'file', 'record_dir', 'receipt', 'history', 'evidence', 'local_file',
                'approval_record', 'upload_response', 'previous_upload_response', 'reuse_response',
                'local_execution_dir', 'common_evidence_directory', 'expected_local_candidate',
                'mapping', 'mapping_file', 'selected_path', 'original_file', 'source_file', 'source_path', 'saved_outputs'}


def recorded_paths(project, document, *, relative=False, field=''):
    """Translate local file fields only; remote paths and historical prose stay intact."""
    if isinstance(document, dict):
        return {key: recorded_paths(project, value, relative=relative, field=key)
                for key, value in document.items()}
    if isinstance(document, list):
        return [recorded_paths(project, value, relative=relative, field=field) for value in document]
    if isinstance(document, str) and document and field in LOCAL_FIELDS:
        spelling = document.replace('\\', '/')
        if (Path(spelling).is_absolute() or PureWindowsPath(spelling).is_absolute()) and (
                not spelling.casefold().startswith(Path(project).resolve().as_posix().casefold() + '/')
                and ('/projects/' + Path(project).name + '/').casefold() not in spelling.casefold()):
            return document  # Remote filesystem evidence or external tools, not project files.
        path = project_file(project, document, recorded=True)
        return path.relative_to(Path(project).resolve()).as_posix() if relative else str(path)
    return document
