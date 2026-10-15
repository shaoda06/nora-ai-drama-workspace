import copy
import json
from pathlib import Path
import tempfile
import unittest

from backend.services.comfy_tasks import SKILL
from backend.services.director_uploads import save_uploaded_workflow, check_pair, pairs


class DirectorUploadsTests(unittest.TestCase):
    def test_report_only_standard_task_copy_remains_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            record = project / 'record'
            record.mkdir()
            stem = 'Minimax-H3-导演台-视频生成-标准版'
            baseline = SKILL / 'references/comfyui-workflow'
            canvas = json.loads((baseline / (stem + '.workflow.json')).read_text(encoding='utf-8'))
            removed = {503, 504, 505, 506}
            canvas['nodes'] = [node for node in canvas['nodes'] if node['id'] not in removed]
            canvas['links'] = [link for link in canvas['links'] if link[1] not in removed and link[3] not in removed]
            retained_links = {link[0] for link in canvas['links']}
            for node in canvas['nodes']:
                for output in node.get('outputs', []):
                    output['links'] = [link for link in (output.get('links') or []) if link in retained_links]
            original = pairs.Canvas(canvas).api(403)
            (record / (stem + '.workflow.json')).write_text(json.dumps(canvas), encoding='utf-8')
            (record / (stem + '.api.json')).write_text(json.dumps(original), encoding='utf-8')
            (record / '输入映射.json').write_text(json.dumps({'uploads': []}), encoding='utf-8')
            save_uploaded_workflow(project, record, original, copy.deepcopy(original), {})
            saved = json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8'))
            self.assertEqual(saved, original)
            self.assertNotIn('504', saved)
            self.assertNotIn('506', saved)

    def test_existing_task_pair_and_mapping_follow_actual_uploaded_path(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            record = project / 'record'
            record.mkdir()
            stem = 'Minimax-H3-导演台-视频生成-标准版'
            baseline = SKILL / 'references/comfyui-workflow'
            for suffix in ('.api.json', '.workflow.json'):
                (record / (stem + suffix)).write_bytes((baseline / (stem + suffix)).read_bytes())
            original = json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8'))
            self.assertEqual(check_pair(record, original)['result'], 'passed')
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
            self.assertEqual(check_pair(record, workflow)['result'], 'passed')
            self.assertEqual(len(pairs.verify(record)), 1)
            mapping = json.loads((record / '输入映射.json').read_text(encoding='utf-8'))
            self.assertEqual(mapping['uploads'], [{'file': 'reference.png', 'input_path': 'real/renamed.png'}])
            self.assertEqual(json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8')), workflow)
            broken = copy.deepcopy(workflow)
            state = json.loads(broken['502']['inputs']['timeline_data'])
            state['batchWorkspaces']['r2v']['segments'][0]['refs'][0]['imageFile'] = 'planned/reference.png'
            broken['502']['inputs']['timeline_data'] = json.dumps(state)
            with self.assertRaisesRegex(ValueError, '核对失败'):
                save_uploaded_workflow(project, record, workflow, broken, uploads)
            self.assertEqual(json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8')), workflow)
