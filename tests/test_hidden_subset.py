import unittest

from ysudoku.state import State, Unit
from ysudoku.techniques import hidden_subset4


class HiddenSubsetTest(unittest.TestCase):
    def test_hidden_triple(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        # digits 1,2,3 only fit in cells 0,1,2
        for c in (0, 1, 2):
            st.dom[c] = 0b1111  # 1,2,3,4
        for c in range(3, 9):
            st.dom[c] = 0b1111000  # 4..9
        hidden_subset4(st)
        for c in (0, 1, 2):
            self.assertEqual(st.dom[c], 0b111)
