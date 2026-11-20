import os
from pathlib import Path
from tempfile import TemporaryDirectory
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
