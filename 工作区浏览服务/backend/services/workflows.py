"""Read bundled formal and backup workflows; never submit or modify them."""
from pathlib import Path
from urllib.parse import quote
from workflow_paths import workflow_directories


def catalogue(root: Path) -> list[dict]:
    items = []
    for directory, group in workflow_directories(root):
        for canvas in sorted(directory.glob('*.workflow.json')):
            name = canvas.name.removesuffix('.workflow.json')
            api = directory / (name + '.api.json')
            items.append({'name': name, 'group': group,
                          'canvasUrl': '/api/workflows/files/' + quote(canvas.relative_to(root).as_posix(), safe='/'),
                          'apiUrl': '/api/workflows/files/' + quote(api.relative_to(root).as_posix(), safe='/') if api.is_file() else None})
    return items
