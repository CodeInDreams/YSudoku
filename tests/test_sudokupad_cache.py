from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ysudoku import sudokupad


class SudokuPadCacheTest(TestCase):
    def test_writes_and_reuses_cache_from_a_fresh_directory(self):
        with TemporaryDirectory() as tmp, patch.object(sudokupad, "CACHE_DIR", Path(tmp)):
            with patch.object(sudokupad, "_http_get", return_value='{"cells": []}') as fetch:
                url = "https://sudokupad.app/ad4xg01xip"
                self.assertEqual(sudokupad.load(url), {"cells": []})
                self.assertEqual(sudokupad.load(url), {"cells": []})
                fetch.assert_called_once()
