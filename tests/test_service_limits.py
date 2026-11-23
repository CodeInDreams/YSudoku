import json
import os
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ysudoku import __version__, llm, server, store
from ysudoku.service_limits import Limits, LLMBudgetExceeded, Rejected, Work


class PublicLimitsTest(unittest.TestCase):
    def test_client_ip_requires_trusted_peer_and_single_header(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {
            "YSUDOKU_TRUSTED_PROXIES": "192.0.2.0/24,2001:db8::/32",
            "YSUDOKU_PROXY_IP_HEADER": "CF-Connecting-IP",
            "YSUDOKU_BANNED_IPS": "203.0.113.5",
            "YSUDOKU_BAN_FILE": str(Path(root) / "bans"),
        }):
            ban_file = Path(os.environ["YSUDOKU_BAN_FILE"])
            ban_file.write_text("2001:db8:1::/48 # test\n")
            limits = Limits(root)
            headers = Message()
            headers["CF-Connecting-IP"] = "::ffff:203.0.113.5"
            self.assertEqual(limits.client_ip("198.51.100.1", headers), "198.51.100.1")
            self.assertTrue(limits.banned(limits.client_ip("192.0.2.12", headers)))
            self.assertTrue(limits.banned("2001:db8:1::123"))
            headers["CF-Connecting-IP"] = "203.0.113.6"
            self.assertEqual(limits.client_ip("192.0.2.12", headers), "192.0.2.12")
            ban_file.write_text("203.0.113.6\n")
            with patch("ysudoku.service_limits.time.monotonic", return_value=limits.bans_checked + 301):
                self.assertTrue(limits.banned("203.0.113.6"))
                self.assertFalse(limits.banned("2001:db8:1::123"))
                self.assertTrue(limits.banned("203.0.113.5"))

    def test_token_usage_includes_all_provider_calls_and_survives_restart(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {
            "YSUDOKU_DAILY_LLM_INPUT_TOKENS": "10",
            "YSUDOKU_DAILY_LLM_OUTPUT_TOKENS": "9",
        }):
            limits = Limits(root)
            work = Work(limits, "192.0.2.18", "example", "Example")
            max_tokens = []

            def fake_post(_config, payload):
                max_tokens.append(payload["max_tokens"])
                return {"usage": {"prompt_tokens": 6, "completion_tokens": 2},
                        "choices": [{"message": {"content": "{}"}}]}

            with patch.object(llm, "_post", side_effect=fake_post) as post:
                token = llm.web_request.set(work.llm_request)
                try:
                    for _ in range(2):
                        self.assertEqual(llm.chat(llm.LLMConfig(), []), "{}")
                    with self.assertRaises(LLMBudgetExceeded):
                        llm.chat(llm.LLMConfig(), [])
                finally:
                    llm.web_request.reset(token)
                self.assertEqual(post.call_count, 2)
            self.assertEqual(max_tokens, [9, 7])
            self.assertTrue(work.llm_fallback)
            self.assertTrue(Limits(root).exhausted())
            with patch.object(limits, "day", return_value="2100-01-01"):
                self.assertFalse(limits.exhausted())

    def test_http_admission_keeps_slot_through_render_and_counts_new_solves(self):
        entered, release = Event(), Event()
        first = "https://sudokupad.app/first-puzzle"
        second = "https://sudokupad.app/second-puzzle"

        def solve(target, _body, *, work, **_opts):
            key = store.key_for(target)
            analysis = store.load_analysis(key)
            if analysis and not _opts["force_rules"]:
                return key, analysis
            work.acquire(solve=True)
            work.title = "Example puzzle"
            analysis = {"puzzle": {"title": work.title, "size": 9}, "source_url": target,
                        "steps": [], "rules": {}}
            store.save_analysis(key, analysis, {"title": work.title})
            return key, analysis

        def render(_url, _steps, *, directory, **_opts):
            entered.set()
            self.assertTrue(release.wait(4))
            Path(directory).mkdir(parents=True, exist_ok=True)
            (Path(directory) / "-1.png").write_bytes(b"cover")

        def wait_job(job):
            for _ in range(100):
                status, data = request(f'/api/job?id={job["id"]}')
                if status != 200 or data["status"] != "running":
                    return status, data
                time.sleep(0.01)
            self.fail("job did not finish")

        with TemporaryDirectory() as root, patch.dict(os.environ, {
            "YSUDOKU_STORE": root, "YSUDOKU_MAX_CONCURRENT": "1",
            "YSUDOKU_DAILY_SOLVES_PER_IP": "1", "YSUDOKU_TRUSTED_PROXIES": "",
            "YSUDOKU_ADMIN_TOKEN": "", "YSUDOKU_ALLOW_DELETE": "0",
        }), patch.object(server, "_stored_analysis", side_effect=solve), patch.object(server.live, "build", side_effect=render):
            with server.serve("127.0.0.1", 0) as http:
                thread = Thread(target=http.serve_forever, daemon=True)
                thread.start()

                def request(path, body=None):
                    data = json.dumps(body).encode() if body is not None else None
                    try:
                        with urlopen(Request(f"http://127.0.0.1:{http.server_port}{path}", data=data, headers={"Content-Type": "application/json"}), timeout=3) as response:
                            return response.status, json.load(response)
                    except HTTPError as error:
                        return error.code, json.load(error)

                try:
                    self.assertEqual(request("/api/health")[1]["version"], __version__)
                    _, job = request("/api/solve/start", {"url": first})
                    result = wait_job(job)
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(result[1]["payload"]["quota"]["remaining"], 0)
                    status, busy = request("/api/solve", {"url": second})
                    self.assertEqual((status, busy["code"]), (429, "server_busy"))
                    self.assertEqual(busy["jobs"][0]["title"], "Example puzzle")
                    self.assertGreaterEqual(busy["jobs"][0]["seconds"], 0)
                    release.set()
                    for _ in range(100):
                        with http.limits.lock:
                            if not http.limits.active:
                                break
                        time.sleep(0.01)
                    status, cached = request("/api/solve", {"url": first})
                    self.assertEqual(status, 200)
                    self.assertTrue(cached["frames"]["complete"])
                    status, exceeded = request("/api/store/refresh_rules", {"target": first})
                    self.assertEqual((status, exceeded["code"]), (429, "daily_solves_exceeded"))
                    self.assertEqual(request("/api/solve", {"url": "../settings.json"})[0], 400)
                    self.assertEqual(request("/api/solve", {"url": second, "notes": "规" * 1001})[0], 400)
                    self.assertEqual(request("/api/store/delete", {"key": store.key_for(first), "layer": "all"})[0], 403)
                    self.assertEqual(request("/api/live/frame?session=..&step=-1")[0], 400)
                    self.assertEqual(Limits(root).usage("127.0.0.1")["remaining"], 0)
                finally:
                    release.set()
                    http.shutdown()
                    thread.join()

    def test_invalid_urls_and_frame_indices(self):
        for url in ("file:///tmp/local.json", "https://sudokupad.app.evil.example/id", "{}"):
            with self.assertRaises(Rejected):
                server._web_target(url)
        with self.assertRaises(ValueError):
            store.frame_path("example", "../../settings")

    def test_count_pruning_uses_last_opened_and_raw_is_included_in_capacity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {
                "YSUDOKU_STORE": str(root / "store"), "YSUDOKU_CACHE": str(root),
                "SUDOKU_EXPLAIN_CACHE": str(root), "YSUDOKU_HISTORY": str(root / "history.json"),
            }):
                self.assertEqual(store.load_settings(), {
                    "max_rules": 1000, "max_steps": 1000, "max_frames": 100, "max_mb": 500,
                })
                with patch.dict(os.environ, {"YSUDOKU_STORAGE_MAX_MB": "25"}):
                    self.assertEqual(store.load_settings()["max_mb"], 25)
                    store.save_settings(max_mb=500)
                    self.assertEqual(store.load_settings()["max_mb"], 500)
                for key, saved, opened in (("old-open", 20, 1), ("recent-open", 10, 2)):
                    meta = {"title": key, "at": saved, "opened_at": opened}
                    store.save_puzzle(key, {"rules": "x" * (1024 * 1024)})
                    store.save_rules(key, {"rules": []}, meta)
                    store.save_analysis(key, {"steps": []}, meta)
                store.save_settings(max_rules=1, max_mb=1)
                self.assertIsNone(store.load_puzzle("old-open"))
                self.assertIsNotNone(store.load_puzzle("recent-open"))
                self.assertEqual(store.storage_info()["counts"]["puzzle"], 1)
                overflow = store.capacity_error()
                self.assertGreater(overflow["used_bytes"], overflow["limit_bytes"])
                self.assertIsNotNone(store.load_analysis("recent-open"), "bytes alone must not trigger eviction")
                with self.assertRaises(store.CountReductionDisabled):
                    store.save_settings(max_rules=0, allow_count_reduction=False)
                limits = Limits(store._root())
                work = Work(limits, "127.0.0.1", "incoming", "Incoming")
                with self.assertRaises(Rejected) as error:
                    work.acquire(solve=True)
                self.assertEqual(error.exception.payload["code"], "storage_limit_exceeded")
                self.assertFalse(limits.active)

    @unittest.skipUnless(os.name == "posix", "POSIX service lock")
    def test_duplicate_service_cannot_bypass_shared_limits(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, YSUDOKU_STORE=root):
            with server.serve("127.0.0.1", 0):
                with self.assertRaisesRegex(RuntimeError, "already has a running"):
                    server.serve("127.0.0.1", 0)
            with server.serve("127.0.0.1", 0):
                pass
