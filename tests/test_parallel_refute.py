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

    def test_deep_refutation_keeps_a_complete_branch_proof(self):
        from itertools import product
        from ysudoku.search import refute_candidate_with_proof
        from ysudoku.state import Reason, State, bits

        class Nogood:
            def __init__(self, forbidden):
                self.forbidden = forbidden
                self._cells = [0, 1, 2]

            def cells(self):
                return self._cells

            def prune(self, state):
                changed = False
                for cell in self._cells:
                    for value in list(bits(state.dom[cell])):
                        feasible = any(
                            tuple(values) != self.forbidden
                            for values in product(*(list(bits(state.dom[c]))
                                                    if c != cell else [value]
                                                    for c in self._cells))
                        )
                        if not feasible:
                            changed |= state.elim(cell, value, Reason("nogood"))
                return changed

        st = State(2, [])
        st.dom = [0b11, 0b11, 0b11, 0b11]
        constraints = [Nogood(tuple(values)) for values in product((1, 2), repeat=3)]
        refuted, proof, _cause = refute_candidate_with_proof(
            st, constraints, 0, 1, time_limit=1.0,
        )

        self.assertTrue(refuted)
        self.assertEqual(proof["branch_cell"], 1)
        self.assertEqual([child["value"] for child in proof["children"]], [1, 2])
        self.assertTrue(all(child["proof"]["cause"] for child in proof["children"]))

    def test_incomplete_deep_search_is_not_reported_as_a_refutation(self):
        from ysudoku.search import refute_candidate_with_proof
        from ysudoku.state import State

        class NeverPrune:
            def cells(self):
                return [0, 1, 2]

            def prune(self, _state):
                return False

        st = State(2, [])
        st.dom = [0b11, 0b11, 0b11, 0b11]
        # Force a branch after the root assumption; the node budget stops
        # before that branch can be proved either way.
        refuted, proof, _cause = refute_candidate_with_proof(
            st, [NeverPrune()], 0, 1, time_limit=1.0, node_limit=1,
        )

        self.assertIsNone(refuted)
        self.assertIsNone(proof)


class WorkersTest(unittest.TestCase):
    def test_env_override(self):
        import os
        from unittest import mock
        from ysudoku.parallel_refute import default_workers

        with mock.patch.dict(os.environ, {"YSUDOKU_REFUTE_WORKERS": "2"}):
            self.assertEqual(default_workers(), 2)


class DynamicTest(unittest.TestCase):
    def test_dynamic_returns_list(self):
        from ysudoku.parallel_refute import run_parallel_dynamic
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b11
        out = run_parallel_dynamic(st, [], [(0, 1), (0, 2)], timeout=0.2)
        self.assertIsInstance(out, list)

    def test_timeout_bounds_batches_without_a_refutation(self):
        import time
        from unittest import mock
        from ysudoku.parallel_refute import run_parallel_dynamic
        from ysudoku.state import State, Unit

        st = State(9, [Unit("row", 0, list(range(9)))])
        st.dom[0] = 0b11

        def slow_no_refutation(_item):
            time.sleep(0.3)
            return None

        candidates = [(0, value) for value in range(1, 21)]
        with mock.patch("ysudoku.parallel_refute._worker", slow_no_refutation), \
                mock.patch.dict("os.environ", {"YSUDOKU_REFUTE_WORKERS": "2"}):
            started = time.monotonic()
            out = run_parallel_dynamic(
                st, [], candidates, timeout=0.1,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(out, [])
        self.assertLess(elapsed, 0.9)
