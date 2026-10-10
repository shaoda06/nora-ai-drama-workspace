import copy
import json
from pathlib import Path
import tempfile
import unittest

from backend.services.director_uploads import SCRIPT, save_uploaded_workflow, pairs


class DirectorUploadsTests(unittest.TestCase):
    def test_existing_task_pair_and_mapping_follow_actual_uploaded_path(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            record = project / 'record'
            record.mkdir()
            stem = 'Minimax-H3-导演台-视频生成-标准版'
            baseline = SCRIPT.parent.parent / 'references/comfyui-workflow'
            for suffix in ('.api.json', '.workflow.json'):
                (record / (stem + suffix)).write_bytes((baseline / (stem + suffix)).read_bytes())
            original = json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8'))
            workflow = copy.deepcopy(original)
            timeline = json.loads(workflow['502']['inputs']['timeline_data'])
            media = {'imageFile': 'real/renamed.png', 'fileName': 'renamed.png', 'subfolder': 'real', 'type': 'input', 'index': 0}
            timeline['segments'][0]['refs'] = [media]
            timeline['batchWorkspaces']['r2v']['segments'][0]['refs'] = [copy.deepcopy(media)]
            workflow['502']['inputs']['timeline_data'] = json.dumps(timeline, ensure_ascii=False)
            (record / '输入映射.json').write_text(json.dumps({'uploads': [{'file': 'reference.png', 'input_path': 'planned/reference.png'}]}))
            uploads = {'real/renamed.png': {'file': str(project / 'reference.png'), 'input_path': 'real/renamed.png'}}
            save_uploaded_workflow(project, record, original, workflow, uploads)
            save_uploaded_workflow(project, record, original, workflow, uploads)
            self.assertEqual(len(pairs.verify(record)), 1)
            mapping = json.loads((record / '输入映射.json').read_text(encoding='utf-8'))
            self.assertEqual(mapping['uploads'], list(uploads.values()))
            self.assertEqual(json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8')), workflow)
            broken = copy.deepcopy(workflow)
            state = json.loads(broken['502']['inputs']['timeline_data'])
            state['batchWorkspaces']['r2v']['segments'][0]['refs'][0]['imageFile'] = 'planned/reference.png'
            broken['502']['inputs']['timeline_data'] = json.dumps(state)
            with self.assertRaisesRegex(ValueError, '核对失败'):
                save_uploaded_workflow(project, record, workflow, broken, uploads)
            self.assertEqual(json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8')), workflow)
