import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.llm import LLMConfig
from ysudoku.model import parse_puzzle
from ysudoku.pipeline import _llm_spec, analyze
from ysudoku.rules import build_inventory, compile_spec


_TMP = tempfile.mkdtemp(prefix="ysudoku-test-")
os.environ["YSUDOKU_CACHE"] = os.path.join(_TMP, "cache")
os.environ["YSUDOKU_RULES"] = os.path.join(_TMP, "rules")


class _Handler(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *args):
        return

    def do_POST(self):
        type(self).calls += 1
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        parts = []
        for message in body.get("messages", []):
            content = message.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(p.get("text", "") for p in content if isinstance(p, dict))
        text = "\n".join(parts)
        if any(isinstance(p, dict) and p.get("type") == "image_url"
               for m in body.get("messages", []) if isinstance(m.get("content"), list)
               for p in m["content"]):
            type(self).image = True
        cage_ids = sorted(set(re.findall(r'"id":\s*"(cage:\d+)"', text)))
        spec = {"rules": [{"kind": "cage", "elements": cage_ids}], "globals": [], "notes": "mock"}
        payload = json.dumps({"choices": [{"message": {"content": json.dumps(spec)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class LLMPipelineTest(unittest.TestCase):
    def setUp(self):
        os.environ["YSUDOKU_CACHE"] = tempfile.mkdtemp(prefix="ysudoku-cache-")
        os.environ["YSUDOKU_RULES"] = os.path.join(tempfile.mkdtemp(prefix="ysudoku-rules-"), "rules")

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    # The local fixture has no SudokuPad URL. Supply an image to the mock API.
    @patch("ysudoku.pipeline._rule_image", return_value="data:image/png;base64,"
           "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
    def test_llm_rule_compilation(self, rule_image):
        config = LLMConfig(base_url=f"http://127.0.0.1:{self.port}", api_key="test", model="mock")
        analysis = analyze(str(ROOT / "fixtures" / "demo-killer.json"), llm_config=config)
        self.assertEqual(analysis.source, "llm")
        self.assertEqual(analysis.status, "solved")
        self.assertEqual(analysis.solution_check, "与题面内置答案一致")
        self.assertEqual(_Handler.calls, 1)

        self.assertTrue(_Handler.image)
        rule_image.assert_called_once()

        cached = analyze(str(ROOT / "fixtures" / "demo-killer.json"), llm_config=config)
        self.assertEqual(cached.source, "cache")
        self.assertEqual(cached.status, "solved")
        self.assertEqual(_Handler.calls, 1, "second run must reuse the cached spec")

    @patch("ysudoku.pipeline._rule_image", return_value="image")
    @patch("ysudoku.pipeline.llm.compile_rules")
    def test_underlay_markers_bind_custom_variables_and_retry_bad_scope(self, compile_llm, _image):
        circle = {"width": 0.72, "height": 0.72, "rounded": True}
        puzzle = parse_puzzle({
            "cells": [[{} for _ in range(4)] for _ in range(4)],
            "cages": [{"cells": [[0, 0], [0, 1]]}],
            "underlays": [
                {**circle, "center": [0.5, 1.5]},
                {**circle, "center": [1.5, 0.5]},
                {"center": [2.5, 0.5], "width": 1, "height": 1},
            ],
        })
        inventory = build_inventory(puzzle)
        def spec(marker):
            return {"rules": [{
                "kind": "custom", "scope": {"element": "cage:0"},
                "predicate": {"op": "gt", "args": [
                    {"op": "var", "element": marker}, {"op": "var", "index": 0},
                ]},
            }]}
        compile_llm.side_effect = [spec("marker:1"), spec("marker:0")]
        rules_spec, _, valid = _llm_spec(puzzle, inventory, LLMConfig(), [])
        self.assertTrue(valid)
        self.assertEqual(compile_llm.call_count, 2)
        request = compile_llm.call_args
        self.assertIn("R2C1", request.kwargs["previous"][-1]["content"])
        self.assertEqual([e["cells"] for e in request.args[2] if e["kind"] == "marker"],
                         [["R1C2"], ["R2C1"]])
        compiled = compile_spec(puzzle, inventory, rules_spec)
        self.assertEqual(compiled.resolved[0]["elements"], ["cage:0", "marker:0"])
        self.assertTrue(compiled.constraints[0].check([1, 2]))
        self.assertFalse(compiled.constraints[0].check([2, 1]))


if __name__ == "__main__":
    unittest.main()
