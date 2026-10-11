"""Keep an existing director task's reopenable canvas in sync before its POST."""
import importlib.util
import json
from pathlib import Path
from project_paths import project_file, recorded_paths

SCRIPT = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts/workflow_baselines.py'
spec = importlib.util.spec_from_file_location('nora_director_pairs', SCRIPT)
pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairs)


def save_uploaded_workflow(project, record, original, workflow, uploaded_materials):
    directors = {key: node for key, node in workflow.items() if node['class_type'] == 'MiniMaxH3Director'}
    if not directors:
        return
    for api_file in record.glob('*.api.json'):
        canvas_file = api_file.with_name(api_file.name.removesuffix('.api.json') + '.workflow.json')
        if not canvas_file.exists():
            continue
        saved = json.loads(api_file.read_text(encoding='utf-8-sig'))
        if saved != original and saved != workflow:
            raise ValueError('任务API副本与登记资料不一致：' + api_file.name)
        canvas = json.loads(canvas_file.read_text(encoding='utf-8-sig'))
        try:
            graph = pairs.Canvas(canvas)
            for key, director in directors.items():
                owner, node_id = graph.find(key)
                node = owner.nodes[node_id]
                named = node['widgets_values_named']
                named['timeline_data'] = director['inputs']['timeline_data']
                node['widgets_values'] = list(named.values())
            # Check the actual in-memory pair before saving or submitting.
            expected = pairs.Canvas(canvas).api(pairs.output_for(api_file.name.removesuffix('.api.json')))
            assert pairs.semantic(workflow) == pairs.semantic(expected), '上传后画布/API不一致'
            for director in directors.values():
                timeline = json.loads(director['inputs']['timeline_data'])
                editor = timeline['batchWorkspaces']['r2v']
                assert pairs.director_editor_state(editor['globalCommon'], True) == pairs.director_editor_state(timeline['global'], True)
                assert [pairs.director_editor_state(group) for group in editor['segments']] == [pairs.director_editor_state(group) for group in timeline['segments']]
        except (AssertionError, KeyError, TypeError) as error:
            raise ValueError('上传后导演台副本核对失败：' + str(error)) from error
        api_file.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        canvas_file.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    mapping_file = record / '输入映射.json'
    mapping = json.loads(mapping_file.read_text(encoding='utf-8-sig'))
    uploaded_files = {Path(item['file']).resolve() for item in uploaded_materials.values()}
    sources = {item['input_path']: item for item in mapping['uploads']
               if project_file(project, item['file'], recorded=True) not in uploaded_files}
    sources.update(uploaded_materials)
    mapping['uploads'] = list(sources.values())
    mapping_file.write_text(json.dumps(recorded_paths(project, mapping, relative=True), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
