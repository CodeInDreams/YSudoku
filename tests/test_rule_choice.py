import unittest
from unittest.mock import patch

from ysudoku.constraints import XSums
from ysudoku.full_rank import FullRank
from ysudoku.model import parse_puzzle
from ysudoku.rule_choice import RuleAlternative, RuleChoice
from ysudoku.rules import CompiledRules, compile_spec
from ysudoku.solve import Solver
from ysudoku.state import bits


def _option(cell, *digits):
    return {"kind": "ir", "relations": [
        {"kind": "tuple", "cells": [cell], "allowed": [[digit] for digit in digits]},
    ]}


class RuleChoiceTest(unittest.TestCase):
    def _state(self, regions, quotas=None):
        puzzle = parse_puzzle({"cells": [[{} for _ in range(4)] for _ in range(4)]})
        rules = compile_spec(puzzle, [], {"rules": [
            {"kind": "rule_choice", "regions": regions, "quotas": quotas},
        ]})
        self.assertEqual(rules.errors, [])
        return Solver(puzzle, rules).state, rules.constraints[0]

    def test_single_region_keeps_union_then_rejects_impossible_rule(self):
        state, choice = self._state([{
            "options": {"A": _option(0, 1, 2), "B": _option(0, 3)},
        }])
        choice.prune(state)
        self.assertEqual(list(bits(state.dom[0])), [1, 2, 3])
        state.elim(0, 3)
        state.begin()
        self.assertFalse(choice.prune(state))
        self.assertTrue(choice.check([2] + [0] * 15))
        self.assertFalse(choice.check([4] + [0] * 15))

    def test_three_regions_use_matching_support(self):
        state, choice = self._state([
            {"options": {"A": _option(0, 1), "B": _option(0, 2)}},
            {"options": {"A": _option(5, 1), "B": _option(5, 2)}},
            {"options": {"A": _option(10, 1), "B": _option(10, 2), "C": _option(10, 3)}},
        ], {"A": 1, "B": 1, "C": 1})
        state.begin()
        self.assertTrue(choice.prune(state))
        self.assertEqual(list(bits(state.dom[0])), [1, 2])
        self.assertEqual(list(bits(state.dom[5])), [1, 2])
        self.assertEqual(list(bits(state.dom[10])), [3])
        self.assertTrue(any(e.reason.data["regions"][2]["unmatched"] == ["A", "B"]
                            for e in state.end()))

    def test_matching_still_prunes_when_joint_propagation_exceeds_budget(self):
        state, choice = self._state([
            {"options": {"A": _option(0, 1), "B": _option(0, 2)}},
            {"options": {"A": _option(5, 1), "B": _option(5, 2)}},
            {"options": {"A": _option(10, 1), "B": _option(10, 2), "C": _option(10, 3)}},
        ], {"A": 1, "B": 1, "C": 1})
        with patch("ysudoku.rule_choice.MAX_JOINT_ASSIGNMENTS", 1):
            choice.prune(state)
        self.assertEqual(list(bits(state.dom[10])), [3])

    def test_joint_assignment_preserves_both_subrule_premises(self):
        puzzle = parse_puzzle({"cells": [[{} for _ in range(4)] for _ in range(4)]})
        state = Solver(puzzle, CompiledRules([])).state
        alternative = RuleAlternative([FullRank([0, 1, 2, 3], 1, "left", 4),
                                       XSums([8, 9, 10, 11], 3, "left")])
        choice = RuleChoice([("region", {"combined": alternative})])
        state.begin()
        branches, rejected = choice._joint(state, [["combined"]])
        self.assertEqual(rejected, [])
        _, branch = branches[0]
        self.assertEqual({p["kind"] for p in branch["premises"]}, {"rank_head", "complement"})
