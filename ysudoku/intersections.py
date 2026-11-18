"""Joint reasoning over overlapping rules.

A target cell defines a small local component: every rule sharing a cell with
the growing set is merged in, up to a hard cell limit.  The component is then
enumerated as a CSP.  A candidate is removed only when the enumeration is
*complete* and no solution contains it; an incomplete search never deletes.
"""

from __future__ import annotations

from .state import State

MAX_COMPONENT_CELLS = 6
MAX_NODES = 20_000


def _units_for(state: State, cells: set[int]):
    out = []
    for unit in state.units:
        members = [c for c in unit.cells if c in cells]
        if len(members) >= 2:
            out.append(members)
    return out


def local_component(state: State, constraints, target: int):
    active = {target}
    chosen = []
    changed = True
    while changed and len(active) <= MAX_COMPONENT_CELLS:
        changed = False
        for constraint in constraints:
            if constraint in chosen:
                continue
            scope = set(constraint.cells())
            if not (scope & active):
                continue
            if len(active | scope) > MAX_COMPONENT_CELLS:
                continue
            chosen.append(constraint)
            active |= scope
            changed = True
    return chosen, active


def _enumerate_supports(state: State, constraints, cells: set[int]):
    """Return (supports, complete). supports[cell] is the set of values seen."""
    variables = sorted(cells, key=lambda c: (state.vals[c] == 0,
                                             state.dom[c].bit_count()))
    domains = {c: [v for v in range(1, state.n + 1) if state.dom[c] >> (v - 1) & 1]
               for c in variables}
    units = _units_for(state, cells)
    assignment: dict[int, int] = {}
    supports = {c: set() for c in variables}
    nodes = 0
    complete = True

    def board():
        return [state.vals[c] or assignment.get(c, 0) for c in range(state.n2)]

    def partial_ok(cell: int, value: int) -> bool:
        for unit in units:
            if cell in unit:
                for other in unit:
                    if other != cell and assignment.get(other) == value:
                        return False
        b = board()
        for constraint in constraints:
            vals = [b[c] for c in constraint.cells()]
            if all(vals) and not constraint.check(b):
                return False
        return True

    def dfs(i: int) -> None:
        nonlocal nodes, complete
        if not complete:
            return
        nodes += 1
        if nodes > MAX_NODES:
            complete = False
            return
        if i == len(variables):
            for c in variables:
                supports[c].add(assignment[c])
            return
        cell = variables[i]
        for value in domains[cell]:
            assignment[cell] = value
            if partial_ok(cell, value):
                dfs(i + 1)
            assignment.pop(cell, None)
            if not complete:
                return

    dfs(0)
    return supports, complete


def unsupported_candidates(state: State, constraints) -> list[tuple[int, int, list]]:
    """Return (cell, value, rules) candidates with no support in a complete search."""
    cache = {}
    out = []
    for target in range(state.n2):
        if state.vals[target]:
            continue
        comp, cells = local_component(state, constraints, target)
        if not comp:
            continue
        key = frozenset(cells)
        if key not in cache:
            cache[key] = _enumerate_supports(state, comp, cells)
        supports, complete = cache[key]
        if not complete:
            continue
        rules = [c.describe() for c in comp]
        for value in range(1, state.n + 1):
            if state.dom[target] >> (value - 1) & 1 and value not in supports[target]:
                out.append((target, value, rules))
    return out
