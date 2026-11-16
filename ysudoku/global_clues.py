"""Global outside-clue solver (Full Rank + X-Sums + unknown type pairing).

The normal engine reasons locally.  This module exists for puzzles whose clues
are global properties of whole lines, which cannot be propagated cell by cell.
It uses OR-Tools CP-SAT and is an *optional* dependency: without it, puzzles of
this class are reported as unsupported rather than silently stalled.
"""

from __future__ import annotations

from collections import defaultdict


class GlobalSolverUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        from ortools.sat.python import cp_model  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - optional dependency
        return False


def _line_cells(clue, n: int):
    if clue.side in ("left", "right"):
        cells = [(clue.index, c) for c in range(n)]
        if clue.side == "right":
            cells = cells[::-1]
    else:
        cells = [(r, clue.index) for r in range(n)]
        if clue.side == "bottom":
            cells = cells[::-1]
    return cells


def solve(puzzle, time_limit: float = 60.0):
    """Return {'grid': [[...]], 'types': ['R'|'X'], 'status': ...} or None."""
    try:
        from ortools.sat.python import cp_model
    except Exception as exc:  # noqa: BLE001
        raise GlobalSolverUnavailable(
            "需要可选依赖 OR-Tools：pip install ortools"
        ) from exc

    n = puzzle.size
    if not puzzle.clues:
        return None
    text = (puzzle.rules_text or "").lower()
    has_rank = "full rank" in text or "full-rank" in text
    has_xsum = "x-sums" in text or "x sums" in text or "xsum" in text
    if not has_rank and not has_xsum:
        return None

    model = cp_model.CpModel()
    x = [[model.NewIntVar(1, n, f"x{r}_{c}") for c in range(n)] for r in range(n)]
    for r in range(n):
        model.AddAllDifferent(x[r])
    for c in range(n):
        model.AddAllDifferent([x[r][c] for r in range(n)])
    box = 3 if n == 9 else (2 if n == 6 else 2)
    width = n // box if n % box == 0 else 3
    for br in range(0, n, box):
        for bc in range(0, n, width):
            model.AddAllDifferent([
                x[r][c] for r in range(br, br + box) for c in range(bc, bc + width)
            ])

    numbers = []
    for r in range(n):
        numbers.append(sum(x[r][c] * 10 ** (n - 1 - c) for c in range(n)))
        numbers.append(sum(x[r][c] * 10 ** c for c in range(n)))
    for c in range(n):
        numbers.append(sum(x[r][c] * 10 ** (n - 1 - r) for r in range(n)))
        numbers.append(sum(x[r][c] * 10 ** r for r in range(n)))

    flags = []
    for i, clue in enumerate(puzzle.clues):
        cells = _line_cells(clue, n)
        vals = [x[r][c] for r, c in cells]
        first = vals[0]
        flag = model.NewBoolVar(f"rank_{i}")
        flags.append(flag)

        pref = [None]
        for k in range(1, n + 1):
            var = model.NewIntVar(0, n * (n + 1) // 2, f"pref_{i}_{k}")
            model.Add(var == sum(vals[:k]))
            pref.append(var)
        idx = model.NewIntVar(1, n, f"idx_{i}")
        model.Add(idx == first)
        total = model.NewIntVar(0, n * (n + 1) // 2, f"total_{i}")
        model.AddElement(idx - 1, pref[1:], total)
        model.Add(total == clue.value).OnlyEnforceIf(flag.Not())

        num = sum(vals[j] * 10 ** (n - 1 - j) for j in range(n))
        cmps = []
        for m_expr in numbers:
            b = model.NewBoolVar(f"cmp_{i}_{len(cmps)}")
            model.Add(m_expr < num).OnlyEnforceIf(b)
            model.Add(m_expr >= num).OnlyEnforceIf(b.Not())
            cmps.append(b)
        rank = model.NewIntVar(1, 2 * n + 2 * n, f"rankval_{i}")
        model.Add(rank == 1 + sum(cmps))
        model.Add(rank == clue.value).OnlyEnforceIf(flag)

    if has_rank and has_xsum:
        by_value = defaultdict(list)
        for i, clue in enumerate(puzzle.clues):
            by_value[clue.value].append(i)
        for idxs in by_value.values():
            if len(idxs) == 2:
                model.AddBoolXOr([flags[idxs[0]], flags[idxs[1]]])
    elif has_xsum and not has_rank:
        for flag in flags:
            model.Add(flag == 0)
    elif has_rank and not has_xsum:
        for flag in flags:
            model.Add(flag == 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": solver.StatusName(status)}
    grid = [[solver.Value(x[r][c]) for c in range(n)] for r in range(n)]
    types = ["R" if solver.Value(flags[i]) else "X" for i in range(len(puzzle.clues))]
    return {"status": "solved", "grid": grid, "types": types}


def verify(puzzle, values: list[int], types: list[str]) -> list[str]:
    """Re-check the clue semantics on a complete grid."""
    n = puzzle.size
    errors: list[str] = []
    numbers = []
    for r in range(n):
        numbers.append(int("".join(str(values[r * n + c]) for c in range(n))))
        numbers.append(int("".join(str(values[r * n + c]) for c in range(n - 1, -1, -1))))
    for c in range(n):
        numbers.append(int("".join(str(values[r * n + c]) for r in range(n))))
        numbers.append(int("".join(str(values[r * n + c]) for r in range(n - 1, -1, -1))))
    for i, clue in enumerate(puzzle.clues):
        cells = _line_cells(clue, n)
        vals = [values[r * n + c] for r, c in cells]
        if i < len(types) and types[i] == "R":
            num = int("".join(str(v) for v in vals))
            rank = 1 + sum(1 for m in numbers if m < num)
            if rank != clue.value:
                errors.append(f"Full Rank clue #{i} expected {clue.value}, got {rank}")
        else:
            x_sum = sum(vals[:vals[0]])
            if x_sum != clue.value:
                errors.append(f"X-Sums clue #{i} expected {clue.value}, got {x_sum}")
    return errors
