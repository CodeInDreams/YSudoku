"""Search used only as a referee: uniqueness, verification, audit."""

from __future__ import annotations

from .state import Contradiction, Reason, State, bits


class BudgetExceeded(Exception):
    pass


def propagate(st: State, constraints, max_rounds: int = 200) -> bool:
    for _ in range(max_rounds):
        changed = False
        for con in constraints:
            try:
                if con.prune(st):
                    changed = True
            except Contradiction:
                return False
        for cell in range(st.n2):
            if st.vals[cell] == 0 and st.dom[cell].bit_count() == 1:
                try:
                    value = st.dom[cell].bit_length()
                    st.place(cell, value, Reason("naked_single", {"cell": cell, "value": value}) if st.record else None)
                except Contradiction:
                    return False
                changed = True
        for unit in st.units:
            for digit in range(1, st.n + 1):
                hosts = [c for c in unit.cells if st.has(c, digit)]
                if not hosts:
                    return False
                if len(hosts) == 1 and st.vals[hosts[0]] == 0:
                    try:
                        st.place(hosts[0], digit, Reason("hidden_single", {
                            "cell": hosts[0], "value": digit, "unit": unit.label,
                            "unit_cells": list(unit.cells),
                        }) if st.record else None)
                    except Contradiction:
                        return False
                    changed = True
        if not changed:
            return True
    return True


def _search(st: State, constraints, limit: int, node_limit: int):
    solutions: list[list[int]] = []
    counter = [0]

    def dfs(state: State) -> None:
        counter[0] += 1
        if counter[0] > node_limit:
            raise BudgetExceeded
        if not propagate(state, constraints):
            return
        if state.solved:
            solutions.append(state.vals.copy())
            return
        unfilled = [c for c in range(state.n2) if state.vals[c] == 0]
        cell = min(unfilled, key=lambda c: state.dom[c].bit_count())
        for value in bits(state.dom[cell]):
            child = state.copy()
            try:
                child.place(cell, value)
            except Contradiction:
                continue
            dfs(child)
            if len(solutions) >= limit:
                return

    try:
        dfs(st.copy())
    except BudgetExceeded:
        return solutions, False
    return solutions, True


def count_solutions(st: State, constraints, limit: int = 2, node_limit: int = 60_000):
    solutions, complete = _search(st, constraints, limit, node_limit)
    return (len(solutions) if complete else None), solutions


def first_solution(st: State, constraints, node_limit: int = 60_000):
    solutions, complete = _search(st, constraints, 1, node_limit)
    return solutions[0] if solutions else None


def satisfiable(st: State, constraints, cell: int, value: int, node_limit: int = 20_000) -> bool | None:
    """Is there a solution with ``cell = value``?  None means "budget exceeded"."""
    child = st.copy()
    if child.vals[cell] == value:
        return True
    if child.vals[cell] or not child.has(cell, value):
        return False
    try:
        child.place(cell, value)
    except Contradiction:
        return False
    solutions, complete = _search(child, constraints, 1, node_limit)
    if solutions:
        return True
    return False if complete else None


def refute_candidate(st: State, constraints, cell: int, value: int,
                     time_limit: float = 1.5):
    """Return (verdict, trace, cause); verdict True means refuted."""
    import time
    if st.vals[cell]:
        return (value != st.vals[cell], [], "")
    if not st.has(cell, value):
        return (True, [], "该候选已经不存在")
    child = st.copy()
    child.record = True
    child.events = []
    try:
        child.place(cell, value, Reason("assumption", {"cell": cell, "value": value}))
    except Contradiction:
        return (True, [], "假设立即矛盾")
    started = time.time()

    def dfs(state: State) -> bool:
        if time.time() - started > time_limit:
            raise BudgetExceeded
        if not propagate(state, constraints):
            return False
        if state.solved:
            return True
        pick = min(
            (c for c in range(state.n2) if state.vals[c] == 0),
            key=lambda c: state.dom[c].bit_count(),
        )
        for candidate in bits(state.dom[pick]):
            branch = state.copy()
            try:
                branch.place(pick, candidate)
            except Contradiction:
                continue
            if dfs(branch):
                return True
        return False

    try:
        if dfs(child):
            return (False, [], "")
        trace = [e for e in child.events if e.reason.kind != "assumption"]
        return (True, trace, "沿规则继续推导后无解")
    except BudgetExceeded:
        return (None, [], "")


def refute_direct_with_trace(st: State, constraints, cell: int, value: int):
    """Assume cell=value and propagate once; return (refuted, trace, cause)."""
    if st.vals[cell]:
        return (value != st.vals[cell], [], "")
    if not st.has(cell, value):
        return (True, [], "该候选已经不存在")
    child = st.copy()
    child.record = True
    child.events = []
    try:
        child.place(cell, value, Reason("assumption", {"cell": cell, "value": value}))
        ok = propagate(child, constraints)
    except Contradiction as exc:
        ok = False
        cause = str(exc)
    else:
        cause = ""
    if ok:
        return (False, [], "")
    if not cause:
        empty = [c for c in range(child.n2) if child.dom[c] == 0]
        if empty:
            cause = f"{empty[0] // child.n + 1}行{empty[0] % child.n + 1}列没有候选"
        else:
            cause = ""
            for unit in child.units:
                for digit in range(1, child.n + 1):
                    if not any(child.has(c, digit) for c in unit.cells):
                        cause = f"{unit.label} 没有位置放 {digit}"
                        break
                if cause:
                    break
            if not cause and child.events:
                last = child.events[-1]
                cause = (f"在 R{last.cell // child.n + 1}C{last.cell % child.n + 1} "
                         f"执行 {last.reason.kind} 后无解")
            cause = cause or "约束传播无解"
    trace = [e for e in child.events if e.reason.kind != "assumption"]
    return (True, trace, cause)
