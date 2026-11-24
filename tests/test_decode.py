import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.decode import decode_payload
from ysudoku.model import parse_puzzle
from ysudoku.rules import build_inventory, heuristic_spec
from ysudoku.sudokupad import load


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


    def test_logic_masters_link_loads_fpuzzles_and_maps_red_whisper_lines(self):
        grid = [[{} for _ in range(6)] for _ in range(6)]
        grid[0][0] = {"value": 1, "given": True}
        grid[0][1] = {"value": 5, "given": False}
        exported = {
            "size": 6, "title": "Local f-puzzles sample", "grid": grid,
            "ruleset": (
                "Dutch Whispers: digits on red lines differ by at least 4.\n"
                "A black dot between two cells means their digits are in a 2:1 ratio."
            ),
            "killercage": [{"cells": ["R1C1", "R1C2"], "value": "6"}],
            "line": [{"lines": [["R1C1", "R2C2", "R3C3"], ["R5C5", "R6C6"]], "outlineC": "#FF7383"},
                     {"lines": [["R2C1", "R3C1", "R4C1"]], "outlineC": "#206aff"}],
            "ratio": [{"cells": ["R4C4", "R4C5"]}],
            "difference": [{"cells": ["R5C4", "R6C4"], "value": "1"}],
        }
        link = "https://sudokupad.app/example1234"
        lmd = "https://logic-masters.de/Raetselportal/Raetsel/zeigen.php?id=TEST"
        with patch("ysudoku.sudokupad._http_get", side_effect=[f'<a href="{link}">Open</a>', "fpuzencoded"]), \
             patch("ysudoku.decode.lzw_decompress", return_value=json.dumps(exported)) as unpack:
            puzzle = parse_puzzle(load(lmd, use_cache=False))
        unpack.assert_called_once_with("encoded")

        self.assertEqual(puzzle.source_url, link)
        self.assertEqual(puzzle.size, 6)
        self.assertEqual(puzzle.givens, {0: 1})
        self.assertEqual(len(puzzle.regions), 6)
        self.assertTrue(all(len(region) == 6 for region in puzzle.regions))
        self.assertEqual(puzzle.lines[0].cells, [0, 7, 14])
        self.assertEqual([dot.cells for dot in puzzle.dots], [[21, 22], [27, 33]])

        spec = heuristic_spec(puzzle, build_inventory(puzzle))
        self.assertEqual([rule["kind"] for rule in spec["rules"]],
                         ["cage", "kropki", "kropki", "dutch_whisper"])
        self.assertEqual(spec["rules"][-1]["elements"], ["line:0", "line:1"])

        puzzle.rules_text = "Between Lines: digits on a line are between its endpoints."
        spec = heuristic_spec(puzzle, build_inventory(puzzle))
        self.assertTrue(any(rule["kind"] == "between" for rule in spec["rules"]))

    def test_unknown_fpuzzles_rule_is_reported(self):
        data = {"size": 4, "grid": [[{} for _ in range(4)] for _ in range(4)],
                "thermometer": [{"lines": [["R1C1", "R1C2"]]}]}
        with patch("ysudoku.decode.lzw_decompress", return_value=json.dumps(data)):
            with self.assertRaisesRegex(ValueError, "thermometer"):
                decode_payload("fpuzencoded")


if __name__ == "__main__":
    unittest.main()
