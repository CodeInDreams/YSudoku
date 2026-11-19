"""Structured geometry payload/validator for LLM arrow extraction."""

from __future__ import annotations

DIRECTIONS = {
    "up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1),
    "up-left": (-1, -1), "up-right": (-1, 1),
    "down-left": (1, -1), "down-right": (1, 1),
}


def geometry_payload(puzzle, arrows: list[dict], underlays: list[dict]):
    rows = len(puzzle.raw.get("cells") or [])
    cols = len((puzzle.raw.get("cells") or [[]])[0])
    return {
        "coordinate_system": "row,col, 1-based, top-left=(1,1)",
        "canvas": [rows, cols],
        "playable": [puzzle.size, puzzle.size],
        "playable_origin": [1, 1],
        "arrows": arrows,
        "underlays": underlays,
    }


def validate_arrow(item: dict, n: int):
    direction = item.get("direction")
    if direction not in DIRECTIONS:
        raise ValueError(f"bad direction {direction}")
    dr, dc = DIRECTIONS[direction]
    entry = item.get("entry") or []
    if len(entry) != 2:
        raise ValueError("entry must be [row,col]")
    r, c = int(entry[0]), int(entry[1])
    if not (1 <= r <= n and 1 <= c <= n):
        raise ValueError("entry outside playable grid")
    cells = item.get("cells") or []
    if len(cells) < 2:
        raise ValueError("arrow too short")
    expected = []
    rr, cc = r, c
    while 1 <= rr <= n and 1 <= cc <= n:
        expected.append([rr, cc])
        rr += dr
        cc += dc
    if [[int(x[0]), int(x[1])] for x in cells] != expected:
        raise ValueError("cells do not follow direction")
    total = item.get("clue")
    if not isinstance(total, int) or total < 1:
        raise ValueError("bad clue")
    return {
        "cells": [(r0 - 1) * n + (c0 - 1) for r0, c0 in expected],
        "total": total,
        "direction": direction,
    }


def validate_all(items, n):
    out = []
    clues = set()
    for item in items:
        rule = validate_arrow(item, n)
        if rule["total"] in clues:
            raise ValueError("duplicate clue")
        clues.add(rule["total"])
        out.append(rule)
    return out
