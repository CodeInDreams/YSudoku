"""Generic constraint IR: rules describe relations, not solving strategy."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


def _values(mask: int):
    while mask:
        bit = mask & -mask
        mask ^= bit
        yield bit.bit_length()


@dataclass(eq=False)
class Relation:
    cells: tuple[int, ...]

    def __post_init__(self):
        self.cells = tuple(int(cell) for cell in self.cells)
        if not self.cells:
            raise ValueError("a relation needs at least one cell")
        if len(set(self.cells)) != len(self.cells):
            raise ValueError("a relation cannot repeat a cell")
        if min(self.cells) < 0:
            raise ValueError("cell indices must be non-negative")

    def signature(self) -> tuple:
        """Stable identity used by the support engine to deduplicate rules."""
        return (type(self).__name__, self.cells)

    def check(self, values: list[int]) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def possible(self, domains: dict[int, int]) -> bool:  # pragma: no cover - interface
        """Whether the relation has support in the current cell domains."""
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover - interface
        return self.__class__.__name__


class AllDifferent(Relation):
    def check(self, values):
        assigned = [values[cell] for cell in self.cells if values[cell]]
        return len(set(assigned)) == len(assigned)

    def possible(self, domains):
        masks = sorted((domains[cell] for cell in self.cells), key=int.bit_count)
        if any(not mask for mask in masks):
            return False

        @lru_cache(maxsize=None)
        def assign(index: int, used: int) -> bool:
            if index == len(masks):
                return True
            available = masks[index] & ~used
            while available:
                bit = available & -available
                available ^= bit
                if assign(index + 1, used | bit):
                    return True
            return False

        return assign(0, 0)

    def describe(self):
        return f"AllDifferent({len(self.cells)} cells)"


class Sum(Relation):
    def __init__(self, cells, total, unique=False):
        super().__init__(tuple(cells))
        self.total = int(total)
        self.unique = bool(unique)

    def sum_terms(self):
        return [(cell, 1) for cell in self.cells], self.total

    def signature(self):
        return (type(self).__name__, self.cells, self.total, self.unique)

    def check(self, values):
        vals = [values[cell] for cell in self.cells]
        assigned = [value for value in vals if value]
        if self.unique and len(set(assigned)) != len(assigned):
            return False
        if len(assigned) == len(vals):
            return sum(assigned) == self.total
        remaining = len(vals) - len(assigned)
        return sum(assigned) + remaining <= self.total

    def possible(self, domains):
        masks = [domains[cell] for cell in self.cells]
        if any(not mask for mask in masks):
            return False
        if self.unique:
            ordered = sorted(masks, key=int.bit_count)

            @lru_cache(maxsize=None)
            def visit(index: int, remaining: int, used: int) -> bool:
                if index == len(ordered):
                    return remaining == 0
                available = ordered[index] & ~used
                while available:
                    bit = available & -available
                    available ^= bit
                    value = bit.bit_length()
                    if value <= remaining and visit(index + 1, remaining - value,
                                                     used | bit):
                        return True
                return False

            return visit(0, self.total, 0)

        reachable = {0}
        for mask in masks:
            reachable = {subtotal + value for subtotal in reachable
                         for value in _values(mask)
                         if subtotal + value <= self.total}
            if not reachable:
                return False
        return self.total in reachable

    def describe(self):
        suffix = ", unique" if self.unique else ""
        return f"Sum({len(self.cells)} cells={self.total}{suffix})"


class Difference(Relation):
    def __init__(self, a, b, minimum=1, maximum=9):
        super().__init__((a, b))
        self.minimum = int(minimum)
        self.maximum = int(maximum)
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("difference bounds must satisfy 0 <= minimum <= maximum")

    def signature(self):
        return (type(self).__name__, self.cells, self.minimum, self.maximum)

    def check(self, values):
        a, b = (values[cell] for cell in self.cells)
        if a and b:
            return self.minimum <= abs(a - b) <= self.maximum
        # Without a board size, an incomplete value vector cannot safely
        # reject a pair; possible() uses the actual candidate masks instead.
        return True

    def possible(self, domains):
        a, b = (domains[cell] for cell in self.cells)
        return any(self.minimum <= abs(x - y) <= self.maximum
                   for x in _values(a) for y in _values(b))

    def describe(self):
        return f"Difference({self.cells[0]},{self.cells[1]})"


class TupleRelation(Relation):
    def __init__(self, cells, allowed, label="Tuple"):
        super().__init__(tuple(cells))
        tuples = {tuple(int(value) for value in row) for row in allowed}
        if any(len(row) != len(self.cells) or any(value < 1 for value in row)
               for row in tuples):
            raise ValueError("allowed tuples must match the scope and use positive digits")
        self.allowed = frozenset(tuples)
        self.label = str(label)

    def signature(self):
        return (type(self).__name__, self.cells, tuple(sorted(self.allowed)), self.label)

    def check(self, values):
        return any(all(not values[cell] or values[cell] == value
                       for cell, value in zip(self.cells, row))
                   for row in self.allowed)

    def possible(self, domains):
        return any(all(domains[cell] & (1 << (value - 1))
                       for cell, value in zip(self.cells, row))
                   for row in self.allowed)

    def describe(self):
        return f"{self.label}({len(self.cells)} cells)"


def relation_from_spec(spec: dict) -> Relation:
    """Build one relation from a small JSON-compatible rule description."""
    kind = str(spec.get("kind", "")).strip().lower()
    cells = spec.get("cells") or []
    if kind in ("all_different", "alldifferent"):
        return AllDifferent(cells)
    if kind == "sum":
        if "total" not in spec:
            raise ValueError("Sum relation requires total")
        return Sum(cells, spec["total"], spec.get("unique", False))
    if kind == "difference":
        if len(cells) != 2:
            raise ValueError("Difference relation requires two cells")
        return Difference(cells[0], cells[1], spec.get("minimum", 1),
                          spec.get("maximum", 9))
    if kind in ("tuple", "tuple_relation"):
        return TupleRelation(cells, spec.get("allowed", []),
                            spec.get("label", "Tuple"))
    raise ValueError(f"unsupported relation kind: {kind or '(empty)'}")
