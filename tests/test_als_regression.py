import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.pipeline import analyze


class ALSRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = analyze(
            str(ROOT / "fixtures" / "als-regression.json"),
            use_llm=False,
            do_audit=True,
        )

    def test_real_puzzle_uses_als(self):
        self.assertEqual(self.analysis.status, "solved")
        self.assertIn("一致", self.analysis.solution_check)
        als_steps = [s for s in self.analysis.result.steps if s.technique == "als"]
        self.assertGreaterEqual(len(als_steps), 1, "top1465 #13 must trigger ALS-XZ")
        for step in als_steps:
            self.assertEqual(step.audit, "ok", f"ALS step {step.index} failed refutation")

    def test_no_unsound_step(self):
        self.assertEqual(self.analysis.audit.get("bad"), 0)
        self.assertGreater(self.analysis.audit.get("checks", 0), 0)


if __name__ == "__main__":
    unittest.main()
