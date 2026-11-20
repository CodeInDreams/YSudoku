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


def _placement_conflict(st, exc):
    cells = tuple(c for c, mask in enumerate(st.dom) if not mask)
    scope = cells
    if cells and st.events:
        last = st.events[-1]
        by = last.reason.data.get("by")
        if last.reason.kind == "unit_peer" and by is not None:
            shared = set(st.unit_of[cells[0]]) & set(st.unit_of[by])
            if shared:
                scope = tuple(st.units[min(shared)].cells)
    return str(exc), cells, None, {"scope": scope, "cells": cells}


def _propagate_with_cause(st: State, constraints, max_rounds: int = 200):
    """Return the terminal contradiction and the facts that establish it."""
    for _ in range(max_rounds):
        changed = False
        for con in constraints:
            first = len(st.events)
            try:
                changed |= bool(con.prune(st))
            except Contradiction as exc:
                empty = next((c for c, mask in enumerate(st.dom) if not mask), None)
                scope = tuple(con.cells())
                cells = (empty,) if empty is not None else ()
                cause = str(exc), cells or scope, None, {
                    "scope": scope or cells, "cells": cells or (scope if len(scope) == 1 else ()),
                }
            else:
                cause = None
            scope = None
            for event in st.events[first:]:
                if scope is None:
                    scope = tuple(con.cells())
                data = {**event.reason.data, "proof_scope": scope}
                if getattr(con, "kind", "") == "pair":
                    other = con.b if event.cell == con.a else con.a
                    data["proof_partner"] = other
                    data["proof_values"] = tuple(v for v in range(1, st.n + 1)
                                                 if con.ok(event.value, v))
                event.reason = Reason(event.reason.kind, data)
            if cause:
                return cause
        for cell in range(st.n2):
            if st.vals[cell] == 0 and st.dom[cell].bit_count() == 1:
                value = st.dom[cell].bit_length()
                try:
                    st.place(cell, value, Reason("naked_single", {"cell": cell, "value": value}))
                except Contradiction as exc:
                    return _placement_conflict(st, exc)
                changed = True
        for unit in st.units:
            for digit in range(1, st.n + 1):
                hosts = [c for c in unit.cells if st.has(c, digit)]
                if not hosts:
                    return f"{unit.label} 没有位置放 {digit}", unit.cells, digit, {
                        "scope": tuple(unit.cells), "cells": (),
                    }
                if len(hosts) == 1 and st.vals[hosts[0]] == 0:
                    try:
                        st.place(hosts[0], digit, Reason("hidden_single", {
                            "cell": hosts[0], "value": digit,
                            "unit": unit.label, "unit_cells": list(unit.cells),
                        }))
                    except Contradiction as exc:
                        return _placement_conflict(st, exc)
                    changed = True
        if not changed:
            break
    return None


def _slice_refutation(proof, full, budget):
    """Keep deductions needed by a leaf contradiction or by a child proof."""
    budget()
    dom = list(proof["pre_dom"])
    vals = list(proof["pre_vals"])
    dependencies = []
    for event in proof["events"]:
        data = event.reason.data
        cell, digit = event.cell, event.value
        kind = event.reason.kind
        removed = [(cell, digit, False)]
        if event.kind == "place":
            removed = [(cell, v, False) for v in bits(dom[cell]) if v != digit]
            removed.append((cell, digit, True))

        if kind == "assumption":
            needs = []
        elif kind == "unit_peer":
            needs = [(data["by"], digit, True)]
        elif kind == "hidden_single":
            needs = [(c, digit, False) for c in data["unit_cells"] if c != cell]
        elif "proof_partner" in data:
            needs = [(data["proof_partner"], v, False) for v in data["proof_values"]]
        elif kind in ("anti_knight", "anti_king"):
            other = data["b"] if cell == data["a"] else data["a"]
            needs = [(other, digit, True)]
        else:
            scope = data.get("proof_scope", (cell,))
            needs = [(c, v, False) for c in scope for v in bits(full & ~dom[c])]
            if kind != "naked_single":
                needs.extend((c, vals[c], True) for c in scope if vals[c])
        dependencies.append((event, removed, needs))
        if event.kind == "place":
            dom[cell] = 1 << (digit - 1)
            vals[cell] = digit
        else:
            dom[cell] &= ~(1 << (digit - 1))

    required = set()
    if proof["cause"]:
        for cell in proof.pop("conflict_cells"):
            digit = proof["conflict_digit"]
            required.update((cell, v, False) for v in ([digit] if digit else bits(full & ~dom[cell])))
            if digit is None and vals[cell]:
                required.add((cell, vals[cell], True))
    else:
        cell = proof["branch_cell"]
        required.update((cell, v, False) for v in bits(full & ~dom[cell]))
        for child in proof["children"]:
            required.update(_slice_refutation(child["proof"], full, budget))

    kept = []
    for event, effects, needs in reversed(dependencies):
        if event.reason.kind == "assumption" or required.intersection(effects):
            required.difference_update(effects)
            required.update(needs)
            kept.append(event)
    proof["events"] = list(reversed(kept))
    return required


class RefutationBudgetExceeded(Exception):
    pass


def proof_cost(proof: dict) -> tuple[int, int, int]:
    """Score a complete refutation by support events, branch depth and nodes."""
    own = sum(1 for e in proof.get("events", ())
              if e.reason.kind != "assumption")
    children = proof.get("children", ())
    if not children:
        return own, 0, 1
    scores = [proof_cost(child["proof"]) for child in children]
    return (
        own + sum(s[0] for s in scores) + len(children),
        1 + max(s[1] for s in scores),
        1 + sum(s[2] for s in scores),
    )


def refute_candidate_with_proof(st: State, constraints, cell: int, value: int,
                                time_limit: float = 1.0,
                                node_limit: int = 17):
    """Prove a candidate impossible and retain the full, explainable branch tree.

    A leaf is a contradiction reached by ordinary constraint propagation. An
    internal node is a branch on one cell whose every candidate has a proof of
    contradiction. Only a complete proof permits exclusion. False means a
    completion was found; None means the limited proof search was inconclusive.
    """
    import time
    if st.vals[cell]:
        return (value != st.vals[cell], None, "")
    if not st.has(cell, value):
        return (True, {"events": [], "cause": "该候选已经不存在"}, "该候选已经不存在")

    started = time.monotonic()
    nodes = 0

    def check_time():
        if time.monotonic() - started > time_limit:
            raise RefutationBudgetExceeded

    def visit(parent, target, digit, depth):
        nonlocal nodes
        nodes += 1
        check_time()
        if nodes > node_limit:
            raise RefutationBudgetExceeded
        state = parent.copy()
        state.record = True
        proof = {
            "assumption": (target, digit), "pre_dom": parent.dom.copy(),
            "pre_vals": parent.vals.copy(), "events": state.events,
            "cause": "", "children": [],
        }
        try:
            state.place(target, digit, Reason("assumption", {"cell": target, "value": digit}))
        except Contradiction as exc:
            conflict = _placement_conflict(state, exc)
        else:
            conflict = _propagate_with_cause(state, constraints)
        check_time()
        if conflict:
            proof["cause"], proof["conflict_cells"], proof["conflict_digit"], proof["visual_conflict"] = conflict
            return proof
        if state.solved:
            return None

        # Only one additional split, on a bivalue cell linked to a change
        # caused by the current assumption.
        if depth >= 1:
            raise RefutationBudgetExceeded
        narrowed = {c for c in range(state.n2) if parent.dom[c] != state.dom[c]}
        linked = set(narrowed)
        for constraint in constraints:
            cells = constraint.cells()
            if narrowed.intersection(cells):
                linked.update(cells)
        options = sorted((c for c in linked if not state.vals[c]
                          and state.dom[c].bit_count() == 2),
                         key=lambda c: (c not in narrowed, c))
        for pick in options[:8]:
            children = []
            for candidate in bits(state.dom[pick]):
                try:
                    subproof = visit(state, pick, candidate, depth + 1)
                except RefutationBudgetExceeded:
                    check_time()
                    break
                if subproof is None:
                    return None
                children.append({"value": candidate, "proof": subproof})
            if len(children) == 2:
                proof.update(branch_cell=pick, children=children)
                return proof
        raise RefutationBudgetExceeded

    try:
        proof = visit(st, cell, value, 0)
        if proof:
            _slice_refutation(proof, st.full, check_time)
    except RefutationBudgetExceeded:
        return (None, None, "")
    if proof is None:
        return (False, None, "")
    cost = proof_cost(proof)
    proof["cost"] = cost
    terminal_causes = []

    def collect_causes(node):
        if node.get("cause"):
            terminal_causes.append(node["cause"])
        for child_proof in node.get("children", ()):
            collect_causes(child_proof["proof"])

    collect_causes(proof)
    cause = terminal_causes[0] if len(terminal_causes) == 1 else (
        f"所有后续分支均矛盾（{len(terminal_causes)} 个终端矛盾）"
    )
    return (True, proof, cause)
