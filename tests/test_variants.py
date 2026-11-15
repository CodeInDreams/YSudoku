import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.pipeline import analyze
from ysudoku.state import State, Unit

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
REGIONS = [[[r, c] for r in range(br, br + 3) for c in range(bc, bc + 3)]
           for br in (0, 3, 6) for bc in (0, 3, 6)]


def puzzle(with_solution=True):
    cells = [[{} for _ in range(9)] for _ in range(9)]
    for i, ch in enumerate(EASY):
        if ch.isdigit():
            cells[i // 9][i % 9] = {"value": int(ch)}
    meta = {"rules": "variant test"}
    if with_solution:
        meta["solution"] = SOLUTION
    data = {"cells": cells, "regions": REGIONS, "metadata": meta}
    data["lines"] = [{"wayPoints": [[0.5, 5.5], [8.5, 5.5]], "color": "#000000", "thickness": 2}]
    return data


def run(spec):
    return analyze(json.dumps(puzzle()), use_llm=False, spec_override=spec)


class VariantTest(unittest.TestCase):
    def test_sandwich(self):
        spec = {"rules": [{"kind": "sandwich", "elements": ["line:0"], "sum": 3}],
                "globals": []}
        analysis = run(spec)
        self.assertEqual(analysis.status, "solved")
        self.assertIn("一致", analysis.solution_check)
        self.assertTrue(any(c.kind == "sandwich" for c in analysis.rules.constraints))

    def test_skyscraper(self):
        spec = {"rules": [{"kind": "skyscraper", "elements": ["line:0"], "clue": 2}],
                "globals": []}
        analysis = run(spec)
        self.assertEqual(analysis.status, "solved")
        self.assertTrue(any(c.kind == "skyscraper" for c in analysis.rules.constraints))

    def test_parity_and_clone(self):
        spec = {
            "rules": [
                {"kind": "odd", "cells": ["R1C1"]},
                {"kind": "clone", "cells": ["R1C1", "R5C5"]},
            ],
            "globals": [],
        }
        analysis = run(spec)
        self.assertEqual(analysis.status, "solved")
        self.assertIn("一致", analysis.solution_check)

    def test_region_sum_check(self):
        from ysudoku.constraints import RegionSum
        values = [0] * 81
        values[0], values[1] = 1, 2
        values[2], values[3] = 1, 2
        regions = {0: 0, 1: 0, 2: 1, 3: 1}
        rule = RegionSum([0, 1, 2, 3], regions)
        self.assertEqual(len(rule.segments()), 2)
        self.assertTrue(rule.check(values))

    def test_six_by_six(self):
        grid = [
            [1, 2, 3, 4, 5, 6], [4, 5, 6, 1, 2, 3], [2, 3, 4, 5, 6, 1],
            [5, 6, 1, 2, 3, 4], [3, 4, 5, 6, 1, 2], [6, 1, 2, 3, 4, 5],
        ]
        cells = [[{"value": grid[r][c]} if (r + c) % 3 != 0 else {} for c in range(6)]
                 for r in range(6)]
        regions = [[[r, c] for r in range(br, br + 2) for c in range(bc, bc + 3)]
                   for br in (0, 2, 4) for bc in (0, 3)]
        data = {"cells": cells, "regions": regions,
                "metadata": {"rules": "6x6", "solution": "".join(map(str, sum(grid, [])))}}
        analysis = analyze(json.dumps(data), use_llm=False)
        self.assertEqual(analysis.puzzle.size, 6)
        self.assertEqual(analysis.status, "solved")
        self.assertIn("一致", analysis.solution_check)


if __name__ == "__main__":
    unittest.main()
