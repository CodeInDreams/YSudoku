from pathlib import Path
import unittest

from ysudoku.chaos_regions import RegionFragments
from ysudoku.constraints import RegionCount
from ysudoku.pipeline import analyze
from ysudoku.region_refutation import refute_count
from ysudoku.state import State


class RegionRefutationTest(unittest.TestCase):
    def test_two_possible_region_counts_are_retained(self):
        board = RegionFragments(State(2, []))
        rule = RegionCount([0, 1], [1, 2])
        self.assertIsNone(refute_count(board, [rule]))
        self.assertEqual(rule.counts, [1, 2])
        self.assertEqual(board.snapshot()["colours"], [])

    def test_refutes_one_region_when_it_would_repeat_a_digit(self):
        state = State(3, [])
        state.place(0, 1)
        state.place(4, 1)
        rule = RegionCount([0, 4], [1, 2])
        board = RegionFragments(state)
        index, count, _ = refute_count(board, [rule])
        self.assertEqual((index, count), (0, 1))
        self.assertEqual(board.owner, list(range(9)))
        self.assertEqual(rule.counts, [1, 2])

    def test_tringle_reduces_only_proven_count_and_keeps_trial_colours_private(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures/tringle.json"
        analysis = analyze(str(fixture), use_llm=False, chaos_time_limit=0.01)
        steps = analysis.result.steps
        cells = [27, 28, 36, 37]
        proof, = [s for s in steps if s.technique == "constraint_simplify"
                  and s.visual["focus"] == cells]
        self.assertEqual(proof.visual["focus"], cells)
        self.assertEqual(proof.visual["colours"], steps[proof.index-1].visual["colours"])
        self.assertIn("R3C3", proof.detail)
        self.assertIn("达不到 9 格", proof.detail)
        self.assertIn("只剩 1 区", proof.detail)
        self.assertFalse(proof.events)
        self.assertTrue(any(g["cells"] == cells for g in steps[proof.index+1].visual["colours"]))
        original = next(c for c in analysis.rules.constraints
                        if c.kind == "region_count" and c.cells() == cells)
        self.assertEqual(original.counts, [1, 4])
        growth = next(s for s in steps[proof.index+2:] if s.title == "区域形状推理")
        self.assertTrue(any({1, 2, 3, 4, 5, 10} <= set(g["cells"])
                            for g in growth.visual["colours"]))

        frontier = next(s for s in steps if s.narration.get("region_anchor") == 9)
        self.assertEqual(frontier.narration["shape_count"], 6)
        self.assertEqual(frontier.narration["targets"], [18])
        self.assertEqual(frontier.visual["focus"], [9, 18])
        self.assertNotIn(9, {c for g in steps[frontier.index - 1].visual["colours"] for c in g["cells"]})
        self.assertTrue(any(g["cells"] == [9, 18] for g in frontier.visual["colours"]))
        self.assertIn("Every shape contains R3C1", frontier.to_dict(9, "en")["detail"])

        relations = next(s for s in steps if "shape_comparisons" in s.narration)
        self.assertGreater(sum(len(c["targets"]) for c in relations.narration["shape_comparisons"]), 1)
        self.assertIn("identical connected 9-cell shape", relations.to_dict(9, "en")["detail"])
