import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch

from ysudoku import server, store


class OpenPuzzleTest(unittest.TestCase):
    def test_preview_precedes_solving_and_reopening_updates_only_open_time(self):
        fixture = str(Path(__file__).resolve().parents[1] / "fixtures/demo-killer.json")
        with TemporaryDirectory() as directory, patch.dict(os.environ, YSUDOKU_STORE=directory):
            seen = []
            with patch.object(server, "initial_screenshot", return_value="preview.png"):
                def open_fixture(at):
                    return server._stored_analysis(
                        fixture, {"llm": False}, opened_at=at,
                        on_preview=lambda url: seen.append(url),
                        on_rules=lambda rules: seen.append("rules"),
                    )

                key, result = open_fixture(100)
                self.assertEqual(seen[:2], ["/api/rulesheet/preview.png", "rules"])
                saved_at = store._meta(key)["at"]
                seen.clear()
                _, result = open_fixture(200)
                self.assertTrue(result["cached"])
                self.assertEqual(seen[:2], ["/api/rulesheet/preview.png", "rules"])
                entry, = store.list_entries()
                self.assertEqual(entry["opened_at"], 200)
                self.assertEqual(entry["at"], saved_at)
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

        def analyze(*_args, on_preview, on_preview_start, **_kwargs):
            on_preview_start()
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
                self.assertFalse(reached_rules.is_set())
                job["preview_ready"].set()
                self.assertTrue(reached_rules.wait(1))
            finally:
                with server._JOBS_LOCK:
                    job = server._JOBS.pop(job_id)
                    job["preview_ready"].set()
