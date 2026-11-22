import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.constraints import XSums
from ysudoku.model import parse_puzzle
from ysudoku.pipeline import analyze
from ysudoku.state import State, Unit, bits


class ClueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = analyze(str(ROOT / "fixtures" / "double-take.json"), use_llm=False)
        cls.puzzle = cls.analysis.puzzle

    def test_outside_clues_are_parsed(self):
        self.assertEqual(len(self.puzzle.clues), 12)
        self.assertEqual(sorted(c.value for c in self.puzzle.clues if c.value == 35), [35, 35])
        sides = {c.side for c in self.puzzle.clues}
        self.assertTrue(sides <= {"top", "bottom", "left", "right"})

    def test_six_by_six_clue_positions(self):
        from ysudoku.model import parse_puzzle
        import json
        data = json.loads((ROOT / "fixtures" / "sandwich-6x6.json").read_text())
        puzzle = parse_puzzle(data)
        self.assertEqual(puzzle.size, 6)
        self.assertEqual([(c.side, c.index, c.value) for c in puzzle.clues], [
            ("top", 1, 2), ("top", 2, 2), ("top", 3, 2), ("top", 4, 2),
            ("left", 1, 0), ("left", 2, 0), ("left", 3, 0), ("left", 4, 0),
        ])
        given_cells = {(c // 6, c % 6): v for c, v in puzzle.givens.items()}
        self.assertEqual(given_cells, {
            (1, 1): 4, (1, 4): 1, (2, 0): 4, (2, 5): 5, (4, 1): 6, (4, 4): 5,
        })

    def test_six_by_six_sandwich_solves(self):
        analysis = analyze(str(ROOT / "fixtures" / "sandwich-6x6.json"),
                           use_llm=False, allow_chains=True)
        self.assertEqual(analysis.status, "solved")
        self.assertIn("一致", analysis.solution_check)

    def test_decoder_keeps_empty_cells(self):
        from ysudoku.decode import decode_payload
        from ysudoku.model import parse_puzzle
        raw = (ROOT / "fixtures" / "raw-6x6.txt").read_text().strip()
        puzzle = parse_puzzle(decode_payload(raw))
        self.assertEqual(puzzle.size, 6)
        self.assertEqual((puzzle.givens.get(1 * 6 + 1), puzzle.givens.get(1 * 6 + 4)), (4, 1))

    def test_paired_clues_retain_both_rule_types(self):
        choices = self.analysis.rules.constraints
        self.assertEqual(len(choices), 6)
        self.assertTrue(all(rule.kind == "rule_choice" for rule in choices))
        self.assertTrue(all(rule.check(self.puzzle.solution) for rule in choices))
        self.assertTrue(any(step.technique == "rule_choice" for step in self.analysis.result.steps))
        self.assertEqual(len({eid for item in self.analysis.rules.resolved
                              if item["kind"] == "rule_choice" for eid in item["elements"]}), 12)

    def test_x_sums_check(self):
        rule = XSums(list(range(9)), 6, "left")
        self.assertTrue(rule.check([3, 1, 2, 4, 5, 6, 7, 8, 9]))
        self.assertFalse(rule.check([3, 1, 3, 4, 5, 6, 7, 8, 9]))
        self.assertTrue(rule.check([3, 1, 2, 0, 0, 0, 0, 0, 0]))  # incomplete

    def test_x_sums_uses_the_complement_in_a_full_unit(self):
        state = State(9, [Unit("row", 0, list(range(9)))])
        state.place(8, 9)
        XSums(list(range(9)), 35, "left").prune(state)
        self.assertEqual(list(bits(state.dom[0])), [7])
        self.assertEqual(list(bits(state.dom[7])), [1])

    def test_double_take_transfers_common_occupancy_between_pairs(self):
        deductions = [step for step in self.analysis.result.steps if step.technique == "rule_choice"]
        self.assertTrue(any(
            e.cell == 19 and e.value == 1
            and any(lock["digit"] == 1 and lock["hosts"] == [64, 73]
                    for lock in e.reason.data.get("occupancy", []))
            for step in deductions for e in step.events
        ))
        expected = {18: 7, 25: 1, 26: 9, 53: 1, 64: 1, 73: 2}
        self.assertEqual({cell: self.analysis.result.values[cell] for cell in expected}, expected)


if __name__ == "__main__":
    unittest.main()
