import unittest

from ysudoku.model import parse_puzzle
from ysudoku.rules import Element, compile_spec
from ysudoku.solve import Solver


class NonConsecutiveTest(unittest.TestCase):
    def test_orienteering_centre_without_assumptions(self):
        puzzle = parse_puzzle({"cells": [[{} for _ in range(9)] for _ in range(9)]})
        puzzle.rules_text = "Non-consecutive: Orthogonally adjacent cells may not contain consecutive digits."
        elements = [Element("top", "cage", [4, 13], {"sum": 11}),
                    Element("bottom", "cage", [67, 76], {"sum": 9}),
                    Element("upper", "line", [22, 31]),
                    Element("lower", "line", [49, 58])]
        spec = {"rules": [{"kind": "cage", "elements": ["top", "bottom"]},
                          {"kind": "german_whisper", "elements": ["upper", "lower"]}]}
        rules = compile_spec(puzzle, elements, spec)
        pairs = [c for c in rules.constraints if getattr(c, "_kind", "") == "non_consecutive"]
        self.assertEqual(len(pairs), 144)
        self.assertNotIn((8, 9), {(c.a, c.b) for c in pairs})
        result = Solver(puzzle, rules).run()
        self.assertEqual(result.values[40], 5)
        self.assertTrue(any(step.technique == "hidden_single" and
                            any(e.cell == 40 and e.kind == "place" for e in step.events)
                            for step in result.steps))
        self.assertFalse(any(step.branch for step in result.steps))
