import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ysudoku.pipeline import analyze
from ysudoku.shaded_inversions import (
    DARK, LIGHT, Shading, clue_cells, line_support, minimum_shaded,
)
from ysudoku.state import Contradiction


class ShadedInversionTest(unittest.TestCase):
    def test_inversions_count_only_shaded_pairs_and_follow_the_clue_side(self):
        light = (0, 4, 0, 0)
        dark = (8, 0, 2, 1)
        self.assertEqual(line_support(light, dark, 3), (light, dark))
        self.assertEqual(line_support(light, dark, 6), ((), ()))
        self.assertEqual(line_support(light[::-1], dark[::-1], 0), (light[::-1], dark[::-1]))
        self.assertEqual(clue_cells(4, SimpleNamespace(side="right", index=0)), (3, 2, 1, 0))
        self.assertEqual(clue_cells(4, SimpleNamespace(side="bottom", index=1)), (13, 9, 5, 1))
        self.assertEqual(minimum_shaded(26), 8)
        self.assertEqual(minimum_shaded(20), 7)
        self.assertEqual(minimum_shaded(0), 0)

    def test_keep_the_correlation_between_digits_and_colours(self):
        full = (15,) * 4
        light, dark = line_support(full, full, 6)
        self.assertEqual(light, (0,) * 4)
        self.assertEqual(dark, (8, 4, 2, 1))

    def test_abort_does_not_remove_candidates(self):
        line_support.cache_clear()
        full = (15,) * 4
        with patch("ysudoku.shaded_inversions.LINE_STATE_LIMIT", 1):
            self.assertEqual(line_support(full, full, 3), (full, full))
        line_support.cache_clear()

    def test_regions_exclude_monochrome_and_alternating_squares(self):
        shading = Shading(4)
        square = (0, 1, 4, 5)
        for cell in square[:3]:
            shading.restrict(cell, DARK)
        self.assertEqual(shading.square(square)[0], "square")
        self.assertEqual(shading.masks[5], LIGHT)

        shading = Shading(4)
        for cell, colour in zip(square, (DARK, LIGHT, LIGHT, DARK)):
            shading.restrict(cell, colour)
        with self.assertRaises(Contradiction):
            shading.square(square)

    def test_orthogonal_bridge_is_forced(self):
        shading = Shading(4)
        for cell in (0, 2):
            shading.restrict(cell, DARK)
        for cell in range(4, 16):
            shading.restrict(cell, LIGHT)
        self.assertEqual(shading.connected(DARK)[0], "bridge")
        self.assertEqual(shading.masks[1], DARK)

    def test_pipeline_dispatches_from_rule_text_without_llm(self):
        data = {
            "cells": [[{} for _ in range(4)] for _ in range(4)],
            "underlays": [{"center": [0.5, -0.5], "text": "6"}],
            "metadata": {"rules": (
                "Divide the grid into two orthogonally connected regions, and shade one of them. "
                "No 2x2 set of cells may be occupied entirely by one region. "
                "Count pairs of two shaded digits where the nearer digit is greater."
            )},
        }
        with patch("ysudoku.pipeline._llm_spec") as llm:
            analysis = analyze(json.dumps(data), use_llm=True, max_steps=10)
            llm.assert_not_called()
        self.assertEqual(analysis.spec["model"], "shaded_inversions")
        self.assertEqual(analysis.shades[:4], [DARK] * 4)
        self.assertEqual(analysis.result.values[:4], [4, 3, 2, 1])
        self.assertIn("at least 4", analysis.to_json(lang="en")["steps"][0]["detail"])
