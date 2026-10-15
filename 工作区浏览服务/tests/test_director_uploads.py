import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
            before = {path: path.read_bytes() for path in record.glob('*')}
            stamps = {path: path.stat().st_mtime_ns for path in record.glob('*')}
            with patch.object(pairs, 'Canvas', side_effect=AssertionError('上传后不重建配对')):
                save_uploaded_workflow(project, record, original, copy.deepcopy(original), {}, [])
            self.assertEqual(before, {path: path.read_bytes() for path in record.glob('*')})
            self.assertEqual(stamps, {path: path.stat().st_mtime_ns for path in record.glob('*')})
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
            timeline = json.loads(original['502']['inputs']['timeline_data'])
            media = {'imageFile': 'planned/reference.png', 'fileName': 'reference.png', 'subfolder': 'planned', 'type': 'input', 'index': 0}
            timeline['segments'][0]['refs'] = [media]
            timeline['batchWorkspaces']['r2v']['segments'][0]['refs'] = [copy.deepcopy(media)]
            original['502']['inputs']['timeline_data'] = json.dumps(timeline, ensure_ascii=False)
            (record / (stem + '.api.json')).write_text(json.dumps(original), 'utf-8')
            canvas_file = record / (stem + '.workflow.json')
            canvas = json.loads(canvas_file.read_text('utf-8'))
            node = next(node for node in canvas['nodes'] if node['id'] == 502)
            node['widgets_values_named']['timeline_data'] = original['502']['inputs']['timeline_data']
            node['widgets_values'] = list(node['widgets_values_named'].values())
            canvas_file.write_text(json.dumps(canvas), 'utf-8')
            self.assertEqual(check_pair(record, original)['result'], 'passed')
            workflow = copy.deepcopy(original)
            for refs in (timeline['segments'][0]['refs'], timeline['batchWorkspaces']['r2v']['segments'][0]['refs']):
                refs[0].update(imageFile='real/renamed.png', fileName='renamed.png', subfolder='real', type='input')
            workflow['502']['inputs']['timeline_data'] = json.dumps(timeline, ensure_ascii=False)
            response = {'input_path': 'real/renamed.png', 'remote': {'name': 'renamed.png', 'subfolder': 'real', 'type': 'input'}}
            bindings = [({'node': '502', 'input': 'timeline_data', 'json-path': path}, response) for path in (
                ['segments', 0, 'refs', 0, 'imageFile'],
                ['batchWorkspaces', 'r2v', 'segments', 0, 'refs', 0, 'imageFile'])]
            (record / '输入映射.json').write_text(json.dumps({'uploads': [{'file': 'reference.png', 'input_path': 'planned/reference.png'}]}))
            uploads = {'real/renamed.png': {'file': str(project / 'reference.png'), 'input_path': 'real/renamed.png'}}
            with patch.object(pairs, 'Canvas', side_effect=AssertionError('上传后不重建配对')), \
                    patch.object(pairs, 'semantic', side_effect=AssertionError('上传后不比较完整工作流')):
                save_uploaded_workflow(project, record, original, workflow, uploads, bindings)
                save_uploaded_workflow(project, record, original, workflow, uploads, bindings)
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
                save_uploaded_workflow(project, record, workflow, broken, uploads, bindings)
            self.assertEqual(json.loads((record / (stem + '.api.json')).read_text(encoding='utf-8')), workflow)

    def test_public_and_group_slots_verify_response_metadata_and_skip_unchanged_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            media = {'imageFile': 'real/shared.png', 'fileName': 'shared.png', 'subfolder': 'real', 'type': 'input'}
            state = {'global': {'refs': [copy.deepcopy(media)]},
                     'segments': [{'refs': [copy.deepcopy(media)]}, {'refs': [copy.deepcopy(media)]}]}
            state['batchWorkspaces'] = {'r2v': {'globalCommon': copy.deepcopy(state['global']),
                                              'segments': copy.deepcopy(state['segments'])}}
            workflow = {'7:502': {'class_type': 'MiniMaxH3Director', 'inputs': {'timeline_data': json.dumps(state)}}}
            (project / '输入映射.json').write_text(json.dumps({'uploads': []}), 'utf-8')
            api = project / 'task.api.json'
            api.write_text('not read during unchanged binding save', 'utf-8')
            canvas_file = project / 'task.workflow.json'
            canvas_file.write_text('not read either', 'utf-8')
            response = {'input_path': 'real/shared.png', 'remote': {'name': 'shared.png', 'subfolder': 'real', 'type': 'input'}}
            bindings = [({'node': '7:502', 'input': 'timeline_data', 'json-path': path}, response) for path in (
                ['global', 'refs', 0, 'imageFile'], ['segments', 1, 'refs', 0, 'imageFile'])]
            uploads = {'real/shared.png': {'file': str(project / 'reference.png'), 'input_path': 'real/shared.png'}}
            before = {path: path.read_bytes() for path in (api, canvas_file)}
            save_uploaded_workflow(project, project, workflow, copy.deepcopy(workflow), uploads, bindings)
            self.assertEqual(before, {path: path.read_bytes() for path in (api, canvas_file)})
            # Stale metadata, mirrors and wrong-group paths fail before any pair write.
            targets = [('global', state['global']['refs'][0]), ('group', state['segments'][1]['refs'][0]),
                       ('editor-public', state['batchWorkspaces']['r2v']['globalCommon']['refs'][0]),
                       ('editor-group', state['batchWorkspaces']['r2v']['segments'][1]['refs'][0])]
            for label, target in targets:
                for field in ('imageFile', 'fileName', 'subfolder', 'type'):
                    with self.subTest(target=label, field=field):
                        value = target[field]
                        target[field] = 'wrong-slot-or-remote-value'
                        broken = copy.deepcopy(workflow)
                        broken['7:502']['inputs']['timeline_data'] = json.dumps(state)
                        with self.assertRaisesRegex(ValueError, '素材绑定核对失败'):
                            save_uploaded_workflow(project, project, workflow, broken, uploads, bindings)
                        self.assertEqual(before, {path: path.read_bytes() for path in (api, canvas_file)})
                        target[field] = value

    def test_changed_nested_director_widget_is_saved_without_graph_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            before = {'global': {'refs': [{'imageFile': 'old.png'}]}, 'segments': []}
            before['batchWorkspaces'] = {'r2v': {'globalCommon': copy.deepcopy(before['global']), 'segments': []}}
            after = copy.deepcopy(before)
            for common in (after['global'], after['batchWorkspaces']['r2v']['globalCommon']):
                common['refs'][0].update(imageFile='actual/new.png', fileName='new.png', subfolder='actual', type='input')
            original = {'7:502': {'class_type': 'MiniMaxH3Director', 'inputs': {'timeline_data': json.dumps(before)}}}
            workflow = copy.deepcopy(original)
            workflow['7:502']['inputs']['timeline_data'] = json.dumps(after)
            canvas = {'nodes': [{'id': 7, 'type': 'subgraph-id'}], 'definitions': {'subgraphs': [
                {'id': 'subgraph-id', 'nodes': [{'id': 502, 'widgets_values_named': original['7:502']['inputs'].copy(),
                                                'widgets_values': list(original['7:502']['inputs'].values())}]}]}}
            (project / 'task.api.json').write_text(json.dumps(original), 'utf-8')
            (project / 'task.workflow.json').write_text(json.dumps(canvas), 'utf-8')
            (project / '输入映射.json').write_text(json.dumps({'uploads': []}), 'utf-8')
            bindings = [({'node': '7:502', 'input': 'timeline_data', 'json-path': ['global', 'refs', 0, 'imageFile']},
                         {'input_path': 'actual/new.png', 'remote': {'name': 'new.png', 'subfolder': 'actual', 'type': 'input'}})]
            with patch.object(pairs, 'Canvas', side_effect=AssertionError('不重建工作流')):
                save_uploaded_workflow(project, project, original, workflow, {}, bindings)
            saved = json.loads((project / 'task.workflow.json').read_text('utf-8'))
            node = saved['definitions']['subgraphs'][0]['nodes'][0]
            self.assertEqual(node['widgets_values_named'], workflow['7:502']['inputs'])
            self.assertEqual(node['widgets_values'], list(workflow['7:502']['inputs'].values()))
