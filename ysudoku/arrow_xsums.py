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
    start = (arrow.get("wayPoints") or [[None, None]])[0]
    x, y = start
    if x is None or y is None:
        return None
    if x < 0:
        col = 0
        row = max(0, min(n - 1, int(round(y - 0.5))))
    elif x > n:
        col = n - 1
        row = max(0, min(n - 1, int(round(y - 0.5))))
    elif y < 0:
        row = 0
        col = max(0, min(n - 1, int(round(x - 0.5))))
    elif y > n:
        row = n - 1
        col = max(0, min(n - 1, int(round(x - 0.5))))
    else:
        return None
    return row, col


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
