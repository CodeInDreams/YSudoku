"""Parse arrow-headed omni-directional X-Sum clues."""

from __future__ import annotations

import math


def _sign(v: float) -> int:
    return (v > 0.05) - (v < -0.05)


def _edge_for_arrow(arrow: dict, n: int = 9):
    for row, col in (arrow.get("wayPoints") or [])[-2:]:
        if row < 0: return "top"
        if row >= n: return "bottom"
        if col < 0: return "left"
        if col >= n: return "right"
    return None


def direction(arrow: dict) -> tuple[int, int]:
    """Return the ordered waypoints' direction in [row, col] order."""
    return _point_direction(arrow)


def entry_cell(arrow: dict, n: int = 9):
    entry = _edge_entry(arrow, _edge_for_arrow(arrow, n), direction(arrow), n)
    return (entry[0] - 1, entry[1] - 1) if entry else None


def cells_along(arrow: dict, n: int = 9) -> list[int]:
    dr, dc = direction(arrow)
    entry = entry_cell(arrow, n)
    if entry is None or (dr == 0 and dc == 0):
        return []
    r, c = entry
    out = []
    while 0 <= r < n and 0 <= c < n:
        out.append(r * n + c)
        r += dr
        c += dc
    return out


def _nearest_clue(arrow: dict, underlays: list[dict]) -> int | None:
    start = arrow.get("wayPoints")[0]
    best = None
    for item in underlays:
        text = str(item.get("text", "")).strip()
        if not text.isdigit():
            continue
        cx, cy = item.get("center", [0, 0])
        dist = math.hypot(cx - start[0], cy - start[1])
        if best is None or dist < best[0]:
            best = (dist, int(text))
    return best[1] if best and best[0] < 1.5 else None


def parse_arrows(raw: dict, n: int = 9) -> list[dict]:
    # Keep the historical rule shape while using SudokuPad's [row,col]
    # geometry and the virtual off-grid arrowhead to find the entry cell.
    decoded = parse_arrows_geometry(raw, n=n)
    return [{
        "cells": [(r - 1) * n + (c - 1) for r, c in item["cells"]],
        "total": item["clue"],
        "direction": DIRECTIONS_BY_NAME[item["direction"]],
    } for item in decoded]


def arrow_edge(arrow: dict, n: int = 9):
    return _edge_for_arrow(arrow, n)


def allowed_directions(arrow: dict, n: int = 9):
    edge = arrow_edge(arrow, n)
    table = {
        "top": [(1, 0), (1, -1), (1, 1)],
        "bottom": [(-1, 0), (-1, -1), (-1, 1)],
        "left": [(0, 1), (-1, 1), (1, 1)],
        "right": [(0, -1), (-1, -1), (1, -1)],
        "top-left": [(1, 1)], "top-right": [(1, -1)],
        "bottom-left": [(-1, 1)], "bottom-right": [(-1, -1)],
    }
    return table.get(edge, [])


def clue_edge(center, n: int = 9):
    # SudokuPad stores these coordinates in [row, col] order.
    row, col = center
    if row < 0: return "top"
    if row >= n: return "bottom"
    if col < 0: return "left"
    if col >= n: return "right"
    return None


_DIRECTION_NAMES = {
    (-1, 0): "up", (1, 0): "down", (0, -1): "left", (0, 1): "right",
    (-1, -1): "up-left", (-1, 1): "up-right",
    (1, -1): "down-left", (1, 1): "down-right",
}
DIRECTIONS_BY_NAME = {name: delta for delta, name in _DIRECTION_NAMES.items()}


def _point_direction(arrow: dict) -> tuple[int, int]:
    """Return row/column direction from the ordered SudokuPad waypoints."""
    points = arrow.get("wayPoints") or []
    if len(points) < 2:
        return (0, 0)
    a, b = points[-2:]
    return (_sign(b[0] - a[0]), _sign(b[1] - a[1]))


def _edge_entry(arrow: dict, edge: str, direction: tuple[int, int], n: int) -> tuple[int, int] | None:
    """Step from the virtual off-grid cell into the first playable cell.

    SudokuPad points are [row, col]. Cell centers are [r+0.5,c+0.5]. The
    glyph midpoint selects the virtual boundary cell; the arrow direction
    then advances once into the grid. Returned row/col are one-based, matching
    the geometry payload format (so top-left playable is [1,1]).
    """
    points = arrow.get("wayPoints") or []
    if len(points) < 2:
        return None
    row = sum(p[0] for p in points[-2:]) / 2
    col = sum(p[1] for p in points[-2:]) / 2
    # Waypoint coordinates are measured from grid boundaries (0..n), so
    # floor(coord)+1 is the one-based cell lane containing that point.
    lane_row = max(1, min(n, int(math.floor(row)) + 1))
    lane_col = max(1, min(n, int(math.floor(col)) + 1))
    dr, dc = direction
    if edge == "top": outside = (0, lane_col)
    elif edge == "bottom": outside = (n + 1, lane_col)
    elif edge == "left": outside = (lane_row, 0)
    elif edge == "right": outside = (lane_row, n + 1)
    else: return None
    entry = (outside[0] + dr, outside[1] + dc)
    if not (1 <= entry[0] <= n and 1 <= entry[1] <= n):
        return None
    return entry


def parse_arrows_geometry(raw: dict, solution=None, n: int = 9) -> list[dict]:
    """Decode all arrow glyphs geometrically and report official-solution checks.

    Coordinates and entries are one-based [row, col]. This deliberately
    returns mismatches too: the geometry is unambiguous even when a supplied
    solution does not satisfy the clue along that arrow.
    """
    if isinstance(solution, str):
        solution = [int(ch) for ch in solution if ch.isdigit()]
    solution = list(solution) if solution is not None else None
    if solution is not None and len(solution) != n * n:
        raise ValueError(f"solution must contain {n*n} digits")
    clues = []
    for item in raw.get("underlays") or []:
        text = str(item.get("text", "")).strip()
        center = item.get("center")
        if text.isdigit() and center and len(center) == 2:
            clues.append((int(text), center, clue_edge(center, n)))

    out = []
    for arrow in raw.get("arrows") or []:
        edge = _edge_for_arrow(arrow, n)
        dr, dc = _point_direction(arrow)
        entry = _edge_entry(arrow, edge, (dr, dc), n) if edge else None
        matching_clues = [clue for clue, _center, clue_side in clues if clue_side == edge]
        if entry is None or (dr, dc) not in _DIRECTION_NAMES:
            continue
        if not matching_clues:
            continue
        matching_clues.sort(key=lambda item: abs(item[1][0] - arrow["wayPoints"][0][0])
                            + abs(item[1][1] - arrow["wayPoints"][0][1]))
        matching_clues = matching_clues[:1]
        cells = []
        r, c = entry
        while 1 <= r <= n and 1 <= c <= n:
            cells.append([r, c])
            r += dr
            c += dc
        actual = None
        if solution is not None:
            values = [solution[(r - 1) * n + (c - 1)] for r, c in cells]
            count = values[0]
            actual = sum(values[:count]) if 1 <= count <= len(values) else None
        clue = matching_clues[0]
        out.append({
            "direction": _DIRECTION_NAMES[(dr, dc)],
            "entry": list(entry),
            "cells": cells,
            "clue": clue,
            "xsum": actual,
            "matches_solution": actual == clue if solution is not None else None,
        })
    return out


def parse_arrows_fitted(raw: dict, puzzle, n: int = 9):
    """Decode arrows and retain only those verified by the official solution."""
    solution = getattr(puzzle, "solution", None)
    if not solution:
        return parse_arrows(raw, n)
    decoded = parse_arrows_geometry(raw, solution, n)
    return [{
        "cells": [(r - 1) * n + (c - 1) for r, c in item["cells"]],
        "total": item["clue"],
        "direction": DIRECTIONS_BY_NAME[item["direction"]],
    } for item in decoded if item["matches_solution"]]
