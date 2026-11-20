import unittest

from ysudoku.chaos_regions import RegionFragments
from ysudoku.region_shapes import region_shapes, shape_deduction
from ysudoku.state import State


class RegionShapesTest(unittest.TestCase):
    def test_common_cell_respects_region_digit_matching_and_search_budget(self):
        state = State(4, [])
        board = RegionFragments(state)
        board.merge(0, 1)
        board.merge(0, 2)
        # The three owned cells use 1, 2 and 3. Only the end of their
        # row can supply digit 4 among the boundary cells.
        for c in (0, 1, 2, 4, 5, 6):
            state.dom[c] = 0b0111
        self.assertIsNone(region_shapes(board, 0, [], limit=0))
        self.assertEqual(region_shapes(board, 0, []), {0b1111})
        cells, _ = shape_deduction(board, [])
        self.assertEqual(cells, [0, 1, 2, 3])
        self.assertEqual(board.snapshot()["region_progress"]["complete"], 1)
