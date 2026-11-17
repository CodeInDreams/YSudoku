import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.narrate import build_step
from ysudoku.pipeline import analyze
from ysudoku.state import Event, Reason


class NarrationTest(unittest.TestCase):
    def test_pair_based_whisper_has_explanation(self):
        events = [Event("elim", 2, 1, Reason("german_whisper", {"a": 2, "b": 3, "diff": 5}), 0x1FF)]
        step = build_step(0, events, 9)
        self.assertIn("Whisper", step.title)
        self.assertIn("R1C3", step.detail)

    def test_pair_based_consecutive_has_explanation(self):
        events = [Event("elim", 2, 1, Reason("consecutive", {"a": 2, "b": 3}), 0x1FF)]
        step = build_step(0, events, 9)
        self.assertIn("连续线", step.title)

    def test_double_slit_does_not_crash(self):
        analysis = analyze(str(ROOT / "fixtures" / "double-slit.json"), use_llm=False)
        self.assertIn(analysis.status, {"solved", "solved-search", "stuck"})
        self.assertGreater(len(analysis.result.steps), 0)


if __name__ == "__main__":
    unittest.main()
