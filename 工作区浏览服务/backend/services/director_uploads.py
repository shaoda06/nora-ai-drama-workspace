"""Keep an existing director task's reopenable canvas in sync before its POST."""
import importlib.util
import json
from pathlib import Path
from project_paths import PreparationPaths

SCRIPT = Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts/workflow_baselines.py'
spec = importlib.util.spec_from_file_location('nora_director_pairs', SCRIPT)
pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairs)


def save_uploaded_workflow(project, record, original, workflow, uploaded_materials, binding_results, *, path_scope=None):
    director = any(node['class_type'] == 'MiniMaxH3Director' for node in workflow.values())
    if not director and not list(record.glob('*.api.json')):
        return
    path_scope = path_scope if path_scope is not None else PreparationPaths(project)
    project, record = path_scope.project, path_scope.file(record)
    # Only upload responses introduce new information here.
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
            if json.loads(path_scope.io_file(api_file).read_text('utf-8-sig')) == workflow:
                continue  # Durable phase recovery: the actual inputs were already saved.
            canvas_file = api_file.with_name(api_file.name.removesuffix('.api.json') + '.workflow.json')
            if not director and not canvas_file.exists():
                path_scope.io_file(api_file).write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                continue
            canvas = json.loads(path_scope.io_file(canvas_file).read_text('utf-8-sig'))
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
            path_scope.io_file(api_file).write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            path_scope.io_file(canvas_file).write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not director or not uploaded_materials:
        return
    mapping_file = record / '输入映射.json'
    original_text = path_scope.io_file(mapping_file).read_text(encoding='utf-8-sig')
    mapping = json.loads(original_text)
    uploaded_files = {path_scope.file(item['file']) for item in uploaded_materials.values()}
    sources = {item['input_path']: item for item in mapping['uploads']
               if path_scope.file(item['file']) not in uploaded_files}
    sources.update(uploaded_materials)
    mapping['uploads'] = list(sources.values())
    text = json.dumps(path_scope.convert(mapping, relative=True), ensure_ascii=False, indent=2) + '\n'
    if original_text != text:
        path_scope.io_file(mapping_file).write_text(text, encoding='utf-8')
