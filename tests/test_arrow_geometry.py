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
