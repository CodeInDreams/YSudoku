import unittest
from ysudoku.model import parse_puzzle

from ysudoku.constraints import Arrow, Cage, IRSupport, PairRule, Thermo
from ysudoku.constraints_ir import AllDifferent, Sum
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
        self.assertIn("R3C9 比 R4C4 小 5", steps[0].detail)
        self.assertIn("若 R4C4 填 8，按上式，R3C9 就要填 3", steps[0].detail)
        self.assertIn("所以 R3C9 只剩 3、4", steps[0].detail)
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

    def test_ir_adapter_exports_each_sum_for_shared_clue_reasoning(self):
        ir = IRSupport([Sum([0, 2], 5), AllDifferent([0, 2]), Sum([2, 4], 8)])
        link, = compile_links([ir], 9)
        state = State(9, [])
        link.apply(state)
        self.assertEqual(link.terms, ((0, 1), (4, -1)))
        self.assertEqual(link.total, -3)
        self.assertEqual(list(bits(state.dom[4])), list(range(4, 10)))

    def test_signed_equation_includes_both_sides_of_arrow(self):
        link, = compile_links([Cage([0, 2], 5), Arrow(4, [0, 2, 6])], 4)
        self.assertIn("R1C1 + R1C3 + R2C3 = R2C1", link.premises[1])
