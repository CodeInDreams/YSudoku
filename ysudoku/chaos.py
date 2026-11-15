"""Chaos construction: regions are unknown and must be discovered.

This is a *search* solver, not a human-style deduction engine.  It assigns
region membership and digits together and returns the first consistent
solution.  It is deliberately bounded: unsolved boards return ``timeout``
instead of running forever.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class _Timeout(Exception):
    pass


@dataclass
class ChaosResult:
    status: str  # solved | timeout | unsupported
    values: list[int]
    regions: list[list[int]] = field(default_factory=list)
    nodes: int = 0
    message: str = ""


def _neighbors(cell: int, n: int):
    r, c = divmod(cell, n)
    if r > 0:
        yield cell - n
    if r + 1 < n:
        yield cell + n
    if c > 0:
        yield cell - 1
    if c + 1 < n:
        yield cell + 1


def solve_chaos(puzzle, constraints, node_limit: int = 300_000,
                time_limit: float = 20.0) -> ChaosResult:
    n = puzzle.size
    if n > 9:
        return ChaosResult("unsupported", [0] * (n * n), message="仅支持 9x9 及以下")
    total = n * n
    givens = dict(puzzle.givens)
    values = [0] * total
    region_of = [-1] * total
    region_cells: list[list[int]] = []
    region_used: list[set[int]] = []
    row_used = [set() for _ in range(n)]
    col_used = [set() for _ in range(n)]
    nodes = [0]
    started = time.time()
    cage_rules = []
    for con in constraints:
        total = getattr(con, "total", None)
        if con.kind == "cage" and total is not None:
            cage_rules.append((set(con.cells()), int(total), bool(getattr(con, "unique", True))))

    def cages_ok() -> bool:
        for cells, total, unique in cage_rules:
            vals = [values[c] for c in cells if values[c]]
            if unique and len(set(vals)) != len(vals):
                return False
            if len(vals) == len(cells):
                if sum(vals) != total:
                    return False
                continue
            remaining = len(cells) - len(vals)
            if not (sum(vals) + remaining <= total <= sum(vals) + remaining * n):
                return False
        return True

    def region_can_grow(index: int) -> bool:
        cells = region_cells[index]
        if len(cells) >= n:
            return True
        return any(region_of[nb] == -1 for c in cells for nb in _neighbors(c, n))

    def check_all() -> bool:
        for con in constraints:
            if not con.check(values):
                return False
        return True

    def dfs(pos: int):
        nodes[0] += 1
        if nodes[0] % 2048 == 0 and time.time() - started > time_limit:
            raise _Timeout
        if nodes[0] > node_limit:
            raise _Timeout
        if pos == total:
            if all(len(cells) == n for cells in region_cells) and check_all():
                return list(values), [list(cells) for cells in region_cells]
            return None

        cell = pos
        r, c = divmod(cell, n)
        adjacent = {
            region_of[nb] for nb in _neighbors(cell, n) if region_of[nb] >= 0
        }
        options = [rr for rr in adjacent if len(region_cells[rr]) < n]
        can_start = len(region_cells) < n
        if can_start:
            options.append(-1)

        for choice in options:
            created = False
            if choice == -1:
                choice = len(region_cells)
                region_cells.append([])
                region_used.append(set())
                created = True
            region_cells[choice].append(cell)
            region_of[cell] = choice
            digits = [givens[cell]] if cell in givens else range(1, n + 1)
            ok = False
            for digit in digits:
                if digit in row_used[r] or digit in col_used[c] or digit in region_used[choice]:
                    continue
                values[cell] = digit
                row_used[r].add(digit)
                col_used[c].add(digit)
                region_used[choice].add(digit)
                if not cages_ok() or not region_can_grow(choice):
                    row_used[r].discard(digit)
                    col_used[c].discard(digit)
                    region_used[choice].discard(digit)
                    values[cell] = 0
                    continue
                try:
                    result = dfs(pos + 1)
                finally:
                    row_used[r].discard(digit)
                    col_used[c].discard(digit)
                    region_used[choice].discard(digit)
                if result:
                    return result
                values[cell] = 0
            region_cells[choice].pop()
            region_of[cell] = -1
            if created:
                region_cells.pop()
                region_used.pop()
        return None

    try:
        result = dfs(0)
    except _Timeout:
        return ChaosResult("timeout", [0] * total, nodes=nodes[0],
                           message=f"搜索超过预算（{nodes[0]} 结点）")
    if result is None:
        return ChaosResult("unsupported", [0] * total, nodes=nodes[0],
                           message="在预算内没有找到一致解")
    values_out, regions_out = result
    return ChaosResult("solved", values_out, regions_out, nodes=nodes[0],
                       message=f"搜索 {nodes[0]} 个结点后找到一致解")


def check_chaos_solution(puzzle, constraints, values: list[int], regions: list[list[int]]) -> list[str]:
    n = puzzle.size
    want = set(range(1, n + 1))
    errors: list[str] = []
    for r in range(n):
        if set(values[r * n:(r + 1) * n]) != want:
            errors.append(f"第{r + 1}行不完整")
    for c in range(n):
        if {values[r * n + c] for r in range(n)} != want:
            errors.append(f"第{c + 1}列不完整")
    if len(regions) != n or any(len(reg) != n for reg in regions):
        errors.append("区域数量或大小不对")
    for i, reg in enumerate(regions):
        if {values[cell] for cell in reg} != want:
            errors.append(f"区域{i + 1}不是 1..{n} 的排列")
    for con in constraints:
        if not con.check(values):
            errors.append(f"违反规则：{con.describe()}")
    return errors
