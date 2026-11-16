import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ysudoku.sudokupad import extract_sudokupad_link


class LogicMastersLinkTest(unittest.TestCase):
    def test_extract_sudokupad_link(self):
        html = '<a href="https://sudokupad.app/eynwusqy5l">SudokuPad</a>'
        self.assertEqual(extract_sudokupad_link(html), "https://sudokupad.app/eynwusqy5l")

    def test_no_link(self):
        self.assertIsNone(extract_sudokupad_link("<a href='https://example.com'>x</a>"))


if __name__ == "__main__":
    unittest.main()
