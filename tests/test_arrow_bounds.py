import unittest

from ysudoku.constraints import Arrow
from ysudoku.state import State, Unit


def units(n=9):
    out = []
    for r in range(n):
        out.append(Unit("row", r, [r * n + c for c in range(n)]))
    for c in range(n):
        out.append(Unit("col", c, [r * n + c for r in range(n)]))
    for br in range(3):
        for bc in range(3):
            out.append(Unit("region", br * 3 + bc,
                            [(br * 3 + r) * n + bc * 3 + c
                             for r in range(3) for c in range(3)]))
    return out


class ArrowBoundsTest(unittest.TestCase):
    def test_arm_in_one_row_has_min_sum_six(self):
        st = State(9, units())
        # R5C2 is the circle; R5C3/R5C4/R5C5 form the arm in row 5.
        arrow = Arrow(37, [38, 39, 40])
        arrow.prune(st)
        allowed = [v for v in range(1, 10) if st.dom[37] >> (v - 1) & 1]
        self.assertEqual(allowed, [6, 7, 8, 9])

    def test_arm_values_support_circle(self):
        st = State(9, units())
        arrow = Arrow(37, [38, 39, 40])
        arrow.prune(st)
        for cell in (38, 39, 40):
            self.assertTrue(st.dom[cell])


if __name__ == "__main__":
    unittest.main()
