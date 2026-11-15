"""Search used only as a referee: uniqueness, verification, audit."""

from __future__ import annotations

from .state import Contradiction, State, bits


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
                    st.place(cell, st.dom[cell].bit_length())
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
                        st.place(hosts[0], digit)
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
