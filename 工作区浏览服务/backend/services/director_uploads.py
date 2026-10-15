"""Keep an existing director task's reopenable canvas in sync before its POST."""
import importlib.util
import json
from pathlib import Path
from project_paths import project_file, recorded_paths

SCRIPT = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts/workflow_baselines.py'
spec = importlib.util.spec_from_file_location('nora_director_pairs', SCRIPT)
pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairs)


def check_pair(record, workflow):
    checked = []
    for api_file in record.glob('*.api.json'):
        canvas_file = api_file.with_name(api_file.name.removesuffix('.api.json') + '.workflow.json')
        if not canvas_file.exists():
            raise ValueError('缺少任务配对画布：' + api_file.name)
        saved = json.loads(api_file.read_text('utf-8-sig'))
        if saved != workflow:
            raise ValueError('任务API副本与登记资料不一致：' + api_file.name)
        try:
            graph = pairs.Canvas(json.loads(canvas_file.read_text('utf-8-sig')))
            # Check exactly the task graph, including its declared terminal outputs.
            linked = {value[0] for node in workflow.values() for value in node['inputs'].values() if pairs.is_link(value)}
            expected = graph.api([key for key in workflow if key not in linked])
            assert pairs.semantic(workflow) == pairs.semantic(expected), '画布/API不一致'
            for node in workflow.values():
                if node['class_type'] == 'MiniMaxH3Director':
                    timeline = json.loads(node['inputs']['timeline_data'])
                    editor = timeline['batchWorkspaces']['r2v']
                    assert pairs.director_editor_state(editor['globalCommon'], True) == pairs.director_editor_state(timeline['global'], True), '公共区与编辑状态不一致'
                    assert [pairs.director_editor_state(group) for group in editor['segments']] == [pairs.director_editor_state(group) for group in timeline['segments']], '分组与编辑状态不一致'
        except (AssertionError, KeyError, TypeError) as error:
            raise ValueError('准备配对核对失败：' + str(error)) from error
        checked.append(api_file.name)
    if not checked and any(node['class_type'] == 'MiniMaxH3Director' for node in workflow.values()):
        raise ValueError('导演台准备阶段缺少实际API／画布配对副本')
    return {'result': 'passed' if checked else 'not_provided', 'files': checked}


def save_uploaded_workflow(project, record, original, workflow, uploaded_materials, binding_results):
    if not any(node['class_type'] == 'MiniMaxH3Director' for node in workflow.values()):
        return
    # Preparation owns the complete pair. Here only upload responses introduce new information.
    documents = {}
    changed_inputs = set()
    try:
        for item, uploaded in binding_results:
            key, field = item['node'], item['input']
            before, actual = original[key]['inputs'][field], workflow[key]['inputs'][field]
            if 'json-path' not in item:
                assert actual == uploaded['input_path'], '素材字段与上传响应不一致'
                if before != actual:
                    changed_inputs.add((key, field))
                continue
            if (key, field) not in documents:
                documents[key, field] = (json.loads(before), json.loads(actual))
            old_document, document = documents[key, field]
            path = item['json-path']
            paths = [path]
            director_media = (workflow[key]['class_type'] == 'MiniMaxH3Director'
                              and field == 'timeline_data' and path[0] in ('global', 'segments'))
            if director_media:
                paths.append(['batchWorkspaces', 'r2v', 'globalCommon', *path[1:]] if path[0] == 'global'
                             else ['batchWorkspaces', 'r2v', *path])
            for target in paths:
                old_parent, parent = old_document, document
                for part in target[:-1]:
                    old_parent, parent = old_parent[part], parent[part]
                expected = {target[-1]: uploaded['input_path']}
                if director_media:
                    remote = uploaded['remote']
                    expected.update(fileName=remote['name'], subfolder=remote['subfolder'], type=remote['type'])
                assert all(parent[name] == value for name, value in expected.items()), '素材槽位与上传响应不一致：' + str(target)
                if any(old_parent.get(name) != value for name, value in expected.items()):
                    changed_inputs.add((key, field))
    except (AssertionError, KeyError, IndexError, TypeError) as error:
        raise ValueError('上传后素材绑定核对失败：' + str(error)) from error

    if changed_inputs:
        for api_file in record.glob('*.api.json'):
            canvas_file = api_file.with_name(api_file.name.removesuffix('.api.json') + '.workflow.json')
            canvas = json.loads(canvas_file.read_text('utf-8-sig'))
            definitions = {group['id']: group for group in canvas.get('definitions', {}).get('subgraphs', [])}
            # Locate only affected widgets, without constructing or comparing the workflow graph.
            for key, field in changed_inputs:
                graph = canvas
                parts = key.split(':')
                for node_id in parts[:-1]:
                    instance = {node['id']: node for node in graph['nodes']}[int(node_id)]
                    graph = definitions[instance['type']]
                node = {node['id']: node for node in graph['nodes']}[int(parts[-1])]
                named = node['widgets_values_named']
                named[field] = workflow[key]['inputs'][field]
                if isinstance(node['widgets_values'], list):
                    node['widgets_values'] = list(named.values())
                else:
                    node['widgets_values'][field] = named[field]
            api_file.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            canvas_file.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not uploaded_materials:
        return
    mapping_file = record / '输入映射.json'
    mapping = json.loads(mapping_file.read_text(encoding='utf-8-sig'))
    uploaded_files = {Path(item['file']).resolve() for item in uploaded_materials.values()}
    sources = {item['input_path']: item for item in mapping['uploads']
               if project_file(project, item['file'], recorded=True) not in uploaded_files}
    sources.update(uploaded_materials)
    mapping['uploads'] = list(sources.values())
    mapping_file.write_text(json.dumps(recorded_paths(project, mapping, relative=True), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
