import unittest

from ysudoku.constraints import Quadruple


class DigitDemandTest(unittest.TestCase):
    def test_quadruple_exposes_multiset(self):
        con = Quadruple([0, 1, 2, 3], [1, 9, 2, 9])
        self.assertEqual(con.digit_demands(), {1: 1, 9: 2, 2: 1})

    def test_plain_constraint_has_no_demand(self):
        class Plain:
            def digit_demands(self):
                return None
        self.assertIsNone(Plain().digit_demands())


if __name__ == "__main__":
    unittest.main()
