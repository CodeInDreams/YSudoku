import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from ysudoku import server, store


class OpenPuzzleTest(unittest.TestCase):
    def test_rule_image_uses_playback_crop_policy(self):
        from ysudoku.pipeline import _rule_image

        with TemporaryDirectory() as directory:
            frame = Path(directory) / "preview.png"
            frame.write_bytes(b"test")
            for outside in (False, True):
                with self.subTest(outside=outside), patch(
                    "ysudoku.pipeline.initial_screenshot", return_value=str(frame)
                ) as capture:
                    puzzle = SimpleNamespace(rule_sheet="", source_url="https://sudokupad.app/example",
                                             size=9, has_outside_clues=outside)
                    _rule_image(puzzle)
                    capture.assert_called_once_with(puzzle.source_url, 9, crop=not outside)

    def test_language_mismatch_requires_explicit_regeneration(self):
        fixture = str(Path(__file__).resolve().parents[1] / "fixtures/demo-killer.json")
        with TemporaryDirectory() as directory, patch.dict(os.environ, YSUDOKU_STORE=directory):
            key, zh = server._stored_analysis(fixture, {"llm": False})
            self.assertEqual(zh["content_lang"], "zh")
            original_hash = store.steps_hash(key)
            # Older versions recorded the requested language without translating the proof.
            legacy = store.load_analysis(key)
            del legacy["content_lang"]
            legacy["lang"] = "en"
            store.save_analysis(key, legacy, {})
            with patch.object(server, "analyze") as analyze:
                _, saved = server._stored_analysis(fixture, {"lang": "en"})
                analyze.assert_not_called()
            self.assertTrue(saved["cached"])
            self.assertEqual(saved["content_lang"], "zh")
            self.assertEqual(saved["steps"], zh["steps"])
            self.assertEqual(store.steps_hash(key), original_hash)
            self.assertNotIn("cache_version", saved)
            _, en = server._stored_analysis(fixture, {"llm": False, "lang": "en"}, force_steps=True)
            self.assertEqual(en["algo_version"], zh["algo_version"])
            self.assertEqual(en["content_lang"], "en")
            self.assertNotEqual(en["steps"][0]["detail"], zh["steps"][0]["detail"])
            self.assertEqual(en["steps"][0]["events"], zh["steps"][0]["events"])
            self.assertNotEqual(store.steps_hash(key), original_hash)

    def test_old_solver_cache_survives_open_and_failed_refresh(self):
        fixture = str(Path(__file__).resolve().parents[1] / "fixtures/demo-killer.json")
        with TemporaryDirectory() as directory, patch.dict(os.environ, YSUDOKU_STORE=directory):
            key, payload = server._stored_analysis(fixture, {"llm": False})
            self.assertEqual(payload["algo_version"], server.ANALYSIS_VERSION)
            payload["algo_version"] -= 1
            payload["status"] = "stuck"
            payload["rule_sheet"] = "/api/rulesheet/old-capture.png"
            payload["message"] = "没有候选可再缩小；可开启「反证」(--allow-chains) 尝试高级试探"
            payload["steps"][0].update(
                technique="forcing_chain",
                detail="反证结论。\n注意：这一步是反证，不是直接推理；如只想看纯逻辑链，请关闭「反证」开关。",
            )
            store.save_analysis(key, payload, {})
            store.frames_dir(key).mkdir()
            store.frame_path(key, -1).write_bytes(b"previous frame")
            with patch.object(server, "analyze", side_effect=RuntimeError("stop refresh")) as analyze:
                _, saved = server._stored_analysis(fixture, {"llm": False, "chains": True, "lang": "en"})
                self.assertTrue(saved["cached"])
                self.assertEqual(saved["cache_version"]["saved"], payload["algo_version"])
                self.assertEqual(saved["cache_version"]["current"], server.ANALYSIS_VERSION)
                self.assertEqual(saved["message"], "没有候选可再缩小")
                self.assertEqual(saved["steps"][0]["detail"], "反证结论。")
                self.assertEqual(saved["rule_sheet"], "")
                analyze.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, "stop refresh"):
                    server._stored_analysis(fixture, {"llm": False}, force_steps=True)
            self.assertEqual(store.load_analysis(key)["algo_version"], payload["algo_version"])
            self.assertEqual(store.frame_path(key, -1).read_bytes(), b"previous frame")
            with patch.object(server, "analyze", wraps=server.analyze) as analyze:
                _, updated = server._stored_analysis(fixture, {"llm": False, "chains": False},
                                                     force_steps=True)
                self.assertTrue(analyze.call_args.kwargs["allow_chains"])
            self.assertEqual(updated["algo_version"], server.ANALYSIS_VERSION)
            self.assertNotIn("cache_version", updated)

    def test_partial_render_cache_rebuilds_and_reports_worker_errors(self):
        def fail_render(_url, _steps, *, wait, **_options):
            self.assertTrue(wait)
            entered.set()
            release.wait(2)
            raise server.live.LiveError("failed before initial screenshot")

        entered, release = Event(), Event()
        with TemporaryDirectory() as directory, patch.dict(os.environ, YSUDOKU_STORE=directory):
            key = "partial"
            analysis = {
                "source_url": "https://sudokupad.app/example",
                "puzzle": {"title": "Example", "size": 9}, "steps": [{}, {}],
            }
            store.save_analysis(key, analysis, {"title": "Example"})
            frames = store.frames_dir(key)
            frames.mkdir(parents=True)
            for step in (-1, 1):
                store.frame_path(key, step).write_bytes(b"old frame")
            store.set_frames_hash(key, "digest", proof_hash=store.hash_json(analysis["steps"]),
                                  renderer=server.live.FRAME_RENDERER_VERSION)
            with server.serve("127.0.0.1", 0) as httpd:
                thread = Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_port}"

                def request(path, body=None):
                    data = json.dumps(body).encode() if body is not None else None
                    with urlopen(Request(base + path, data=data, headers={"Content-Type": "application/json"}), timeout=2) as response:
                        return json.load(response)

                try:
                    with patch.object(server.live, "build", side_effect=fail_render) as build:
                        body = {"key": key}
                        self.assertTrue(request("/api/live/build", body)["building"])
                        self.assertTrue(entered.wait(1))
                        self.assertTrue(request("/api/live/build", body)["building"])
                        build.assert_called_once()
                        progress_url = "/api/live/progress?session=partial&total=2"
                        self.assertFalse(request(progress_url)["complete"])
                        self.assertFalse(store.has_frames(key, "digest"))
                        release.set()
                        progress = request(progress_url)
                        for _ in range(50):
                            if progress["error"]:
                                break
                            time.sleep(0.02)
                            progress = request(progress_url)
                        self.assertEqual(progress["error"]["message"], "failed before initial screenshot")
                finally:
                    release.set()
                    httpd.shutdown()
                    thread.join()

    def test_preview_precedes_solving_and_reopening_updates_only_open_time(self):
        fixture = str(Path(__file__).resolve().parents[1] / "fixtures/demo-killer.json")
        with TemporaryDirectory() as directory, patch.dict(os.environ, YSUDOKU_STORE=directory):
            seen = []
            with patch.object(server, "initial_screenshot", return_value="preview.png") as screenshot:
                def open_fixture(at):
                    return server._stored_analysis(
                        fixture, {"llm": False}, opened_at=at,
                        on_preview=lambda url: seen.append(url),
                        on_rules=lambda rules: seen.append("rules"),
                    )

                key, result = open_fixture(time.time())
                self.assertEqual(seen[:2], ["/api/rulesheet/preview.png", "rules"])
                self.assertTrue(screenshot.call_args.kwargs["crop"])
                saved = store._meta(key)
                reopened_at = saved["opened_at"] + 1
                seen.clear()
                _, result = open_fixture(reopened_at)
                self.assertTrue(result["cached"])
                self.assertEqual(seen[:2], ["/api/rulesheet/preview.png", "rules"])
                entry, = store.list_entries()
                self.assertEqual(entry["opened_at"], reopened_at)
                self.assertEqual(entry["at"], saved["at"])
                seen.clear()
                _, result = server._stored_analysis(
                    fixture, {"llm": False}, on_preview=seen.append,
                    on_preview_start=lambda: seen.append("preview"),
                    on_rules=lambda rules: seen.append("rules"),
                    on_step=lambda *args: seen.append("solve"),
                )
                self.assertTrue(result["cached"])
                self.assertEqual(seen, [])


    def test_browser_job_waits_for_initial_preview(self):
        reached_rules = Event()

        def analyze(*_args, on_preview, on_preview_start, on_title, **_kwargs):
            on_preview_start()
            on_title("Sample puzzle")
            on_preview("/api/rulesheet/preview.png")
            reached_rules.set()
            return "key", {}

        with patch.object(server, "_stored_analysis", side_effect=analyze):
            job_id = server._start_job("sample", {"wait_for_preview": True}, False)
            try:
                deadline = time.monotonic() + 1
                while True:
                    with server._JOBS_LOCK:
                        job = dict(server._JOBS[job_id])
                    if job.get("preview") or time.monotonic() >= deadline:
                        break
                    time.sleep(0.01)
                self.assertEqual(job["preview"], "/api/rulesheet/preview.png")
                self.assertEqual(job["phase"], "preview")
                self.assertEqual(job["title"], "Sample puzzle")
                self.assertFalse(reached_rules.is_set())
                job["preview_ready"].set()
                self.assertTrue(reached_rules.wait(1))
            finally:
                with server._JOBS_LOCK:
                    job = server._JOBS.pop(job_id)
                    job["preview_ready"].set()
