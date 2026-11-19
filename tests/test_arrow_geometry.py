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

    def test_sudokupad_route66_coordinate_mapping_and_solution_checks(self):
        from ysudoku.arrow_xsums import parse_arrows_geometry

        raw = {
            "underlays": [
                {"center": [-0.667, 5.5], "text": "10"},
                {"center": [3.5, -0.5], "text": "12"},
                {"center": [5.5, 9.333], "text": "19"},
            ],
            "arrows": [
                {"wayPoints": [[-0.255, 5.255], [-0.078, 5.078]]},
                {"wayPoints": [[-0.255, 5.745], [-0.078, 5.922]]},
                {"wayPoints": [[-0.292, 5.5], [-0.042, 5.5]]},
                {"wayPoints": [[3.255, -0.255], [3.078, -0.078]]},
                {"wayPoints": [[3.745, -0.255], [3.922, -0.078]]},
                {"wayPoints": [[3.5, -0.292], [3.5, -0.042]]},
                {"wayPoints": [[5.5, 9.297], [5.5, 9.037]]},
                {"wayPoints": [[5.745, 9.255], [5.922, 9.078]]},
                {"wayPoints": [[5.255, 9.255], [5.078, 9.078]]},
            ],
        }
        solution = "157942386629138457384756192412573869578691234936824715791485623843269571265317948"
        items = parse_arrows_geometry(raw, solution)
        self.assertEqual(len(items), 9)
        self.assertEqual(items[0]["direction"], "down-left")
        self.assertEqual(items[0]["entry"], [1, 5])
        self.assertEqual(items[0]["cells"][:3], [[1, 5], [2, 4], [3, 3]])
        self.assertEqual([item["direction"] for item in items], [
            "down-left", "down-right", "down", "up-right", "down-right",
            "right", "left", "down-left", "up-left",
        ])
        self.assertEqual([item["entry"] for item in items], [
            [1, 5], [1, 7], [1, 6], [3, 1], [5, 1], [4, 1],
            [6, 9], [7, 9], [5, 9],
        ])
        self.assertEqual([item["clue"] for item in items], [10] * 3 + [12] * 3 + [19] * 3)
        self.assertTrue(all(item["matches_solution"] for item in items))
        self.assertEqual([item["xsum"] for item in items], [10] * 3 + [12] * 3 + [19] * 3)


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
