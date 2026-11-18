import unittest

from ysudoku.intersections import components


class Dummy:
    def __init__(self, cells):
        self._cells = cells

    def cells(self):
        return self._cells


class ComponentsTest(unittest.TestCase):
    def test_shared_cells_merge(self):
        a, b, c = Dummy([0, 1]), Dummy([1, 2]), Dummy([3, 4])
        groups = components([a, b, c])
        self.assertEqual(sorted(len(g) for g in groups), [1, 2])


if __name__ == "__main__":
    unittest.main()


class Constraint:
    def __init__(self, a, b):
        self.a, self.b = a, b

    def cells(self):
        return [self.a, self.b]

    def check(self, values):
        if values[self.a] == 0 or values[self.b] == 0:
            return True
        return values[self.a] != values[self.b]

    def describe(self):
        return "!="


class SupportTest(unittest.TestCase):
    def test_no_support_for_equal_values(self):
        from ysudoku.intersections import _has_support
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = st.dom[1] = 0b10  # both only value 2
        self.assertFalse(_has_support(st, [Constraint(0, 1)], 0, 2))
        self.assertTrue(_has_support(st, [Constraint(0, 1)], 0, 1))
