"""Scheduler that produces a human-style solving path, plus auditing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .narrate import Step, build_step
from .search import count_solutions, satisfiable
from .state import Contradiction, State, bits, build_units, cell_name
from .techniques import TECHNIQUES


@dataclass
class SolveResult:
    status: str  # solved | stuck | invalid
    steps: list[Step]
    values: list[int]
    message: str = ""
    audit: dict = field(default_factory=dict)


class Solver:
    def __init__(self, puzzle, rules, allow_chains: bool = False):
        self.puzzle = puzzle
        self.rules = rules
        self.units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti))
        self.state = State(puzzle.size, self.units)
        self.constraints = list(rules.constraints)
        self.allow_chains = allow_chains
        self.steps: list[Step] = []
        self.invalid: str | None = None
        try:
            for cell, value in puzzle.givens.items():
                self.state.place(cell, value)
        except Contradiction as exc:
            self.invalid = f"题目自相矛盾：{exc}"
        self.initial = self.state.dom.copy()

    def _pre(self):
        return self.state.dom.copy(), self.state.vals.copy()

    def next_step(self):
        for constraint in self.constraints:
            pre_dom, pre_vals = self._pre()
            self.state.begin()
            try:
                constraint.prune(self.state)
            except Contradiction as exc:
                self.state.record = False
                self.state.events = []
                return None, f"规则「{constraint.describe()}」推导出矛盾：{exc}"
            events = self.state.end()
            if events:
                step = build_step(len(self.steps), events, self.state.n)
                step.pre_dom, step.pre_vals = pre_dom, pre_vals
                return step, None

        for name, _tier, technique in TECHNIQUES:
            if name == "forcing_chain" and not self.allow_chains:
                continue
            pre_dom, pre_vals = self._pre()
            try:
                events = technique(self.state, self.constraints)
            except Contradiction as exc:
                self.state.record = False
                return None, f"技巧推导出矛盾：{exc}"
            if events:
                step = build_step(len(self.steps), events, self.state.n)
                step.pre_dom, step.pre_vals = pre_dom, pre_vals
                return step, None
        return None, None

    def run(self, max_steps: int = 4000) -> SolveResult:
        if self.invalid:
            return SolveResult("invalid", [], self.state.vals, self.invalid)
        while not self.state.solved:
            if len(self.steps) >= max_steps:
                return SolveResult("stuck", self.steps, self.state.vals,
                                   f"超过 {max_steps} 步仍未解完")
            step, error = self.next_step()
            if error:
                return SolveResult("invalid", self.steps, self.state.vals, error)
            if step is None:
                tried = sorted({s.technique for s in self.steps})
                hint = "" if self.allow_chains else "；可开启「反证」(--allow-chains) 尝试高级试探"
                return SolveResult(
                    "stuck", self.steps, self.state.vals,
                    f"已尝试 {len(tried)} 类技巧仍卡住{hint}",
                )
            self.steps.append(step)
        return SolveResult("solved", self.steps, self.state.vals, "")


# ------------------------------------------------------------------ validation


def check_solution(puzzle, rules, values: list[int]) -> list[str]:
    errors: list[str] = []
    units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti))
    want = set(range(1, puzzle.size + 1))
    for unit in units:
        vals = [values[c] for c in unit.cells]
        if set(vals) != want:
            errors.append(f"{unit.label} 不是 1..{puzzle.size} 的排列")
    for constraint in rules.constraints:
        if not constraint.check(values):
            errors.append(f"违反规则：{constraint.describe()}")
    return errors


def compare_with_solution(puzzle, values: list[int]) -> str | None:
    if not puzzle.solution:
        return None
    diffs = [cell_name(c, puzzle.size) for c in range(puzzle.size ** 2)
             if values[c] != puzzle.solution[c]]
    if diffs:
        return f"与题面内置答案不一致：{', '.join(diffs[:8])}"
    return None


# ------------------------------------------------------------------ audit


def audit_steps(puzzle, rules, steps: list[Step], node_limit: int = 12_000,
                max_checks: int = 240) -> dict:
    units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti))
    checks = ok = bad = unknown = 0
    for step in steps:
        step_checks = 0
        if checks >= max_checks:
            step.audit = "skipped"
            continue
        pre = State(puzzle.size, units)
        pre.dom = step.pre_dom.copy()
        pre.vals = step.pre_vals.copy()
        step_ok = True
        for event in step.events:
            if event.reason.kind == "unit_peer":
                continue
            if checks >= max_checks:
                break
            if event.kind == "elim":
                result = satisfiable(pre, rules.constraints, event.cell, event.value, node_limit)
                checks += 1
                step_checks += 1
                if result is True:
                    bad += 1
                    step_ok = False
                elif result is None:
                    unknown += 1
                else:
                    ok += 1
            else:
                for alt in bits(event.before & ~(1 << (event.value - 1))):
                    result = satisfiable(pre, rules.constraints, event.cell, alt, node_limit)
                    checks += 1
                    step_checks += 1
                    if result is True:
                        bad += 1
                        step_ok = False
                        break
                    if result is None:
                        unknown += 1
                    else:
                        ok += 1
        if not step_ok:
            step.audit = "bad"
        elif step_checks:
            step.audit = "ok"
        else:
            step.audit = "unknown"
    return {"checks": checks, "ok": ok, "bad": bad, "unknown": unknown}
