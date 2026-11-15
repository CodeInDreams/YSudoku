import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.state import State, Unit
from ysudoku.techniques import medusa


class MedusaTest(unittest.TestCase):
    def test_trap(self):
        # strong: cell 0 {1,2}, cell 3 {1,2}, unit [0,3] for 1 and 2
        # weak: cell 5 sees (0,2) and (3,2) through 3-host units
        units = [Unit("u", 0, [0, 3]), Unit("u", 1, [0, 5, 6]), Unit("u", 2, [3, 5, 7])]
        st = State(9, units)
        for cell in range(81):
            st.dom[cell] = 1 << 8  # only 9
        for cell in (0, 3):
            st.dom[cell] = (1 << 0) | (1 << 1)  # {1,2}
        st.dom[5] = (1 << 1) | (1 << 3)  # {2,4}
        for cell in (6, 7):
            st.dom[cell] = 1 << 1  # {2}
        events = medusa(st)
        self.assertIsNotNone(events)
        self.assertFalse(st.has(5, 2))
        self.assertEqual(events[0].reason.kind, "medusa")
        self.assertEqual(events[0].reason.data["mode"], "trap")


if __name__ == "__main__":
    unittest.main()
