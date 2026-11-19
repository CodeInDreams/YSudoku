"""Variant constraints: propagation plus explainable reasons."""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations, product

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
        # A cage that leaves one host for a value should fill it immediately.
        for cell in cells:
            if st.vals[cell] or st.dom[cell].bit_count() != 1:
                continue
            value = (st.dom[cell] & -st.dom[cell]).bit_length()
            changed |= st.place(cell, value, reason)
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

        # Arm cells sharing a row/column/box are distinct; their sum has a
        # lower bound 1+2+...+k even when the plain sum allows repeats.
        arm = self.arm
        shared = None
        for unit in st.units:
            members = [c for c in arm if c in set(unit.cells)]
            if len(members) == len(arm):
                shared = unit
                break
        if shared is not None:
            k = len(arm)
            reachable = {s for s in reachable if s >= k * (k + 1) // 2}

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
                if any((v + s) in reachable for s in other_sums):
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



def _sum_support(domains: list[int], total: int):
    """Per-cell value masks that can take part in a sum equal to ``total``."""
    count = len(domains)
    prefix = [{0}]
    for dom in domains:
        prefix.append({s + v for s in prefix[-1] for v in bits(dom)})
    if total not in prefix[-1]:
        return None
    suffix = [set() for _ in range(count + 1)]
    suffix[count] = {0}
    for i in range(count - 1, -1, -1):
        suffix[i] = {s + v for s in suffix[i + 1] for v in bits(domains[i])}
    masks = [0] * count
    for i, dom in enumerate(domains):
        for value in bits(dom):
            rest = total - value
            if any(rest - s in suffix[i + 1] for s in prefix[i]):
                masks[i] |= 1 << (value - 1)
    return masks


class Parity(Constraint):
    kind = "parity"

    def __init__(self, cells: list[int], parity: str):
        self._cells = list(cells)
        self.parity = parity

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return ("奇数" if self.parity == "odd" else "偶数") + f"（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": self.parity, "cells": self._cells}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        return all(v % 2 == (1 if self.parity == "odd" else 0) for v in vals)

    def prune(self, st: State) -> bool:
        keep = 0
        for v in range(1, st.n + 1):
            if v % 2 == (1 if self.parity == "odd" else 0):
                keep |= 1 << (v - 1)
        reason = Reason(self.parity, {"cells": self._cells})
        changed = False
        for cell in self._cells:
            changed |= st.restrict(cell, keep, reason)
        return changed


class Clone(Constraint):
    kind = "clone"

    def __init__(self, cells: list[int]):
        self._cells = list(cells)

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"克隆（{len(self._cells)} 格相同）"

    def to_dict(self) -> dict:
        return {"kind": "clone", "cells": self._cells}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        return len(set(vals)) == 1

    def prune(self, st: State) -> bool:
        common = st.full
        for cell in self._cells:
            common &= st.dom[cell]
        if common == 0:
            raise Contradiction("clone cells have no common digit")
        reason = Reason("clone", {"cells": self._cells})
        changed = False
        for cell in self._cells:
            changed |= st.restrict(cell, common, reason)
        return changed


class Sandwich(Constraint):
    kind = "sandwich"

    def __init__(self, cells: list[int], total: int):
        self._cells = list(cells)
        self.total = total

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"三明治 {self.total}（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "sandwich", "cells": self._cells, "sum": self.total}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        high = len(vals)
        if 1 not in vals or high not in vals:
            return False
        i, j = vals.index(1), vals.index(high)
        lo, hi = min(i, j), max(i, j)
        return sum(vals[lo + 1:hi]) == self.total

    def prune(self, st: State) -> bool:
        cells = self._cells
        n = st.n
        pos1 = pos9 = 0
        feasible = False
        for i in range(n):
            for j in range(i + 1, n):
                between = cells[i + 1:j]
                masks = _sum_support([st.dom[c] for c in between], self.total)
                if masks is None:
                    continue
                if st.has(cells[i], 1) and st.has(cells[j], n):
                    feasible = True
                    pos1 |= 1 << i
                    pos9 |= 1 << j
                    pass
                if st.has(cells[i], n) and st.has(cells[j], 1):
                    feasible = True
                    pos9 |= 1 << i
                    pos1 |= 1 << j
                    pass
        if not feasible:
            raise Contradiction(f"sandwich {self.total} has no position pair")
        reason = Reason("sandwich", {"cells": cells, "sum": self.total})
        changed = False
        for idx, cell in enumerate(cells):
            if not (pos1 >> idx) & 1:
                changed |= st.elim(cell, 1, reason)
            if not (pos9 >> idx) & 1:
                changed |= st.elim(cell, n, reason)
        return changed


class Skyscraper(Constraint):
    kind = "skyscraper"

    def __init__(self, cells: list[int], clue: int, direction: str = "left"):
        self._cells = list(cells)
        self.clue = clue
        self.direction = direction

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        side = "左" if self.direction == "left" else "右"
        return f"摩天楼（{side}看 {self.clue} 栋）"

    def to_dict(self) -> dict:
        return {"kind": "skyscraper", "cells": self._cells,
                "clue": self.clue, "direction": self.direction}

    def _ordered(self) -> list[int]:
        return self._cells if self.direction == "left" else list(reversed(self._cells))

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._ordered()]
        if any(v == 0 for v in vals):
            return True
        seen = 0
        best = 0
        for v in vals:
            if v > best:
                best = v
                seen += 1
        return seen == self.clue

    def prune(self, st: State) -> bool:
        cells = self._ordered()
        n = st.n
        reason = Reason("skyscraper", {"cells": self._cells, "clue": self.clue,
                                       "direction": self.direction})
        changed = False
        if self.clue == 1:
            changed |= st.place(cells[0], n, reason)
        elif self.clue == n:
            for i, cell in enumerate(cells):
                changed |= st.place(cell, i + 1, reason)
        else:
            changed |= st.elim(cells[0], n, reason)
        return changed


class RegionSum(Constraint):
    kind = "region_sum"

    def __init__(self, cells: list[int], region_of: dict[int, int]):
        self._cells = list(cells)
        self.region_of = region_of

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"区域和线（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "region_sum", "cells": self._cells}

    def segments(self) -> list[list[int]]:
        segs: list[list[int]] = []
        for cell in self._cells:
            if segs and self.region_of.get(cell) == self.region_of.get(segs[-1][-1]):
                segs[-1].append(cell)
            else:
                segs.append([cell])
        return segs

    def check(self, values: list[int]) -> bool:
        sums = []
        for seg in self.segments():
            vals = [values[c] for c in seg]
            if any(v == 0 for v in vals):
                return True
            sums.append(sum(vals))
        return len(set(sums)) <= 1

    def prune(self, st: State) -> bool:
        segs = self.segments()
        if len(segs) < 2:
            return False
        possible = []
        for seg in segs:
            reach = {0}
            for cell in seg:
                reach = {s + v for s in reach for v in bits(st.dom[cell])}
            possible.append(reach)
        common = set.intersection(*possible)
        if not common:
            raise Contradiction("region-sum segments cannot agree")
        reason = Reason("region_sum", {"cells": self._cells,
                                       "segments": segs, "sums": sorted(common)})
        changed = False
        for seg in segs:
            support = [0] * len(seg)
            for total in common:
                masks = _sum_support([st.dom[c] for c in seg], total)
                if masks:
                    for i, mask in enumerate(masks):
                        support[i] |= mask
            for cell, mask in zip(seg, support):
                if mask:
                    changed |= st.restrict(cell, mask, reason)
        return changed


class XSums(Constraint):
    """X-Sums: the first digit X, read from ``side``, bounds the sum of X cells."""

    kind = "x_sums"

    def __init__(self, cells: list[int], total: int, side: str = "top"):
        self._cells = list(cells)
        self.total = int(total)
        self.side = side

    def cells(self) -> list[int]:
        return self._cells

    def ordered(self) -> list[int]:
        if self.side in ("top", "left", "arrow"):
            return list(self._cells)
        return list(reversed(self._cells))

    def describe(self) -> str:
        return f"X-Sums {self.total}（{self.side}）"

    def to_dict(self) -> dict:
        return {"kind": "x_sums", "cells": self._cells, "sum": self.total, "side": self.side}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self.ordered()]
        if any(v == 0 for v in vals):
            return True
        x = vals[0]
        if not 1 <= x <= len(vals):
            return False
        return sum(vals[:x]) == self.total

    def prune(self, st: State) -> bool:
        cells = self.ordered()
        first = cells[0]
        reason = Reason("x_sums", {
            "cells": self._cells, "sum": self.total, "side": self.side,
        })
        changed = False
        feasible_sets = set()

        # Outside clues point along one row or column. All cells in an X-Sum
        # prefix therefore have to be distinct. Enumerating digit sets (at
        # most C(9, 4) for a 9x9 sum) is both stronger and cheaper than trying
        # every ordered tuple, and it gives direct support for each candidate.
        line_unit = next((unit for unit in st.units
                          if set(cells).issubset(unit.cells)), None)
        if line_unit is not None:
            supports = [0] * len(cells)
            feasible_x = []
            for x in bits(st.dom[first]):
                if not 1 <= x <= len(cells):
                    continue
                span = cells[:x]
                doms = [st.dom[cell] for cell in span]
                doms[0] &= 1 << (x - 1)
                if not doms[0]:
                    continue
                possible_sets = digit_sets(x, self.total, st.n)
                for combo in possible_sets:
                    if not _matchable(combo, doms):
                        continue
                    feasible_x.append(x)
                    feasible_sets.add((x, combo))
                    # Keep only values that participate in at least one
                    # matching of the required digits to the prefix cells.
                    for i, cell in enumerate(span):
                        for value in bits(doms[i]):
                            forced = list(doms)
                            forced[i] = 1 << (value - 1)
                            if _matchable(combo, forced):
                                supports[cells.index(cell)] |= 1 << (value - 1)
            if not feasible_x:
                raise Contradiction("X-Sum prefix has no feasible digit set")
            reason.data["feasible_x"] = sorted(set(feasible_x))
            reason.data["feasible_sets"] = [
                {"x": x, "digits": list(combo)}
                for x, combo in sorted(feasible_sets)
            ]
            for cell, allowed in zip(cells, supports):
                if allowed:
                    changed |= st.restrict(cell, allowed, reason)
            return changed

        # Generic fallback for non-row/column X-Sums such as a custom arrow.
        # Respect only the actual all-different groups that cover cells in the
        # prefix; unrelated prefix cells may repeat.
        for x in bits(st.dom[first]):
            if not 1 <= x <= len(cells):
                changed |= st.elim(first, x, reason)
                continue
            span = cells[:x]
            groups = []
            for unit in st.units:
                members = [i for i, cell in enumerate(span) if cell in unit.cells]
                if len(members) > 1:
                    groups.append(members)
            values = [x]

            def feasible(index: int, remaining: int) -> bool:
                if index == len(span):
                    return remaining == 0
                cell = span[index]
                for value in bits(st.dom[cell]):
                    if any(value == values[j] for group in groups if index in group
                           for j in group if j < index):
                        continue
                    values.append(value)
                    if feasible(index + 1, remaining - value):
                        return True
                    values.pop()
                return False

            if not feasible(1, self.total - x):
                changed |= st.elim(first, x, reason)

        # For non-linear scopes, if X is fixed, retain the general ordered
        # assignment propagation used by arrows and custom X-Sums.
        if st.dom[first].bit_count() == 1:
            x = st.dom[first].bit_length()
            if 2 <= x <= len(cells) and x <= 6:
                from itertools import combinations_with_replacement, permutations
                span = cells[:x]
                groups = []
                for unit in st.units:
                    members = [i for i, cell in enumerate(span) if cell in unit.cells]
                    if len(members) >= 2:
                        groups.append(members)
                for con in getattr(st, "constraints", []):
                    cs = con.cells()
                    if len(cs) != 2 or not set(cs) <= set(span):
                        continue
                    if getattr(con, "kind", "") in ("anti", "german_whisper",
                                                    "dutch_whisper", "consecutive"):
                        groups.append([span.index(cell) for cell in cs])
                feasible_assignments = []
                for combo in combinations_with_replacement(range(1, st.n + 1), x):
                    if sum(combo) != self.total:
                        continue
                    for perm in set(permutations(combo)):
                        if any(not (st.dom[span[i]] >> (value - 1) & 1)
                               for i, value in enumerate(perm)):
                            continue
                        if any(len({perm[i] for i in group}) != len(group)
                               for group in groups):
                            continue
                        feasible_assignments.append(perm)
                if not feasible_assignments:
                    raise Contradiction("X-Sum prefix has no feasible assignment")
                for i, cell in enumerate(span):
                    allowed = 0
                    for value in bits(st.dom[cell]):
                        if any(perm[i] == value for perm in feasible_assignments):
                            allowed |= 1 << (value - 1)
                    changed |= st.restrict(cell, allowed, reason)
        return changed




class ClassCover(Constraint):
    """Every block must contain at least one digit from each class."""

    kind = "class_cover"

    def __init__(self, cells: list[int], classes: list[set[int]]):
        self._cells = list(cells)
        self.classes = [set(c) for c in classes]

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return "2×2 类覆盖（" + "/".join(
            ",".join(str(v) for v in sorted(c)) for c in self.classes
        ) + "）"

    def to_dict(self) -> dict:
        return {"kind": "class_cover", "cells": self._cells,
                "classes": [sorted(c) for c in self.classes]}

    def check(self, values: list[int]) -> bool:
        vals = [values[c] for c in self._cells]
        if any(v == 0 for v in vals):
            return True
        return all(any(v in cls for v in vals) for cls in self.classes)

    def prune(self, st: State) -> bool:
        base = {"cells": self._cells,
                "classes": [sorted(c) for c in self.classes]}
        reason = Reason("class_cover", base)
        changed = False
        for cls in self.classes:
            mask = 0
            for value in cls:
                mask |= 1 << (value - 1)
            hosts = [c for c in self._cells if st.dom[c] & mask]
            if not hosts:
                raise Contradiction("2x2 class cover has no host")
            if len(hosts) == 1:
                detail = dict(base, forced_cell=hosts[0], forced_class=sorted(cls),
                              hosts=[c for c in self._cells if c not in hosts])
                changed |= st.restrict(hosts[0], mask, Reason("class_cover", detail))
        if changed:
            return True
        total = 1
        for cell in self._cells:
            total *= st.dom[cell].bit_count()
            if total > 512:
                return False
        support = [0] * len(self._cells)
        feasible = False
        for combo in product(*[list(bits(st.dom[c])) for c in self._cells]):
            if all(any(v in cls for v in combo) for cls in self.classes):
                feasible = True
                for i, v in enumerate(combo):
                    support[i] |= 1 << (v - 1)
        if not feasible:
            raise Contradiction("2x2 class cover has no support")
        for cell, mask in zip(self._cells, support):
            changed |= st.restrict(cell, mask, reason)
        return changed


class RegionCount(Constraint):
    """Region-aware rule: the scope cells must span one of the allowed counts."""

    kind = "region_count"

    def __init__(self, cells: list[int], counts: list[int]):
        self._cells = list(cells)
        self.counts = sorted({int(c) for c in counts})
        if not self.counts:
            raise ValueError("region_count needs at least one count")

    def cells(self) -> list[int]:
        return self._cells

    def describe(self) -> str:
        return f"区域计数 {self.counts}（{len(self._cells)} 格）"

    def to_dict(self) -> dict:
        return {"kind": "region_count", "cells": self._cells, "counts": self.counts}

    def check(self, values: list[int]) -> bool:
        return True  # needs regions; see check_regions

    def check_regions(self, values: list[int], region_of: dict[int, int]) -> bool:
        regions = {region_of.get(c, -1) for c in self._cells}
        return len(regions) in self.counts

    def prune(self, st: State) -> bool:
        return False


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
