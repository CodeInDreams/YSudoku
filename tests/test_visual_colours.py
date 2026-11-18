import unittest

from ysudoku.state import Reason
from ysudoku.visual_colours import xv_colours


class Event:
    def __init__(self, kind, data):
        self.kind = "elim"
        self.reason = Reason(kind, data)


class VisualColoursTest(unittest.TestCase):
    def test_v_pair_gets_two_colours(self):
        out = xv_colours([Event("xv", {"a": 3, "b": 4, "sum": 5})])
        self.assertEqual([c["cells"] for c in out], [[3], [4]])
        self.assertNotEqual(out[0]["colour"], out[1]["colour"])

    def test_no_colours_for_other_rules(self):
        self.assertEqual(xv_colours([Event("arrow", {"circle": 1})]), [])


if __name__ == "__main__":
    unittest.main()
