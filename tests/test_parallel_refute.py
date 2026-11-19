import unittest

from ysudoku.parallel_refute import merge_result
from ysudoku.state import State, Unit


class MergeTest(unittest.TestCase):
    def test_discards_stale_candidate(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b1  # value 1 already gone
        result = (0, 1, [], "test", 0)
        self.assertIsNone(merge_result(st, [], result))

    def test_applies_valid_candidate(self):
        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b11
        result = (0, 1, [], "test", 0)
        merged = merge_result(st, [], result)
        self.assertIsNotNone(merged)
        self.assertFalse(st.dom[0] & 1)


class RefuterTest(unittest.TestCase):
    def test_dispatch_and_poll(self):
        import time
        from ysudoku.parallel_refute import Refuter
        from ysudoku.search import refute_direct_with_trace
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b11
        # no constraints means no refutation; just ensure dispatch/poll terminate
        r = Refuter([])
        r.dispatch(st, [(0, 1), (0, 2)])
        for _ in range(40):
            r.poll()
            if not r.busy():
                break
            time.sleep(0.05)
        self.assertIsInstance(r.results, list)


class WorkersTest(unittest.TestCase):
    def test_env_override(self):
        import os
        from unittest import mock
        from ysudoku.parallel_refute import default_workers

        with mock.patch.dict(os.environ, {"YSUDOKU_REFUTE_WORKERS": "2"}):
            self.assertEqual(default_workers(), 2)
