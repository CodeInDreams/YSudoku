"""Combine the endpoint cases of two Between Lines without solving any case by search."""

from dataclasses import dataclass
from itertools import combinations, product
from time import monotonic

from .constraints import Between, _matching_masks
from .search import _propagate_with_cause
from .state import Contradiction, Reason, Unit, bits, cell_name


@dataclass
class _HouseMatching:
    unit: Unit

    def cells(self):
        return self.unit.cells

    def prune(self, state):
        cells = self.unit.cells
        supports = _matching_masks(tuple(state.dom[c] for c in cells), state.full)
        if supports is None:
            raise Contradiction(f"{self.unit.label}没有互异布局")
        changed = False
        for cell, mask in zip(cells, supports):
            changed |= state.restrict(cell, mask)
        return changed


def _trial(state, rules, assignments):
    board = state.copy()
    board.constraints = rules
    try:
        for cell, digit in assignments:
            board.place(cell, digit)
    except Contradiction as exc:
        return None, str(exc)
    if conflict := _propagate_with_cause(board, rules):
        return None, conflict[0]
    return board.dom, None


def endpoint_support(state, constraints, deadline, max_combinations=96):
    lines = [tuple(rule.cells()) for rule in constraints if isinstance(rule, Between)]
    if len(lines) < 2 or state.n > 9:
        return None
    rules = [*constraints, *(_HouseMatching(unit) for unit in state.units
                              if len(unit.cells) == state.n)]
    options = {}
    for left, right in combinations(lines, 2):
        ends = ((left[0], left[-1]), (right[0], right[-1]))
        if len({cell for pair in ends for cell in pair}) < 3:
            continue
        for a, b in ends:
            pair = a, b
            if pair in options:
                continue
            choices = []
            for start, end in product(bits(state.dom[a]), bits(state.dom[b])):
                if abs(start - end) < 2:
                    continue
                if monotonic() >= deadline:
                    return None
                kept, _ = _trial(state, rules, ((a, start), (b, end)))
                if kept is not None:
                    choices.append((start, end))
            options[pair] = choices

        first, second = (options[pair] for pair in ends)
        if not first or not second or len(first) * len(second) > max_combinations:
            continue

        supported = [0] * state.n2
        retained, rejected = [], []
        for left_case, right_case in product(first, second):
            if monotonic() >= deadline:
                return None
            assignments = (*zip(ends[0], left_case), *zip(ends[1], right_case))
            masks, cause = _trial(state, rules, assignments)
            case = left_case, right_case
            if masks is None:
                rejected.append((case, cause))
                continue
            retained.append(case)
            supported = [a | b for a, b in zip(supported, masks)]

        if not retained:
            continue
        changes = {c: mask for c, mask in enumerate(supported) if mask != state.dom[c]}
        if changes:
            return changes, {
                "lines": (left, right), "individual": (first, second),
                "retained": retained, "rejected": rejected,
                "hypothesis": any(getattr(rule, "hypothesis", False) for rule in constraints),
            }
    return None


def apply_between_cases(solver, deadline):
    found = endpoint_support(solver.state, solver.constraints, deadline)
    if found is None:
        return None
    supported, evidence = found
    before, values = solver._pre()
    cells = list(dict.fromkeys(cell for line in evidence["lines"] for cell in line))
    solver.state.begin()
    for c, mask in supported.items():
        solver.state.restrict(c, mask, Reason("between_cases", {"cells": cells}))
    step = solver._commit(solver.state.end(), before, values)
    step.technique, step.title, step.tier = "between_cases", "之间线端点组合", 3
    step.detail = between_cases_text(evidence, solver.state.n, "zh")
    step.narration = evidence
    step.visual["groups"] = [{"cells": list(line), "kind": "line"} for line in evidence["lines"]]
    step.visual["premise"] = [c for line in evidence["lines"] for c in (line[0], line[-1])]
    solver.steps.append(step)
    return step


def between_cases_text(evidence, n, lang, *, expanded=False):
    english = lang == "en"
    lines = []
    for scope, options in zip(evidence["lines"], evidence["individual"]):
        names = f"{cell_name(scope[0], n)} → {cell_name(scope[-1], n)}"
        line = f"{names} · {len(options)} " + ("endpoint pairs" if english else "组端点取值")
        if expanded:
            line += " · " + ", ".join(f"({a}, {b})" for a, b in options)
        lines.append(line)
    tried = len(evidence["retained"]) + len(evidence["rejected"])
    kept = len(evidence["retained"])
    lines.append(
        f"Pair the endpoint choices and propagate the clues and all-different houses. "
        f"{kept} of {tried} combined cases survive. Keep only candidates supported by a surviving case."
        if english else
        f"把两条线的端点选择配对，再传播题规和每个行列宫的互异限制。"
        f"{tried} 种组合中剩下 {kept} 种。只保留至少有一种组合支持的候选。"
    )
    if expanded:
        from .step_locale import _cause
        retained = [f"({a}, {b}) / ({c}, {d})" for (a, b), (c, d) in evidence["retained"]]
        lines.append(("Surviving cases" if english else "保留的组合") + " · " + ", ".join(retained))
        for cases, cause in evidence["rejected"]:
            pairs = " / ".join(f"({a}, {b})" for a, b in cases)
            lines.append(f"{pairs} · " + (_cause(cause, None, n) if english else cause))
    return "\n".join(lines)
