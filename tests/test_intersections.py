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
