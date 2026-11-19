"""Parallel refutation candidates with serial merge-on-main-thread semantics."""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass

from .search import refute_direct_with_trace
from .state import Contradiction, Reason, State

def physical_cores() -> int:
    try:
        pairs = set()
        phys = core = None
        for line in open("/proc/cpuinfo", encoding="utf-8"):
            if line.startswith("physical id"):
                phys = line.split(":")[1].strip()
            elif line.startswith("core id"):
                core = line.split(":")[1].strip()
                if phys is not None and core is not None:
                    pairs.add((phys, core))
        if pairs:
            return len(pairs)
    except OSError:
        pass
    import os
    return os.cpu_count() or 1


def default_workers() -> int:
    import os
    override = os.environ.get("YSUDOKU_REFUTE_WORKERS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    return max(1, physical_cores() - 1)


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


def _process_main(item, conn):
    try:
        conn.send(_worker(item))
    except Exception:
        conn.send(None)
    finally:
        conn.close()


def run_parallel(state: State, constraints, candidates, timeout: float = 3.0):
    """Fork two workers; the main thread polls their pipes at safe points."""
    global _STATE, _CONSTRAINTS
    _STATE, _CONSTRAINTS = state, constraints
    if not candidates:
        return []
    ctx = mp.get_context("fork")
    pending = list(candidates)
    running = []
    results = []
    first_at = None
    deadline = None

    def start_next():
        if not pending:
            return
        item = pending.pop(0)
        recv, send = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_process_main, args=(item, send), daemon=True)
        proc.start()
        send.close()
        running.append((proc, recv))

    for _ in range(2):
        start_next()

    import time as _time
    while running:
        now = _time.monotonic()
        if deadline is not None and now >= deadline:
            break
        for entry in list(running):
            proc, conn = entry
            if conn.poll(0):
                try:
                    item = conn.recv()
                except EOFError:
                    item = None
                if item is not None:
                    results.append(item)
                    if first_at is None:
                        first_at = now
                        deadline = now + timeout
                running.remove(entry)
                proc.join(timeout=0.1)
                start_next()
        _time.sleep(0.05)
    for proc, conn in running:
        conn.close()
        proc.terminate()
        proc.join(timeout=0.2)
    return results


def merge_result(state: State, constraints, result):
    """Apply one result only if its candidate is still valid; else discard."""
    from .state import Contradiction, Reason

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


def _batch_main(items, conn):
    try:
        for item in items:
            result = _worker(item)
            if result is not None:
                conn.send(result)
    except Exception:
        pass
    finally:
        conn.close()


class Refuter:
    """Non-blocking dispatch of refutation candidates to two forked workers."""

    def __init__(self, constraints, timeout: float = 3.0, workers: int | None = None):
        self.constraints = constraints
        self.timeout = timeout
        self.workers = max(1, workers or default_workers())
        self.running = []
        self.first_at = None
        self.deadline = None
        self.results = []

    def dispatch(self, state: State, candidates):
        global _STATE, _CONSTRAINTS
        if not candidates:
            return
        _STATE, _CONSTRAINTS = state, self.constraints
        ctx = mp.get_context("fork")
        size = (len(candidates) + self.workers - 1) // self.workers
        for offset in range(0, len(candidates), size):
            batch = candidates[offset:offset + size]
            if not batch:
                continue
            recv, send = ctx.Pipe(duplex=False)
            proc = ctx.Process(target=_batch_main, args=(batch, send), daemon=True)
            proc.start()
            send.close()
            self.running.append((proc, recv))

    def poll(self):
        import time as _time
        now = _time.monotonic()
        fresh = []
        if self.deadline is not None and now >= self.deadline:
            self._stop()
            return self.results
        for entry in list(self.running):
            proc, conn = entry
            while conn.poll(0):
                try:
                    item = conn.recv()
                except EOFError:
                    break
                if item is not None:
                    fresh.append(item)
                    self.results.append(item)
                    if self.first_at is None:
                        self.first_at = now
                        self.deadline = now + self.timeout
            if not conn.poll(0):
                continue
        return fresh

    def _stop(self):
        for proc, conn in self.running:
            conn.close()
            proc.terminate()
            proc.join(timeout=0.2)
        self.running = []

    def busy(self):
        return bool(self.running) and (self.deadline is None or __import__("time").monotonic() < self.deadline)


def _task_main(conn):
    try:
        while True:
            item = conn.recv()
            if item is None:
                break
            conn.send(_worker(item))
    except (EOFError, OSError):
        pass
    finally:
        conn.close()


def run_parallel_dynamic(state: State, constraints, candidates, timeout: float = 3.0):
    """Two forked workers pull the next candidate as soon as they are free."""
    global _STATE, _CONSTRAINTS
    _STATE, _CONSTRAINTS = state, constraints
    if not candidates:
        return []
    ctx = mp.get_context("fork")
    pending = list(candidates)
    workers = []
    results = []
    deadline = None
    import time as _time
    for _ in range(min(default_workers(), len(pending))):
        parent, child = ctx.Pipe(duplex=True)
        proc = ctx.Process(target=_task_main, args=(child,), daemon=True)
        proc.start()
        child.close()
        item = pending.pop(0)
        parent.send(item)
        workers.append((proc, parent))
    empty_since = None
    while workers:
        now = _time.monotonic()
        if not pending:
            if empty_since is None:
                empty_since = now
            elif now - empty_since > 0.5:
                break
        else:
            empty_since = None
        if deadline is not None and now >= deadline:
            break
        alive = []
        for proc, conn in workers:
            if conn.poll(0):
                try:
                    item = conn.recv()
                except EOFError:
                    item = None
                if item is not None:
                    results.append(item)
                    if deadline is None:
                        deadline = now + timeout
                try:
                    if pending:
                        conn.send(pending.pop(0))
                    else:
                        conn.send(None)
                except (BrokenPipeError, OSError):
                    pass
            alive.append((proc, conn))
        workers = alive
        if not pending and all(not conn.poll(0) for _p, conn in workers):
            # give already-running workers a chance to answer
            pass
        _time.sleep(0.05)
    for proc, conn in workers:
        conn.close()
        proc.terminate()
        proc.join(timeout=0.2)
    return results
