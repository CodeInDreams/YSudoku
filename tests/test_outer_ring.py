import unittest

from ysudoku.model import parse_puzzle


def make_data():
    rows = [[{} for _ in range(11)] for _ in range(11)]
    rows[0][0] = {"value": 5}
    regions = []
    for br in range(3):
        for bc in range(3):
            regions.append([[br * 3 + r + 1, bc * 3 + c + 1] for r in range(3) for c in range(3)])
    return {
        "cells": rows,
        "regions": regions,
        "metadata": {"title": "ring", "solution": "?" * 121, "rules": ""},
    }


class OuterRingTest(unittest.TestCase):
    def test_crops_11_to_9(self):
        puzzle = parse_puzzle(make_data())
        self.assertEqual(puzzle.size, 9)
        self.assertEqual(puzzle.givens, {0: 5})

    def test_clue_outside_is_dropped(self):
        data = make_data()
        data["cells"][0][10] = {"value": 9}
        puzzle = parse_puzzle(data)
        self.assertNotIn(9, puzzle.givens)

    def test_padded_solution_keeps_only_the_playable_grid(self):
        data = make_data()
        grid = "123456789"
        data["metadata"]["solution"] = (grid + "??") * 9 + "?" * 22
        self.assertEqual(parse_puzzle(data).solution, [int(x) for x in grid * 9])


if __name__ == "__main__":
    unittest.main()


class OneBasedRegionTest(unittest.TestCase):
    def test_one_based_coords(self):
        data = make_data()
        puzzle = parse_puzzle(data)
        self.assertLess(max(max(r) for r in puzzle.regions), 81)
        self.assertEqual(len(puzzle.regions), 9)
