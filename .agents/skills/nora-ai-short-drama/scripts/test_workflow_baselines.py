import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
import workflow_baselines as wb
from workflow_paths import workflow_file, workflow_root, workflow_directories

ROOT = Path(__file__).resolve().parents[1]
BASELINES = workflow_root(ROOT)
RETAINED = BASELINES / "非正式工作流"

class BaselineTests(unittest.TestCase):
    def test_formal_rife_is_checked(self):
        results = {item['workflow']: item for item in wb.verify(BASELINES)}
        formal = 'RTX-RIFE-自动切镜保护超分插帧'
        self.assertTrue(workflow_file(formal, 'api').is_file())
        self.assertEqual(results[formal]['node_package'], 'ComfyUI-Nora-RIFE-CutTest.zip')
        self.assertEqual(results[formal]['postprocess_delivery']['target_fps'], 30)

    def test_postprocess_rejects_bypassed_processing_and_wrong_timing(self):
        name = 'RTX-RIFE-自动切镜保护超分插帧'
        original = json.loads((workflow_file(name, 'api')).read_text(encoding='utf-8'))
        for field in ('scale', 'scene_cut_threshold'):
            changed = copy.deepcopy(original)
            del changed['12']['inputs'][field]
            with self.assertRaisesRegex(AssertionError, 'required RIFE inputs'):
                wb.validate_postprocess(changed, name)
        for node_id, field, value in [('12', 'source_fps', 24), ('1', 'images', ['7', 0]),
                                      ('16', 'images', ['12', 0]), ('16', 'frame_rate', ['7', 2]),
                                      ('16', 'audio', None), ('16', 'trim_to_audio', True)]:
            with self.subTest(node_id=node_id, field=field):
                changed = copy.deepcopy(original)
                changed[node_id]['inputs'][field] = value
                with self.assertRaises(AssertionError):
                    wb.validate_postprocess(changed, name)
        original['12']['class_type'] = 'RIFEInterpolation'
        with self.assertRaisesRegex(AssertionError, 'interpolation node'):
            wb.validate_postprocess(original, name)

    def test_rife_package_requires_complete_installable_contents(self):
        package = ROOT / 'dependencies/ComfyUI节点资源/ComfyUI-Nora-RIFE-CutTest.zip'
        wb.validate_rife_package(package)
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp, 'incomplete.zip')
            with zipfile.ZipFile(package) as source, zipfile.ZipFile(broken, 'w') as dest:
                for name in source.namelist():
                    if not name.endswith('/cut_protection.py'):
                        dest.writestr(name, source.read(name))
            with self.assertRaisesRegex(AssertionError, 'Incomplete'):
                wb.validate_rife_package(broken)

    def test_postprocess_delivery_recommendations_do_not_gate_other_paired_targets(self):
        stem = 'RTX-RIFE-自动切镜保护超分插帧'
        for width, height, fps, note_count in ((1920, 1080, 30, 0), (1080, 1920, 30, 0),
                                             (3840, 2160, 60, 0), (1280, 720, 24, 2)):
            with self.subTest(width=width, height=height, fps=fps), tempfile.TemporaryDirectory() as tmp:
                api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
                canvas = json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8'))
                api['1']['inputs'].update({'resize_type.width': width, 'resize_type.height': height})
                api['12']['inputs']['target_fps'] = fps
                for node in canvas['nodes']:
                    if node['id'] in (1, 12):
                        values = node['widgets_values_named']
                        if node['id'] == 1:
                            values.update({'resize_type.width': width, 'resize_type.height': height})
                        else:
                            values['target_fps'] = fps
                        node['widgets_values'] = list(values.values())
                Path(tmp, f'{stem}.api.json').write_text(json.dumps(api), encoding='utf-8')
                Path(tmp, f'{stem}.workflow.json').write_text(json.dumps(canvas), encoding='utf-8')
                report = wb.verify(tmp)[0]['postprocess_delivery']
                self.assertEqual((report['width'], report['height'], report['target_fps']), (width, height, fps))
                self.assertEqual(len(report['recommendation_notes']), note_count)
                self.assertEqual(report['crf'], 19)

    def test_postprocess_default_uses_30fps_and_preserves_audio_and_output_timing(self):
        stem = 'RTX-RIFE-自动切镜保护超分插帧'
        api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
        graph = wb.Canvas(json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8')))
        self.assertEqual(api['12']['inputs']['target_fps'], 30)
        self.assertEqual(api['12']['class_type'], 'NoraRIFEInterpolationCutTest')
        self.assertEqual(api['12']['inputs']['scene_cut_threshold'], 0.15)
        self.assertEqual(api['12']['inputs']['model_name'], 'flownet.pkl')
        self.assertEqual(api['12']['inputs']['source_fps'], ['7', 2])
        self.assertEqual(api['16']['inputs']['frame_rate'], ['12', 1])
        self.assertEqual(api['16']['inputs']['audio'], ['7', 1])
        self.assertFalse(api['16']['inputs']['trim_to_audio'])

    def test_rtx_baselines_explicit_required_parameters(self):
        for stem in ('RTX-图片2倍超分', 'RTX-RIFE-自动切镜保护超分插帧'):
            with self.subTest(stem=stem):
                api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
                graph = wb.Canvas(json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8')))
                for inputs in (api['1']['inputs'], graph.nodes[1]['widgets_values_named']):
                    self.assertEqual(inputs['strength'], 1.0)
                    self.assertEqual(inputs['image_encoding'], '8-bit RGB')
                wb.validate_rtx_inputs(api)

    def test_pair_check_rejects_rtx_fields_missing_from_both_representations(self):
        stem = 'RTX-RIFE-自动切镜保护超分插帧'
        for field in ('strength', 'image_encoding'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
                canvas = json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8'))
                del api['1']['inputs'][field]
                node = next(n for n in canvas['nodes'] if n['id'] == 1)
                del node['widgets_values_named'][field]
                node['widgets_values'] = list(node['widgets_values_named'].values())
                Path(tmp, f'{stem}.api.json').write_text(json.dumps(api), encoding='utf-8')
                Path(tmp, f'{stem}.workflow.json').write_text(json.dumps(canvas), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, field):
                    wb.verify(tmp)

    def test_rtx_rejects_invalid_required_values(self):
        valid = {'strength': 1.0, 'image_encoding': '8-bit RGB'}
        for field, value in (('strength', True), ('strength', -0.1), ('strength', 1.1),
                             ('strength', '1'), ('strength', math.inf), ('image_encoding', 'RGB')):
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    wb.validate_rtx_inputs({'1': {'class_type': 'RTXVideoSuperResolution',
                                                  'inputs': {**valid, field: value}}})

    def test_video_preview_dimensions_and_refine_target(self):
        stem = 'Minimax-H3-导演台-视频生成-标准版'
        canvas = wb.Canvas(json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8')))
        api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
        # Check both persisted representations, including the UI's named values.
        director = canvas.nodes[502]['widgets_values_named']
        for inputs in (director, api['502']['inputs']):
            self.assertEqual((inputs['width'], inputs['height'], inputs['frame_rate']), (864, 480, 24))
            timeline = json.loads(inputs['timeline_data'])
            self.assertEqual((timeline['width'], timeline['height'], timeline['frameRate']), (864, 480, 24))
            output = timeline['output']
            for key, value in {'mode': 'fixed', 'width': 864, 'height': 480, 'longEdge': 864,
                               'megapixels': 0.4, 'multiple': 32, 'aspectRatio': '16:9 (宽屏)'}.items():
                self.assertEqual(output[key], value, key)
            self.assertEqual(inputs['ref_max_size'], 864)
            self.assertEqual(output['refImageSize'], '1536')
            for segment in timeline['segments']:
                self.assertEqual(segment['refImageSize'], '1536')
        self.assertEqual(api['408']['inputs']['head_chunks'], 4)
        self.assertEqual(api['409']['inputs']['chunks'], 2)
        self.assertEqual(api['409']['inputs']['seq_threshold'], 4096)
        refine = api['407']['inputs']
        self.assertEqual((refine['mode'], refine['upscale_method']), ('upscale', 'h3_latent'))
        self.assertEqual((refine['width'], refine['height']), (1536, 864))
        self.assertEqual(refine['megapixels'], 1.265625)
        self.assertTrue(refine['confirm_first_pass'])
        self.assertEqual(refine['passes'], 1)
        # Refine resolves dimensions from source aspect and MP, then snaps to 32.
        pixels = refine['megapixels'] * 1024 ** 2
        aspect = director['width'] / director['height']
        resolved = (round(math.sqrt(pixels * aspect) / 32) * 32,
                    round(math.sqrt(pixels / aspect) / 32) * 32)
        self.assertEqual(resolved, (1536, 864))

    def test_director_named_cache_pair_and_conflicting_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = 'Minimax-H3-导演台-视频生成-标准版'
            canvas = json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8'))
            api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
            director = next(node for node in canvas['nodes'] if node['type'] == 'MiniMaxH3Director')
            api_director = next(node for node in api.values() if node['class_type'] == 'MiniMaxH3Director')
            name = '测试项目-EP003-C001'
            director['widgets_values_named']['cache_name'] = name
            director['widgets_values'] = list(director['widgets_values_named'].values())
            api_director['inputs']['cache_name'] = name
            Path(tmp, f'{stem}.workflow.json').write_text(json.dumps(canvas), encoding='utf-8')
            api_path = Path(tmp, f'{stem}.api.json')
            api_path.write_text(json.dumps(api), encoding='utf-8')
            self.assertEqual(len(wb.verify(tmp)), 1)
            api_director['inputs']['cache_name'] = '测试项目-EP003-C002'
            api_path.write_text(json.dumps(api), encoding='utf-8')
            self.assertEqual(len(wb.verify(tmp)), 1)

    def test_legacy_director_pair_without_cache_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = 'Minimax-H3-导演台-视频生成-标准版'
            canvas = json.loads((workflow_file(stem, 'workflow')).read_text(encoding='utf-8'))
            api = json.loads((workflow_file(stem, 'api')).read_text(encoding='utf-8'))
            director = next(node for node in canvas['nodes'] if node['type'] == 'MiniMaxH3Director')
            director['widgets_values_named'].pop('cache_name')
            director['widgets_values'] = list(director['widgets_values_named'].values())
            next(node for node in api.values() if node['class_type'] == 'MiniMaxH3Director')['inputs'].pop('cache_name')
            Path(tmp, f'{stem}.workflow.json').write_text(json.dumps(canvas), encoding='utf-8')
            Path(tmp, f'{stem}.api.json').write_text(json.dumps(api), encoding='utf-8')
            self.assertEqual(len(wb.verify(tmp)), 1)

    def test_all_pairs_and_reference_branches(self):
        results = wb.verify(BASELINES)
        self.assertEqual(len(results), 6)
        for folder, group in workflow_directories(BASELINES):
            self.assertEqual(len(wb.verify(folder)), 1 if group == 'backup' or folder.name == 'Minimax-H3' else 2)
        self.assertIn('Minimax-H3-导演台-YZ文武双全-SelfLift-备用测试', {r['workflow'] for r in results})
        h3 = [r for r in results if r["optional_references"]]
        self.assertEqual(h3, [])

    def test_standard_default_lora_chain(self):
        standard = json.loads(workflow_file('Minimax-H3-导演台-视频生成-标准版', 'api').read_text(encoding='utf-8'))
        for node in ("128", "342", "344", "345"):
            self.assertNotIn(node, standard)
        self.assertEqual(standard["53"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(standard["53"]["inputs"]["lora_name"], "minimax_h3_dmad_full_dareties_v4_step600_comfy_fro.safetensors")
        self.assertEqual(standard["53"]["inputs"]["strength_model"], 0.8)
        self.assertEqual(standard["53"]["inputs"]["model"], ["331", 0])
        self.assertEqual(standard["331"]["class_type"], "ModelAttentionBackend")
        self.assertEqual(standard["331"]["inputs"], {"attention": "comfy kitchen attention", "model": ["192", 0]})
        for node in ("406", "58", "332"):
            self.assertNotIn(node, standard)
        self.assertEqual(standard["343"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(standard["343"]["inputs"]["lora_name"], "H3_speed_slider_1.1.safetensors")
        self.assertEqual(standard["343"]["inputs"]["strength_model"], 3.0)
        self.assertEqual(standard["343"]["inputs"]["model"], ["53", 0])
        self.assertEqual(standard["405"]["inputs"]["model"], ["343", 0])

    def test_standard_lora_presets_export_only_selected_models_in_both_stages(self):
        baseline = json.loads(workflow_file('Minimax-H3-导演台-视频生成-标准版', 'workflow').read_text(encoding='utf-8'))
        optional = {128, 342, 344, 345}
        defaults = {node['id']: node for node in baseline['nodes']}
        self.assertEqual({key: defaults[key]['mode'] for key in optional}, dict.fromkeys(optional, 4))
        for key in (53, 343):
            self.assertEqual(defaults[key]['mode'], 0)
        expected = {
            1: ([53, 343], 19),
            2: ([53, 128, 343], 20),
            3: ([53, 342, 344, 345, 343], 22),
            4: ([53, 128, 342, 344, 345, 343], 23),
        }
        for choice, (chain, count) in expected.items():
            with self.subTest(choice=choice):
                canvas_data = copy.deepcopy(baseline)
                for node in canvas_data['nodes']:
                    if node['id'] in optional:
                        node['mode'] = 0 if node['id'] in chain else 4
                canvas = wb.Canvas(canvas_data)
                self.assertEqual(len(canvas.api([403, 504, 506])), count)
                for output in (504, 506):
                    graph = canvas.api(output)
                    for key in optional:
                        self.assertEqual(str(key) in graph, key in chain)
                    for parent, node in zip([331, *chain], [*chain, 405]):
                        self.assertEqual(graph[str(node)]['inputs']['model'], [str(parent), 0])
                    self.assertEqual(graph['53']['inputs']['strength_model'], 0.8)
                    self.assertEqual(graph['343']['inputs']['strength_model'], 3.0)
                    for node, strength in ((128, 0.5), (342, 0.65), (344, 0.35), (345, 0.35)):
                        if node in chain:
                            self.assertEqual(graph[str(node)]['inputs']['strength_model'], strength)

    def test_standard_saves_both_stages_without_final_output_dependency_in_first_pass(self):
        canvas = wb.Canvas(json.loads((workflow_file('Minimax-H3-导演台-视频生成-标准版', 'workflow')).read_text(encoding="utf-8")))
        first = canvas.api(504)
        second = canvas.api(506)
        self.assertNotIn("505", first)
        self.assertNotIn("503", second)
        self.assertEqual(first["503"]["inputs"]["images"], ["502", 6])
        self.assertEqual(second["505"]["inputs"]["images"], ["502", 0])
        for graph, create_id, save_id in ((first, "503", "504"), (second, "505", "506")):
            for node in ("128", "342", "344", "345"):
                self.assertNotIn(node, graph)
            self.assertEqual(graph["343"]["inputs"]["model"], ["53", 0])
            self.assertEqual(graph["405"]["inputs"]["model"], ["343", 0])
            self.assertEqual(graph["409"]["inputs"]["chunks"], 2)
            self.assertEqual(graph[create_id]["inputs"]["audio"], ["502", 1])
            self.assertEqual(graph[create_id]["inputs"]["fps"], ["502", 2])
            self.assertEqual(graph[save_id]["inputs"]["video"], [create_id, 0])
            self.assertEqual(graph[save_id]["inputs"]["format"], "mp4")
            self.assertEqual(graph[save_id]["inputs"]["format.codec"], "h264")
        self.assertNotEqual(first["504"]["inputs"]["filename_prefix"], second["506"]["inputs"]["filename_prefix"])
        self.assertTrue(first["407"]["inputs"]["confirm_first_pass"])
        self.assertEqual(first["407"]["inputs"]["seed_mode"], "inherit")

    def test_standard_pair_detects_missing_first_pass_save_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Minimax-H3-导演台-视频生成-标准版"
            for suffix in ("workflow", "api"):
                source = workflow_file(name, suffix)
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            del api["504"]
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "Missing API output"):
                wb.verify(tmp)

    def test_retained_pairs_can_be_checked_directly(self):
        results = wb.verify(RETAINED)
        self.assertEqual(len(results), 1)
        self.assertIn('Minimax-H3-导演台-YZ文武双全-SelfLift-备用测试', {r['workflow'] for r in results})
        self.assertEqual(sum(r["reference_combinations"] for r in results), 0)

    def test_confirmation_pair_requires_report_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Minimax-H3-导演台-视频生成-标准版"
            for suffix in ("workflow", "api"):
                source = workflow_file(name, suffix)
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            del api["403"]
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "Missing API output"):
                wb.verify(tmp)

    def test_detects_upscale_factor_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "RTX-图片2倍超分"
            for suffix in ("workflow", "api"):
                source = workflow_file(name, suffix)
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            api["1"]["inputs"]["resize_type.scale"] = 4
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, '2x'):
                wb.verify(tmp)

    def test_detects_broken_canvas_link(self):
        source = workflow_file('Qwen2.1-文生图-普通版', 'workflow')
        canvas = json.loads(source.read_text(encoding="utf-8"))
        canvas["links"][0][1] = 987654321
        with self.assertRaises(AssertionError):
            wb.Canvas(canvas)

    def test_detects_director_timeline_size_conflict(self):
        source = workflow_file('Minimax-H3-导演台-视频生成-标准版', 'api')
        api = json.loads(source.read_text(encoding="utf-8"))
        timeline = json.loads(api['502']['inputs']['timeline_data'])
        timeline['width'] = 960
        with self.assertRaisesRegex(AssertionError, "Director timeline mismatch"):
            self.verify_director_timeline(timeline)

    def verify_director_timeline(self, timeline):
        source = workflow_file('Minimax-H3-导演台-视频生成-标准版', 'api')
        api = json.loads(source.read_text(encoding="utf-8"))
        api['502']['inputs']['timeline_data'] = json.dumps(timeline)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, source.name).write_text(json.dumps(api), encoding="utf-8")
            return wb.verify(tmp)

    def test_accepts_native_director_workspace_projection(self):
        source = workflow_file('Minimax-H3-导演台-视频生成-标准版', 'api')
        timeline = json.loads(json.loads(source.read_text(encoding="utf-8"))["502"]["inputs"]["timeline_data"])
        timeline["global"]["refs"] = [{"index": 0, "imageFile": "cast.png", "fileName": "cast.png", "previewB64": "ui-only"}]
        workspace = timeline["batchWorkspaces"]["r2v"]
        # The native editor stores shared content only, with media defaults and no previews.
        fields = ("commonEnabled", "commonCollapsed", "prompt", "refs", "refAudios", "refVideos")
        workspace["globalCommon"] = {k: copy.deepcopy(timeline["global"][k]) for k in fields}
        workspace["globalCommon"]["refs"] = [{"index": 0, "imageFile": "cast.png", "fileName": "cast.png", "type": "input", "subfolder": ""}]
        timeline["segments"][0]["genImage"] = {}
        timeline["segments"][0]["previewFrames"] = ["ui-only"]
        workspace["segments"][0]["genImage"] = {"imageFile": "", "fileName": ""}
        workspace["segments"][0].pop("startImage")
        workspace["segments"][0].pop("endImage")
        self.assertNotEqual(workspace["globalCommon"], timeline["global"])
        self.assertNotEqual(workspace["segments"], timeline["segments"])
        self.assertEqual(len(self.verify_director_timeline(timeline)), 1)

    def test_detects_director_workspace_content_drift(self):
        source = workflow_file('Minimax-H3-导演台-视频生成-标准版', 'api')
        original = json.loads(json.loads(source.read_text(encoding="utf-8"))["502"]["inputs"]["timeline_data"])
        for change in ("public_prompt", "public_media", "segment_prompt", "segment_media", "duration", "selection"):
            with self.subTest(change=change):
                timeline = copy.deepcopy(original)
                workspace = timeline["batchWorkspaces"]["r2v"]
                if change == "public_prompt":
                    workspace["globalCommon"]["prompt"] = "stale public prompt"
                elif change == "public_media":
                    workspace["globalCommon"]["refs"] = [{"index": 0, "imageFile": "stale.png"}]
                elif change == "segment_prompt":
                    workspace["segments"][0]["prompt"] = "stale segment prompt"
                elif change == "segment_media":
                    workspace["segments"][0]["refVideos"] = [{"index": 0, "videoFile": "stale.mp4"}]
                elif change == "duration":
                    workspace["segments"][0]["durationSec"] += 1
                else:
                    workspace["runSelectEnabled"] = True
                    workspace["runSelection"] = [1]
                with self.assertRaisesRegex(AssertionError, "workspace mismatch"):
                    self.verify_director_timeline(timeline)

    def test_detects_canvas_widget_value_drift_inside_subgraph(self):
        canvas = {'nodes': [{'id': 1, 'type': 'child'}], 'links': [],
                  'definitions': {'subgraphs': [{'id': 'child', 'nodes': [
                      {'id': 2, 'type': 'PrimitiveStringMultiline',
                       'widgets_values_named': {'value': 'actual'}, 'widgets_values': ['stale']}
                  ], 'links': []}]}}
        with self.assertRaisesRegex(AssertionError, "widget mismatch"):
            wb.Canvas(canvas["definitions"]["subgraphs"][0])

    @unittest.skipUnless(hasattr(time, "tzset"), "requires local timezone switching")
    def test_client_timestamp_follows_machine_timezone(self):
        spec = importlib.util.spec_from_file_location("nora_client", ROOT / "references/comfyui-scripts/comfyui_client.py")
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        try:
            with patch.dict(os.environ, {"TZ": "Etc/GMT+5"}):
                time.tzset()
                self.assertTrue(client.now().endswith("-05:00"))
            with patch.dict(os.environ, {"TZ": "Etc/GMT-9"}):
                time.tzset()
                self.assertTrue(client.now().endswith("+09:00"))
        finally:
            time.tzset()

if __name__ == "__main__":
    unittest.main()
