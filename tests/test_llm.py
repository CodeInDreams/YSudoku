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
from ysudoku.pipeline import analyze


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


if __name__ == "__main__":
    unittest.main()
