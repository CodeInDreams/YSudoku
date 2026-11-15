"""Variant constraints: propagation plus explainable reasons."""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations

from . import predicate as predicate_mod
from .state import Contradiction, Reason, State, bits, cell_name


def _matchable(combo: tuple[int, ...], doms: list[int]) -> bool:
    """Can every digit of ``combo`` be placed on a distinct cell of ``doms``?"""
    k = len(combo)
    full = (1 << k) - 1
    reach = {0}
    for digit in combo:
        nxt = set()
        bit = 1 << (digit - 1)
        for used in reach:
            for i in range(k):
                if not used >> i & 1 and doms[i] & bit:
                    nxt.add(used | (1 << i))
        reach = nxt
        if not reach:
            return False
    return full in reach


@lru_cache(maxsize=8192)
def digit_sets(k: int, total: int, n: int) -> tuple[tuple[int, ...], ...]:
    return tuple(c for c in combinations(range(1, n + 1), k) if sum(c) == total)


@lru_cache(maxsize=8192)
def consecutive_windows(k: int, n: int) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(range(s, s + k)) for s in range(1, n - k + 2))


def _bounds(dom: int) -> tuple[int, int]:
    return (dom & -dom).bit_length(), dom.bit_length()


class Constraint:
    kind = "constraint"
    tier = 1

    def cells(self) -> list[int]:
        return []

    def prune(self, st: State) -> bool:
        return False

    def check(self, values: list[int]) -> bool:
        return True

    def describe(self) -> str:
        return self.kind

    def to_dict(self) -> dict:
        return {"kind": self.kind}

    def check(self, values: list[int]) -> bool:
        return True


class Cage(Constraint):
    kind = "cage"

    def __init__(self, cells: list[int], total: int, unique: bool = True):
        self._cells = list(cells)
        self.total = total
        self.unique = unique

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"杀手笼 {self.total}（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "cage", "cells": self._cells, "sum": self.total}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        return sum(vals) == self.total and (not self.unique or len(set(vals)) == len(vals))

    def prune(self, st: State) -> bool:
        cells = self._cells
        k = len(cells)
        reason = Reason("cage", {"cells": cells, "sum": self.total})
        changed = False

        if not self.unique or k > 6:
            mins = [_bounds(st.dom[c])[0] for c in cells]
            maxs = [_bounds(st.dom[c])[1] for c in cells]
            total_min, total_max = sum(mins), sum(maxs)
            if self.total < total_min or self.total > total_max:
                raise Contradiction(f"cage {self.total} impossible")
            for i, c in enumerate(cells):
                rest_min = total_min - mins[i]
                rest_max = total_max - maxs[i]
                lo = max(1, self.total - rest_max)
                hi = min(st.n, self.total - rest_min)
                allow = st.full & ((1 << hi) - 1) & ~((1 << (lo - 1)) - 1)
                changed |= st.restrict(c, allow, reason)
            return changed

        combos = [c for c in digit_sets(k, self.total, st.n)]
        feasible = []
        doms = [st.dom[c] for c in cells]
        for combo in combos:
            if all(any(doms[i] >> (d - 1) & 1 for i in range(k)) for d in combo):
                if _matchable(combo, doms):
                    feasible.append(combo)
        if not feasible:
            raise Contradiction(f"cage {self.total} has no feasible combination")
        reason.data["combos"] = [list(c) for c in feasible]

        for i, cell in enumerate(cells):
            allowed = 0
            for value in bits(st.dom[cell]):
                if any(value in combo for combo in feasible):
                    probe = list(doms)
                    probe[i] = 1 << (value - 1)
                    if any(_matchable(combo, probe) for combo in feasible):
                        allowed |= 1 << (value - 1)
            changed |= st.restrict(cell, allowed, reason)
        return changed


class Thermo(Constraint):
    kind = "thermo"

    def __init__(self, cells: list[int]):
        self._cells = list(cells)

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"温度计（{len(self._cells)} 格，严格递增）"

    def to_dict(self) -> dict:
        return {"kind": "thermo", "cells": self._cells}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        return all(v == 0 for v in vals) or all(a < b for a, b in zip(vals, vals[1:]))

    def prune(self, st: State) -> bool:
        cells = self._cells
        k = len(cells)
        if k < 2:
            return False
        reason = Reason("thermo", {"cells": cells})
        changed = False
        pref = [0] * k
        suff = [0] * k
        pref[0] = st.dom[cells[0]]
        for i in range(1, k):
            allowed = 0
            for v in bits(st.dom[cells[i]]):
                lower = (1 << (v - 1)) - 1
                if pref[i - 1] & lower:
                    allowed |= 1 << (v - 1)
            pref[i] = allowed
        suff[k - 1] = st.dom[cells[k - 1]]
        for i in range(k - 2, -1, -1):
            allowed = 0
            for v in bits(st.dom[cells[i]]):
                higher = st.full & ~((1 << v) - 1)
                if suff[i + 1] & higher:
                    allowed |= 1 << (v - 1)
            suff[i] = allowed
        for i, cell in enumerate(cells):
            changed |= st.restrict(cell, pref[i] & suff[i], reason)
        return changed


class Arrow(Constraint):
    kind = "arrow"

    def __init__(self, circle: int, arm: list[int]):
        self.circle = circle
        self.arm = list(arm)

    def cells(self) -> list[int]:
        return [self.circle] + self.arm

    def describe(self) -> str:
        return f"箭头（圈 R{self.circle // 9 + 1}C{self.circle % 9 + 1} = 箭身之和）"

    def to_dict(self) -> dict:
        return {"kind": "arrow", "circle": self.circle, "arm": self.arm}

    def check(self, values: list[int]) -> bool:
        if values[self.circle] == 0:
            return True
        return values[self.circle] == sum(values[c] for c in self.arm)

    def prune(self, st: State) -> bool:
        reason = Reason("arrow", {"circle": self.circle, "arm": self.arm})
        changed = False
        reach = {0}
        for cell in self.arm:
            reach = {s + v for s in reach for v in bits(st.dom[cell])}
        circle_mask = st.dom[self.circle]
        reachable = {s for s in reach if circle_mask >> (s - 1) & 1}
        if not reachable:
            raise Contradiction("arrow has no feasible sum")
        keep = 0
        for s in reachable:
            keep |= 1 << (s - 1)
        changed |= st.restrict(self.circle, keep, reason)

        for i, cell in enumerate(self.arm):
            others = self.arm[:i] + self.arm[i + 1:]
            other_sums = {0}
            for other in others:
                other_sums = {s + v for s in other_sums for v in bits(st.dom[other])}
            allowed = 0
            for v in bits(st.dom[cell]):
                if any(
                    (v + s) in possible
                    for s in other_sums
                    for possible in [{x for x in reachable}]
                ):
                    allowed |= 1 << (v - 1)
            changed |= st.restrict(cell, allowed, reason)
        return changed


class PairRule(Constraint):
    """Generic binary rule: every value of one cell needs a partner."""

    kind = "pair"

    def __init__(self, a: int, b: int, kind: str, ok, label: str, **params):
        self.a = a
        self.b = b
        self._kind = kind
        self.ok = ok
        self.label = label
        self.params = params

    def cells(self) -> list[int]:
        return [self.a, self.b]

    def describe(self) -> str:
        return self.label

    def to_dict(self) -> dict:
        return {"kind": self._kind, "a": self.a, "b": self.b, **self.params}

    def check(self, values: list[int]) -> bool:
        if values[self.a] == 0 or values[self.b] == 0:
            return True
        return self.ok(values[self.a], values[self.b])

    def prune(self, st: State) -> bool:
        reason = Reason(self._kind, {"a": self.a, "b": self.b, **self.params})
        changed = False
        for cell, other in ((self.a, self.b), (self.b, self.a)):
            for value in bits(st.dom[cell]):
                if not any(self.ok(value, w) for w in bits(st.dom[other])):
                    changed |= st.elim(cell, value, reason)
        return changed


class Quadruple(Constraint):
    kind = "quadruple"

    def __init__(self, cells: list[int], digits: list[int]):
        self._cells = list(cells)
        self.digits = list(digits)

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"四格提示 {''.join(map(str, self.digits))}"

    def to_dict(self) -> dict:
        return {"kind": "quadruple", "cells": self._cells, "digits": self.digits}

    def check(self, values: list[int]) -> bool:
        present = [values[c] for c in self._cells]
        if any(v == 0 for v in present):
            return True
        remaining = list(present)
        for digit in self.digits:
            if digit in remaining:
                remaining.remove(digit)
            else:
                return False
        return True

    def prune(self, st: State) -> bool:
        reason = Reason("quadruple", {"cells": self._cells, "digits": self.digits})
        changed = False
        needs = list(self.digits)

        def coverable(probe: list[int] | None = None) -> bool:
            doms = probe or [st.dom[c] for c in self._cells]
            reach = {0}
            for digit in needs:
                nxt = set()
                for used in reach:
                    for i, dom in enumerate(doms):
                        if not used >> i & 1 and dom >> (digit - 1) & 1:
                            nxt.add(used | (1 << i))
                if not nxt:
                    return False
                reach = nxt
            return bool(reach)

        if not coverable():
            raise Contradiction("quadruple cannot be covered")

        for i, cell in enumerate(self._cells):
            for value in bits(st.dom[cell]):
                probe = [st.dom[c] for c in self._cells]
                probe[i] = 1 << (value - 1)
                if not coverable(probe):
                    changed |= st.elim(cell, value, reason)

        # A required digit with a single possible host must go there.
        for digit in set(needs):
            hosts = [c for c in self._cells if st.has(c, digit)]
            if len(hosts) == 1 and self.digits.count(digit) == 1:
                changed |= st.place(hosts[0], digit, reason)
        return changed


class Palindrome(Constraint):
    kind = "palindrome"

    def __init__(self, cells: list[int]):
        self._cells = list(cells)

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"回文线（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "palindrome", "cells": self._cells}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        return all(vals[i] == vals[-1 - i] for i in range(len(vals) // 2))

    def prune(self, st: State) -> bool:
        reason = Reason("palindrome", {"cells": self._cells})
        changed = False
        k = len(self._cells)
        for i in range(k // 2):
            a, b = self._cells[i], self._cells[k - 1 - i]
            keep = st.dom[a] & st.dom[b]
            changed |= st.restrict(a, keep, reason)
            changed |= st.restrict(b, keep, reason)
        return changed


class Renban(Constraint):
    kind = "renban"

    def __init__(self, cells: list[int]):
        self._cells = list(cells)

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"Renban（{len(self._cells)} 格连续数）"

    def to_dict(self) -> dict:
        return {"kind": "renban", "cells": self._cells}

    def check(self, values: list[int]) -> bool:
        vals = sorted(values[c] for c in self._cells)
        if any(v == 0 for v in vals):
            return True
        return all(b == a + 1 for a, b in zip(vals, vals[1:]))

    def prune(self, st: State) -> bool:
        k = len(self._cells)
        reason = Reason("renban", {"cells": self._cells})
        doms = [st.dom[c] for c in self._cells]
        windows = [w for w in consecutive_windows(k, st.n) if _matchable(w, doms)]
        if not windows:
            raise Contradiction("renban has no feasible window")
        changed = False
        for i, cell in enumerate(self._cells):
            allowed = 0
            for value in bits(st.dom[cell]):
                if not any(value in w for w in windows):
                    continue
                probe = list(doms)
                probe[i] = 1 << (value - 1)
                if any(_matchable(w, probe) for w in windows):
                    allowed |= 1 << (value - 1)
            changed |= st.restrict(cell, allowed, reason)
        return changed


class Between(Constraint):
    kind = "between"

    def __init__(self, cells: list[int]):
        self._cells = list(cells)

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"之间线（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "between", "cells": self._cells}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        a, b = vals[0], vals[-1]
        lo, hi = min(a, b), max(a, b)
        return all(lo < v < hi for v in vals[1:-1])

    def prune(self, st: State) -> bool:
        if len(self._cells) < 3:
            return False
        reason = Reason("between", {"cells": self._cells})
        changed = False
        a, b = self._cells[0], self._cells[-1]
        for cell in self._cells[1:-1]:
            for value in bits(st.dom[cell]):
                ok = any(
                    (x < value < y) or (y < value < x)
                    for x in bits(st.dom[a])
                    for y in bits(st.dom[b])
                )
                if not ok:
                    changed |= st.elim(cell, value, reason)
        return changed


class SumLine(Constraint):
    """Little-killer style: a set of cells has a fixed sum."""

    kind = "sum_line"

    def __init__(self, cells: list[int], total: int):
        self._cells = list(cells)
        self.total = total

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"小杀手 {self.total}（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "little_killer", "cells": self._cells, "sum": self.total}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        return sum(vals) == self.total

    def prune(self, st: State) -> bool:
        reason = Reason("little_killer", {"cells": self._cells, "sum": self.total})
        changed = False
        cells = self._cells

        reach = {0}
        for cell in cells:
            reach = {s + v for s in reach for v in bits(st.dom[cell])}
        if self.total not in reach:
            raise Contradiction(f"sum line {self.total} impossible")

        for i, cell in enumerate(cells):
            others = cells[:i] + cells[i + 1:]
            other_sums = {0}
            for other in others:
                other_sums = {s + v for s in other_sums for v in bits(st.dom[other])}
            allowed = 0
            for v in bits(st.dom[cell]):
                if (self.total - v) in other_sums:
                    allowed |= 1 << (v - 1)
            changed |= st.restrict(cell, allowed, reason)
        return changed


class Custom(Constraint):
    """L2 rule: a typed predicate over a small scope of cells."""

    kind = "custom"

    def __init__(self, scope: list[int], node, cite: str = "", hypothesis: bool = False):
        self._scope = list(scope)
        self.node = node
        self.cite = cite
        self.hypothesis = hypothesis

    def cells(self) -> list[int]:
        return self._scope

    def describe(self) -> str:
        label = self.cite or "自定义规则"
        return f"自定义规则（{label}）"

    def to_dict(self) -> dict:
        return {
            "kind": "custom",
            "cells": self._scope,
            "predicate": self.node.to_json(),
            "cite": self.cite,
            "hypothesis": self.hypothesis,
        }

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._scope]
        if any(v == 0 for v in vals):
            return True
        return predicate_mod.evaluate(self.node, vals)

    def prune(self, st: State) -> bool:
        domains = [st.dom[c] for c in self._scope]
        supported = predicate_mod.prune_by_enumeration(domains, self.node)
        if supported is None:
            return False
        if any(mask == 0 for mask in supported):
            raise Contradiction(f"custom rule {self.cite or ''} has no support")
        reason = Reason("custom", {
            "scope": self._scope,
            "cite": self.cite,
            "predicate": self.node.to_json(),
            "hypothesis": self.hypothesis,
        })
        changed = False
        for cell, mask in zip(self._scope, supported):
            changed |= st.restrict(cell, mask, reason)
        return changed


class AntiPair(Constraint):
    kind = "anti"

    def __init__(self, a: int, b: int, kind: str, label: str):
        self.a = a
        self.b = b
        self._kind = kind
        self.label = label

    def cells(self) -> list[int]:
        return [self.a, self.b]

    def describe(self) -> str:
        return self.label

    def to_dict(self) -> dict:
        return {"kind": self._kind, "a": self.a, "b": self.b}

    def check(self, values: list[int]) -> bool:
        if values[self.a] == 0 or values[self.b] == 0:
            return True
        return values[self.a] != values[self.b]

    def prune(self, st: State) -> bool:
        if st.vals[self.a]:
            return st.elim(self.b, st.vals[self.a], Reason(self._kind, {"a": self.a, "b": self.b}))
        if st.vals[self.b]:
            return st.elim(self.a, st.vals[self.b], Reason(self._kind, {"a": self.a, "b": self.b}))
        return False
