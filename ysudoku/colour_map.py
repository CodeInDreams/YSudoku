"""Colour-class model.

Same colour means the same class; different colours mean different classes.
A cell may belong to several classes, but never more than four.
"""

from .palette import FORBIDDEN, is_allowed

MAX_COLOURS_PER_CELL = 4


class ColourError(ValueError):
    pass


class ColourMap:
    def __init__(self, n: int = 9):
        self.n = n
        self._cells: dict[int, set[int]] = {}

    def colours(self, cell: int) -> set[int]:
        return set(self._cells.get(cell, ()))

    def add(self, cell: int, colour: int) -> None:
        if not is_allowed(colour):
            raise ColourError(f"colour {colour} is forbidden")
        current = self._cells.setdefault(cell, set())
        if colour in current:
            return
        if len(current) >= MAX_COLOURS_PER_CELL:
            raise ColourError(f"cell {cell} already has {MAX_COLOURS_PER_CELL} colours")
        current.add(colour)

    def remove(self, cell: int, colour: int) -> None:
        current = self._cells.get(cell)
        if current:
            current.discard(colour)
            if not current:
                self._cells.pop(cell, None)

    def set_group(self, cells: list[int], colours: tuple[int, ...]) -> None:
        """Give each cell exactly one colour from a pair/triple group."""
        if len(cells) != len(colours):
            raise ColourError("cells and colours must have the same length")
        for cell, colour in zip(cells, colours):
            current = self._cells.get(cell, set())
            if current and colour not in current and len(current) >= MAX_COLOURS_PER_CELL:
                raise ColourError(f"cell {cell} already has {MAX_COLOURS_PER_CELL} colours")
            self.add(cell, colour)

    def same_class(self, a: int, b: int) -> bool:
        return bool(self._cells.get(a, set()) & self._cells.get(b, set()))

    def different_class(self, a: int, b: int) -> bool:
        left, right = self._cells.get(a, set()), self._cells.get(b, set())
        return bool(left) and bool(right) and not (left & right)

    def validate(self) -> None:
        for cell, colours in self._cells.items():
            if len(colours) > MAX_COLOURS_PER_CELL:
                raise ColourError(f"cell {cell} has too many colours")
            if any(c in FORBIDDEN for c in colours):
                raise ColourError(f"cell {cell} uses a forbidden colour")
