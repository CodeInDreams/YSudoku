import unittest

from ysudoku.parallel_refute import merge_result
from ysudoku.state import State, Unit


class MergeTest(unittest.TestCase):
    def test_discards_stale_candidate(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b1  # value 1 already gone
        result = (0, 1, [], "test", 0)
        self.assertIsNone(merge_result(st, [], result))

    def test_applies_valid_candidate(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b11
        result = (0, 1, [], "test", 0)
        merged = merge_result(st, [], result)
        self.assertIsNotNone(merged)
        self.assertFalse(st.dom[0] & 1)
