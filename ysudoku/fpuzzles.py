"""Import supported f-puzzles geometry into the SudokuPad drawing inventory."""

from math import isqrt
import re


_METADATA = {"size", "grid", "title", "author", "ruleset", "solution",
             "successMessage", "disabledlogic", "truecandidatesoptions"}
_SUPPORTED = {"killercage", "line", "ratio", "difference"}


def _cell(name, n):
    match = re.fullmatch(r"R([1-9]\d*)C([1-9]\d*)", name, re.I) if isinstance(name, str) else None
    if match:
        row, col = (int(v) - 1 for v in match.groups())
        if row < n and col < n:
            return [row, col]
    raise ValueError(f"f-puzzles 格坐标无效：{name!r}")


def _centre(cells, n):
    a, b = (_cell(name, n) for name in cells)
    if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
        raise ValueError("f-puzzles Kropki 点必须连接两个正交相邻格")
    return [(a[i] + b[i] + 1) / 2 for i in range(2)]


def normalize_fpuzzles(data):
    if not isinstance(data, dict):
        raise ValueError("f-puzzles 盘面必须是 JSON 对象")
    unsupported = sorted(key for key, value in data.items() if value and key not in _METADATA | _SUPPORTED)
    if unsupported:
        raise ValueError("暂不支持这些 f-puzzles 元素：" + "、".join(unsupported))
    n = data.get("size")
    grid = data.get("grid")
    if type(n) is not int or not 1 <= n <= 16 or not isinstance(grid, list) or len(grid) != n or any(
        not isinstance(row, list) or len(row) != n for row in grid
    ):
        raise ValueError("f-puzzles 网格尺寸无效")

    height = next(h for h in range(isqrt(n), 0, -1) if n % h == 0)
    width = n // height
    regions = [[] for _ in range(n)]
    cells = []
    for r, row in enumerate(grid):
        converted = []
        for c, cell in enumerate(row):
            if not isinstance(cell, dict):
                raise ValueError("f-puzzles 网格包含无效格数据")
            region = cell.get("region", (r // height) * height + c // width)
            if type(region) is not int or not 0 <= region < n:
                raise ValueError("f-puzzles 区域编号无效")
            regions[region].append([r, c])
            if cell.get("given"):
                value = int(cell["value"])
                if not 1 <= value <= n:
                    raise ValueError("f-puzzles 给定数超出网格尺寸")
                converted.append({"value": value})
            else:
                converted.append({})
        cells.append(converted)
    if any(len(region) != n for region in regions):
        raise ValueError("f-puzzles 区域的格数与网格尺寸不符")

    lines = []
    for line in data.get("line") or []:
        for segment in line["lines"]:
            points = [[r + 0.5, c + 0.5] for r, c in (_cell(name, n) for name in segment)]
            lines.append({"wayPoints": points, "color": line.get("outlineC"),
                          "thickness": float(line.get("width", 0.25)) * 64})
    dots = []
    for kind, values, colour in (("ratio", ("2", "2:1"), "#000000"),
                                  ("difference", ("1",), "#ffffff")):
        for dot in data.get(kind) or []:
            value = dot.get("value")
            if value is not None and str(value) not in ("", *values):
                raise ValueError(f"暂不支持该 f-puzzles {kind} 点的数值")
            dots.append({"center": _centre(dot["cells"], n), "width": 0.3, "height": 0.3,
                         "rounded": True, "backgroundColor": colour})
    metadata = {"title": data.get("title") or "Untitled", "author": data.get("author") or "",
                "rules": data.get("ruleset") or ""}
    solution = data.get("solution")
    if isinstance(solution, list):
        solution = "".join(map(str, solution))
    if isinstance(solution, str) and len(solution) == n * n and solution.isascii() and solution.isdigit():
        metadata["solution"] = solution

    return {
        "format": "fpuz", "cells": cells, "regions": regions, "metadata": metadata,
        "cages": [{"cells": [_cell(cell, n) for cell in cage["cells"]],
                   "value": cage.get("value")} for cage in data.get("killercage") or []],
        "lines": lines, "overlays": dots,
    }
