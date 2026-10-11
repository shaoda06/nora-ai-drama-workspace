"""Read the formal workflow directory; never submit or modify workflows."""
from pathlib import Path
from urllib.parse import quote


def catalogue(root: Path) -> list[dict]:
    items = []
    for canvas in sorted(root.glob('*.workflow.json')):
        name = canvas.name.removesuffix('.workflow.json')
        api = root / (name + '.api.json')
        items.append({'name': name, 'explicitOnly': name.endswith('-去油版'),
                      'canvasUrl': '/api/workflows/files/' + quote(canvas.name, safe=''),
                      'apiUrl': '/api/workflows/files/' + quote(api.name, safe='') if api.is_file() else None})
    return items
