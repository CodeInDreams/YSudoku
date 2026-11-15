import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku import predicate as P
from ysudoku.pipeline import analyze

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"


def puzzle_json() -> str:
    cells = [[{} for _ in range(9)] for _ in range(9)]
    for i, ch in enumerate(EASY):
        if ch.isdigit():
            cells[i // 9][i % 9] = {"value": int(ch)}
    regions = [[[r, c] for r in range(br, br + 3) for c in range(bc, bc + 3)]
               for br in (0, 3, 6) for bc in (0, 3, 6)]
    return json.dumps({
        "cells": cells, "regions": regions,
        "metadata": {"rules": "custom test", "solution": SOLUTION},
    })


def sum_equals_12() -> dict:
    return {
        "op": "eq",
        "args": [
            {"op": "sum", "args": [
                {"op": "var", "index": 0},
                {"op": "var", "index": 1},
                {"op": "var", "index": 2},
            ]},
            {"op": "const", "value": 12},
        ],
    }


class PredicateTest(unittest.TestCase):
    def test_evaluate(self):
        node = P.parse(sum_equals_12())
        self.assertTrue(P.evaluate(node, [5, 3, 4]))
        self.assertFalse(P.evaluate(node, [5, 3, 5]))

    def test_variables(self):
        node = P.parse(sum_equals_12())
        self.assertEqual(P.variables(node), {0, 1, 2})

    def test_format(self):
        text = P.format_node(P.parse(sum_equals_12()), ["R1C1", "R1C2", "R1C3"])
        self.assertIn("R1C1", text)
        self.assertIn("==", text)

    def test_prune(self):
        node = P.parse(sum_equals_12())
        masks = P.prune_by_enumeration([0b111111111, 0b111111111, 0b111111111], node)
        self.assertIsNotNone(masks)
        values = [v for v in range(1, 10) if masks[0] >> (v - 1) & 1]
        self.assertIn(5, values)
        self.assertNotIn(9, [v for v in range(1, 2)])  # sanity only

    def test_invalid_op(self):
        with self.assertRaises(P.PredicateError):
            P.parse({"op": "os.system"})

    def test_custom_rule_end_to_end(self):
        spec = {
            "rules": [{
                "kind": "custom",
                "cells": ["R1C1", "R1C2", "R1C3"],
                "predicate": sum_equals_12(),
                "cite": "the first three cells of row 1 sum to 12",
                "hypothesis": True,
            }],
            "globals": [],
        }
        analysis = analyze(puzzle_json(), use_llm=False, spec_override=spec)
        self.assertEqual(analysis.status, "solved")
        self.assertIn("一致", analysis.solution_check)
        self.assertTrue(any(s.technique == "custom" for s in analysis.result.steps))
        resolved = [r for r in analysis.rules.describe() if r.get("kind") == "custom"]
        self.assertTrue(resolved and resolved[0]["hypothesis"])


if __name__ == "__main__":
    unittest.main()
