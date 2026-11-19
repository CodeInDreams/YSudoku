"""Parallel refutation candidates with serial merge-on-main-thread semantics."""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass

from .search import refute_direct_with_trace
from .state import Contradiction, Reason, State

_STATE: State | None = None
_CONSTRAINTS = None


def _worker(item):
    cell, value = item
    if _STATE is None:
        return None
    child = _STATE.copy()
    try:
        refuted, trace, cause = refute_direct_with_trace(
            child, _CONSTRAINTS, cell, value)
    except Exception:
        return None
    if not refuted:
        return None
    places = sum(1 for e in trace if e.kind == "place")
    return (cell, value, trace, cause, places)


def run_parallel(state: State, constraints, candidates, timeout: float = 3.0):
    """Run candidates in forked workers; return results collected until timeout."""
    global _STATE, _CONSTRAINTS
    _STATE, _CONSTRAINTS = state, constraints
    if not candidates:
        return []
    ctx = mp.get_context("fork")
    results = []
    with ctx.Pool(processes=min(4, len(candidates))) as pool:
        it = pool.imap_unordered(_worker, candidates)
        first_at = None
        deadline = None
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            wait = 30 if deadline is None else max(0.0, deadline - now)
            try:
                item = it.next(timeout=wait)
            except (StopIteration, mp.TimeoutError):
                break
            if item is not None:
                results.append(item)
                if first_at is None:
                    first_at = now
                    deadline = now + timeout
        pool.terminate()
    return results


def merge_result(state: State, constraints, result):
    """Apply one result only if its candidate is still valid; else discard."""
    cell, value, trace, cause, _places = result
    if state.vals[cell] or not (state.dom[cell] >> (value - 1) & 1):
        return None
    pre_dom, pre_vals = state.dom.copy(), state.vals.copy()
    state.begin()
    try:
        state.elim(cell, value, Reason("contradiction", {
            "cell": cell, "value": value, "phase": "end", "cause": cause,
        }))
    except Contradiction:
        state.rollback()
        return None
    events = state.end()
    return events, pre_dom, pre_vals
