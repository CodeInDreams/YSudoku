import unittest


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
        from ysudoku.intersections import unsupported_candidates
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = st.dom[1] = 0b10  # both only value 2
        found = unsupported_candidates(st, [Constraint(0, 1)])
        self.assertIn((0, 2), [(c, v) for c, v, _ in found])
