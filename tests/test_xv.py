import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.model import parse_puzzle
from ysudoku.rules import build_inventory, compile_spec, heuristic_spec


def overlay(center, text, width=0.35):
    return {
        "center": center, "width": width, "height": width,
        "text": text, "fontSize": 14,
    }


class XVOverlayTest(unittest.TestCase):
    def test_all_overlay_orientations(self):
        data = {
            "id": "xv-test",
            "metadata": {"title": "XV", "rules": "XV: V sums to 5, X sums to 10."},
            "cells": [[{} for _ in range(9)] for _ in range(9)],
            "overlays": [
                overlay([0.5, 1], "V"),   # horizontal pair R1C1/R1C2
                overlay([1, 0.5], "X"),   # vertical pair R1C1/R2C1
                overlay([3.5, 4], "V"),
                overlay([4, 3.5], "X"),
            ],
        }
        puzzle = parse_puzzle(data)
        self.assertEqual(
            [(clue.mark, clue.cells) for clue in puzzle.xv_clues],
            [("V", [0, 1]), ("X", [0, 9]), ("V", [30, 31]), ("X", [30, 39])],
        )
        inventory = build_inventory(puzzle)
        self.assertEqual(len([e for e in inventory if e.kind == "xv"]), 4)

    def test_xv_is_auto_rescued_when_llm_omits_it(self):
        data = {
            "id": "xv-rescue",
            "metadata": {"title": "XV", "rules": "XV rules apply."},
            "cells": [[{} for _ in range(9)] for _ in range(9)],
            "overlays": [overlay([0.5, 1], "V"), overlay([1, 0.5], "X")],
        }
        puzzle = parse_puzzle(data)
        inventory = build_inventory(puzzle)
        rules = compile_spec(puzzle, inventory, {"rules": []}, source="llm")
        self.assertEqual(sum(1 for r in rules.resolved if r["kind"] == "xv"), 2)
        heuristic = compile_spec(puzzle, inventory,
                                 heuristic_spec(puzzle, inventory), source="heuristic")
        self.assertEqual(sum(1 for r in heuristic.resolved if r["kind"] == "xv"), 2)

    def test_underlay_xv(self):
        data = {
            "id": "xv-underlay",
            "metadata": {"title": "XV", "rules": "XV rules apply."},
            "cells": [[{} for _ in range(9)] for _ in range(9)],
            "underlays": [overlay([0.5, 1], "V")],
        }
        puzzle = parse_puzzle(data)
        self.assertEqual([(c.mark, c.cells) for c in puzzle.xv_clues], [("V", [0, 1])])


if __name__ == "__main__":
    unittest.main()
