import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.model import parse_puzzle
from ysudoku.rules import build_inventory
from ysudoku.rulesheet import legend_text, render


class RuleSheetTest(unittest.TestCase):
    def test_render_png_and_legend(self):
        puzzle = parse_puzzle(json.loads((ROOT / "fixtures" / "double-slit.json").read_text()))
        elements = build_inventory(puzzle)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sheet.png"
            legend = render(puzzle, elements, path)
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(len(legend), len(elements))
            text = legend_text(puzzle, elements, legend)
            self.assertIn("Numbers on the image", text)
            self.assertIn(elements[0].id, text)


if __name__ == "__main__":
    unittest.main()
