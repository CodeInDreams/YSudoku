import unittest

from ysudoku.chaos_regions import RegionFragments, colour_distance, region_steps
from ysudoku.constraints import RegionCount
from ysudoku.model import parse_puzzle
from ysudoku.rules import CompiledRules
from ysudoku.solve import Solver
from ysudoku.state import State


class RegionFragmentsTest(unittest.TestCase):
    def test_distinct_colours_can_later_merge(self):
        f = RegionFragments(State(4, []))
        self.assertFalse(f.snapshot()["colours"])
        f.clue(RegionCount([0, 1], [2]))
        f.clue(RegionCount([4, 5], [2]))
        second = f.colours[4]
        snapshot = f.snapshot()
        display = {group["cells"][0]: group["colour"] for group in snapshot["colours"]}
        self.assertIn({"a": display[0], "b": display[4], "possible": True}, snapshot["region_pairs"])
        f.clue(RegionCount([0, 4], [1]))
        self.assertEqual(f.owner[0], f.owner[4])
        self.assertNotIn(second, f.colours.values())
        self.assertTrue(f.blocked(f.owner[4], f.owner[5]))
        self.assertNotEqual(f.owner[1], f.owner[5])
        self.assertEqual(len(snapshot["colours"]), 4)

    def test_ambiguous_three_region_clue_does_not_colour(self):
        f = RegionFragments(State(4, []))
        self.assertIsNone(f.clue(RegionCount([0, 1, 4, 5], [3])))
        self.assertEqual(f.snapshot()["colours"], [])

    def test_adjacent_pieces_use_contrasting_native_swatches(self):
        f = RegionFragments(State(4, []))
        f.colours = {0: 3, 1: 16}  # Blue and cyan would be neighbours.
        f.display_colours = {0: 3}
        palette = f.region_palette()
        self.assertEqual(palette[0], 3)
        self.assertGreater(colour_distance(palette[0], palette[1]), colour_distance(3, 16))
        self.assertEqual(f.colours, {0: 3, 1: 16})

    def test_existing_colours_stay_when_fragments_become_adjacent(self):
        f = RegionFragments(State(4, []))
        f.colours = {0: 3, 2: 16}
        self.assertEqual(f.region_palette(), {0: 3, 2: 16})
        f.merge(0, 1)
        self.assertEqual(f.region_palette(), {0: 3, 2: 16})

    def test_ordinary_edges_are_only_drawn_where_colour_does_not_show_them(self):
        f = RegionFragments(State(4, []))
        f.apart(0, 1)
        f.apart(0, 4)
        f.mark(0)
        f.mark(1)
        edges = {tuple(e["cells"]): e["status"] for e in f.snapshot()["region_edges"]}
        self.assertNotIn((0, 1), edges)
        self.assertEqual(edges[(0, 4)], "confirmed")

    def test_capacity_includes_space_left_for_other_regions(self):
        f = RegionFragments(State(4, []))
        # This diagonal pair isolates cell 0. A region containing both
        # must reserve room for cell 0 as well.
        self.assertEqual(f.minimum_size({1, 4}), 4)
        f.merge(1, 2)
        f.merge(f.owner[1], 3)
        self.assertTrue(f.blocked(f.owner[1], 4))
        f.apart(0, f.owner[1])
        a, b, _ = f.capacity()
        self.assertEqual({a, b}, {0, 4})

    def test_same_region_prunes_digits_in_non_peer_cells(self):
        grid = [[{} for _ in range(4)] for _ in range(4)]
        grid[0][0] = {"value": 3}
        puzzle = parse_puzzle({"cells": grid, "metadata": {"rules": "Chaos Construction"}})
        rules = CompiledRules([RegionCount([0, 5], [1])])
        solver = Solver(puzzle, rules)
        self.assertTrue(solver.state.has(5, 3))
        steps = []
        region_steps(solver, rules, steps)
        self.assertFalse(solver.state.has(5, 3))
        self.assertTrue(any("排除 3" in s.detail for s in steps))
        for step in steps:
            for cell in range(16):
                self.assertLessEqual(sum(cell in group["cells"] for group in step.visual["colours"]), 4)
