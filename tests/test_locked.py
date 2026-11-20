import unittest

from ysudoku.narrate import build_step
from ysudoku.state import State, Unit
from ysudoku.techniques import locked_candidates


class LockedCandidatesTest(unittest.TestCase):
    def test_batches_same_region_from_one_candidate_snapshot(self):
        cells = [6, 7, 8, 15, 16, 17, 24, 25, 26]
        state = State(9, [Unit("region", 2, cells)])
        for cell in cells:
            if cell not in (6, 15):
                state.elim(cell, 9)
            if cell not in (7, 16):
                state.elim(cell, 8)
        events = locked_candidates(state)
        expected = {(r * 9 + col, digit) for r in range(3, 9)
                    for col, digit in ((6, 9), (7, 8))}
        self.assertEqual({(ev.cell, ev.value) for ev in events}, expected)
        step = build_step(0, events, 9)
        self.assertIn("数字 8", step.detail)
        self.assertIn("数字 9", step.detail)
        self.assertEqual(set(step.visual["focus"]), {cell for cell, _ in expected})

    def test_does_not_use_a_new_lock_created_in_same_step(self):
        region = Unit("region", 0, [0, 1, 2, 9, 10, 11, 18, 19, 20])
        other = Unit("region", 1, [3, 4, 5, 12, 13, 14, 21, 22, 23])
        state = State(9, [region, other])
        for cell in region.cells:
            if cell not in (0, 1):
                state.elim(cell, 6)
        for cell in other.cells:
            if cell not in (3, 12, 13):
                state.elim(cell, 6)
        self.assertEqual({e.cell for e in locked_candidates(state)}, {3, 6, 7, 8})
        self.assertTrue(state.has(16, 6))
        self.assertIn(16, {e.cell for e in locked_candidates(state)})
