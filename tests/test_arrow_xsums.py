import unittest

from ysudoku.arrow_xsums import cells_along, direction, entry_cell, parse_arrows


def arrow(points):
    return {"wayPoints": points}


class ArrowXsumTest(unittest.TestCase):
    def test_left_right(self):
        a = arrow([[-0.2, 5.5], [0.2, 5.5]])
        self.assertEqual(direction(a), (1, 0))
        self.assertEqual(entry_cell(a), (0, 5))
        self.assertEqual(cells_along(a)[:3], [5, 14, 23])

    def test_top_down(self):
        a = arrow([[3.5, -0.2], [3.5, 0.2]])
        self.assertEqual(direction(a), (0, 1))
        self.assertEqual(entry_cell(a), (3, 0))
        self.assertEqual(cells_along(a)[:3], [27, 28, 29])

    def test_diagonal(self):
        a = arrow([[-0.2, 5.5], [0.2, 5.1]])
        self.assertEqual(direction(a), (1, -1))
        self.assertEqual(cells_along(a)[:3], [4, 12, 20])

    def test_clue_association_and_nine_rules(self):
        underlays = [
            {"center": [-0.667, 5.5], "text": "10"},
            {"center": [3.5, -0.5], "text": "12"},
            {"center": [5.5, 9.33], "text": "19"},
        ]
        arrows = [
            arrow([[-0.2, 5.5], [0.2, 5.5]]),
            arrow([[-0.2, 5.2], [0.2, 4.8]]),
            arrow([[-0.2, 5.8], [0.2, 6.2]]),
            arrow([[3.5, -0.2], [3.5, 0.2]]),
            arrow([[3.2, -0.2], [2.8, 0.2]]),
            arrow([[3.8, -0.2], [4.2, 0.2]]),
            arrow([[5.5, 9.2], [5.5, 8.8]]),
            arrow([[5.2, 9.2], [4.8, 8.8]]),
            arrow([[5.8, 9.2], [6.2, 8.8]]),
        ]
        rules = parse_arrows({"underlays": underlays, "arrows": arrows})
        self.assertEqual(len(rules), 9)
        self.assertEqual({r["total"] for r in rules}, {10, 12, 19})


if __name__ == "__main__":
    unittest.main()


class CompileArrowTest(unittest.TestCase):
    def test_nine_arrows_become_nine_xsums(self):
        from ysudoku.model import parse_puzzle
        from ysudoku import rules

        underlays = [
            {"center": [-0.667, 5.5], "text": "10"},
            {"center": [3.5, -0.5], "text": "12"},
            {"center": [5.5, 9.33], "text": "19"},
        ]
        arrows = [
            arrow([[-0.2, 5.5], [0.2, 5.5]]),
            arrow([[-0.2, 5.2], [0.2, 4.8]]),
            arrow([[-0.2, 5.8], [0.2, 6.2]]),
            arrow([[3.5, -0.2], [3.5, 0.2]]),
            arrow([[3.2, -0.2], [2.8, 0.2]]),
            arrow([[3.8, -0.2], [4.2, 0.2]]),
            arrow([[5.5, 9.2], [5.5, 8.8]]),
            arrow([[5.2, 9.2], [4.8, 8.8]]),
            arrow([[5.8, 9.2], [6.2, 8.8]]),
        ]
        regions = [[[br * 3 + r + 1, bc * 3 + c + 1] for r in range(3) for c in range(3)]
                   for br in range(3) for bc in range(3)]
        data = {
            "cells": [[{} for _ in range(9)] for _ in range(9)],
            "regions": regions,
            "underlays": underlays,
            "arrows": arrows,
            "metadata": {
                "rules": "Clues outside the grid are omni-directional x-sums.",
            },
        }
        puzzle = parse_puzzle(data)
        spec = rules.heuristic_spec(puzzle, rules.build_inventory(puzzle))
        compiled = rules.compile_spec(puzzle, rules.build_inventory(puzzle), spec)
        sequence_rules = [r for r in compiled.resolved
                          if r.get("kind") == "x_sums" and r.get("params", {}).get("cells")]
        self.assertEqual(len(sequence_rules), 9)
