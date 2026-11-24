import unittest
from time import monotonic

from ysudoku.between_cases import endpoint_support
from ysudoku.constraints import Between
from ysudoku.state import State, Unit


class BetweenCasesTest(unittest.TestCase):
    def test_join_two_endpoint_pairs_through_a_shared_house(self):
        # Two three-cell lines share a row across their endpoints. Digits 1 and
        # 4 cannot be used by both lines in that row at once.
        state = State(5, [Unit("row", 0, list(range(5)))])
        state.dom[0] = 0b00001
        state.dom[1] = 0b11000
        state.dom[2] = 0b00010
        state.dom[3] = 0b11000
        state.dom[4] = 0b00100
        state.dom[5] = 0b00110
        state.dom[6] = 0b01000
        constraints = [Between([0, 5, 1]), Between([2, 6, 3])]
        changes, details = endpoint_support(state, constraints, monotonic() + 3)

        self.assertEqual(changes[1], 0b01000)
        self.assertEqual(changes[3], 0b10000)
        self.assertTrue(details["retained"])
        self.assertEqual(state.dom[1], 0b11000)

    def test_incomplete_endpoint_trial_leaves_state_unchanged(self):
        state = State(4, [])
        lines = [Between([0, 1, 2]), Between([4, 5, 6])]
        self.assertIsNone(endpoint_support(state, lines, monotonic() - 1))
        self.assertEqual(state.dom, [15] * 16)
