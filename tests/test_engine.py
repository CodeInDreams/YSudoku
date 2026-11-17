import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.pipeline import analyze
from ysudoku.solve import check_solution


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = analyze(str(ROOT / "fixtures" / "demo-killer.json"), use_llm=False)

    def test_solved(self):
        self.assertEqual(self.analysis.status, "solved")
        self.assertGreater(len(self.analysis.result.steps), 10)

    def test_matches_solution(self):
        self.assertIn("一致", self.analysis.solution_check)
        errors = check_solution(self.analysis.puzzle, self.analysis.rules,
                                self.analysis.result.values)
        self.assertEqual(errors, [])

    def test_every_step_has_explanation(self):
        for step in self.analysis.result.steps:
            self.assertTrue(step.title)
            self.assertTrue(step.detail)
            self.assertTrue(step.events)

    def test_visual_script(self):
        step = self.analysis.result.steps[0]
        self.assertIn("groups", step.visual)
        self.assertTrue(step.visual["focus"])


if __name__ == "__main__":
    unittest.main()
