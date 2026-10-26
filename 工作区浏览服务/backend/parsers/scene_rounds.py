"""Project episode compositions and retain explicit legacy scene history."""
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import quote

SCRIPT = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts/scene_rounds.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('nora_scene_rounds', SCRIPT)
rounds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rounds)

from episode_rounds import episode_manifest_key, scene_entries, validate_episode_manifest


def load_episode_rounds(episode, read):
    raw = read(episode_manifest_key(episode))
    if raw is None:
        return []
    return [{'number': item['number'], 'scenes': list(item['scenes'])}
            for item in validate_episode_manifest(json.loads(raw), episode)['rounds']]

def load_scene_rounds(project, episode, scene, read):
    from .project import field, markdown, document_header
    from .generation import segment_body
    result = []
    for entry in scene_entries(project, episode, scene, read):
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
