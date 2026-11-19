"""Generic local-support engine over constraint IR."""

from __future__ import annotations

from .state import State

MAX_CELLS = 8
MAX_NODES = 40000


def _component(relations, target):
    active = {target}
    chosen = []
    changed = True
    while changed and len(active) <= MAX_CELLS:
        changed = False
        for rel in relations:
            if rel in chosen:
                continue
            scope = set(rel.cells)
            if not (scope & active):
                continue
            if len(active | scope) > MAX_CELLS:
                continue
            chosen.append(rel)
            active |= scope
            changed = True
    return chosen, active


def _supports(state: State, relations, cells):
    variables = sorted(cells, key=lambda c: state.dom[c].bit_count())
    assignment = {}
    supports = {c: set() for c in variables}
    nodes = 0
    complete = True

    def board():
        return [state.vals[c] or assignment.get(c, 0) for c in range(state.n2)]

    def dfs(i):
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
        for v in range(1, state.n + 1):
            if not (state.dom[cell] >> (v - 1) & 1):
                continue
            assignment[cell] = v
            b = board()
            if all(rel.check(b) for rel in relations):
                dfs(i + 1)
            assignment.pop(cell, None)
            if not complete:
                return

    dfs(0)
    return supports, complete


def unsupported(state: State, relations):
    cache = {}
    found = []
    for target in range(state.n2):
        if state.vals[target]:
            continue
        comp, cells = _component(relations, target)
        if not comp:
            continue
        key = frozenset(cells)
        if key not in cache:
            cache[key] = _supports(state, comp, cells)
        supports, complete = cache[key]
        if not complete:
            continue
        for v in range(1, state.n + 1):
            if state.dom[target] >> (v - 1) & 1 and v not in supports[target]:
                found.append((target, v, [r.describe() for r in comp]))
    return found
