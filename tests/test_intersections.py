import unittest
from unittest.mock import patch

from ysudoku.constraints import IRSupport
from ysudoku.constraints_ir import TupleRelation
from ysudoku.intersections import PatternPropagation
from ysudoku.state import State, Unit


class Constraint:
    def __init__(self, a, b):
        self.a, self.b = a, b

    def cells(self):
        return [self.a, self.b]

    def check(self, values):
        if values[self.a] == 0 or values[self.b] == 0:
            return True
        return values[self.a] != values[self.b]

    def describe(self):
        return "!="


class SupportTest(unittest.TestCase):
    def test_no_support_for_equal_values(self):
        from ysudoku.intersections import unsupported_candidates
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = st.dom[1] = 0b10  # both only value 2
        found = unsupported_candidates(st, [Constraint(0, 1)])
        self.assertIn((0, 2), [(c, v) for c, v, _ in found])


class Unary:
    def __init__(self, cell, value):
        self.cell, self.value = cell, value

    def cells(self):
        return [self.cell]

    def check(self, values):
        return values[self.cell] in (0, self.value)

    def describe(self):
        return f"cell{self.cell}={self.value}"


class BfsTest(unittest.TestCase):
    def test_pair_is_needed(self):
        from ysudoku.intersections import bfs_unsupported
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b11
        found = bfs_unsupported(st, [Unary(0, 1), Unary(0, 2)], max_rules=2)
        self.assertTrue(found)
        self.assertEqual(found[0][0], 0)


class PatternTest(unittest.TestCase):
    def test_house_occupancy_eliminates_incompatible_group(self):
        state = State(9, [Unit("row", 0, list(range(9)))])
        left = IRSupport([TupleRelation([0, 1], [(1, 2), (3, 4)])])
        right = IRSupport([TupleRelation([2, 3], [(1, 3), (5, 6)])])
        state.dom[:4] = [0b101, 0b1010, 0b10001, 0b100100]

        allowed, reason = PatternPropagation().find(state, [left, right])

        self.assertEqual(allowed, {2: 1 << 4, 3: 1 << 5})
        self.assertEqual(reason.data["hosts"], [[0, 1], [2, 3]])
        self.assertEqual(reason.data["unit"], "第1行")

    def test_shared_cells_keep_value_pairing(self):
        state = State(4, [])
        left = IRSupport([TupleRelation([0, 5, 10], [(1, 2, 3), (2, 1, 4)])])
        right = IRSupport([TupleRelation([5, 0, 15], [(2, 1, 3), (1, 1, 4)])])
        state.dom[0] = state.dom[5] = 0b0011
        state.dom[10] = state.dom[15] = 0b1100

        allowed, reason = PatternPropagation().find(state, [left, right])

        self.assertEqual(allowed, {0: 1, 5: 2, 10: 4, 15: 4})
        self.assertEqual(reason.data["shared"], [0, 5])

    def test_incomplete_patterns_cannot_lock_a_digit(self):
        state = State(4, [Unit("row", 0, list(range(4)))])
        rule = IRSupport([TupleRelation([0, 1], [(1, 2), (3, 4)])])
        with patch("ysudoku.intersections.MAX_NODES", 3):
            self.assertIsNone(PatternPropagation().find(state, [rule]))
