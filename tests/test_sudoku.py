import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.pipeline import analyze

EASY = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"


def puzzle_json(text: str) -> str:
    cells = [[{} for _ in range(9)] for _ in range(9)]
    for i, ch in enumerate(text):
        if ch.isdigit():
            cells[i // 9][i % 9] = {"value": int(ch)}
    regions = [[[r, c] for r in range(br, br + 3) for c in range(bc, bc + 3)]
               for br in (0, 3, 6) for bc in (0, 3, 6)]
    return json.dumps({"cells": cells, "regions": regions})


class PlainSudokuTest(unittest.TestCase):
    def test_easy(self):
        analysis = analyze(puzzle_json(EASY), use_llm=False)
        self.assertEqual(analysis.status, "solved")
        self.assertEqual(analysis.result.values[:9], [5, 3, 4, 6, 7, 8, 9, 1, 2])


if __name__ == "__main__":
    unittest.main()
