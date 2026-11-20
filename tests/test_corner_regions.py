import unittest
from itertools import product

from ysudoku.chaos_regions import RegionFragments, region_steps
from ysudoku.constraints import RegionCount
from ysudoku.model import parse_puzzle
from ysudoku.rules import CompiledRules
from ysudoku.solve import Solver
from ysudoku.state import State, Contradiction


class CornerRegionTest(unittest.TestCase):
    def test_all_orientations_and_equivalence(self):
        for corner, a, b, diagonal in ((0, 1, 9, 10), (8, 7, 17, 16),
                                        (72, 63, 73, 64), (80, 71, 79, 70)):
            fragments = RegionFragments(State(9, []))
            cells = [diagonal, a, b, corner]
            clue = RegionCount(cells, [3])
            self.assertTrue(fragments.replace_corner_clue(clue))
            for values in product(range(4), repeat=4):
                labels = dict(zip(cells, values))
                connected = labels[corner] in (labels[a], labels[b])
                distinct = all(labels[i] != labels[j] for i, j in fragments.separate)
                self.assertEqual(connected and distinct, connected and len(set(values)) == 3)
            snapshot = fragments.snapshot()
            choice, = snapshot["region_options"]
            self.assertEqual(choice["cells"], [corner])
            self.assertEqual(set(choice["colours"]), {
                g["colour"] for g in snapshot["colours"] if g["cells"][0] in (a, b)
            })
            self.assertEqual(len(snapshot["colours"]), 3)
            def local_edges(result):
                return [e for e in result["region_edges"] if set(e["cells"]) <= set(cells)]

            self.assertEqual(sum(edge["status"] == "confirmed" for edge in local_edges(snapshot)), 2)
            self.assertEqual(sum(edge["status"] == "candidate" for edge in local_edges(snapshot)), 2)
            fragments.apart(corner, a)
            self.assertTrue(fragments.propagate_choices())
            self.assertEqual(fragments.owner[corner], fragments.owner[b])
            self.assertFalse(fragments.snapshot()["region_options"])
            resolved = {tuple(sorted(e["cells"])): e["status"] for e in local_edges(fragments.snapshot())}
            self.assertEqual(resolved[tuple(sorted((corner, a)))], "confirmed")
            self.assertEqual(resolved[tuple(sorted((corner, b)))], "excluded")
            self.assertEqual(len(local_edges(snapshot)), 4)

    def test_replacement_is_active_and_rejects_two_blocked_exits(self):
        p = parse_puzzle({"cells": [[{} for _ in range(4)] for _ in range(4)],
                          "metadata": {"rules": "Chaos Construction"}})
        corner = RegionCount([2, 3, 6, 7], [3])
        interior = RegionCount([5, 6, 9, 10], [3])
        rules = CompiledRules([corner, interior])
        fragments = region_steps(Solver(p, rules), rules, [])
        self.assertEqual([c.cells() for c in fragments.count_clues], [interior.cells()])
        self.assertIn(corner, rules.constraints)
        fragments.apart(3, 2)
        fragments.apart(3, 7)
        with self.assertRaises(Contradiction):
            fragments.propagate_choices()
