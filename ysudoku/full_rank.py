"""Lexicographic rank of a row or column read from an edge."""

from functools import lru_cache

from .constraints import Constraint
from .state import Contradiction, Reason, bits


@lru_cache(maxsize=16)
def _readings(n):
    rows = tuple(tuple(r * n + c for c in range(n)) for r in range(n))
    cols = tuple(tuple(r * n + c for r in range(n)) for c in range(n))
    return {"left": rows, "right": tuple(row[::-1] for row in rows),
            "top": cols, "bottom": tuple(col[::-1] for col in cols)}


@lru_cache(maxsize=12_000)
def _extreme(masks, reverse=False):
    """Find the lexicographic extreme among distinct-digit readings."""
    @lru_cache(maxsize=None)
    def visit(i, used):
        if i == len(masks):
            return ()
        choices = list(bits(masks[i] & ~used))
        for value in reversed(choices) if reverse else choices:
            tail = visit(i + 1, used | (1 << (value - 1)))
            if tail is not None:
                return (value, *tail)
        return None

    return visit(0, 0)


class FullRank(Constraint):
    kind = "full_rank"

    def __init__(self, cells, rank, side, n):
        self._cells = tuple(cells)
        self.rank, self.side, self.n = rank, side, n
        if not 1 <= rank <= 4 * n or self._cells not in _readings(n).get(side, ()):
            raise ValueError("Full Rank 需要一条完整的盘外读数和 1 到 4n 的排名")
        self.head = (rank - 1) // 4 + 1

    def cells(self):
        return list(self._cells)

    def describe(self):
        return f"Full Rank {self.rank}"

    def to_dict(self):
        return {"kind": self.kind, "cells": self.cells(), "rank": self.rank, "side": self.side}

    def check(self, values):
        reading = tuple(values[c] for c in self._cells)
        if reading[0] and reading[0] != self.head:
            return False
        if not all(values):
            return True
        smaller = sum(tuple(values[c] for c in cells) < reading
                      for lines in _readings(self.n).values() for cells in lines)
        return self.rank == 1 + smaller

    def prune(self, st):
        first = self._cells[0]
        bit = 1 << (self.head - 1)
        if not st.dom[first] & bit:
            raise Contradiction(f"排名 {self.rank} 的首格必须是 {self.head}")
        # Every edge has each digit once. Only one line from each of the
        # other three edges can affect this clue's order within its group.
        lows, highs = [], []
        for side, lines in _readings(self.n).items():
            if side == self.side:
                continue
            bounds = []
            for cells in lines:
                if not st.dom[cells[0]] & bit:
                    continue
                masks = (bit, *(st.dom[c] for c in cells[1:]))
                low = _extreme(masks)
                if low is not None:
                    bounds.append((low, _extreme(masks, True)))
            if not bounds:
                raise Contradiction(f"{side} 没有首位是 {self.head} 的可行读数")
            lows.append(min(low for low, _ in bounds))
            highs.append(max(high for _, high in bounds))
        smaller = (self.rank - 1) % 4
        lower = sorted(lows)[smaller - 1] if smaller else None
        upper = sorted(highs)[smaller] if smaller < 3 else None
        reason = Reason(self.kind, {"cells": self.cells(), "rank": self.rank, "head": self.head,
                                    "lower": lower, "upper": upper})
        changed = st.restrict(first, bit, reason)
        masks = tuple(st.dom[c] for c in self._cells)
        if all(mask.bit_count() == 1 for mask in masks) and all(st.vals) and not self.check(st.vals):
            raise Contradiction(f"读数达不到 Full Rank {self.rank}")
        for index, cell in enumerate(self._cells[1:], 1):
            allowed = 0
            for digit in bits(masks[index]):
                forced = (*masks[:index], 1 << (digit - 1), *masks[index + 1:])
                low = _extreme(forced)
                if low is None or upper is not None and low > upper:
                    continue
                if lower is None or _extreme(forced, True) > lower:
                    allowed |= 1 << (digit - 1)
            changed |= st.restrict(cell, allowed, reason)
        return changed
