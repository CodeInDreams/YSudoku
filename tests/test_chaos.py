import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.pipeline import analyze
from ysudoku.chaos import check_chaos_solution, solve_chaos
from ysudoku.chaos_regions import region_steps
from ysudoku.constraints import Constraint
from ysudoku.model import parse_puzzle
from ysudoku.rules import CompiledRules
from ysudoku.solve import Solver

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

    def test_region_count_provider_retains_its_digit_check(self):
        class MixedRule(Constraint):
            def cells(self):
                return [0, 1]

            def region_counts(self):
                return [1]

            def check(self, values):
                return values[0] in (0, 2)

        puzzle = parse_puzzle({"cells": [[{}, {}], [{}, {}]],
                               "metadata": {"rules": "Chaos Construction"}})
        rule = MixedRule()
        regions = [[0, 1], [2, 3]]
        self.assertTrue(check_chaos_solution(puzzle, [rule], [1, 2, 2, 1], regions))
        self.assertTrue(check_chaos_solution(puzzle, [rule], [2, 1, 1, 2], [[0, 2], [1, 3]]))
        self.assertEqual(check_chaos_solution(puzzle, [rule], [2, 1, 1, 2], regions), [])

        rules = CompiledRules([rule])
        fragments = region_steps(Solver(puzzle, rules), rules, [])
        self.assertEqual(fragments.owner[0], fragments.owner[1])
        result = solve_chaos(puzzle, [rule], fragments=fragments)
        self.assertEqual(result.status, "solved")
        self.assertEqual(result.values, [2, 1, 1, 2])


if __name__ == "__main__":
    unittest.main()
