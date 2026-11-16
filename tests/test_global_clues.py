import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku import global_clues
from ysudoku.pipeline import analyze


@unittest.skipUnless(global_clues.available(), "OR-Tools not installed")
class GlobalClueTest(unittest.TestCase):
    def test_double_take(self):
        analysis = analyze(
            str(ROOT / "fixtures" / "double-take.json"),
            use_llm=False,
            global_time_limit=120,
        )
        self.assertEqual(analysis.status, "solved-global")
        self.assertEqual(len(analysis.clue_types), 12)
        self.assertIn("自检通过", analysis.solution_check)
        self.assertTrue(all(v in (1, 2, 3, 4, 5, 6, 7, 8, 9) for v in analysis.result.values))


if __name__ == "__main__":
    unittest.main()
