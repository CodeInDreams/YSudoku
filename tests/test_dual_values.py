import json
import unittest

from ysudoku.constraints import PairRule, Renban
from ysudoku.dual_values import (
    DualValues, Deduction, EFFECTIVE, HONEST, LIAR, MODE, WRITTEN, solve_dual,
)
from ysudoku.model import parse_puzzle
from ysudoku.pipeline import analyze
from ysudoku.state import bits


def empty_four():
    return {"cells": [[{} for _ in range(4)] for _ in range(4)]}


def fix(board, cell, layer, mask):
    allowed = list(board.dom[cell])
    allowed[layer] = mask
    board._apply((cell,), (allowed,), Deduction("assume", (cell,)))


class DualValuesTest(unittest.TestCase):
    def test_equal_effective_peers_force_one_liar(self):
        puzzle = parse_puzzle(empty_four())
        pair = PairRule(0, 1, "xv", lambda a, b: a + b == 4, "sum", sum=4)
        board = DualValues(puzzle, [pair])
        fix(board, 0, EFFECTIVE, 0b0010)
        board.next_deduction()

        self.assertEqual(board.dom[1][EFFECTIVE], 0b0010)
        self.assertEqual(board.dom[1][MODE], HONEST | LIAR)
        fix(board, 0, MODE, HONEST)
        board.next_deduction()
        self.assertEqual(board.dom[0][WRITTEN], 0b0010)
        self.assertEqual(board.dom[1][MODE], LIAR)
        self.assertEqual(list(bits(board.dom[1][WRITTEN])), [1, 3, 4])

    def test_unit_counts_liars_and_applies_sudoku_to_written_digits(self):
        board = DualValues(parse_puzzle(empty_four()), [])
        for cell, digit in enumerate((1, 2, 3)):
            fix(board, cell, MODE, HONEST)
            fix(board, cell, EFFECTIVE, 1 << (digit - 1))
        reason = board.next_deduction()

        self.assertEqual(reason.kind, "unit")
        self.assertEqual(board.dom[3][MODE], LIAR)
        self.assertEqual(board.dom[3][WRITTEN], 0b1000)
        self.assertEqual(list(bits(board.dom[3][EFFECTIVE])), [1, 2, 3])

    def test_joint_clues_combine_value_constraints(self):
        puzzle = parse_puzzle(empty_four())
        pair = PairRule(0, 1, "xv", lambda a, b: a + b == 5, "sum", sum=5)
        result, _, _ = solve_dual(
            puzzle, [pair, Renban([0, 1, 4])], max_steps=80, allow_chains=False,
        )
        self.assertEqual(result.status, "stuck")
        joint = next(step for step in result.steps if step.narration["dual_reason"]["kind"] == "joint")
        self.assertIn("Combine the clues", joint.to_dict(4, "en")["detail"])
        self.assertTrue(any(row["cell"] == 4 and row["effective"] == [1, 4] for row in joint.candidates))

    def test_only_supported_coloured_lines_are_applied_to_values(self):
        data = empty_four()
        data["metadata"] = {"rules": (
            "Normal sudoku rules apply.\n\n"
            "LIAR CELLS: Every row, column and box contains one liar cell, whose real value is different from its digit.\n"
            "• Every liar cell contains a different digit from 1-4.\n"
            "• Every liar cell has a different value from 1-4.\n\n"
            "RENBAN LINES: The VALUES on a pink line form a non-repeating set of consecutive digits."
        )}
        points = [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [0.5, 0.5]]
        data["lines"] = [{"color": colour, "wayPoints": points} for colour in ("#ffffff", "#e779f4ff")]

        result = analyze(json.dumps(data), use_llm=False)
        self.assertEqual(result.status, "stuck")
        self.assertEqual(result.rules.constraints[0].cells(), [0, 1, 5])
        self.assertEqual(len(result.rules.constraints), 1)
        self.assertEqual(result.spec["model"], "liar_values")

        data["metadata"]["rules"] += "\n\nKILLER CAGES: Digits sum to their cage totals."
        self.assertEqual(analyze(json.dumps(data), use_llm=False).status, "unsupported")

    def test_completion_checks_both_domains_and_the_liar_quota(self):
        data = empty_four()
        written = (1, 2, 3, 4, 3, 4, 1, 2, 2, 1, 4, 3, 4, 3, 2, 1)
        for cell, digit in enumerate(written):
            data["cells"][cell // 4][cell % 4]["value"] = digit
        board = DualValues(parse_puzzle(data), [])
        changes = {0: 2, 7: 4, 10: 3, 13: 1}
        for cell, digit in enumerate(written):
            fix(board, cell, EFFECTIVE, 1 << (changes.get(cell, digit) - 1))
        self.assertTrue(board.verified())
        # Changing the effective value of a second cell in a row fails the quota.
        board.dom[1] = (0b0010, 0b0100, LIAR, 0b0010, 0b0100)
        self.assertFalse(board.verified())
