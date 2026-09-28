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

class BaselineTests(unittest.TestCase):
    def test_all_pairs_and_reference_branches(self):
        results = wb.verify(BASELINES)
        self.assertEqual(len(results), 7)
        h3 = [r for r in results if r["optional_references"]]
        self.assertEqual(len(h3), 2)
        self.assertTrue(all(r["reference_combinations"] == 147 for r in h3))

    def test_detects_api_parameter_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Qwen2.1-文生图-普通版"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text())
            api["459:458"]["inputs"]["seed"] += 1
            api_path.write_text(json.dumps(api))
            with self.assertRaisesRegex(AssertionError, "mismatch"):
                wb.verify(tmp)

    def test_detects_missing_optional_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "Nora-MiniMaxH3-多参考视频-仅一采"
            for suffix in ("workflow", "api"):
                source = BASELINES / f"{name}.{suffix}.json"
                Path(tmp, source.name).write_bytes(source.read_bytes())
            api_path = Path(tmp, f"{name}.api.json")
            api = json.loads(api_path.read_text())
            del api["51"]
            api_path.write_text(json.dumps(api))
            with self.assertRaises(AssertionError):
                wb.verify(tmp)

    def test_detects_broken_canvas_link(self):
        source = BASELINES / "Qwen2.1-文生图-普通版.workflow.json"
        canvas = json.loads(source.read_text())
        canvas["links"][0][1] = 987654321
        with self.assertRaises(AssertionError):
            wb.Canvas(canvas)

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
