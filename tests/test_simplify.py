import unittest

from ysudoku.constraints import Arrow, Cage, ExactDigits, IRSupport
from ysudoku.constraints_ir import AllDifferent, Sum
from ysudoku.model import parse_puzzle
from ysudoku.rules import CompiledRules
from ysudoku.simplify import simplify
from ysudoku.solve import Solver
from ysudoku.state import State, bits


class SimplifyTest(unittest.TestCase):
    def test_solver_replaces_cage_and_keeps_pair_correlation(self):
        grid = [[{} for _ in range(9)] for _ in range(9)]
        grid[0][0] = {"value": 6}
        cage = Cage([0, 31, 62], 9)
        rules = CompiledRules([cage])
        solver = Solver(parse_puzzle({"cells": grid}), rules)
        step, error = solver.next_step()
        self.assertIsNone(error)
        self.assertEqual(step.technique, "constraint_simplify")
        self.assertIn("9−6=3", step.detail)
        target, = solver.constraints
        self.assertIsInstance(target, ExactDigits)
        self.assertEqual(target.cells(), [31, 62])
        self.assertEqual(list(bits(solver.state.dom[31])), [1, 2])
        self.assertIs(rules.constraints[0], cage)
        self.assertIsNone(simplify(target, solver.state))
        solver.state.place(31, 2)
        target.prune(solver.state)
        self.assertEqual(solver.state.vals[62], 1)

    def test_directional_rule_cannot_gain_a_permutation(self):
        state = State(9, [])
        state.place(2, 1)
        state.dom[0] = state.dom[1] = 3
        self.assertIsNone(simplify(Arrow(0, [1, 2]), state))

    def test_ir_conjunction_can_reduce_but_unit_is_not_a_source(self):
        state = State(9, [])
        state.place(0, 6)
        scope = [0, 1, 2]
        unit = AllDifferent(scope)
        pair, _ = simplify(IRSupport([Sum(scope, 9), unit]), state)
        self.assertEqual(pair.digits, [1, 2])
        self.assertIsNone(simplify(IRSupport([unit]), state))

    def test_arrow_can_reduce_and_preserve_multiplicity(self):
        state = State(9, [])
        state.place(0, 2)
        pair, _ = simplify(Arrow(0, [1, 2]), state)
        self.assertEqual(pair.digits, [1, 1])
        self.assertTrue(pair.check([2, 1, 1]))
        self.assertFalse(pair.check([2, 2, 1]))

    def test_multiple_or_zero_combinations_do_not_replace(self):
        state = State(9, [])
        self.assertIsNone(simplify(Cage([0, 1], 5), state))
        cage = Cage([0, 1], 3)
        cage.non_consecutive_pair = True
        self.assertIsNone(simplify(cage, state))
