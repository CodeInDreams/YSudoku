import unittest

from ysudoku.arrow_geometry import validate_all


class ArrowGeometryTest(unittest.TestCase):
    def test_valid_diagonal(self):
        items = [{
            "direction": "down-left", "entry": [1, 5],
            "cells": [[1, 5], [2, 4], [3, 3], [4, 2], [5, 1]], "clue": 10,
        }]
        self.assertEqual(validate_all(items, 9)[0]["cells"][0], 4)

    def test_rejects_jump(self):
        items = [{
            "direction": "down-left", "entry": [1, 5],
            "cells": [[1, 5], [2, 3]], "clue": 10,
        }]
        with self.assertRaises(ValueError):
            validate_all(items, 9)


class ApplyTest(unittest.TestCase):
    def test_applies_valid_arrows(self):
        from types import SimpleNamespace
        from ysudoku.pipeline import _apply_arrow_geometry

        puzzle = SimpleNamespace(size=9, clues=[None])
        spec = {"rules": [], "arrows": [{
            "direction": "down-left", "entry": [1, 5],
            "cells": [[1, 5], [2, 4], [3, 3], [4, 2], [5, 1]], "clue": 10,
        }]}
        warnings = []
        _apply_arrow_geometry(puzzle, spec, warnings)
        self.assertEqual(spec["rules"][0]["kind"], "x_sums")
        self.assertEqual(warnings, [])
