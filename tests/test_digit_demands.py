import unittest

from ysudoku.chaos_regions import RegionFragments, _region_digit_step
from ysudoku.constraints import Quadruple, RegionCount
from ysudoku.state import State


class DigitDemandTest(unittest.TestCase):
    def test_quadruple_exposes_multiset(self):
        con = Quadruple([0, 1, 2, 3], [1, 9, 2, 9])
        self.assertEqual(con.digit_demands(), {1: 1, 9: 2, 2: 1})

    def test_lock_uses_only_hosts_and_works_with_another_provider(self):
        class RequiredDigit:
            def cells(self):
                return [0, 1, 4, 5]

            def digit_demands(self):
                return {3: 1}

        state = State(4, [])
        fragments = RegionFragments(state)
        fragments.merge(0, 1)
        fragments.merge(fragments.owner[1], 2)
        rule = RequiredDigit()
        state.elim(4, 3)
        self.assertIsNone(_region_digit_step(fragments, [rule], 0))
        self.assertTrue(state.has(2, 3))

        state.elim(5, 3)
        step = _region_digit_step(fragments, [rule], 0)
        self.assertEqual(step.visual["premise"], [0, 1])
        self.assertEqual(step.visual["focus"], [2])
        self.assertEqual(step.visual["groups"], [{"cells": [0, 1], "kind": "premise"}])
        self.assertEqual([(e.cell, e.value) for e in step.events], [(2, 3)])
        self.assertFalse(state.has(2, 3))
        self.assertTrue(state.has(3, 3))

    def test_repeat_demands_simplify_region_counts_within_scope(self):
        rule = RegionCount([0, 1, 4, 5], [1, 4])
        rule.simplify_with_digit_demands([0, 6], {3: 2})
        self.assertEqual(rule.region_counts(), [1, 4])
        rule.simplify_with_digit_demands([0, 5], {3: 2})
        self.assertEqual(rule.region_counts(), [4])
        self.assertEqual(rule.repeat_witness, (3, 2))


if __name__ == "__main__":
    unittest.main()
