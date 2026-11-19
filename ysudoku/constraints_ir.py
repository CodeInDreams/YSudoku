"""Generic constraint IR: rules describe relations, not solving strategy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Relation:
    cells: tuple[int, ...]

    def check(self, values: list[int]) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover - interface
        return self.__class__.__name__


class AllDifferent(Relation):
    def check(self, values):
        vals = [values[c] for c in self.cells]
        return 0 in vals or len(set(vals)) == len(vals)

    def describe(self):
        return f"AllDifferent({len(self.cells)} cells)"


class Sum(Relation):
    def __init__(self, cells, total, unique=False):
        super().__init__(tuple(cells))
        self.total = int(total)
        self.unique = bool(unique)

    def check(self, values):
        vals = [values[c] for c in self.cells]
        if 0 in vals:
            return True
        if sum(vals) != self.total:
            return False
        return not self.unique or len(set(vals)) == len(vals)

    def describe(self):
        return f"Sum({len(self.cells)} cells={self.total})"


class Difference(Relation):
    def __init__(self, a, b, minimum=1, maximum=9):
        super().__init__((a, b))
        self.minimum = minimum
        self.maximum = maximum

    def check(self, values):
        a, b = values[self.cells[0]], values[self.cells[1]]
        if not a or not b:
            return True
        return self.minimum <= abs(a - b) <= self.maximum

    def describe(self):
        return f"Difference({self.cells[0]},{self.cells[1]})"


class TupleRelation(Relation):
    def __init__(self, cells, allowed, label="Tuple"):
        super().__init__(tuple(cells))
        self.allowed = {tuple(x) for x in allowed}
        self.label = label

    def check(self, values):
        vals = tuple(values[c] for c in self.cells)
        return 0 in vals or vals in self.allowed

    def describe(self):
        return f"{self.label}({len(self.cells)} cells)"
