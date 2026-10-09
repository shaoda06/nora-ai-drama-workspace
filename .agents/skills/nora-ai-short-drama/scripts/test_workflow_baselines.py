import copy
import importlib.util
import json
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
    def test_all_pairs_and_reference_branches(self):
        results = wb.verify(BASELINES)
        self.assertEqual(len(results), 11)
        h3 = [r for r in results if r["optional_references"]]
        self.assertEqual(len(h3), 1)
        self.assertTrue(all(r["reference_combinations"] == 147 for r in h3))

    def test_video_variants_differ_only_by_optional_lora(self):
        standard = json.loads((BASELINES / "Minimax-H3-导演台-视频生成-标准版.api.json").read_text(encoding="utf-8"))
        deoiled = json.loads((BASELINES / "Minimax-H3-导演台-视频生成-去油版.api.json").read_text(encoding="utf-8"))
        self.assertNotIn("128", standard)
        self.assertEqual(deoiled["128"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(deoiled["128"]["inputs"]["model"], ["58", 0])
        self.assertEqual(deoiled["53"]["inputs"]["model"], ["128", 0])
        self.assertEqual(standard["53"]["inputs"]["model"], ["58", 0])
        deoiled.pop("128")
        deoiled["53"]["inputs"]["model"] = ["58", 0]
        self.assertEqual(wb.semantic(standard), wb.semantic(deoiled))

    def test_retained_pairs_can_be_checked_directly(self):
        results = wb.verify(RETAINED)
        self.assertEqual(len(results), 5)
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
