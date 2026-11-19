import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ysudoku import store
from ysudoku.server import _safe_static


class PathSafetyTest(unittest.TestCase):
    def test_cache_key_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict("os.environ", {"YSUDOKU_STORE": tmp}):
            with self.assertRaises(ValueError):
                store._entry_dir("../escape")

    def test_static_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "ok.txt").write_text("ok")
            self.assertIsNotNone(_safe_static(base, "ok.txt"))
            self.assertIsNone(_safe_static(base, "../etc/passwd"))

    def test_layer_name_is_fixed(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict("os.environ", {"YSUDOKU_STORE": tmp}):
            store._entry_dir("abc")
            with self.assertRaises(ValueError):
                store.delete_layer("abc", "../../x")


if __name__ == "__main__":
    unittest.main()
