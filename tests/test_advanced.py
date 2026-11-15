import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.constraints import ClassCover
from ysudoku.model import parse_puzzle
from ysudoku.pipeline import analyze
from ysudoku.rules import build_inventory, compile_spec

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
REGIONS = [[[r, c] for r in range(br, br + 3) for c in range(bc, bc + 3)]
           for br in (0, 3, 6) for bc in (0, 3, 6)]


def data():
    cells = [[{} for _ in range(9)] for _ in range(9)]
    for i, ch in enumerate(EASY):
        if ch.isdigit():
            cells[i // 9][i % 9] = {"value": int(ch)}
    return {"cells": cells, "regions": REGIONS, "metadata": {"rules": "test"}}


class AdvancedTest(unittest.TestCase):
    def test_class_cover_check(self):
        rule = ClassCover([0, 1], [{1, 4, 7}, {2, 5, 8}])
        self.assertTrue(rule.check([1, 2, 0, 0]))
        self.assertFalse(rule.check([1, 1, 0, 0]))

    def test_modular_compiles_64_blocks(self):
        puzzle = parse_puzzle(data())
        inventory = build_inventory(puzzle)
        rules = compile_spec(puzzle, inventory, {"rules": [], "globals": [{"kind": "modular"}]})
        covers = [c for c in rules.constraints if isinstance(c, ClassCover)]
        self.assertEqual(len(covers), 64)
        self.assertTrue(any(r.get("kind") == "modular" for r in rules.describe()))

    def test_medusa_does_not_break_solving(self):
        analysis = analyze(json.dumps(data()), use_llm=False)
        self.assertEqual(analysis.status, "solved")


if __name__ == "__main__":
    unittest.main()


class RegionCountTest(unittest.TestCase):
    def test_check_regions(self):
        from ysudoku.constraints import RegionCount
        rule = RegionCount([0, 1, 2, 3], [3])
        self.assertTrue(rule.check_regions([0, 0, 0, 0], {0: 0, 1: 1, 2: 2, 3: 0}))
        self.assertFalse(rule.check_regions([0, 0, 0, 0], {0: 0, 1: 0, 2: 0, 3: 0}))

    def test_compile_region_count(self):
        puzzle = parse_puzzle(data())
        inventory = build_inventory(puzzle)
        spec = {"rules": [{"kind": "region_count",
                           "cells": ["R1C1", "R1C2", "R2C1", "R2C2"],
                           "counts": [1, 4]}], "globals": []}
        rules = compile_spec(puzzle, inventory, spec)
        kinds = [c.kind for c in rules.constraints]
        self.assertIn("region_count", kinds)
