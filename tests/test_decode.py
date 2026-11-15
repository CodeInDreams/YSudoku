import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.decode import decode_payload
from ysudoku.model import parse_puzzle


class DecodeTest(unittest.TestCase):
    def test_scl_payload(self):
        raw = (ROOT / "fixtures" / "raw-scl.txt").read_text().strip()
        data = decode_payload(raw)
        puzzle = parse_puzzle(data)
        self.assertEqual(puzzle.size, 9)
        self.assertEqual(len(puzzle.givens), 0)
        self.assertEqual(len(puzzle.circles), 8)
        self.assertEqual(sum(len(c.texts) for c in puzzle.circles), 32)
        self.assertIsNotNone(puzzle.solution)
        self.assertTrue(all(1 <= v <= 9 for v in puzzle.solution))


if __name__ == "__main__":
    unittest.main()
