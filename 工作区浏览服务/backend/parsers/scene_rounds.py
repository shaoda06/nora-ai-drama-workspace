"""Read explicit scene revision compositions without inferring history from media."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import quote

SCRIPT = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts/scene_rounds.py'
spec = importlib.util.spec_from_file_location('nora_scene_rounds', SCRIPT)
rounds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rounds)

def load_scene_rounds(project, episode, scene, read):
    from .project import field, markdown, document_header
    from .generation import segment_body
    key = rounds.manifest_key(episode, scene)
    raw = read(key)
    if raw is None:
        return []
    data = rounds.validate_manifest(json.loads(raw), episode, scene)
    result = []
    for entry in data['rounds']:
        item = {**entry, 'issues': []}
        documents = {}
        for kind in ('script', 'storyboard'):
            reference = entry[kind]
            file = reference['file']
            if Path(file).is_absolute() or not (project / file).resolve().is_relative_to(project):
                raise ValueError('场次轮次文档越出项目：' + file)
            text = read(file)
            if text is None or field(text, '文档版本').rstrip('。') != reference['version']:
                item['issues'].append(('剧本' if kind == 'script' else '分镜') + '文件缺失或版本不匹配')
                item[kind] = None
                continue
            documents[kind] = text
            doc = {'title': Path(file).stem, 'html': markdown(text, file), 'url': quote(file, safe='/-._~'), **document_header(text, file)}
            item[kind] = {'kind': 'document', 'name': Path(file).stem, 'key': file, 'url': doc['url'], 'doc': doc, 'version': reference['version']}
        item['segments'] = [{**segment,
            'scriptHtml': markdown(segment_body(documents.get('storyboard', ''), segment['id']), entry['storyboard']['file']),
            'scriptUrl': quote(entry['storyboard']['file'], safe='/-._~')} for segment in entry['segments']]
        result.append(item)
    return result
