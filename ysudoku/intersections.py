"""Joint reasoning over overlapping rules.

A target cell defines a small local component: every rule sharing a cell with
the growing set is merged in, up to a hard cell limit.  The component is then
enumerated as a CSP.  A candidate is removed only when the enumeration is
*complete* and no solution contains it; an incomplete search never deletes.
"""

from __future__ import annotations

from functools import lru_cache

from .constraints import AntiPair, Clone, Palindrome, Renban, _matching_masks, consecutive_windows
from .state import Contradiction, Reason, State, bits

MAX_COMPONENT_CELLS = 6
MAX_NODES = 20_000


@lru_cache(maxsize=2048)
def _required_renban_digits(domains, n):
    required = (1 << n) - 1
    feasible = False
    for window in consecutive_windows(len(domains), n):
        mask = sum(1 << (digit - 1) for digit in window)
        if _matching_masks(domains, mask) is not None:
            required &= mask
            feasible = True
    return required if feasible else 0


def _equal_groups(rule):
    cells = rule.cells()
    if isinstance(rule, Clone):
        yield cells
    elif isinstance(rule, Palindrome):
        yield from zip(cells[:len(cells) // 2], reversed(cells))


def _equal_digit_cover(state, constraints):
    """An equal group cannot use a required digit if it sees every possible host."""
    equal = [(rule, tuple(group)) for rule in constraints for group in _equal_groups(rule)]
    for rule in constraints:
        if not isinstance(rule, Renban) or not equal:
            continue
        scope = rule.cells()
        required = _required_renban_digits(tuple(state.dom[c] for c in scope), state.n)
        for equal_rule, group in equal:
            seen = set().union(*(state.peers[c] for c in group))
            unseen = 0
            for cell in scope:
                if cell not in seen:
                    unseen |= state.dom[cell]
            eliminated = required & ~unseen
            changes = {cell: state.dom[cell] & ~eliminated for cell in group
                       if state.dom[cell] & eliminated}
            if changes:
                return changes, Reason("equal_digit_cover", {
                    "cells": scope, "equal": group, "digits": eliminated,
                    "hypothesis": any(getattr(r, "hypothesis", False) for r in (rule, equal_rule)),
                })
    return None


def _single_digit_layout(state, constraints):
    """Find where one digit can appear with matching positions on equal lines."""
    renbans = [rule for rule in constraints if isinstance(rule, Renban)]
    equal = [tuple(group) for rule in constraints for group in _equal_groups(rule)]
    if not renbans or not equal or state.n > 9:
        return None

    def mask(cells):
        return sum(1 << c for c in set(cells))

    def indexes(value):
        return (i - 1 for i in bits(value))

    required = [mask(unit.cells) for unit in state.units if len(unit.cells) == state.n]
    covered = 0
    for unit in required:
        covered |= unit
    if covered != (1 << state.n2) - 1:
        return None
    bans = [mask(peers) for peers in state.peers]
    groups = [mask(group) for group in equal]
    scope_masks = [(mask(rule.cells()), _required_renban_digits(
        tuple(state.dom[c] for c in rule.cells()), state.n)) for rule in renbans]
    for scope, _ in scope_masks:
        for cell in indexes(scope):
            bans[cell] |= scope ^ (1 << cell)
    choices = []
    for cell in range(state.n2):
        companions = 1 << cell
        while True:
            before = companions
            for group in groups:
                if group & companions:
                    companions |= group
            if companions == before:
                break
        excluded = 0
        for peer in indexes(companions):
            excluded |= bans[peer]
        choices.append((companions, excluded))

    for digit in range(1, state.n + 1):
        candidate = 1 << (digit - 1)
        possible = mask(c for c in range(state.n2) if state.dom[c] & candidate)
        needed = required + [scope for scope, values in scope_masks if values & candidate]
        supported, nodes = 0, 0

        def visit(available, outstanding, placed):
            nonlocal supported, nodes
            if supported == possible:
                return True
            nodes += 1
            if nodes > 20_000:
                return False
            if not outstanding:
                supported |= placed
                return True
            narrowest = min((unit & available for unit in outstanding), key=int.bit_count)
            for cell in indexes(narrowest):
                companions, excluded = choices[cell]
                if companions & excluded or companions & available != companions:
                    continue
                if not visit(available & ~(companions | excluded),
                             [unit for unit in outstanding if not unit & companions],
                             placed | companions):
                    return False
            return True

        if visit(possible, needed, 0) and supported != possible:
            if not supported:
                raise Contradiction(f"数字 {digit} 在行列宫、Renban 与同值格之间没有可行布局")
            cells = list(indexes(possible & ~supported))
            return {c: state.dom[c] & ~candidate for c in cells}, Reason("single_digit_layout", {
                "digit": digit, "equal": equal, "renbans": [r.cells() for r in renbans],
                "hypothesis": any(getattr(r, "hypothesis", False) for r in constraints),
            })
    return None


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


def visit_assignments(state: State, constraints, cells, visit):
    """Visit valid assignments to a bounded local scope, returning completeness."""
    variables = sorted(cells, key=lambda c: (state.vals[c] == 0,
                                             state.dom[c].bit_count()))
    domains = {c: [v for v in range(1, state.n + 1) if state.dom[c] >> (v - 1) & 1]
               for c in variables}
    assigned = state.vals.copy()
    scope = set(cells)
    peers = {cell: scope.intersection(state.peers[cell]) for cell in cells}
    scopes = [(constraint, constraint.cells()) for constraint in constraints]
    nodes = 0
    complete = True

    def partial_ok(cell: int, value: int) -> bool:
        return (all(assigned[other] != value for other in peers[cell])
                and all(not all(assigned[c] for c in rule_cells) or constraint.check(assigned)
                        for constraint, rule_cells in scopes))

    def dfs(i: int) -> None:
        nonlocal nodes, complete
        if not complete:
            return
        nodes += 1
        if nodes > MAX_NODES:
            complete = False
            return
        if i == len(variables):
            visit(assigned)
            return
        cell = variables[i]
        for value in domains[cell]:
            assigned[cell] = value
            if partial_ok(cell, value):
                dfs(i + 1)
            assigned[cell] = state.vals[cell]
            if not complete:
                return

    dfs(0)
    return complete


def _enumerate_supports(state: State, constraints, cells: set[int]):
    """Return (supports, complete). supports[cell] is the set of values seen."""
    supports = {cell: set() for cell in cells}

    def record(assigned):
        for cell in cells:
            supports[cell].add(assigned[cell])

    return supports, visit_assignments(state, constraints, cells, record)


class PatternPropagation:
    """Combine local combinations through shared cells or an all-different unit."""

    def __init__(self):
        self.cache = {}

    def _patterns(self, state, rule, cells):
        signature = tuple(state.dom[c] for c in cells)
        saved = self.cache.get(rule)
        if saved is not None and saved[0] == signature:
            return saved[1]
        patterns = []

        def record(assigned):
            patterns.append(tuple(1 << (assigned[c] - 1) for c in cells))

        complete = visit_assignments(state, [rule], cells, record)
        result = patterns if complete else None
        self.cache[rule] = signature, result
        return result

    @staticmethod
    def _project(cells, patterns, shared, in_unit):
        """Group combinations by the information the other rule can see."""
        shared_indices = [cells.index(c) for c in shared]
        unit_indices = [i for i, c in enumerate(cells) if c in in_unit]
        groups = {}
        for pattern in patterns:
            shared_values = tuple(pattern[i] for i in shared_indices)
            # Cells in the same unit are distinct, so sum equals bitwise union.
            occupied = sum(pattern[i] for i in unit_indices)
            supported = groups.setdefault((shared_values, occupied), [0] * len(cells))
            for i, bit in enumerate(pattern):
                supported[i] |= bit
        return groups

    @staticmethod
    def _locked(state, rule, cells, patterns, unit, inside):
        indices = [cells.index(c) for c in inside]
        mandatory = state.full
        for pattern in patterns:
            mandatory &= sum(pattern[i] for i in indices)
            if not mandatory:
                return None
        allowed = {c: state.dom[c] & ~mandatory
                   for c in unit.cells if c not in inside and state.dom[c] & mandatory}
        if not allowed:
            return None
        hosts = [c for c, i in zip(inside, indices)
                 if any(pattern[i] & mandatory for pattern in patterns)]
        return allowed, Reason("pattern_support", {
            "rules": [rule.describe()], "scopes": [list(cells)],
            "unit": unit.label, "unit_cells": unit.cells,
            "hosts": hosts, "digits": mandatory,
            "hypothesis": unit.hypothesis or bool(getattr(rule, "hypothesis", False)),
        })

    @staticmethod
    def _joined(state, left, right, shared, unit, left_inside, right_inside):
        lrule, lcells, lgroups = left
        rrule, rcells, rgroups = right
        lkeep, rkeep = set(), set()
        right_by_shared = {}
        for key in rgroups:
            right_by_shared.setdefault(key[0], []).append(key)
        for lkey in lgroups:
            for rkey in right_by_shared.get(lkey[0], ()):
                if not lkey[1] & rkey[1]:
                    lkeep.add(lkey)
                    rkeep.add(rkey)
        if not lkeep:
            raise Contradiction(f"「{lrule.describe()}」与「{rrule.describe()}」没有兼容组合")
        allowed = {}
        for cells, groups, keep in ((lcells, lgroups, lkeep), (rcells, rgroups, rkeep)):
            masks = [0] * len(cells)
            for key in keep:
                for index, mask in enumerate(groups[key]):
                    masks[index] |= mask
            for cell, mask in zip(cells, masks):
                allowed[cell] = allowed.get(cell, state.dom[cell]) & mask
        changes = {cell: mask for cell, mask in allowed.items() if mask != state.dom[cell]}
        if not changes:
            return None
        return changes, Reason("pattern_support", {
            "rules": [lrule.describe(), rrule.describe()],
            "scopes": [list(lcells), list(rcells)], "shared": list(shared),
            "unit": unit.label if unit else "", "unit_cells": unit.cells if unit else [],
            "hosts": [list(left_inside), list(right_inside)],
            "occupancy": [sorted({key[1] for key in g}) for g in (lgroups, rgroups)],
            "hypothesis": (bool(unit and unit.hypothesis)
                           or any(getattr(rule, "hypothesis", False) for rule in (lrule, rrule))),
        })

    def find(self, state, constraints):
        if equal_cover := _equal_digit_cover(state, constraints):
            return equal_cover
        tables = []
        for rule in constraints:
            # Board-wide anti constraints expand to many binary edges. Their
            # single-cell effects are already handled by direct propagation.
            if isinstance(rule, AntiPair):
                continue
            cells = tuple(dict.fromkeys(rule.cells()))
            if not 2 <= len(cells) <= MAX_COMPONENT_CELLS or all(state.vals[c] for c in cells):
                continue
            patterns = self._patterns(state, rule, cells)
            if patterns is None:
                continue
            if not patterns:
                raise Contradiction(f"「{rule.describe()}」没有合法组合")
            by_unit = {}
            for c in cells:
                for ui in state.unit_of[c]:
                    by_unit.setdefault(ui, []).append(c)
            tables.append((rule, cells, patterns, by_unit))
            for ui, inside in by_unit.items():
                if len(inside) >= 2:
                    result = self._locked(state, rule, cells, patterns, state.units[ui], inside)
                    if result:
                        return result

        projections = {}

        def project(table, shared, inside):
            rule, cells, patterns, _ = table
            key = (rule, shared, inside)
            if key not in projections:
                projections[key] = self._project(cells, patterns, shared, inside)
            return rule, cells, projections[key]

        for i, left in enumerate(tables):
            for right in tables[i + 1:]:
                shared = tuple(sorted(set(left[1]).intersection(right[1])))
                if len(shared) >= 2:
                    result = self._joined(state, project(left, shared, ()),
                                          project(right, shared, ()), shared, None, (), ())
                    if result:
                        return result
                for ui in sorted(left[3].keys() & right[3].keys()):
                    left_inside = tuple(c for c in left[3][ui] if c not in shared)
                    right_inside = tuple(c for c in right[3][ui] if c not in shared)
                    if not left_inside or not right_inside:
                        continue
                    if not shared and len(left_inside) == len(right_inside) == 1:
                        continue
                    result = self._joined(state, project(left, shared, left_inside),
                                          project(right, shared, right_inside), shared,
                                          state.units[ui], left_inside, right_inside)
                    if result:
                        return result
        return _single_digit_layout(state, constraints)


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


def bfs_unsupported(state: State, constraints, max_rules: int = 3):
    """Breadth-first by rule count: single rules, then pairs, then triples."""
    from itertools import combinations

    cache = {}
    for target in range(state.n2):
        if state.vals[target]:
            continue
        direct = [c for c in constraints if target in c.cells()]
        if not direct:
            continue
        active = set().union(*(set(c.cells()) for c in direct))
        pool = list(direct)
        for c in constraints:
            if c in pool:
                continue
            if set(c.cells()) & active:
                pool.append(c)
            if len(pool) >= 10:
                break
        for size in range(1, max_rules + 1):
            for combo in combinations(pool, size):
                combo = list(combo)
                cells = set().union(*(set(c.cells()) for c in combo))
                if target not in cells or len(cells) > MAX_COMPONENT_CELLS:
                    continue
                key = tuple(id(c) for c in combo)
                if key not in cache:
                    cache[key] = _enumerate_supports(state, combo, cells)
                supports, complete = cache[key]
                if not complete:
                    continue
                rules = [c.describe() for c in combo]
                for value in range(1, state.n + 1):
                    if state.dom[target] >> (value - 1) & 1 and value not in supports[target]:
                        return [(target, value, rules)]
    return []


def joint_refute(state: State, constraints, cell: int, value: int):
    """Refute cell=value by a complete local component search."""
    child = state.copy()
    child.dom[cell] = 1 << (value - 1)
    comp, cells = local_component(child, constraints, cell)
    if not comp or len(cells) > MAX_COMPONENT_CELLS:
        return None
    supports, complete = _enumerate_supports(child, comp, cells)
    if not complete:
        return None
    rules = [c.describe() for c in comp]
    if not supports.get(cell):
        return True, "联合规则无一致赋值：" + "；".join(rules[:6]), rules
    return None
