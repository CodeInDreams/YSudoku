"""Parse arrow-headed omni-directional X-Sum clues."""

from __future__ import annotations

import math


def _sign(v: float) -> int:
    return (v > 0.05) - (v < -0.05)


def direction(arrow: dict) -> tuple[int, int]:
    p = arrow.get("wayPoints") or []
    if len(p) < 2:
        return (0, 0)
    dx, dy = p[-1][0] - p[-2][0], p[-1][1] - p[-2][1]
    return (_sign(dy), _sign(dx))


def entry_cell(arrow: dict, n: int = 9) -> tuple[int, int] | None:
    start = (arrow.get("wayPoints") or [[None, None]])[-1]
    x, y = start
    if x is None or y is None:
        return None
    row = int(round(y - 0.5))
    col = int(round(x - 0.5))
    dr, dc = direction(arrow)
    return row + dr, col + dc


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
    underlays = raw.get("underlays") or []
    out = []
    for arrow in raw.get("arrows") or []:
        total = _nearest_clue(arrow, underlays)
        cells = cells_along(arrow, n)
        if total is None or len(cells) < 2:
            continue
        out.append({"cells": cells, "total": total, "direction": direction(arrow)})
    return out


def parse_arrows_fitted(raw: dict, puzzle, n: int = 9):
    """Fit arrows to the official solution when available."""
    solution = getattr(puzzle, "solution", None)
    underlays = raw.get("underlays") or []
    clues = []
    for item in underlays:
        text = str(item.get("text", "")).strip()
        if text.isdigit():
            clues.append((int(text), item.get("center", [0, 0])))
    arrows = raw.get("arrows") or []
    if not solution or not clues:
        return parse_arrows(raw, n)
    out = []
    for arrow in arrows:
        base = direction(arrow)
        if base == (0, 0):
            continue
        entries = []
        for dr, dc in (base, (-base[0], -base[1])):
            for r in range(n):
                for c in range(n):
                    if dr > 0 and r != 0:
                        continue
                    if dr < 0 and r != n - 1:
                        continue
                    if dc > 0 and c != 0:
                        continue
                    if dc < 0 and c != n - 1:
                        continue
                    cells = []
                    rr, cc = r, c
                    while 0 <= rr < n and 0 <= cc < n:
                        cells.append(rr * n + cc)
                        rr += dr
                        cc += dc
                    first = solution[cells[0]]
                    if not (1 <= first <= len(cells)):
                        continue
                    s = sum(solution[c] for c in cells[:first]) if all(solution[c] for c in cells[:first]) else None
                    if s is None:
                        continue
                    for total, center in clues:
                        if s == total:
                            head = (arrow.get("wayPoints") or [[0, 0]])[-1]
                            dist = (center[0] - head[0]) ** 2 + (center[1] - head[1]) ** 2
                            entries.append((dist, total, cells))
        if entries:
            entries.sort(key=lambda x: x[0])
            _dist, total, cells = entries[0]
            out.append({"cells": cells, "total": total, "direction": (dr, dc)})
    return out
