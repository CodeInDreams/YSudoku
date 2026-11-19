"""Human-style solving techniques, layered by difficulty."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from .constraints import Cage

PALETTE = [
    ("#ef4444", "#3b82f6"),
    ("#22c55e", "#f59e0b"),
    ("#a855f7", "#14b8a6"),
    ("#ec4899", "#84cc16"),
    ("#f97316", "#6366f1"),
    ("#06b6d4", "#eab308"),
]
from .state import Reason, State, bits


def _wrap(st: State):
    events = st.end()
    return events or None


# ------------------------------------------------------------------ tier 1


def forty_five(st: State, constraints=None):
    """Innie/outie: a unit is covered by complete cages plus a few leftover cells."""
    if not constraints:
        return None
    n = st.n
    cage_of = {}
    for con in constraints:
        if isinstance(con, Cage) and con.total is not None:
            for cell in con.cells():
                cage_of[cell] = con
    full = n * (n + 1) // 2
    st.begin()
    for unit in st.units:
        if unit.kind == "diagonal":
            continue
        cells = set(unit.cells)
        used: set[int] = set()
        total = 0
        partial = False
        seen: set[int] = set()
        for cell in unit.cells:
            con = cage_of.get(cell)
            if con is None or id(con) in seen:
                continue
            seen.add(id(con))
            if set(con.cells()) <= cells:
                used |= set(con.cells())
                total += con.total
            else:
                partial = True
                break
        if partial:
            continue
        leftover = [c for c in unit.cells if c not in used]
        target = full - total
        if len(leftover) == 1:
            cell = leftover[0]
            if st.vals[cell] or not (1 <= target <= n):
                continue
            st.place(cell, target, Reason("innie", {
                "cell": cell, "value": target, "unit": unit.label,
                "unit_kind": unit.kind, "unit_cells": unit.cells,
                "cages": [c.describe() for c in
                          {(id(cage_of[x])): cage_of[x] for x in unit.cells if x in cage_of}.values()
                          if c.total is not None],
                "sum": total, "leftover": leftover,
            }))
            return _wrap(st)
        if len(leftover) == 2:
            a, b = leftover
            if st.vals[a] and st.vals[b]:
                continue
            reason = Reason("outie", {
                "cells": leftover, "sum": target, "unit": unit.label,
                "unit_kind": unit.kind, "unit_cells": unit.cells,
                "cages": [c.describe() for c in
                          {(id(cage_of[x])): cage_of[x] for x in unit.cells if x in cage_of}.values()
                          if c.total is not None],
                "covered": total,
            })
            made = False
            if st.vals[a]:
                made |= st.place(b, target - st.vals[a], reason)
            elif st.vals[b]:
                made |= st.place(a, target - st.vals[b], reason)
            else:
                for x in bits(st.dom[a]):
                    if target - x == x or not st.has(b, target - x):
                        made |= st.elim(a, x, reason)
                for y in bits(st.dom[b]):
                    if target - y == y or not st.has(a, target - y):
                        made |= st.elim(b, y, reason)
            if made:
                return _wrap(st)
    return _wrap(st)


def naked_single(st: State, constraints=None):
    st.begin()
    for cell in range(st.n2):
        if st.vals[cell] == 0 and st.dom[cell].bit_count() == 1:
            value = st.dom[cell].bit_length()
            st.place(cell, value, Reason("naked_single", {"cell": cell, "value": value}))
            return _wrap(st)
    return _wrap(st)


def hidden_single(st: State, constraints=None):
    st.begin()
    for unit in st.units:
        for digit in range(1, st.n + 1):
            hosts = [c for c in unit.cells if st.has(c, digit)]
            if len(hosts) != 1:
                continue
            cell = hosts[0]
            if st.vals[cell] == digit:
                continue
            if st.vals[cell]:
                continue
            st.place(
                cell,
                digit,
                Reason(
                    "hidden_single",
                    {
                        "cell": cell,
                        "value": digit,
                        "unit": unit.label,
                        "unit_kind": unit.kind,
                        "unit_cells": unit.cells,
                    },
                ),
            )
            return _wrap(st)
    return _wrap(st)


# ------------------------------------------------------------------ tier 2


def locked_candidates(st: State, constraints=None):
    st.begin()
    n = st.n
    for unit in st.units:
        if unit.kind not in ("region", "row", "col"):
            continue
        for digit in range(1, n + 1):
            hosts = [c for c in unit.cells if st.has(c, digit)]
            if len(hosts) < 2:
                continue
            rows = {c // n for c in hosts}
            cols = {c % n for c in hosts}
            if unit.kind == "region":
                if len(rows) == 1:
                    r = rows.pop()
                    outside = [r * n + c for c in range(n) if r * n + c not in unit.cells]
                    made = any(
                        st.elim(c, digit, Reason("locked", {
                            "digit": digit, "unit": unit.label, "unit_kind": unit.kind,
                            "unit_cells": unit.cells, "target": "row", "index": r,
                            "cells": hosts,
                        }))
                        for c in outside
                    )
                    if made:
                        return _wrap(st)
                if len(cols) == 1:
                    c = cols.pop()
                    outside = [r * n + c for r in range(n) if r * n + c not in unit.cells]
                    made = any(
                        st.elim(cell, digit, Reason("locked", {
                            "digit": digit, "unit": unit.label, "unit_kind": unit.kind,
                            "unit_cells": unit.cells, "target": "col", "index": c,
                            "cells": hosts,
                        }))
                        for cell in outside
                    )
                    if made:
                        return _wrap(st)
            else:  # row/col claiming
                regions = [u for u in st.units if u.kind == "region" and any(c in u.cells for c in hosts)]
                for region in regions:
                    if all(c in region.cells for c in hosts):
                        outside = [c for c in region.cells if c not in unit.cells]
                        made = any(
                            st.elim(c, digit, Reason("locked", {
                                "digit": digit, "unit": unit.label, "unit_kind": unit.kind,
                                "unit_cells": unit.cells, "target": "region",
                                "cells": hosts, "region_cells": region.cells,
                            }))
                            for c in outside
                        )
                        if made:
                            return _wrap(st)
    return _wrap(st)


def naked_subset(st: State, constraints=None, max_size: int = 3):
    st.begin()
    for unit in st.units:
        candidates = [c for c in unit.cells if st.vals[c] == 0 and 2 <= st.dom[c].bit_count() <= max_size]
        for size in range(2, max_size + 1):
            for combo in combinations(candidates, size):
                mask = 0
                for c in combo:
                    mask |= st.dom[c]
                if mask.bit_count() != size:
                    continue
                others = [c for c in unit.cells if c not in combo and st.vals[c] == 0]
                reason = Reason("subset", {
                    "cells": list(combo), "digits": list(bits(mask)),
                    "unit": unit.label, "unit_kind": unit.kind, "unit_cells": unit.cells,
                })
                made = False
                for other in others:
                    for value in bits(mask):
                        if st.has(other, value):
                            st.elim(other, value, reason)
                            made = True
                if made:
                    return _wrap(st)
    return _wrap(st)


def hidden_subset(st: State, constraints=None, max_size: int = 2):
    st.begin()
    for unit in st.units:
        positions = {}
        for digit in range(1, st.n + 1):
            hosts = [c for c in unit.cells if st.has(c, digit)]
            if 2 <= len(hosts) <= max_size:
                positions[digit] = hosts
        digits = list(positions)
        for size in range(2, max_size + 1):
            for combo in combinations(digits, size):
                cells = set()
                for d in combo:
                    cells.update(positions[d])
                if len(cells) != size:
                    continue
                mask = sum(1 << (d - 1) for d in combo)
                reason = Reason("hidden_subset", {
                    "cells": sorted(cells), "digits": list(combo),
                    "unit": unit.label, "unit_kind": unit.kind, "unit_cells": unit.cells,
                })
                made = False
                for c in cells:
                    if st.dom[c] != mask:
                        st.restrict(c, mask, reason)
                        made = True
                if made:
                    return _wrap(st)
    return _wrap(st)


# ------------------------------------------------------------------ tier 3


def x_wing(st: State, constraints=None):
    st.begin()
    n = st.n
    for digit in range(1, n + 1):
        by_row = {}
        for r in range(n):
            cols = [c for c in range(n) if st.has(r * n + c, digit)]
            if len(cols) == 2:
                by_row[r] = cols
        for r1, r2 in combinations(by_row, 2):
            if by_row[r1] != by_row[r2]:
                continue
            c1, c2 = by_row[r1]
            reason = Reason("xwing", {
                "digit": digit, "cells": [r1 * n + c1, r1 * n + c2, r2 * n + c1, r2 * n + c2],
                "rows": [r1, r2], "cols": [c1, c2], "orientation": "row",
            })
            made = False
            for r in range(n):
                if r in (r1, r2):
                    continue
                for c in (c1, c2):
                    if st.has(r * n + c, digit):
                        st.elim(r * n + c, digit, reason)
                        made = True
            if made:
                return _wrap(st)
        by_col = {}
        for c in range(n):
            rows = [r for r in range(n) if st.has(r * n + c, digit)]
            if len(rows) == 2:
                by_col[c] = rows
        for c1, c2 in combinations(by_col, 2):
            if by_col[c1] != by_col[c2]:
                continue
            r1, r2 = by_col[c1]
            reason = Reason("xwing", {
                "digit": digit, "cells": [r1 * n + c1, r1 * n + c2, r2 * n + c1, r2 * n + c2],
                "rows": [r1, r2], "cols": [c1, c2], "orientation": "col",
            })
            made = False
            for c in range(n):
                if c in (c1, c2):
                    continue
                for r in (r1, r2):
                    if st.has(r * n + c, digit):
                        st.elim(r * n + c, digit, reason)
                        made = True
            if made:
                return _wrap(st)
    return _wrap(st)


def xy_wing(st: State, constraints=None):
    st.begin()
    for pivot in range(st.n2):
        if st.vals[pivot] or st.dom[pivot].bit_count() != 2:
            continue
        a, b = bits(st.dom[pivot])
        for wing1 in st.peers[pivot]:
            if st.vals[wing1]:
                continue
            d1 = st.dom[wing1]
            if d1.bit_count() != 2 or not d1 & (1 << (a - 1)) or d1 & (1 << (b - 1)):
                continue
            c = (d1 & ~(1 << (a - 1))).bit_length()
            for wing2 in st.peers[pivot]:
                if wing2 == wing1 or st.vals[wing2]:
                    continue
                d2 = st.dom[wing2]
                if d2.bit_count() != 2 or not d2 & (1 << (b - 1)) or d2 & (1 << (a - 1)):
                    continue
                if not d2 & (1 << (c - 1)):
                    continue
                reason = Reason("xy_wing", {
                    "pivot": pivot, "wings": [wing1, wing2], "digits": [a, b, c],
                })
                made = False
                targets = (set(st.peers[wing1]) & set(st.peers[wing2])) - {pivot, wing1, wing2}
                for cell in targets:
                    if st.has(cell, c):
                        st.elim(cell, c, reason)
                        made = True
                if made:
                    return _wrap(st)
    return _wrap(st)


def w_wing(st: State, constraints=None):
    st.begin()
    pairs = {}
    for cell in range(st.n2):
        if st.vals[cell] == 0 and st.dom[cell].bit_count() == 2:
            pairs.setdefault(st.dom[cell], []).append(cell)
    links = {}
    for unit in st.units:
        for digit in range(1, st.n + 1):
            hosts = [c for c in unit.cells if st.has(c, digit)]
            if len(hosts) == 2:
                links.setdefault(digit, []).append(tuple(hosts))
    for mask, cells in pairs.items():
        if len(cells) < 2:
            continue
        a, b = bits(mask)
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                x, y = cells[i], cells[j]
                for digit, other in ((a, b), (b, a)):
                    for p, q in links.get(digit, []):
                        if (p in st.peers[x] and q in st.peers[y]) or (
                            q in st.peers[x] and p in st.peers[y]
                        ):
                            reason = Reason("w_wing", {
                                "cells": [x, y], "link": [p, q], "digits": [digit, other],
                            })
                            made = False
                            for cell in (set(st.peers[x]) & set(st.peers[y])) - {x, y}:
                                if st.has(cell, other):
                                    st.elim(cell, other, reason)
                                    made = True
                            if made:
                                return _wrap(st)
    return _wrap(st)


def forcing_chain(st: State, constraints=None):
    """T4: assume a candidate and refute it by propagation (labelled as 反证)."""
    if not constraints:
        return None
    from .search import propagate

    st.begin()
    order = sorted(
        (c for c in range(st.n2) if st.vals[c] == 0),
        key=lambda c: st.dom[c].bit_count(),
    )
    probes = 0
    for cell in order[:24]:
        if st.dom[cell].bit_count() > 3:
            continue
        for value in bits(st.dom[cell]):
            probes += 1
            if probes > 120:
                return _wrap(st)
            child = st.copy()
            child.record = True
            child.events = []
            try:
                child.place(cell, value, Reason("assumption", {"cell": cell, "value": value}))
                ok = propagate(child, constraints)
            except Contradiction:
                ok = False
            if ok:
                continue
            trace = [
                {
                    "kind": e.kind,
                    "cell": e.cell,
                    "value": e.value,
                    "reason": e.reason.kind,
                }
                for e in child.events
                if e.reason.kind != "assumption"
            ][-6:]
            reason = Reason("forcing_chain", {
                "cell": cell,
                "value": value,
                "trace": trace,
                "steps": max(0, len(child.events) - 1),
            })
            st.elim(cell, value, reason)
            return _wrap(st)
    return _wrap(st)


def coloring(st: State, constraints=None):
    """Single-digit simple coloring: strong links -> two colours -> wrap/trap."""
    st.begin()
    for digit in range(1, st.n + 1):
        links: list[tuple[int, int]] = []
        for unit in st.units:
            hosts = [c for c in unit.cells if st.has(c, digit)]
            if len(hosts) == 2:
                links.append((hosts[0], hosts[1]))
        if not links:
            continue
        adj: dict[int, set[int]] = {}
        for a, b in links:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        color: dict[int, int] = {}
        components: list[list[int]] = []
        for start in adj:
            if start in color:
                continue
            color[start] = 0
            stack = [start]
            comp: list[int] = []
            while stack:
                cell = stack.pop()
                comp.append(cell)
                for other in adj[cell]:
                    if other not in color:
                        color[other] = 1 - color[cell]
                        stack.append(other)
            components.append(comp)
        for comp_index, comp in enumerate(components):
            comp_set = set(comp)
            comp_links = [(a, b) for a, b in links if a in comp_set and b in comp_set]
            groups = {0: [c for c in comp if color[c] == 0],
                      1: [c for c in comp if color[c] == 1]}
            # colour wrap: two same-colour cells see each other -> that colour is false
            for tone in (0, 1):
                cells = groups[tone]
                conflict = any(
                    b in st.peers[a]
                    for i, a in enumerate(cells)
                    for b in cells[i + 1:]
                )
                if not conflict:
                    continue
                reason = Reason("coloring", {
                    "digit": digit, "mode": "wrap", "color": tone,
                    "cells": cells, "links": comp_links,
                    "colors": {str(c): color[c] for c in comp},
                    "component": comp_index,
                    "palette": [list(p) for p in PALETTE],
                    "labels": [chr(ord("A") + i) for i in range(2 * len(PALETTE))],
                })
                made = False
                for cell in cells:
                    made |= st.elim(cell, digit, reason)
                if made:
                    return _wrap(st)
            # colour trap: a cell seeing both colours cannot hold the digit
            for cell in range(st.n2):
                if cell in comp_set or not st.has(cell, digit):
                    continue
                sees0 = any(c in st.peers[cell] for c in groups[0])
                sees1 = any(c in st.peers[cell] for c in groups[1])
                if sees0 and sees1:
                    reason = Reason("coloring", {
                        "digit": digit, "mode": "trap", "color": None,
                        "cells": [cell], "links": comp_links,
                        "colors": {str(c): color[c] for c in comp},
                        "component": comp_index,
                        "palette": [list(p) for p in PALETTE],
                        "labels": [chr(ord("A") + i) for i in range(2 * len(PALETTE))],
                    })
                    st.elim(cell, digit, reason)
                    return _wrap(st)
    return _wrap(st)


def medusa(st: State, constraints=None):
    """3D Medusa: colour candidates, not just one digit."""
    st.begin()
    nodes: list[tuple[int, int]] = []
    for cell in range(st.n2):
        if st.vals[cell]:
            continue
        for digit in bits(st.dom[cell]):
            nodes.append((cell, digit))
    if not nodes:
        return _wrap(st)
    node_set = set(nodes)
    strong: dict[tuple[int, int], set] = defaultdict(set)
    weak: dict[tuple[int, int], set] = defaultdict(set)

    for cell in range(st.n2):
        if st.vals[cell]:
            continue
        digits = list(bits(st.dom[cell]))
        for i in range(len(digits)):
            for j in range(i + 1, len(digits)):
                a, b = (cell, digits[i]), (cell, digits[j])
                weak[a].add(b)
                weak[b].add(a)
        if len(digits) == 2:
            a, b = (cell, digits[0]), (cell, digits[1])
            strong[a].add(b)
            strong[b].add(a)

    for unit in st.units:
        for digit in range(1, st.n + 1):
            hosts = [c for c in unit.cells if st.has(c, digit)]
            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    a, b = (hosts[i], digit), (hosts[j], digit)
                    weak[a].add(b)
                    weak[b].add(a)
            if len(hosts) == 2:
                a, b = (hosts[0], digit), (hosts[1], digit)
                strong[a].add(b)
                strong[b].add(a)

    color: dict[tuple[int, int], int] = {}
    components: list[list[tuple[int, int]]] = []
    for start in strong:
        if start in color:
            continue
        color[start] = 0
        stack = [start]
        comp = []
        while stack:
            node = stack.pop()
            comp.append(node)
            for other in strong[node]:
                if other not in color:
                    color[other] = 1 - color[node]
                    stack.append(other)
        components.append(comp)

    for comp_index, comp in enumerate(components):
        comp_set = set(comp)
        if any(color[b] == color[a] for a in comp for b in strong[a] if b in comp_set):
            continue  # odd strong-link cycle: colouring inconsistent, skip safely

        links = [(a, b) for a in comp for b in strong[a] if a < b]
        groups = {0: [n for n in comp if color[n] == 0],
                  1: [n for n in comp if color[n] == 1]}

        # 1. same-colour weak link -> the colour is impossible
        for tone in (0, 1):
            conflict = None
            for a in groups[tone]:
                for b in weak.get(a, ()):  # type: ignore[arg-type]
                    if b in comp_set and color[b] == tone:
                        conflict = (a, b)
                        break
                if conflict:
                    break
            if not conflict:
                continue
            reason = Reason("medusa", {
                "mode": "wrap", "color": tone,
                "cells": [n[0] for n in groups[tone]],
                "nodes": [list(n) for n in groups[tone]],
                "links": [[a[0], a[1], b[0], b[1]] for a, b in links],
                "colors": {f"{c}:{d}": color[(c, d)] for c, d in comp},
                "component": comp_index,
                "palette": [list(p) for p in PALETTE],
                "labels": [chr(ord("A") + i) for i in range(2 * len(PALETTE))],
            })
            made = False
            for cell, digit in groups[tone]:
                made |= st.elim(cell, digit, reason)
            if made:
                return _wrap(st)

        # 2. a candidate seeing both colours
        for cell, digit in nodes:
            node = (cell, digit)
            if node in comp_set:
                continue
            sees = {color[other] for other in weak.get(node, ()) if other in comp_set}
            if sees == {0, 1}:
                reason = Reason("medusa", {
                    "mode": "trap", "cells": [cell], "nodes": [list(node)],
                    "links": [[a[0], a[1], b[0], b[1]] for a, b in links],
                    "colors": {f"{c}:{d}": color[(c, d)] for c, d in comp},
                    "component": comp_index,
                    "palette": [list(p) for p in PALETTE],
                    "labels": [chr(ord("A") + i) for i in range(2 * len(PALETTE))],
                })
                st.elim(cell, digit, reason)
                return _wrap(st)

        # 3. a cell holding both colours: any third candidate is false
        tones_by_cell: dict[int, set[int]] = defaultdict(set)
        for cell, _digit in comp:
            tones_by_cell[cell].add(color[(cell, _digit)])
        for cell, tones in tones_by_cell.items():
            if tones != {0, 1}:
                continue
            keep = {d for c, d in comp if c == cell}
            reason = Reason("medusa", {
                "mode": "cell", "cells": [cell],
                "nodes": [[cell, d] for d in keep],
                "links": [[a[0], a[1], b[0], b[1]] for a, b in links],
                "colors": {f"{c}:{d}": color[(c, d)] for c, d in comp},
                "component": comp_index,
                "palette": [list(p) for p in PALETTE],
                "labels": [chr(ord("A") + i) for i in range(2 * len(PALETTE))],
            })
            made = False
            for digit in bits(st.dom[cell]):
                if digit not in keep:
                    made |= st.elim(cell, digit, reason)
            if made:
                return _wrap(st)
    return _wrap(st)


def x_chain(st: State, constraints=None):
    """Single-digit alternating strong/weak chain; ends see a common target."""
    st.begin()
    budget = [6000]
    for digit in range(1, st.n + 1):
        hosts = {c for c in range(st.n2) if st.has(c, digit)}
        if len(hosts) < 4:
            continue
        strong: dict[int, set[int]] = defaultdict(set)
        for unit in st.units:
            members = [c for c in unit.cells if c in hosts]
            if len(members) == 2:
                strong[members[0]].add(members[1])
                strong[members[1]].add(members[0])
        if not strong:
            continue
        weak: dict[int, set[int]] = defaultdict(set)
        for a in hosts:
            for b in st.peers[a]:
                if b in hosts:
                    weak[a].add(b)

        def walk(start: int):
            found = []

            def dfs(node: int, need_strong: bool, path: list[int]):
                budget[0] -= 1
                if budget[0] < 0:
                    return
                if len(path) > 8:
                    return
                edges = strong[node] if need_strong else weak[node]
                for nxt in edges:
                    if nxt in path:
                        continue
                    new_path = path + [nxt]
                    if need_strong and len(new_path) >= 4:
                        found.append((start, nxt, new_path))
                    dfs(nxt, not need_strong, new_path)
                    if budget[0] < 0:
                        return

            dfs(start, True, [start])
            return found

        for start in sorted(hosts):
            for a, b, path in walk(start):
                if budget[0] < 0:
                    return _wrap(st)
                targets = (set(st.peers[a]) & set(st.peers[b])) - set(path)
                for cell in targets:
                    if st.has(cell, digit):
                        reason = Reason("x_chain", {
                            "digit": digit, "cells": path, "ends": [a, b],
                            "target": cell,
                        })
                        st.elim(cell, digit, reason)
                        return _wrap(st)
    return _wrap(st)


def als(st: State, constraints=None):
    """ALS-XZ: two almost-locked sets with a restricted common and a shared Z."""
    st.begin()
    als_list: list[tuple[tuple[int, ...], int]] = []
    seen: set[frozenset[int]] = set()
    for unit in st.units:
        candidates = [c for c in unit.cells if st.vals[c] == 0]
        if len(candidates) < 2:
            continue
        for k in (2, 3):
            for combo in combinations(candidates, k):
                key = frozenset(combo)
                if key in seen:
                    continue
                union = 0
                for cell in combo:
                    union |= st.dom[cell]
                if union.bit_count() != k + 1:
                    continue
                seen.add(key)
                als_list.append((combo, union))
    if len(als_list) > 500:
        als_list = als_list[:500]

    for i in range(len(als_list)):
        a1, u1 = als_list[i]
        set1 = set(a1)
        for j in range(i + 1, len(als_list)):
            a2, u2 = als_list[j]
            if set1 & set(a2):
                continue
            common = u1 & u2
            if common.bit_count() < 2:
                continue
            for x in bits(common):
                cells1x = [c for c in a1 if st.has(c, x)]
                cells2x = [c for c in a2 if st.has(c, x)]
                if not cells1x or not cells2x:
                    continue
                if not all(b in st.peers[a] for a in cells1x for b in cells2x):
                    continue
                for z in bits(common):
                    if z == x:
                        continue
                    cells1z = [c for c in a1 if st.has(c, z)]
                    cells2z = [c for c in a2 if st.has(c, z)]
                    if not cells1z or not cells2z:
                        continue
                    inside = set1 | set(a2)
                    for cell in range(st.n2):
                        if cell in inside or not st.has(cell, z):
                            continue
                        if all(cell in st.peers[p] for p in cells1z + cells2z):
                            reason = Reason("als", {
                                "als1": list(a1), "als2": list(a2),
                                "x": x, "z": z, "target": cell,
                            })
                            st.elim(cell, z, reason)
                            return _wrap(st)
    return _wrap(st)


def _bivalue_cells(st):
    return [c for c in range(st.n2) if st.vals[c] == 0 and st.dom[c].bit_count() == 2]


def _trigger_bivalue(st):
    return bool(_bivalue_cells(st))


def _trigger_two_bivalue(st):
    return len(_bivalue_cells(st)) >= 2


def _trigger_strong_link(st):
    for unit in st.units:
        for digit in range(1, st.n + 1):
            if sum(1 for c in unit.cells if st.has(c, digit)) == 2:
                return True
    return False


def _trigger_x_wing(st):
    for digit in range(1, st.n + 1):
        rows = sum(1 for r in range(st.n)
                   if sum(1 for c in range(st.n) if st.has(r * st.n + c, digit)) == 2)
        cols = sum(1 for c in range(st.n)
                   if sum(1 for r in range(st.n) if st.has(r * st.n + c, digit)) == 2)
        if rows >= 2 or cols >= 2:
            return True
    return False


def _trigger_small_domain(st):
    return any(st.vals[c] == 0 and st.dom[c].bit_count() <= 3 for c in range(st.n2))


TRIGGERS = {
    "x_wing": _trigger_x_wing,
    "xy_wing": _trigger_bivalue,
    "w_wing": _trigger_two_bivalue,
    "coloring": _trigger_strong_link,
    "medusa": _trigger_strong_link,
    "x_chain": _trigger_strong_link,
    "als": _trigger_bivalue,
    "forcing_chain": _trigger_small_domain,
}


def naked_subset4(st: State, constraints=None):
    return naked_subset(st, constraints, max_size=4)


def hidden_subset4(st: State, constraints=None):
    return hidden_subset(st, constraints, max_size=4)


TECHNIQUES = [
    ("naked_single", 1, naked_single),
    ("hidden_single", 1, hidden_single),
    ("forty_five", 2, forty_five),
    ("hidden_subset", 2, hidden_subset4),
    ("locked", 2, locked_candidates),
    ("subset", 2, naked_subset4),
    ("x_wing", 3, x_wing),
    ("xy_wing", 3, xy_wing),
    ("w_wing", 3, w_wing),
    ("coloring", 3, coloring),
    ("medusa", 3, medusa),
    ("x_chain", 3, x_chain),
    ("als", 3, als),
    ("forcing_chain", 4, forcing_chain),
]
