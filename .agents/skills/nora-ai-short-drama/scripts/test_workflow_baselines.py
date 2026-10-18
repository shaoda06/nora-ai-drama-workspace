import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import workflow_baselines as wb

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "references/comfyui-workflow"
RETAINED = BASELINES / "非正式工作流"

class BaselineTests(unittest.TestCase):
    def test_rtx_baselines_explicit_required_parameters(self):
        for stem in ('Nora-RTX-图片2倍超分', 'Nora-RTX-AusBoss-切镜保护超分插帧'):
            with self.subTest(stem=stem):
                api = json.loads((BASELINES / f'{stem}.api.json').read_text(encoding='utf-8'))
                graph = wb.Canvas(json.loads((BASELINES / f'{stem}.workflow.json').read_text(encoding='utf-8')))
                for inputs in (api['1']['inputs'], graph.nodes[1]['widgets_values_named']):
                    self.assertEqual(inputs['strength'], 1.0)
                    self.assertEqual(inputs['image_encoding'], '8-bit RGB')
                wb.validate_rtx_inputs(api)

    def test_pair_check_rejects_rtx_fields_missing_from_both_representations(self):
        stem = 'Nora-RTX-AusBoss-切镜保护超分插帧'
        for field in ('strength', 'image_encoding'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                api = json.loads((BASELINES / f'{stem}.api.json').read_text(encoding='utf-8'))
                canvas = json.loads((BASELINES / f'{stem}.workflow.json').read_text(encoding='utf-8'))
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
        for variant in ('标准版', '去油版'):
            with self.subTest(variant=variant):
                stem = f'Minimax-H3-导演台-视频生成-{variant}'
                canvas = wb.Canvas(json.loads((BASELINES / f'{stem}.workflow.json').read_text(encoding='utf-8')))
                api = json.loads((BASELINES / f'{stem}.api.json').read_text(encoding='utf-8'))
                # Check both persisted representations, including the UI's named values.
                director = canvas.nodes[502]['widgets_values_named']
                self.assertEqual(wb.semantic(canvas.api(wb.output_for(stem))), wb.semantic(api))
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
        for variant in ('标准版', '去油版'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                stem = f'Minimax-H3-导演台-视频生成-{variant}'
                canvas = json.loads((BASELINES / f'{stem}.workflow.json').read_text(encoding='utf-8'))
                api = json.loads((BASELINES / f'{stem}.api.json').read_text(encoding='utf-8'))
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
                with self.assertRaisesRegex(AssertionError, 'Canvas/API mismatch'):
                    wb.verify(tmp)

    def test_legacy_director_pair_without_cache_name(self):
        for variant in ('标准版', '去油版'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                stem = f'Minimax-H3-导演台-视频生成-{variant}'
                canvas = json.loads((BASELINES / f'{stem}.workflow.json').read_text(encoding='utf-8'))
                api = json.loads((BASELINES / f'{stem}.api.json').read_text(encoding='utf-8'))
                director = next(node for node in canvas['nodes'] if node['type'] == 'MiniMaxH3Director')
                director['widgets_values_named'].pop('cache_name')
                director['widgets_values'] = list(director['widgets_values_named'].values())
                next(node for node in api.values() if node['class_type'] == 'MiniMaxH3Director')['inputs'].pop('cache_name')
                Path(tmp, f'{stem}.workflow.json').write_text(json.dumps(canvas), encoding='utf-8')
                Path(tmp, f'{stem}.api.json').write_text(json.dumps(api), encoding='utf-8')
                self.assertEqual(len(wb.verify(tmp)), 1)

    def test_all_pairs_and_reference_branches(self):
        results = wb.verify(BASELINES)
        self.assertEqual(len(results), 12)
        self.assertIn('Minimax-H3-导演台-YZ文武双全-SelfLift-备用测试', {r['workflow'] for r in results})
        h3 = [r for r in results if r["optional_references"]]
        self.assertEqual(len(h3), 1)
        self.assertTrue(all(r["reference_combinations"] == 147 for r in h3))

    def test_video_variants_share_generation_backbone(self):
        standard = json.loads((BASELINES / "Minimax-H3-导演台-视频生成-标准版.api.json").read_text(encoding="utf-8"))
        deoiled = json.loads((BASELINES / "Minimax-H3-导演台-视频生成-去油版.api.json").read_text(encoding="utf-8"))
        self.assertNotIn("128", standard)
        self.assertEqual(deoiled["128"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(deoiled["128"]["inputs"]["model"], ["58", 0])
        self.assertEqual(deoiled["53"]["inputs"]["model"], ["128", 0])
        self.assertEqual(standard["53"]["inputs"]["model"], ["58", 0])
        for node in ("503", "504", "505", "506"):
            standard.pop(node)
        deoiled.pop("128")
        deoiled["53"]["inputs"]["model"] = ["58", 0]
        self.assertEqual(wb.semantic(standard), wb.semantic(deoiled))

    def test_standard_saves_both_stages_without_final_output_dependency_in_first_pass(self):
        canvas = wb.Canvas(json.loads((BASELINES / "Minimax-H3-导演台-视频生成-标准版.workflow.json").read_text(encoding="utf-8")))
        first = canvas.api(504)
        second = canvas.api(506)
        self.assertNotIn("505", first)
        self.assertNotIn("503", second)
        self.assertEqual(first["503"]["inputs"]["images"], ["502", 6])
        self.assertEqual(second["505"]["inputs"]["images"], ["502", 0])
        for graph, create_id, save_id in ((first, "503", "504"), (second, "505", "506")):
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
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            del api["504"]
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "mismatch"):
                wb.verify(tmp)

    def test_retained_pairs_can_be_checked_directly(self):
        results = wb.verify(RETAINED)
        self.assertEqual(len(results), 6)
        self.assertIn('Minimax-H3-导演台-YZ文武双全-SelfLift-备用测试', {r['workflow'] for r in results})
        self.assertEqual(sum(r["reference_combinations"] for r in results), 147)

    def test_confirmation_pair_requires_report_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Minimax-H3-导演台-视频生成-标准版"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            del api["403"]
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "mismatch"):
                wb.verify(tmp)

    def test_detects_api_parameter_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Qwen2.1-文生图-普通版"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            api["459:458"]["inputs"]["seed"] += 1
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "mismatch"):
                wb.verify(tmp)

    def test_detects_upscale_factor_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Nora-RTX-图片2倍超分"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text(encoding="utf-8"))
            api["1"]["inputs"]["resize_type.scale"] = 4
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "mismatch"):
                wb.verify(tmp)

    def test_detects_missing_optional_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Nora-MiniMaxH3-多参考视频-仅二采"
            retained = Path(tmp, "非正式工作流")
            retained.mkdir()
            for suffix in ("workflow", "api"):
                source = RETAINED / f"{name}.{suffix}.json"
                (retained / source.name).write_bytes(source.read_bytes())
            api_path = retained / f"{name}.api.json"
            api = json.loads(api_path.read_text(encoding="utf-8"))
            del api["51"]
            api_path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaises(AssertionError):
                wb.verify(tmp)

    def test_detects_broken_canvas_link(self):
        source = BASELINES / "Qwen2.1-文生图-普通版.workflow.json"
        canvas = json.loads(source.read_text(encoding="utf-8"))
        canvas["links"][0][1] = 987654321
        with self.assertRaises(AssertionError):
            wb.Canvas(canvas)

    def test_detects_director_timeline_size_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = RETAINED / "Nora-MiniMaxH3-多参考视频-仅一采.workflow.json"
            canvas = json.loads(source.read_text(encoding="utf-8"))
            director = next(n for n in canvas["nodes"] if n["id"] == 402)
            timeline = json.loads(director["widgets_values_named"]["timeline_data"])
            timeline["width"] = 960
            director["widgets_values_named"]["timeline_data"] = json.dumps(timeline)
            names = list(director["widgets_values_named"])
            director["widgets_values"][names.index("timeline_data")] = director["widgets_values_named"]["timeline_data"]
            Path(tmp, source.name).write_text(json.dumps(canvas), encoding="utf-8")
            api = wb.Canvas(canvas).api(264)
            Path(tmp, source.name.replace(".workflow.", ".api.")).write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "Director timeline mismatch"):
                wb.verify(tmp)

    def verify_director_timeline(self, timeline):
        source = RETAINED / "Nora-MiniMaxH3-多参考视频-仅一采.workflow.json"
        canvas = json.loads(source.read_text(encoding="utf-8"))
        director = next(n for n in canvas["nodes"] if n["id"] == 402)
        value = json.dumps(timeline)
        names = list(director["widgets_values_named"])
        director["widgets_values_named"]["timeline_data"] = value
        director["widgets_values"][names.index("timeline_data")] = value
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, source.name).write_text(json.dumps(canvas), encoding="utf-8")
            api = wb.Canvas(canvas).api(264)
            Path(tmp, source.name.replace(".workflow.", ".api.")).write_text(json.dumps(api), encoding="utf-8")
            return wb.verify(tmp)

    def test_accepts_native_director_workspace_projection(self):
        source = RETAINED / "Nora-MiniMaxH3-多参考视频-仅一采.api.json"
        timeline = json.loads(json.loads(source.read_text(encoding="utf-8"))["402"]["inputs"]["timeline_data"])
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
        source = RETAINED / "Nora-MiniMaxH3-多参考视频-仅一采.api.json"
        original = json.loads(json.loads(source.read_text(encoding="utf-8"))["402"]["inputs"]["timeline_data"])
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
        source = BASELINES / "Qwen2.1-文生图-普通版.workflow.json"
        canvas = json.loads(source.read_text(encoding="utf-8"))
        encoder = next(n for n in canvas["definitions"]["subgraphs"][0]["nodes"] if n["id"] == 452)
        encoder["widgets_values"][1] = encoder["widgets_values"][0]
        with self.assertRaisesRegex(AssertionError, "widget mismatch"):
            wb.Canvas(canvas).api(461)

    def test_detects_extra_active_canvas_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Nora-RTX-图片2倍超分"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            path = Path(tmp, f"{name}.workflow.json")
            canvas = json.loads(path.read_text(encoding="utf-8"))
            next(n for n in canvas["nodes"] if n["id"] == 5)["mode"] = 0
            path.write_text(json.dumps(canvas), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "active node mismatch"):
                wb.verify(tmp)

    def test_detects_stale_converted_widget_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Qwen2.1-图生图-普通版"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            path = Path(tmp, f"{name}.workflow.json")
            canvas = json.loads(path.read_text(encoding="utf-8"))
            encoder = next(n for n in canvas["definitions"]["subgraphs"][0]["nodes"] if n["id"] == 474)
            encoder["widgets_values_named"]["resolution"] = 1024
            encoder["widgets_values"][2] = 1024
            path.write_text(json.dumps(canvas), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "stored parameter mismatch"):
                wb.verify(tmp)

    def test_detects_canvas_seed_randomization(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Qwen2.1-图生图-普通版"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            path = Path(tmp, f"{name}.workflow.json")
            canvas = json.loads(path.read_text(encoding="utf-8"))
            sampler = next(n for n in canvas["definitions"]["subgraphs"][0]["nodes"] if n["id"] == 458)
            sampler["widgets_values_named"]["control_after_generate"] = "randomize"
            sampler["widgets_values"][1] = "randomize"
            path.write_text(json.dumps(canvas), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "seed control mismatch"):
                wb.verify(tmp)

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
