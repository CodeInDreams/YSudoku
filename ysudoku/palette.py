"""SudokuPad colour palette policy for generated colour annotations.

The first three swatches are grey and must never be used.
Swatches 4-9 (0-based indices 3-8) are the first-page colours.
Further colours come from the second page (index 9+).
"""

FORBIDDEN = (0, 1, 2)

# First-page, 0-based indices.
BLUE, GREEN, YELLOW, ORANGE, RED, PURPLE = 3, 4, 5, 6, 7, 8

PAIR_GROUPS = (
    (BLUE, GREEN),
    (YELLOW, ORANGE),
    (RED, PURPLE),
)

TRIPLE_GROUPS = (
    (BLUE, GREEN, PURPLE),
    (RED, YELLOW, ORANGE),
)

SECOND_PAGE = tuple(range(9, 18))


def pair_colours(index: int = 0) -> tuple[int, int]:
    """Return two distinct allowed swatches for the index-th pair."""
    return PAIR_GROUPS[index % len(PAIR_GROUPS)]


def triple_colours(index: int = 0) -> tuple[int, int, int]:
    """Return three distinct allowed swatches for the index-th triple."""
    return TRIPLE_GROUPS[index % len(TRIPLE_GROUPS)]


def colours_for(size: int, index: int = 0) -> tuple[int, ...]:
    if size == 2:
        return pair_colours(index)
    if size == 3:
        return triple_colours(index)
    if size <= 0:
        return ()
    if size <= len(SECOND_PAGE):
        return SECOND_PAGE[:size]
    raise ValueError("not enough palette colours")


def is_allowed(colour: int) -> bool:
    return colour not in FORBIDDEN
