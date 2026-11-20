import unittest

from ysudoku.constraints import ProductLine
from ysudoku.model import _svg_points, parse_puzzle
from ysudoku.state import State, Unit


class ProductLineTest(unittest.TestCase):
    def test_svg_points(self):
        pts = _svg_points("M32 32L160 32", 9)
        self.assertEqual(pts, [[0.5, 0.5], [0.5, 2.5]])

    def test_parse_svg_lines(self):
        cells = [[{} for _ in range(9)] for _ in range(9)]
        data = {"cells": cells, "regions": [], "lines": [
            {"color": "#0d00ffff", "duration": "M32 32L160 32"}]}
        puzzle = parse_puzzle(data)
        self.assertEqual(len(puzzle.lines), 1)
        self.assertEqual(puzzle.lines[0].cells, [0, 1, 2])

    def test_product_prune(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b111
        st.dom[1] = 0b1111
        st.dom[2] = 0b111111
        ProductLine([0, 1, 2], 48).prune(st)
        for c in (0, 1, 2):
            self.assertFalse(st.dom[c] & (1 << 7))  # no 8: 48 has no factor 8 in 3 digits
