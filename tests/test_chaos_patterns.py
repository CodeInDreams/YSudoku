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
        for element in inventory:
            if element.kind == "circle":
                counts = [3] if "dddd" in (element.attrs.get("fill") or "") else [1, 4]
                spec["rules"].append({"kind": "region_count", "elements": [element.id],
                                      "counts": counts})
        rules = compile_spec(puzzle, inventory, spec)
        solver = Solver(puzzle, rules)
        steps = _chaos_pattern_steps(puzzle, rules, solver.state)
        self.assertEqual(len(steps), 8)
        self.assertEqual(steps[0].technique, "chaos_pattern")
        self.assertEqual(steps[0].events, [])
        self.assertEqual(len(steps[0].visual["focus"]), 4)
        self.assertIn("区域划分只剩", steps[0].detail)


if __name__ == "__main__":
    unittest.main()
