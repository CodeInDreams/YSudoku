import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.state import State, Unit
from ysudoku.techniques import x_chain


class XChainTest(unittest.TestCase):
    def test_chain_eliminates_common_peer(self):
        # 0-S-1-W-2-S-3 chain; cell 4 sees both ends 0 and 3
        units = [
            Unit("u", 0, [0, 1]),
            Unit("u", 1, [1, 2, 5]),
            Unit("u", 2, [2, 3]),
            Unit("u", 3, [0, 4, 6]),
            Unit("u", 4, [3, 4, 7]),
        ]
        st = State(9, units)
        for cell in range(81):
            st.dom[cell] = 1 << 8  # 9
        for cell in (0, 1, 2, 3, 5, 6, 7):
            st.dom[cell] = 1 << 4  # 5
        st.dom[4] = (1 << 4) | (1 << 8)  # {5,9}
        events = x_chain(st)
        self.assertIsNotNone(events)
        self.assertFalse(st.has(4, 5))
        self.assertTrue(st.has(4, 9))
        self.assertEqual(events[0].reason.kind, "x_chain")


if __name__ == "__main__":
    unittest.main()
