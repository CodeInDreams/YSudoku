import unittest
from ysudoku.model import parse_puzzle

from ysudoku.constraints import Arrow, Cage, PairRule, Thermo
from ysudoku.rules import CompiledRules
from ysudoku.solve import Solver
from ysudoku.state import State, bits
from ysudoku.sum_links import compile_links


class SumLinksTest(unittest.TestCase):
    def test_v_arrow_then_thermo_without_assumptions(self):
        a, b, c, d, e = 0, 13, 26, 30, 43
        v = PairRule(a, b, "xv", lambda x, y: x + y == 5, "V", sum=5)
        rules = CompiledRules([v, Arrow(d, [a, b, c]), Thermo([c, e])])
        puzzle = parse_puzzle({"cells": [[{} for _ in range(9)] for _ in range(9)]})
        solver = Solver(puzzle, rules)
        solver.state.dom[d] = 0b110000000
        result = solver.run()
        self.assertEqual(list(bits(solver.state.dom[c])), [3, 4])
        self.assertEqual(min(bits(solver.state.dom[e])), 4)
        steps = [s for s in result.steps if s.technique == "sum_link"]
        self.assertEqual(len(steps), 1)
        self.assertIn("箭头", steps[0].detail)
        self.assertIn("V ", steps[0].detail)
        self.assertFalse(any(s.branch for s in result.steps))
        solver.state.dom[d] = 1 << 8
        solver.run()
        self.assertEqual(solver.state.vals[c], 4)

    def test_partially_overlapping_cages_keep_noncontiguous_values(self):
        link, = compile_links([Cage([0, 2, 4], 12), Cage([2, 4, 6], 10)], 9)
        state = State(9, [])
        state.dom[6] = 0b101
        link.apply(state)
        self.assertEqual(list(bits(state.dom[0])), [3, 5])
