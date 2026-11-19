import unittest

from ysudoku.constraints_ir import AllDifferent, Difference, Sum, TupleRelation
from ysudoku.constraints import IRSupport
from ysudoku.narrate import build_step
from ysudoku.state import State, Unit
from ysudoku import support_engine
from ysudoku.support_engine import unsupported


class IRTest(unittest.TestCase):
    def test_sum_supports_are_filtered(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        rels = [Sum([62, 70, 78], 19), AllDifferent([62, 70, 78])]
        st.dom[62] = 0b100  # 3
        found = unsupported(st, rels)
        bad = [v for c, v, _ in found if c in (70, 78)]
        self.assertEqual(sorted(set(bad)), [1, 2, 3, 4, 5, 6, 8])
        self.assertTrue(found.complete)

    def test_difference(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = st.dom[1] = 0b11
        found = unsupported(st, [Difference(0, 1, 5, 9)])
        self.assertTrue(found)
        self.assertTrue(found.complete)

    def test_same_scope_relations_keep_distinct_parameters(self):
        st = State(9, [])
        relations = [Sum([0, 1], 3), Sum([0, 1], 4)]
        self.assertNotEqual(relations[0].signature(), relations[1].signature())
        found = unsupported(st, relations)
        self.assertTrue(found.complete)
        self.assertEqual(len(found), 18)

    def test_eight_cell_all_different_finishes_without_enumerating_all_permutations(self):
        st = State(9, [])
        found = unsupported(st, [AllDifferent(range(8))])
        self.assertTrue(found.complete)
        self.assertEqual(found.unresolved, [])
        self.assertFalse(found)

    def test_too_large_component_is_reported_as_unknown(self):
        st = State(9, [])
        found = unsupported(st, [AllDifferent(range(9))])
        self.assertFalse(found.complete)
        self.assertTrue(any("local cell limit" in reason
                            for _cell, _value, reason in found.unresolved))

    def test_partial_relations_detect_impossibility(self):
        all_different = AllDifferent([0, 1, 2])
        self.assertFalse(all_different.check([4, 4, 0]))
        self.assertFalse(Sum([0, 1], 3).check([8, 8]))
        self.assertFalse(TupleRelation([0, 1], [(1, 2)]).check([3, 0]))

    def test_relation_validates_scope_and_tuples(self):
        with self.assertRaises(ValueError):
            AllDifferent([0, 0])
        with self.assertRaises(ValueError):
            TupleRelation([0, 1], [(1,)])

    def test_node_limit_is_reported_as_unknown(self):
        st = State(9, [])
        old_limit = support_engine.MAX_NODES
        try:
            support_engine.MAX_NODES = 1
            result = unsupported(st, [AllDifferent(range(8))], max_nodes=1)
        finally:
            support_engine.MAX_NODES = old_limit
        self.assertFalse(result.complete)
        self.assertTrue(result.unresolved)

    def test_out_of_board_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            unsupported(State(4, []), [AllDifferent([0, 16])])

    def test_fully_assigned_relation_contradiction_is_reported(self):
        st = State(9, [])
        st.vals[0], st.vals[1] = 1, 1
        st.dom[0], st.dom[1] = 1, 1
        result = unsupported(st, [AllDifferent([0, 1])])
        self.assertEqual(result.contradictions, ["AllDifferent(2 cells)"])
        self.assertTrue(result.complete)

    def test_ir_adapter_emits_explainable_solver_events(self):
        st = State(9, [])
        st.dom[0] = st.dom[1] = 0b111
        st.record = True
        constraint = IRSupport([Sum([0, 1], 4), AllDifferent([0, 1])])
        self.assertTrue(constraint.prune(st))
        self.assertEqual([(event.cell, event.value) for event in st.events],
                         [(0, 2), (1, 2)])
        step = build_step(0, st.events, 9)
        self.assertEqual(step.technique, "ir_support")
        self.assertIn("Sum(2 cells=4)", step.detail)

    def test_ir_spec_compiles_into_regular_solver_constraint(self):
        import json
        from pathlib import Path
        from ysudoku.model import parse_puzzle
        from ysudoku.rules import build_inventory, compile_spec

        root = Path(__file__).resolve().parents[1]
        puzzle = parse_puzzle(json.loads((root / "fixtures" / "double-take.json").read_text()))
        spec = {"rules": [{"kind": "ir", "relations": [
            {"kind": "sum", "cells": [0, 1], "total": 4},
            {"kind": "all_different", "cells": [0, 1]},
        ]}]}
        compiled = compile_spec(puzzle, build_inventory(puzzle), spec)
        self.assertEqual([constraint.kind for constraint in compiled.constraints],
                         ["ir_support"])
        self.assertEqual(compiled.resolved[0]["kind"], "ir")
