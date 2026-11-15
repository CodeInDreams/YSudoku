import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.state import State, Unit
from ysudoku.techniques import als


class ALSTest(unittest.TestCase):
    def test_als_xz(self):
        # A = {0,1} with {1,2,3}, B = {2,3} with {1,2,4}
        # X=1 is restricted (all 1-cells see each other), Z=2 is common.
        units = [
            Unit("u", 0, [0, 1]), Unit("u", 1, [2, 3]),
            Unit("u", 2, [0, 2]), Unit("u", 3, [0, 3]),
            Unit("u", 4, [1, 2]), Unit("u", 5, [1, 3]),
            Unit("u", 6, [0, 4]), Unit("u", 7, [2, 4]),
        ]
        st = State(9, units)
        for cell in range(81):
            st.dom[cell] = 1 << 8  # only 9

        def set_dom(cell, *values):
            mask = 0
            for value in values:
                mask |= 1 << (value - 1)
            st.dom[cell] = mask

        set_dom(0, 1, 2)
        set_dom(1, 1, 3)
        set_dom(2, 1, 2)
        set_dom(3, 1, 4)
        set_dom(4, 2, 9)

        events = als(st)
        self.assertIsNotNone(events)
        self.assertFalse(st.has(4, 2))
        reason = events[0].reason
        self.assertEqual(reason.kind, "als")
        self.assertEqual(reason.data["x"], 1)
        self.assertEqual(reason.data["z"], 2)
        self.assertEqual(reason.data["target"], 4)


if __name__ == "__main__":
    unittest.main()
