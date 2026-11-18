import unittest

from ysudoku.constraints import XSums
from ysudoku.state import State, Unit


def units(n=9):
    out = []
    for r in range(n):
        out.append(Unit("row", r, [r * n + c for c in range(n)]))
    for c in range(n):
        out.append(Unit("col", c, [r * n + c for r in range(n)]))
    return out


class XSumsTest(unittest.TestCase):
    def test_first_digit_range_with_distinct_digits(self):
        st = State(9, units())
        cells = [r * 9 for r in range(9)]  # column 0
        XSums(cells, 10, "top").prune(st)
        allowed = [v for v in range(1, 10) if st.dom[cells[0]] >> (v - 1) & 1]
        self.assertEqual(allowed, [2, 3, 4])

    def test_one_impossible(self):
        st = State(9, units())
        cells = [r * 9 for r in range(9)]
        XSums(cells, 10, "top").prune(st)
        self.assertFalse(st.dom[cells[0]] >> 0 & 1)


if __name__ == "__main__":
    unittest.main()
