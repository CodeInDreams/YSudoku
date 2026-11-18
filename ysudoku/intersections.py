"""Generic reasoning over overlapping constraint regions.

Rules are hyperedges over cells.  Rules that share a cell form a connected
component.  Instead of applying one rule at a time, test each candidate
against the whole component: keep it only if the component has at least one
complete assignment containing that candidate.
"""

from __future__ import annotations

from .state import State

MAX_COMPONENT_CELLS = 8
MAX_NODES = 3000


def components(constraints) -> list[list]:
    parent = list(range(len(constraints)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    owners: dict[int, int] = {}
    for index, constraint in enumerate(constraints):
        for cell in constraint.cells():
            if cell in owners:
                union(index, owners[cell])
            else:
                owners[cell] = index
    groups: dict[int, list] = {}
    for index, constraint in enumerate(constraints):
        groups.setdefault(find(index), []).append(constraint)
    return list(groups.values())


def _units_of(state: State, cells: set[int]):
    units = []
    for ui, unit in enumerate(state.units):
        members = [c for c in unit.cells if c in cells]
        if len(members) >= 2:
            units.append((unit.label, members))
    return units


def _has_support(state: State, comp, cell: int, value: int, budget: int = MAX_NODES) -> bool:
    cells = sorted({c for constraint in comp for c in constraint.cells()})
    if len(cells) > MAX_COMPONENT_CELLS:
        return True
    domains = {c: {v for v in range(1, state.n + 1) if state.dom[c] >> (v - 1) & 1}
               for c in cells}
    domains[cell] = {value}
    order = sorted(cells, key=lambda c: len(domains[c]))
    assignment: dict[int, int] = {}
    nodes = [0]

    def ok_partial(constraint) -> bool:
        board = [state.vals[c] or assignment.get(c, 0) for c in range(state.n2)]
        return constraint.check(board)

    def dfs(i: int) -> bool:
        nodes[0] += 1
        if nodes[0] > budget:
            return True
        if i == len(order):
            for unit in state.units:
                values = [assignment.get(c, 0) for c in unit.cells]
                if all(values) and len(set(values)) != len(values):
                    return False
            return True
        current = order[i]
        for v in domains[current]:
            assignment[current] = v
            if all(ok_partial(c) for c in comp):
                if dfs(i + 1):
                    return True
            assignment.pop(current, None)
        return False

    return dfs(0)


def unsupported_candidates(state: State, constraints) -> list[tuple[int, int, list]]:
    """Return (cell, value, rules) for candidates unsupported in a local overlap."""
    found = []
    for cell in range(state.n2):
        if state.vals[cell]:
            continue
        active = {cell}
        comp = []
        changed = True
        while changed and len(active) <= MAX_COMPONENT_CELLS:
            changed = False
            for constraint in constraints:
                if constraint in comp:
                    continue
                scope = set(constraint.cells())
                if not (scope & active):
                    continue
                if len(active | scope) > MAX_COMPONENT_CELLS:
                    continue
                comp.append(constraint)
                active |= scope
                changed = True
        if not comp:
            continue
        rules = [constraint.describe() for constraint in comp]
        for value in range(1, state.n + 1):
            if not (state.dom[cell] >> (value - 1) & 1):
                continue
            if not _has_support(state, comp, cell, value):
                found.append((cell, value, rules))
    return found
