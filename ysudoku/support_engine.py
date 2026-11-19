"""Generic local-support engine over constraint IR."""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import State

MAX_CELLS = 8
MAX_NODES = 40_000


@dataclass
class SupportResult:
    eliminations: list[tuple[int, int, list[str]]] = field(default_factory=list)
    unresolved: list[tuple[int, int, str]] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unresolved

    def __iter__(self):
        # Keep the original iterable behavior while exposing incomplete work.
        return iter(self.eliminations)

    def __bool__(self):
        return bool(self.eliminations or self.unresolved or self.contradictions)

    def __len__(self):
        return len(self.eliminations)

    def __getitem__(self, index):
        return self.eliminations[index]


def _component(relations, target, max_cells):
    active = {target}
    chosen = []
    chosen_signatures = set()
    blocked = []
    changed = True
    while changed:
        changed = False
        for relation in relations:
            signature = relation.signature()
            if signature in chosen_signatures:
                continue
            scope = set(relation.cells)
            if not (scope & active):
                continue
            if len(active | scope) > max_cells:
                blocked.append(relation.describe())
                chosen_signatures.add(signature)
                continue
            chosen.append(relation)
            chosen_signatures.add(signature)
            active |= scope
            changed = True
    return chosen, active, sorted(set(blocked))


def _has_support(state: State, relations, cells, target: int, value: int, max_nodes: int):
    domains = {cell: (1 << (state.vals[cell] - 1) if state.vals[cell]
                      else state.dom[cell]) for cell in cells}
    forced = 1 << (value - 1)
    if not domains[target] & forced:
        return True, True
    domains[target] = forced

    variables = sorted((cell for cell in cells if not state.vals[cell]
                        and cell != target),
                       key=lambda cell: domains[cell].bit_count())
    nodes = 0
    exhausted = False

    def dfs(index):
        nonlocal nodes, exhausted
        nodes += 1
        if nodes > max_nodes:
            exhausted = True
            return False
        if any(not relation.possible(domains) for relation in relations):
            return False
        if index == len(variables):
            return True
        cell = variables[index]
        original = domains[cell]
        for bit_index in range(state.n):
            bit = 1 << bit_index
            if not original & bit:
                continue
            domains[cell] = bit
            if dfs(index + 1):
                domains[cell] = original
                return True
            if exhausted:
                break
        domains[cell] = original
        return False

    found = dfs(0)
    return found, not exhausted


def analyze_support(state: State, relations, *, max_cells: int = MAX_CELLS,
                    max_nodes: int = MAX_NODES) -> SupportResult:
    relations = list(relations)
    if max_cells < 1 or max_nodes < 1:
        raise ValueError("support limits must be positive")
    for relation in relations:
        if any(cell >= state.n2 for cell in relation.cells):
            raise ValueError(f"relation scope exceeds board: {relation.describe()}")

    result = SupportResult()
    for relation in relations:
        if all(state.vals[cell] for cell in relation.cells):
            if not relation.check(state.vals):
                result.contradictions.append(relation.describe())
    for target in range(state.n2):
        if state.vals[target]:
            continue
        component, cells, blocked = _component(relations, target, max_cells)
        if not component and not blocked:
            continue
        descriptions = [relation.describe() for relation in component]
        for value in range(1, state.n + 1):
            if not state.dom[target] >> (value - 1) & 1:
                continue
            found, complete = _has_support(state, component, cells, target, value, max_nodes)
            if found:
                if blocked:
                    result.unresolved.append((target, value,
                                              "component exceeds local cell limit: "
                                              + "; ".join(blocked)))
                continue
            if not complete:
                result.unresolved.append((target, value,
                                          f"support search exceeded {max_nodes} nodes"))
            else:
                result.eliminations.append((target, value, descriptions))
    return result


def unsupported(state: State, relations, *, max_cells: int = MAX_CELLS,
                max_nodes: int = MAX_NODES) -> SupportResult:
    """Return sound eliminations and report candidates not fully checked."""
    return analyze_support(state, relations, max_cells=max_cells,
                           max_nodes=max_nodes)
