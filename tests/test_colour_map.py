import unittest

from ysudoku import palette as p
from ysudoku.colour_map import ColourError, ColourMap


class ColourMapTest(unittest.TestCase):
    def test_same_and_different(self):
        cm = ColourMap()
        cm.add(0, p.BLUE)
        cm.add(1, p.BLUE)
        cm.add(2, p.GREEN)
        self.assertTrue(cm.same_class(0, 1))
        self.assertTrue(cm.different_class(0, 2))

    def test_forbidden(self):
        cm = ColourMap()
        with self.assertRaises(ColourError):
            cm.add(0, 0)

    def test_max_four(self):
        cm = ColourMap()
        for colour in (3, 4, 5, 6):
            cm.add(0, colour)
        with self.assertRaises(ColourError):
            cm.add(0, 7)

    def test_class_digits(self):
        cm = ColourMap()
        cm.add(0, p.BLUE)
        cm.add(1, p.BLUE)
        cm.set_class_digits(p.BLUE, {1, 4})
        self.assertEqual(cm.allowed_digits(0), {1, 4})
        self.assertEqual(cm.allowed_digits(1), {1, 4})

    def test_group(self):
        cm = ColourMap()
        cm.set_group([0, 1], p.pair_colours(0))
        self.assertTrue(cm.different_class(0, 1))


if __name__ == "__main__":
    unittest.main()
