import unittest
from itertools import product
from time import monotonic

from ysudoku.shade_layout import ShadeLayout, ShadeTable, indexes, outer_cells, perimeter_patterns
from ysudoku.shaded_inversions import DARK, LIGHT, Shading, _line_analysis


class ShadeLayoutTest(unittest.TestCase):
    def test_project_complete_colour_patterns_from_a_line(self):
        # With fixed descending digits, each dark pair is an inversion. To get
        # exactly one inversion there must be exactly two shaded positions.
        fixed = (8, 4, 2, 1)
        _, _, patterns = _line_analysis(fixed, fixed, 1)
        self.assertEqual(set(indexes(patterns)), {3, 5, 6, 9, 10, 12})

    def test_budget_expiry_is_not_a_contradiction(self):
        shape = Shading(3)
        layout = ShadeLayout(3, shape.squares, shape.neighbours, [])
        self.assertEqual(layout.search(0, 0, monotonic() - 1), (None, 0))
        self.assertIsNone(layout.search(0, 0, monotonic() + 2, limit=0)[0])

    def test_perimeter_patterns_allow_at_most_two_transitions(self):
        run = tuple(perimeter_patterns(8))
        self.assertEqual(len(set(run)), 8 * 7 + 2)
        self.assertNotIn(0b01010101, run)
        self.assertIn(0b11000001, run)
        self.assertEqual(len(set(outer_cells(4))), 12)

    def test_layout_support_matches_exhaustive_small_grid(self):
        shape = Shading(3)
        coords = (3, 4, 5)
        table = ShadeTable.build(coords, (0b011, 0b110))
        layout = ShadeLayout(3, shape.squares, shape.neighbours, [table], [((1, 4, 7), 1)])
        supported_dark, supported_light = set(), set()
        for candidate in product((LIGHT, DARK), repeat=9):
            shape.masks[:] = candidate
            if not shape.valid() or sum(candidate[c] == DARK for c in (1, 4, 7)) < 1:
                continue
            if sum((candidate[c] == DARK) << i for i, c in enumerate(coords)) not in (3, 6):
                continue
            supported_dark.update(c for c, x in enumerate(candidate) if x == DARK)
            supported_light.update(c for c, x in enumerate(candidate) if x == LIGHT)
        self.assertTrue(supported_dark and supported_light)
        for cell in range(9):
            bit = 1 << cell
            self.assertEqual(bool(layout.search(bit, 0, monotonic() + 2)[0]), cell in supported_dark)
            self.assertEqual(bool(layout.search(0, bit, monotonic() + 2)[0]), cell in supported_light)
