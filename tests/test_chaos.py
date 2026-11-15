import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.pipeline import analyze

SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"


def chaos_data(rules: str) -> str:
    cells = [[{"value": int(SOLUTION[r * 9 + c])} if (r * 9 + c) % 3 == 0 else {}
              for c in range(9)] for r in range(9)]
    return json.dumps({
        "cells": cells,
        "regions": [],
        "metadata": {"rules": rules, "solution": SOLUTION},
    })


class ChaosTest(unittest.TestCase):
    def test_search_solution(self):
        analysis = analyze(chaos_data("Normal Chaos Construction rules apply."),
                           use_llm=False, chaos_time_limit=5)
        self.assertEqual(analysis.status, "solved-search")
        self.assertEqual(len(analysis.chaos_regions), 9)
        self.assertTrue(all(len(region) == 9 for region in analysis.chaos_regions))
        for r in range(9):
            row = analysis.result.values[r * 9:(r + 1) * 9]
            self.assertEqual(sorted(row), list(range(1, 10)))
        self.assertIn("通过", analysis.solution_check)

    def test_exotic_regions_unsupported(self):
        rules = "Normal Chaos Construction rules apply. Trisection circles: ..."
        analysis = analyze(chaos_data(rules), use_llm=False, chaos_time_limit=2)
        self.assertEqual(analysis.status, "unsupported")


if __name__ == "__main__":
    unittest.main()
