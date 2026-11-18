"""Scheduler that produces a human-style solving path, plus auditing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .narrate import Step, build_step
from .search import count_solutions, satisfiable
from .state import Contradiction, Event, Reason, State, bits, build_units, cell_name
from .techniques import TECHNIQUES, TRIGGERS


@dataclass
class SolveResult:
    status: str  # solved | stuck | invalid
    steps: list[Step]
    values: list[int]
    message: str = ""
    audit: dict = field(default_factory=dict)


class Solver:
    def __init__(self, puzzle, rules, allow_chains: bool = False, on_step=None):
        self.puzzle = puzzle
        self.rules = rules
        self.units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti),
                                 chaos=puzzle.is_chaos)
        self.state = State(puzzle.size, self.units)
        self.constraints = list(rules.constraints)
        self.allow_chains = allow_chains
        self.on_step = on_step
        self.steps: list[Step] = []
        self.focus: set[int] = set()
        self.invalid: str | None = None
        try:
            for cell, value in puzzle.givens.items():
                self.state.place(cell, value)
        except Contradiction as exc:
            self.invalid = f"题目自相矛盾：{exc}"
        self.initial = self.state.dom.copy()

    def _pre(self):
        return self.state.dom.copy(), self.state.vals.copy()

    def _candidates(self, events, pre_dom):
        masks: dict[int, int] = {}
        for ev in events:
            if ev.kind not in ("elim", "place"):
                continue
            if ev.cell not in masks:
                masks[ev.cell] = pre_dom[ev.cell]
            if ev.kind == "elim":
                masks[ev.cell] &= ~(1 << (ev.value - 1))
            else:
                masks[ev.cell] = 1 << (ev.value - 1)
        out = []
        for cell, mask in masks.items():
            digits = [v for v in range(1, self.state.n + 1) if mask & (1 << (v - 1))]
            if digits:
                out.append({"cell": cell, "digits": digits})
        return out[:8]

    def _commit(self, events, pre_dom, pre_vals):
        events = [e for e in events if not pre_vals[e.cell]]
        if not events:
            return None
        events = [
            e for e in self.state.events
            if e.kind == "place" or not self.state.vals[e.cell]
        ]
        step = build_step(len(self.steps), events, self.state.n)
        step.pre_dom, step.pre_vals = pre_dom, pre_vals
        step.candidates = self._candidates(events, pre_dom)
        placed = {e.cell for e in events if e.kind == "place"}
        primary = {e.cell for e in events if e.reason.kind != "unit_peer"}
        self.focus = placed or primary or {events[0].cell}
        return step

    def _technique_step(self, name, technique):
        trigger = TRIGGERS.get(name)
        if trigger is not None and not trigger(self.state):
            return None
        pre_dom, pre_vals = self._pre()
        try:
            events = technique(self.state, self.constraints)
        except Contradiction as exc:
            self.state.record = False
            return None, f"技巧推导出矛盾：{exc}"
        if not events:
            return None
        return self._commit(events, pre_dom, pre_vals)

    def _constraint_step(self, constraint):
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
            # A rule/constraint that itself leaves one host in its scope fills it
            # immediately. Peer eliminations outside the scope remain dependent
            # follow-up steps.
            reason = events[0].reason
            for cell in constraint.cells():
                if self.state.vals[cell] or self.state.dom[cell].bit_count() != 1:
                    continue
                value = (self.state.dom[cell] & -self.state.dom[cell]).bit_length()
                self.state.record = True
                self.state.place(cell, value, reason)
                self.state.record = False
            events = self.state.events
            return self._commit(events, pre_dom, pre_vals)
        return None

    def next_step(self):
        # Explicit user/predicate constraints are authoritative and run first.
        for constraint in self.constraints:
            if getattr(constraint, "kind", "") != "custom":
                continue
            result = self._constraint_step(constraint)
            if isinstance(result, tuple):
                return result
            if result is not None:
                return result, None

        # Singles first: after every placement, close all naked/hidden singles
        # before spending a step on a global rule.
        by_name = {name: (name, technique) for name, _tier, technique in TECHNIQUES}
        for name in ("naked_single", "hidden_single"):
            _name, technique = by_name[name]
            result = self._technique_step(name, technique)
            if isinstance(result, tuple):
                return result
            if result is not None:
                return result, None

        # Then constraints, preferring ones around the last step and ones whose
        # cells have the fewest remaining candidates.
        def constraint_key(constraint):
            cells = constraint.cells()
            overlap = len(set(cells) & self.focus)
            smallest = min(
                (self.state.dom[cell].bit_count() for cell in cells
                 if not self.state.vals[cell]),
                default=self.state.n + 1,
            )
            return (-overlap, smallest)

        ordered = sorted(self.constraints, key=constraint_key)
        for constraint in ordered:
            if getattr(constraint, "kind", "") == "custom":
                continue
            result = self._constraint_step(constraint)
            if isinstance(result, tuple):
                return result
            if result is not None:
                return result, None

        for name, _tier, technique in TECHNIQUES:
            if name in ("naked_single", "hidden_single"):
                continue
            if name == "forcing_chain" and not self.allow_chains:
                continue
            result = self._technique_step(name, technique)
            if isinstance(result, tuple):
                return result
            if result is not None:
                return result, None
        return None, None

    def _merge_sibling_singles(self, steps: list[Step]) -> list[Step]:
        """Merge all independent singles directly caused by the same origin.

        Dependent steps may sit between siblings; they stay in place, while the
        direct children are folded into the first child step.
        """
        i = 0
        while i < len(steps):
            origin = steps[i]
            origin_cells = {e.cell for e in origin.events}
            direct: list[int] = []
            j = i + 1
            while j < len(steps) and steps[j].technique in (
                "naked_single", "hidden_single",
            ):
                places = [e for e in steps[j].events if e.kind == "place"]
                if places and all(p.cell in origin_cells for p in places):
                    cells = {p.cell for p in places}
                    blocked = any(
                        e.cell in cells
                        for middle in steps[i + 1:j]
                        for e in middle.events
                    )
                    if not blocked:
                        direct.append(j)
                j += 1
            if len(direct) >= 2:
                target = steps[direct[0]]
                remove: list[int] = []
                for k in direct[1:]:
                    right = steps[k]
                    right_places = [e for e in right.events if e.kind == "place"]
                    target_places = {e.cell for e in target.events if e.kind == "place"}
                    if any(p.cell in target_places for p in right_places):
                        continue
                    target.events.extend(right.events)
                    target.candidates = target.candidates + [
                        c for c in right.candidates
                        if c["cell"] not in {x["cell"] for x in target.candidates}
                    ]
                    target.visual["focus"] = sorted(
                        set(target.visual.get("focus", []))
                        | set(right.visual.get("focus", []))
                    )
                    extra = "；".join(
                        f"{cell_name(p.cell, self.state.n)} = {p.value}"
                        for p in right_places
                    )
                    target.detail = target.detail + "\n" + extra
                    remove.append(k)
                for k in reversed(remove):
                    steps.pop(k)
            i += 1
        for index, step in enumerate(steps):
            step.index = index
        return steps

    def _contradiction_intro(self, cell: int, value: int, phase: str,
                             pre_dom: list[int], pre_vals: list[int]) -> Step:
        name = cell_name(cell, self.state.n)
        prefix = {"start": "反证开始", "check": "反证检查"}[phase]
        label = f"{prefix}：假设 {name}={value}"
        if phase == "start":
            detail = (
                f"反证开始：假设 {name} = {value}。\n"
                "这是一个临时假设，不写入正式棋盘；接下来检查它是否导出矛盾。"
            )
        else:
            detail = (
                f"反证检查：在假设 {name} = {value} 下继续传播约束并穷举分支。\n"
                "如果所有分支都无解，这个假设就被推翻。"
            )
        visual = {
            "focus": [],
            "premise": [],
            "groups": [{"cells": [cell], "kind": "assumption"}],
            "links": [],
            "chips": [],
            "assumption": {"cells": [cell], "label": label},
        }
        step = Step(
            index=len(self.steps), technique="contradiction", tier=4,
            title=prefix, detail=detail, events=[], visual=visual,
        )
        step.pre_dom, step.pre_vals = pre_dom, pre_vals
        step.candidates = []
        return step

    def _minimal_trace(self, child, trace, cause="", assumption_cell=None):
        n = child.n
        dom = list(child.dom)
        for e in trace:
            if e.kind == "place":
                dom[e.cell] = 1 << (e.value - 1)
            else:
                dom[e.cell] &= ~(1 << (e.value - 1))
        empty = next((c for c in range(len(dom)) if dom[c] == 0), None)
        if empty is None:
            import re
            m = re.search(r"(\d+)行(\d+)列没有候选", cause)
            if m:
                empty = (int(m.group(1)) - 1) * n + int(m.group(2)) - 1
        if empty is None:
            return list(trace)

        last_place = {}
        last_elim = {}
        for idx, e in enumerate(trace):
            if e.kind == "place":
                last_place[e.cell] = idx
            else:
                last_elim[(e.cell, e.value)] = idx

        needed = set()

        def scope_cells(event):
            data = event.reason.data or {}
            cells = set()
            for key in ("cells", "unit_cells", "arm"):
                for item in data.get(key) or []:
                    if isinstance(item, int):
                        cells.add(item)
            for key in ("a", "b", "by", "circle", "cell"):
                item = data.get(key)
                if isinstance(item, int):
                    cells.add(item)
            return cells

        def require(idx):
            if idx in needed or idx < 0 or idx >= len(trace):
                return
            needed.add(idx)
            e = trace[idx]
            if e.kind == "elim" and e.reason.kind == "unit_peer":
                by = e.reason.data.get("by")
                if by in last_place and last_place[by] < idx:
                    require(last_place[by])
                return
            if e.kind == "elim":
                scope = scope_cells(e)
                for j in range(idx):
                    if trace[j].cell in scope:
                        require(j)
                return
            if e.kind == "place":
                if e.reason.kind in ("probe_single", "naked_single"):
                    for v in range(1, n + 1):
                        if v != e.value and (e.cell, v) in last_elim and last_elim[(e.cell, v)] < idx:
                            require(last_elim[(e.cell, v)])
                elif e.reason.kind in ("probe_hidden", "hidden_single"):
                    for c in e.reason.data.get("unit_cells") or []:
                        if c != e.cell and (c, e.value) in last_elim and last_elim[(c, e.value)] < idx:
                            require(last_elim[(c, e.value)])

        for v in range(1, n + 1):
            if (empty, v) in last_elim:
                require(last_elim[(empty, v)])
        selected = [trace[i] for i in sorted(needed)]
        selected = [e for e in selected if not (
            e.kind == "elim" and e.reason.kind == "unit_peer"
            and e.reason.data.get("by") == assumption_cell)]
        return selected or list(trace)

    def _scope_note(self, chunk):
        if not chunk:
            return ""
        data = chunk[0].reason.data or {}
        kind = chunk[0].reason.kind
        if kind == "unit_peer" and data.get("by") is not None:
            return f"理由：{cell_name(data['by'], self.state.n)} 已填，同区排除。"
        if kind == "xv":
            return f"参与：{cell_name(data['a'], self.state.n)} / {cell_name(data['b'], self.state.n)}（V/X 配对）。"
        if kind == "arrow":
            circle = data.get("circle")
            arm = data.get("arm") or []
            return ("参与：圆 " + cell_name(circle, self.state.n) + "，箭身 "
                    + "、".join(cell_name(c, self.state.n) for c in arm) + "。")
        if kind in ("german_whisper", "dutch_whisper"):
            return f"参与：{cell_name(data['a'], self.state.n)} / {cell_name(data['b'], self.state.n)}。"
        return ""

    def _why_placed(self, event, pre_dom):
        data = event.reason.data or {}
        n = self.state.n
        values = lambda cell: [v for v in range(1, n + 1) if pre_dom[cell] >> (v - 1) & 1]
        if event.reason.kind == "naked_single":
            return f"{cell_name(event.cell, n)} 的候选只剩 {values(event.cell)}。"
        if event.reason.kind == "hidden_single":
            unit = data.get("unit", "所在单元")
            others = [c for c in data.get("unit_cells") or []
                      if c != event.cell and event.value in values(c)]
            return (f"{unit} 中数字 {event.value} 只能放在 {cell_name(event.cell, n)}；"
                    f"其他格候选均不含 {event.value}。")
        return ""

    def _why_eliminated(self, event, pre_dom):
        from itertools import product
        data = event.reason.data or {}
        kind = event.reason.kind
        n = self.state.n
        values = lambda cell: [v for v in range(1, n + 1) if pre_dom[cell] >> (v - 1) & 1]
        cell = event.cell
        value = event.value
        if kind == "unit_peer" and data.get("by") is not None:
            return f"{cell_name(data['by'], n)} 已经填入，同区不能再填 {value}。"
        if kind == "xv":
            a, b = data.get("a"), data.get("b")
            other = b if cell == a else a
            need = int(data.get("sum", 10)) - value
            allowed = [v for v in values(other) if v == need]
            return (f"若 {cell_name(cell, n)}={value}，则 {cell_name(other, n)} 必须为 {need}；"
                    f"当前候选 {values(other)}，{'可行' if allowed else '无交集'}。")
        if kind == "arrow":
            circle = data.get("circle")
            arm = data.get("arm") or []
            if cell == circle:
                return (f"箭身 {arm and '、'.join(cell_name(c, n) for c in arm)} 的候选和无法等于 {value}。")
            others = [c for c in arm if c != cell]
            circle_values = values(circle)
            sums = set()
            for combo in product(*[values(c) for c in others]):
                total = sum(combo) + value
                if total in circle_values:
                    sums.add(total)
            return (f"若 {cell_name(cell, n)}={value}，箭身可行和需落在圆 {cell_name(circle, n)} 的候选 "
                    f"{circle_values}；当前{'有' if sums else '没有任何'}匹配和。")
        if kind in ("german_whisper", "dutch_whisper"):
            a, b = data.get("a"), data.get("b")
            other = b if cell == a else a
            partners = [v for v in values(other) if abs(v - value) >= 5]
            return (f"若 {cell_name(cell, n)}={value}，{cell_name(other, n)} 需与它差至少 5；"
                    f"当前候选 {values(other)}，{'有' if partners else '没有'}合法伙伴。")
        return ""

    def _group_events(self, events):
        groups = []
        for e in events:
            data = e.reason.data or {}
            scope = tuple(sorted(data.get("cells") or data.get("unit_cells") or []))
            key = (e.reason.kind, scope, data.get("by"))
            if groups and groups[-1][0] == key:
                groups[-1][1].append(e)
            else:
                groups.append((key, [e]))
        merged = []
        for key, group in groups:
            if (len(group) == 1 and group[0].kind == "place"
                    and group[0].reason.kind in ("probe_single", "naked_single")):
                cell = group[0].cell
                for prev in reversed(merged):
                    if any(e.cell == cell and e.kind == "elim" for e in prev):
                        prev.append(group[0])
                        break
                else:
                    merged.append(group)
                continue
            merged.append(group)
        return merged

    def contradiction_step(self, deadline: float, per_candidate: float = 1.2):
        import time
        from .search import refute_direct_with_trace
        pre_dom, pre_vals = self._pre()
        cells = sorted((c for c in range(self.state.n2) if not self.state.vals[c]),
                       key=lambda c: self.state.dom[c].bit_count())
        best = None
        tested = 0
        for cell in cells:
            if time.time() > deadline:
                break
            values = list(bits(self.state.dom[cell]))
            if len(values) < 2:
                continue
            for value in values:
                if time.time() > deadline or tested >= 80:
                    break
                refuted, trace, cause = refute_direct_with_trace(
                    self.state, self.constraints, cell, value)
                tested += 1
                if refuted is not True:
                    continue
                meaningful = [e for e in trace
                              if e.kind == "place" or e.reason.kind != "unit_peer"]
                score = (
                    1 if len(values) == 2 else 0,
                    sum(1 for e in meaningful if e.kind == "place"),
                    sum(1 for e in meaningful if e.kind == "elim"),
                    len({e.reason.kind for e in meaningful}),
                    -len(meaningful),
                    -len(values),
                )
                if best is None or score > best[0]:
                    best = (score, cell, value, values, trace, cause)
            if time.time() > deadline:
                break
        if best is None:
            return None
        _, cell, value, values, trace, cause = best
        name = cell_name(cell, self.state.n)

        intro = Step(
            index=len(self.steps), technique="contradiction", tier=4,
            title="反证开始",
            detail=f"反证开始：假设 {name} = {value}。",
            events=[Event("place", cell, value, Reason("contradiction", {
                "cell": cell, "value": value, "phase": "start"}), pre_dom[cell])],
            visual={"focus": [], "premise": [],
                    "groups": [{"cells": [cell], "kind": "assumption"}],
                    "links": [], "chips": [],
                    "assumption": {"cells": [cell],
                                   "label": f"反证开始：假设 {name}={value}"}},
            branch=True)
        intro.pre_dom, intro.pre_vals = pre_dom, pre_vals
        intro.candidates = [{"cell": cell, "digits": [value]}]
        self.steps.append(intro)
        if self.on_step:
            try: self.on_step(intro)
            except Exception: pass

        child = self.state.copy()
        child.place(cell, value, Reason("contradiction", {
            "cell": cell, "value": value, "phase": "start"}))
        minimal = self._minimal_trace(child, list(trace), cause, cell)
        chunks = self._group_events(minimal)
        run_state = child
        for index, chunk in enumerate(chunks):
            if not chunk:
                continue
            pre_dom = list(run_state.dom)
            pre_vals = list(run_state.vals)
            lines = [f"反证推理（{index + 1}/{len(chunks)}）：在假设 {name} = {value} 下："]
            for event in chunk:
                if event.kind == "place":
                    lines.append(f"→ {cell_name(event.cell, self.state.n)} = {event.value}（{event.reason.kind}）")
                else:
                    lines.append(f"→ {cell_name(event.cell, self.state.n)} ≠ {event.value}（{event.reason.kind}）")
            support_dom = list(pre_dom)
            for event in chunk:
                bit = 1 << (event.value - 1)
                if event.kind == "place":
                    support_dom[event.cell] = bit
                else:
                    support_dom[event.cell] &= ~bit
            seen_reasons = set()
            for event in chunk:
                if event.kind == "place":
                    why = self._why_placed(event, support_dom)
                    if why:
                        lines.append(f"依据：{why}")
                    continue
                why = self._why_eliminated(event, support_dom)
                key = (event.cell, event.value, event.reason.kind)
                if why and key not in seen_reasons:
                    seen_reasons.add(key)
                    lines.append(f"依据：{why}")
            note = self._scope_note(chunk)
            if note:
                lines.append(note)
            if index == len(chunks) - 1:
                lines.append(f"出现矛盾：{cause}。")
            reasoning = Step(
                index=len(self.steps), technique="contradiction", tier=4,
                title=f"反证推理 {index + 1}/{len(chunks)}",
                detail="\n".join(lines), events=chunk,
                visual={"focus": [], "premise": [],
                        "groups": [{"cells": [cell], "kind": "assumption"}],
                        "links": [], "chips": [],
                        "assumption": {"cells": [cell],
                                       "label": f"反证推理：假设 {name}={value}"}},
                branch=True)
            reasoning.pre_dom = pre_dom
            reasoning.pre_vals = pre_vals
            reasoning.candidates = self._candidates(chunk, pre_dom)
            self.steps.append(reasoning)
            if self.on_step:
                try: self.on_step(reasoning)
                except Exception: pass
            for event in chunk:
                bit = 1 << (event.value - 1)
                if event.kind == "place":
                    run_state.vals[event.cell] = event.value
                    run_state.dom[event.cell] = bit
                else:
                    run_state.dom[event.cell] &= ~bit

        refuted = Step(
            index=len(self.steps), technique="contradiction", tier=4,
            title="反证推翻",
            detail=f"反证推翻：假设 {name} = {value} 的推导出现矛盾：{cause}。",
            events=[], visual={"focus": [], "premise": [],
                               "groups": [{"cells": [cell], "kind": "assumption"}],
                               "links": [], "chips": [],
                               "assumption": {"cells": [cell],
                                              "label": f"反证推翻：假设 {name}={value}"}},
            branch=True)
        refuted.pre_dom, refuted.pre_vals = pre_dom, pre_vals
        refuted.candidates = []
        self.steps.append(refuted)
        if self.on_step:
            try: self.on_step(refuted)
            except Exception: pass

        revert = Step(
            index=len(self.steps), technique="contradiction", tier=4,
            title="反证回退", detail=f"反证回退：撤销假设 {name} = {value}。",
            events=[], visual={"focus": [], "premise": [],
                               "groups": [{"cells": [cell], "kind": "assumption"}],
                               "links": [], "chips": [],
                               "assumption": {"cells": [cell],
                                              "label": f"反证回退：假设 {name}={value}"}},
            branch=True, revert=True)
        revert.pre_dom, revert.pre_vals = pre_dom, pre_vals
        revert.candidates = []
        self.steps.append(revert)
        if self.on_step:
            try: self.on_step(revert)
            except Exception: pass

        forced = values[0] if len(values) == 2 and values[1] == value else (values[1] if len(values) == 2 else None)
        reason = Reason("contradiction", {"cell": cell, "value": value,
                                          "forced": forced, "phase": "end",
                                          "cause": cause})
        self.state.begin()
        if forced is not None:
            self.state.place(cell, forced, reason)
        else:
            self.state.elim(cell, value, reason)
        events = self.state.end()
        step = self._commit(events, pre_dom, pre_vals)
        if step is None:
            return None
        step.title = "反证结论"
        self.steps.append(step)
        if self.on_step:
            try: self.on_step(step)
            except Exception: pass
        return step

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
            if self.on_step is not None:
                try:
                    self.on_step(step)
                except Exception:
                    pass
        return SolveResult("solved", self._merge_sibling_singles(self.steps),
                           self.state.vals, "")


# ------------------------------------------------------------------ validation


def check_solution(puzzle, rules, values: list[int]) -> list[str]:
    errors: list[str] = []
    units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti),
                        chaos=puzzle.is_chaos)
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
    units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti),
                        chaos=puzzle.is_chaos)
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
