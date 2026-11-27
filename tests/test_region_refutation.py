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
        growth = next(s for s in steps[proof.index+2:] if s.title == "区域边界反证")
        self.assertLessEqual(len(growth.detail.splitlines()), 7)
        self.assertIn("达不到 9 格", growth.detail)
        self.assertFalse(growth.events)
        english = analysis.to_json(lang="en")["steps"][growth.index]
        self.assertEqual(english["title"], "Region border refutation")
        self.assertIn("can reach at most", english["detail"])
        self.assertIn("needs 9", english["detail"])
        self.assertTrue(any({1, 2, 3, 4, 5, 10} <= set(g["cells"])
                            for s in steps[growth.index:] for g in s.visual["colours"]))
        self.assertFalse(any("shape_comparisons" in s.narration
                             and "shared_region_cases" not in s.narration for s in steps))

        self.assertTrue(any("圈要求 9" in s.detail and "R3C2 排除 9" in s.detail
                            for s in steps))
