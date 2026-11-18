import unittest

from ysudoku import palette as p


class PaletteTest(unittest.TestCase):
    def test_no_grey(self):
        for group in (*p.PAIR_GROUPS, *p.TRIPLE_GROUPS):
            for colour in group:
                self.assertTrue(p.is_allowed(colour))
                self.assertNotIn(colour, p.FORBIDDEN)

    def test_pairs_are_distinct(self):
        for i in range(3):
            a, b = p.pair_colours(i)
            self.assertNotEqual(a, b)

    def test_triples_are_distinct(self):
        for i in range(2):
            a, b, c = p.triple_colours(i)
            self.assertEqual(len({a, b, c}), 3)

    def test_more_uses_second_page(self):
        self.assertEqual(p.colours_for(4), p.SECOND_PAGE[:4])


if __name__ == "__main__":
    unittest.main()
