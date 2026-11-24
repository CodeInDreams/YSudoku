import unittest
from copy import copy
from itertools import combinations

from ysudoku.chaos_regions import RegionFragments
from ysudoku.constraints import Constraint, RegionCount
from ysudoku.model import parse_puzzle
from ysudoku.refutation_path import _region_endpoint, _shorten_digits
from ysudoku.rules import CompiledRules
from ysudoku.search import refute_candidate_with_proof
from ysudoku.solve import Solver
from ysudoku.state import Reason, State


class Gate(Constraint):
    kind = "test_gate"

    def __init__(self, source, digit, target, excluded):
        self.source, self.digit = source, digit
        self.target, self.excluded = target, excluded

    def cells(self):
        return [self.source, self.target]

    def prune(self, state):
        return (state.vals[self.source] == self.digit
                and state.elim(self.target, self.excluded, Reason(self.kind)))

    def check(self, values):
        return values[self.source] != self.digit or values[self.target] != self.excluded


class RefutationPathTest(unittest.TestCase):
    def test_replay_replaces_a_redundant_proof_and_keeps_the_required_one(self):
        puzzle = parse_puzzle({"cells": [[{} for _ in range(4)] for _ in range(4)]})
        rules = CompiledRules([Gate(0, 1, 2, 3), Gate(1, 1, 2, 3), Gate(1, 2, 0, 1)])
        solver = Solver(puzzle, rules)
        solver.state = State(4, [])
        solver.state.constraints = solver.constraints
        solver.state.dom[:2] = [0b11, 0b11]
        solver.state.place(2, 3)
        checkpoint = solver.fork_for_replay()
        costs = {}
        for cell in (0, 1):
            refuted, proof, cause = refute_candidate_with_proof(solver.state, rules.constraints, cell, 1)
            self.assertTrue(refuted)
            start = len(solver.steps)
            solver.apply_refutation(cell, 1, proof, cause)
            costs[cell, 1] = len(solver.steps) - start
            self.assertEqual(solver.run(candidate_maps=False).status, "stuck")

        shortened = _shorten_digits(checkpoint, solver, costs)
        self.assertLess(len(shortened.steps), len(solver.steps))
        self.assertEqual(shortened.state.vals, solver.state.vals)
        self.assertEqual(shortened.state.dom, solver.state.dom)
        assumptions = [step for step in shortened.steps if step.narration.get("phase") == "start"]
        self.assertEqual([step.narration["cell"] for step in assumptions], [1])
        self.assertEqual(assumptions[0].pre_dom[0], 0b11)
        self.assertEqual([step.index for step in shortened.steps], list(range(len(shortened.steps))))

    def test_region_endpoint_retains_live_count_options(self):
        fragments = RegionFragments(State(4, []))
        clue = RegionCount([0, 1, 4, 5], [1, 4])
        fragments.all_count_clues = [clue]
        narrowed = copy(clue)
        narrowed.counts = [4]
        broader_endpoint = _region_endpoint(fragments)
        fragments.all_count_clues = [narrowed]
        self.assertNotEqual(_region_endpoint(fragments), broader_endpoint)

        for a, b in combinations(clue.cells(), 2):
            fragments.apart(a, b)
        fixed_endpoint = _region_endpoint(fragments)
        fragments.all_count_clues = [clue]
        self.assertEqual(_region_endpoint(fragments), fixed_endpoint)
