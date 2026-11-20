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

    def test_old_client_pen_actions_are_replaced_by_saved_edge_meaning(self):
        cells = [7, 8]
        analysis = {"steps": [
            {"visual": {"region_edges": [{"cells": cells, "status": "candidate"}]}},
            {"visual": {"region_edges": [{"cells": cells, "status": "confirmed"}]}},
            {"visual": {"region_edges": [{"cells": cells, "status": "excluded"}]}},
            {"visual": {"region_edges": []}},
        ]}
        stale = [[{"op": "pen", "cells": cells, "index": 6}]] * 4
        directions = server._canonical_frame_actions(stale, analysis)
        self.assertEqual([frame[0]["index"] for frame in directions], [5, 1, 4, 4])
        self.assertEqual([frame[0]["enabled"] for frame in directions], [True, True, True, False])
