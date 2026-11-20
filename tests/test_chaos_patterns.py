import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.model import parse_puzzle
from ysudoku.pipeline import _chaos_pattern_steps
from ysudoku.rules import build_inventory, compile_spec, heuristic_spec
from ysudoku.solve import Solver


class ChaosPatternTest(unittest.TestCase):
    def test_circle_patterns_are_observable(self):
        puzzle = parse_puzzle(json.loads((ROOT / "fixtures" / "tringle.json").read_text()))
        inventory = build_inventory(puzzle)
        spec = heuristic_spec(puzzle, inventory)
        rules = compile_spec(puzzle, inventory, spec)
        solver = Solver(puzzle, rules)
        steps = _chaos_pattern_steps(puzzle, rules, solver.state)
        self.assertEqual(len(steps), 8)
        self.assertEqual(steps[0].technique, "chaos_pattern")
        self.assertEqual(steps[0].events, [])
        self.assertEqual(len(steps[0].visual["focus"]), 4)
        self.assertIn("两两不同区", steps[0].detail)
        counts = [c for c in rules.constraints if c.kind == "region_count"]
        self.assertEqual(counts[0].clue_counts, [1, 4])
        self.assertEqual(counts[0].counts, [4])
        self.assertEqual(counts[0].repeat_witness, (9, 2))
        self.assertEqual([c.counts for c in counts[1:4]], [[1, 4]] * 3)
        self.assertEqual([c.counts for c in counts[4:]], [[3]] * 4)


if __name__ == "__main__":
    unittest.main()
