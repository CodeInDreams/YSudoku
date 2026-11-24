"""Check colour layouts against projected clue patterns and planar connectivity."""

from dataclasses import dataclass
from math import comb
from time import monotonic


def indexes(mask):
    while mask:
        bit = mask & -mask
        mask ^= bit
        yield bit.bit_length() - 1


def cell_mask(cells):
    return sum(1 << c for c in cells)


def outer_cells(n):
    return (tuple(range(n)) + tuple(r * n + n - 1 for r in range(1, n))
            + tuple((n - 1) * n + c for c in range(n - 2, -1, -1))
            + tuple(r * n for r in range(n - 2, 0, -1)))


def perimeter_patterns(length):
    """Both colours cannot have alternating runs on the perimeter."""
    full = (1 << length) - 1
    yield 0
    yield full
    for size in range(1, length):
        interval = (1 << size) - 1
        for start in range(length):
            shifted = interval << start
            yield (shifted & full) | (shifted >> length)


@dataclass(frozen=True)
class ShadeTable:
    cells: tuple[int, ...]
    scope: int
    active: int
    dark: dict[int, int]

    @classmethod
    def build(cls, cells, patterns):
        dark = dict.fromkeys(cells, 0)
        active = 0
        for i, pattern in enumerate(patterns):
            bit = 1 << i
            active |= bit
            for j in indexes(pattern):
                dark[cells[j]] |= bit
        return cls(cells, cell_mask(cells), active, dark)


class LayoutBudget(Exception):
    pass


class ShadeLayout:
    """An independent colour relaxation. A surviving layout does not fix digits."""

    def __init__(self, n, squares, neighbours, clues, minimums=()):
        perimeter = outer_cells(n)
        self.tables = [*clues, ShadeTable.build(perimeter, perimeter_patterns(len(perimeter)))]
        self.neighbours = tuple(cell_mask(adjacent) for adjacent in neighbours)
        self.minimums = tuple((cell_mask(cells), amount) for cells, amount in minimums)
        self.options = {(size, required): sum(comb(size, i) for i in range(required, size + 1))
                        for size in range(n + 1) for required in range(size + 1)}
        self.full = (1 << (n * n)) - 1
        self.clauses = []
        for square in squares:
            a, b, c, d = (1 << cell for cell in square)
            whole = a | b | c | d
            self.clauses.extend(((whole, 0), (0, whole), (a | d, b | c), (b | c, a | d)))
        self.weights = [sum(cell in table.dark for table in clues)
                        + sum(bool(scope & (1 << cell)) for scope, _ in self.minimums)
                        for cell in range(n * n)]
        self.impossible = set()

    def _reachable(self, seed, available):
        seen = seed
        while seed:
            cell = seed & -seed
            seed ^= cell
            next_cells = self.neighbours[cell.bit_length() - 1] & available & ~seen
            seen |= next_cells
            seed |= next_cells
        return seen

    def _propagate(self, dark, light, patterns):
        while True:
            prior = dark, light
            for scope, required in self.minimums:
                available = scope & ~light
                amount = available.bit_count()
                if amount < required:
                    return None
                if amount == required:
                    dark |= available
            for i, table in enumerate(self.tables):
                remaining = patterns[i]
                for cell in indexes(table.scope & dark):
                    remaining &= table.dark[cell]
                for cell in indexes(table.scope & light):
                    remaining &= ~table.dark[cell]
                if not remaining:
                    return None
                patterns[i] = remaining
                for cell in indexes(table.scope & ~(dark | light)):
                    if not remaining & table.dark[cell]:
                        light |= 1 << cell
                    elif not remaining & ~table.dark[cell]:
                        dark |= 1 << cell

            for prohibited_dark, prohibited_light in self.clauses:
                if dark & prohibited_light or light & prohibited_dark:
                    continue
                unknown = (prohibited_dark | prohibited_light) & ~(dark | light)
                if not unknown:
                    return None
                if not unknown & (unknown - 1):
                    dark |= unknown & prohibited_light
                    light |= unknown & prohibited_dark

            if dark:
                connected = self._reachable(dark & -dark, self.full & ~light)
                if dark & ~connected:
                    return None
                light |= self.full & ~connected
            if light:
                connected = self._reachable(light & -light, self.full & ~dark)
                if light & ~connected:
                    return None
                dark |= self.full & ~connected
            if dark & light:
                return None
            if (dark, light) == prior:
                return dark, light

    def search(self, dark, light, deadline, limit=25_000):
        """Return a witness, zero for a complete contradiction, or None on budget."""
        nodes = 0

        def look(dark, light, patterns):
            nonlocal nodes
            nodes += 1
            if nodes > limit or (nodes % 32 == 0 and monotonic() >= deadline):
                raise LayoutBudget
            key = dark, light
            if key in self.impossible:
                return 0
            patterns = patterns.copy()
            narrowed = self._propagate(dark, light, patterns)
            if narrowed is None:
                result = 0
            else:
                dark, light = narrowed
                unknown = self.full & ~(dark | light)
                if not unknown:
                    result = dark if dark and light else 0
                else:
                    choices = [(patterns[i].bit_count(), i, table.scope & unknown)
                               for i, table in enumerate(self.tables[:-1]) if table.scope & unknown]
                    for i, (scope, required) in enumerate(self.minimums, len(self.tables)):
                        remaining = scope & unknown
                        need = required - (scope & dark).bit_count()
                        if remaining and need > 0:
                            choices.append((self.options[remaining.bit_count(), need], i, remaining))
                    subset = min(choices)[2] if choices else unknown
                    fixed = dark | light
                    cell = max(indexes(subset), key=lambda c: (
                        self.weights[c] + (self.neighbours[c] & fixed).bit_count(), -c,
                    ))
                    bit = 1 << cell
                    result = look(dark | bit, light, patterns) or look(dark, light | bit, patterns)
            if not result and len(self.impossible) < 60_000:
                self.impossible.add(key)
            return result

        if monotonic() >= deadline:
            return None, 0
        try:
            witness = look(dark, light, [table.active for table in self.tables])
        except LayoutBudget:
            return None, nodes
        return witness, nodes
