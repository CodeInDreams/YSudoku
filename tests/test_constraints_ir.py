import unittest

from ysudoku.constraints_ir import AllDifferent, Difference, Sum
from ysudoku.state import State, Unit
from ysudoku.support_engine import unsupported


class IRTest(unittest.TestCase):
    def test_sum_requires_pair_fourteen(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        rels = [Sum([62, 70, 78], 19), AllDifferent([62, 70, 78])]
        st.dom[62] = 0b100  # 3
        found = unsupported(st, rels)
        bad = [v for c, v, _ in found if c in (70, 78)]
        self.assertEqual(sorted(set(bad)), [1, 2, 3, 4, 5, 6, 8])

    def test_difference(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = st.dom[1] = 0b11
        rels = [Difference(0, 1, 5, 9)]
        found = unsupported(st, rels)
        self.assertTrue(found)
