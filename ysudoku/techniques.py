"""Human-style solving techniques, layered by difficulty."""

from __future__ import annotations

from itertools import combinations

from .constraints import Cage
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


TECHNIQUES = [
    ("naked_single", 1, naked_single),
    ("hidden_single", 1, hidden_single),
    ("forty_five", 2, forty_five),
    ("hidden_subset", 2, hidden_subset),
    ("locked", 2, locked_candidates),
    ("subset", 2, naked_subset),
    ("x_wing", 3, x_wing),
    ("xy_wing", 3, xy_wing),
    ("w_wing", 3, w_wing),
    ("forcing_chain", 4, forcing_chain),
]
