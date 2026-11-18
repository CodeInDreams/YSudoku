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


class DiagonalXSumsTest(unittest.TestCase):
    def test_diagonal_allows_repeats(self):
        st = State(9, units())
        cells = [r * 9 + r for r in range(9)]
        st.dom[cells[0]] = 0b10000  # N=5
        st.dom[cells[1]] = 0b1
        st.dom[cells[2]] = 0b1
        st.dom[cells[3]] = 0b1
        st.dom[cells[4]] = 0b1
        # 5 + 1+1+1+1 = 9; repeats are legal on a diagonal.
        XSums(cells, 9, "top").prune(st)
        self.assertTrue(st.dom[cells[0]] >> 4 & 1)


class DiagonalBoxGroupsTest(unittest.TestCase):
    def test_shared_box_members_are_distinct(self):
        from ysudoku.constraints import XSums
        from ysudoku.state import State, Unit
        us = units()
        # two cells in the same box: (1,1) and (2,2) of box 0
        us.append(Unit("region", 0, [0, 1, 2, 9, 10, 11, 18, 19, 20]))
        st = State(9, us)
        cells = [10, 19]  # both in region 0
        st.dom[cells[0]] = 0b10  # N=2
        st.dom[cells[1]] = 0b10  # only 2, duplicate -> impossible
        with self.assertRaises(Exception):
            XSums(cells, 4, "top").prune(st)
