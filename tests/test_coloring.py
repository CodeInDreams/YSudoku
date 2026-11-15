import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.state import State, Unit
from ysudoku.techniques import coloring


def blank_state(units):
    st = State(9, units)
    for cell in range(81):
        st.dom[cell] &= ~(1 << 4)  # remove digit 5 everywhere
    return st


class ColoringTest(unittest.TestCase):
    def test_wrap(self):
        # a 3-cycle of strong links: 0-1, 1-2, 2-0 -> colour 0 appears twice
        units = [
            Unit("u", 0, [0, 1, 3, 4]),
            Unit("u", 1, [1, 2, 3, 4]),
            Unit("u", 2, [0, 2, 3, 4]),
        ]
        st = blank_state(units)
        for cell in (0, 1, 2):
            st.dom[cell] |= 1 << 4
        events = coloring(st)
        self.assertIsNotNone(events)
        remaining = [c for c in (0, 1, 2) if st.has(c, 5)]
        self.assertEqual(len(remaining), 1, "one colour class must survive")
        self.assertEqual(events[0].reason.kind, "coloring")
        self.assertEqual(events[0].reason.data["mode"], "wrap")

    def test_trap(self):
        # 0-1 is a strong link; cell 5 sees both ends but is not part of the chain
        units = [
            Unit("u", 0, [0, 1, 3, 4]),
            Unit("u", 1, [0, 5, 6]),
            Unit("u", 2, [1, 5, 7]),
        ]
        st = blank_state(units)
        for cell in (0, 1, 5, 6, 7):
            st.dom[cell] |= 1 << 4
        events = coloring(st)
        self.assertIsNotNone(events)
        self.assertFalse(st.has(5, 5))
        self.assertEqual(events[0].reason.data["mode"], "trap")


if __name__ == "__main__":
    unittest.main()
