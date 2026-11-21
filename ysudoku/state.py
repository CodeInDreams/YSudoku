"""Candidate state, units and the event log used to build explanations."""

from __future__ import annotations

from dataclasses import dataclass, field


class Contradiction(Exception):
    """Raised when a propagation step empties a domain."""


@dataclass
class Reason:
    kind: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "data": self.data}


@dataclass
class Event:
    kind: str  # "place" | "elim"
    cell: int
    value: int
    reason: Reason
    before: int = 0  # candidate mask before this event

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "cell": self.cell,
            "value": self.value,
            "reason": self.reason.to_dict(),
        }


@dataclass
class Unit:
    kind: str  # row / col / region / diagonal / line / distinct
    index: int
    cells: list[int]
    hypothesis: bool = False

    @property
    def label(self) -> str:
        if self.kind == "row":
            return f"第{self.index + 1}行"
        if self.kind == "col":
            return f"第{self.index + 1}列"
        if self.kind == "region":
            return f"区域{self.index + 1}"
        if self.kind == "diagonal":
            return "主对角线" if self.index == 0 else "副对角线"
        if self.kind == "line":
            return f"第{self.index + 1}条线"
        if self.kind == "distinct":
            return f"互异单元{self.index + 1}"
        return f"单元{self.index + 1}"


def cell_name(cell: int, n: int) -> str:
    r, c = divmod(cell, n)
    return f"R{r + 1}C{c + 1}"


def bits(mask: int):
    while mask:
        low = mask & -mask
        yield low.bit_length()
        mask ^= low


def singleton(mask: int) -> int:
    return mask.bit_length()


def build_units(puzzle, diagonals: tuple[bool, bool] = (False, False),
                chaos: bool = False) -> list[Unit]:
    n = puzzle.size
    units: list[Unit] = []
    for r in range(n):
        units.append(Unit("row", r, [r * n + c for c in range(n)]))
    for c in range(n):
        units.append(Unit("col", c, [r * n + c for r in range(n)]))
    if not chaos:
        regions = puzzle.regions or puzzle.box_regions()
        for i, region in enumerate(regions):
            units.append(Unit("region", i, list(region)))
    if diagonals[0]:
        units.append(Unit("diagonal", 0, [i * n + i for i in range(n)]))
    if diagonals[1]:
        units.append(Unit("diagonal", 1, [i * n + (n - 1 - i) for i in range(n)]))
    return units


class State:
    """Candidate domains with an optional human-readable event log."""

    def __init__(self, n: int, units: list[Unit], record: bool = False):
        self.n = n
        self.n2 = n * n
        self.full = (1 << n) - 1
        self.units = units
        self.dom = [self.full] * self.n2
        self.vals = [0] * self.n2
        self.record = record
        self.events: list[Event] = []
        self.peers: list[list[int]] = [[] for _ in range(self.n2)]
        for unit in units:
            for cell in unit.cells:
                self.peers[cell].extend(c for c in unit.cells if c != cell)
        self.peers = [sorted(set(p)) for p in self.peers]
        self.unit_of: list[list[int]] = [[] for _ in range(self.n2)]
        for ui, unit in enumerate(units):
            for cell in unit.cells:
                self.unit_of[cell].append(ui)

    # ------------------------------------------------------------- mutation
    def begin(self) -> None:
        self._snapshot = (list(self.dom), list(self.vals))
        self.events = []
        self.record = True

    def rollback(self) -> None:
        if getattr(self, "_snapshot", None) is not None:
            self.dom, self.vals = list(self._snapshot[0]), list(self._snapshot[1])
        self.events = []
        self.record = False

    def end(self) -> list[Event]:
        self.record = False
        return self.events

    def has(self, cell: int, value: int) -> bool:
        return bool(self.dom[cell] & (1 << (value - 1)))

    def elim(self, cell: int, value: int, reason: Reason | None = None) -> bool:
        bit = 1 << (value - 1)
        if not self.dom[cell] & bit:
            return False
        self.dom[cell] ^= bit
        if self.record and reason is not None:
            self.events.append(Event("elim", cell, value, reason, self.dom[cell] | bit))
        if self.dom[cell] == 0:
            raise Contradiction(f"{cell_name(cell, self.n)} has no candidates left")
        return True

    def place(self, cell: int, value: int, reason: Reason | None = None) -> bool:
        if self.vals[cell] == value:
            return False
        if self.vals[cell]:
            raise Contradiction(f"{cell_name(cell, self.n)} already filled")
        if not self.has(cell, value):
            raise Contradiction(f"{cell_name(cell, self.n)} cannot be {value}")
        self.vals[cell] = value
        self.dom[cell] = 1 << (value - 1)
        if self.record and reason is not None:
            self.events.append(Event("place", cell, value, reason, self.dom[cell] | (1 << (value - 1))))
        for peer in self.peers[cell]:
            self.elim(peer, value, Reason("unit_peer", {"by": cell, "value": value}))
        return True

    def restrict(self, cell: int, mask: int, reason: Reason | None = None) -> bool:
        removed = self.dom[cell] & ~mask
        if not removed:
            return False
        for value in bits(removed):
            self.elim(cell, value, reason)
        return True

    # ------------------------------------------------------------- helpers
    def copy(self) -> "State":
        clone = State.__new__(State)
        clone.n = self.n
        clone.n2 = self.n2
        clone.full = self.full
        clone.units = self.units
        clone.dom = self.dom.copy()
        clone.vals = self.vals.copy()
        clone.record = False
        clone.events = []
        clone.peers = self.peers
        clone.unit_of = self.unit_of
        return clone

    @property
    def solved(self) -> bool:
        return all(self.vals)

    def size(self, cell: int) -> int:
        return self.dom[cell].bit_count()

    def assigned(self) -> dict[int, int]:
        return {c: v for c, v in enumerate(self.vals) if v}

    def as_grid(self) -> list[list[int]]:
        return [self.vals[r * self.n:(r + 1) * self.n] for r in range(self.n)]
