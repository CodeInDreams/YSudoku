import unittest

from ysudoku.chaos_regions import RegionFragments
from ysudoku.region_shapes import region_shapes, separated_shape_anchors, shape_deduction
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
        proof = shape_deduction(board, [])
        self.assertEqual(proof.cells, [0, 1, 2, 3])
        self.assertEqual(board.snapshot()["region_progress"]["complete"], 1)


    def test_nonadjacent_fragments_can_be_proven_distinct_in_one_step(self):
        board = RegionFragments(State(4, []))
        for root in (0, 5, 10):
            board.mark(root)
        self.assertFalse(board.blocked(0, 5))
        self.assertFalse(board.blocked(5, 10))

        proof = separated_shape_anchors(board, {0: {0xF}, 5: {0xF0}, 10: {0xF00}})

        self.assertEqual(proof.cells, [0, 5, 10])
        self.assertEqual(len(proof.evidence["shape_comparisons"]), 2)
        self.assertTrue(board.blocked(0, 5))
        self.assertTrue(board.blocked(5, 10))
        self.assertIsNone(separated_shape_anchors(board, {0: {0xF}, 5: {0xF0}, 10: {0xF00}}))

    def test_shared_shape_keeps_two_fragments_eligible_to_merge(self):
        board = RegionFragments(State(4, []))
        board.mark(0)
        board.mark(5)
        shape = 0b110011  # the upper left 2x2 square
        self.assertIsNone(separated_shape_anchors(board, {0: {shape}, 5: {shape}}))
        self.assertFalse(board.blocked(0, 5))
