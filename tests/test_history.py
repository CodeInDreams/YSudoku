import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku import history


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ysudoku-history-")
        os.environ["YSUDOKU_HISTORY"] = os.path.join(self.tmp, "history.json")
        history.clear()

    def tearDown(self):
        os.environ.pop("YSUDOKU_HISTORY", None)

    def _analysis(self, title="Demo", steps=3, status="solved"):
        return SimpleNamespace(
            puzzle=SimpleNamespace(title=title, author="me", puzzle_id="abc"),
            result=SimpleNamespace(steps=list(range(steps))),
            status=status,
            source="heuristic",
        )

    def test_record_and_load(self):
        history.record("https://sudokupad.app/abc", self._analysis())
        entries = history.load()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Demo")
        self.assertEqual(entries[0]["steps"], 3)
        self.assertEqual(entries[0]["status"], "solved")

    def test_dedupe_and_clear(self):
        history.record("https://sudokupad.app/abc", self._analysis(steps=1))
        history.record("https://sudokupad.app/abc", self._analysis(steps=5))
        entries = history.load()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["steps"], 5)
        history.clear()
        self.assertEqual(history.load(), [])


if __name__ == "__main__":
    unittest.main()
