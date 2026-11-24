"""Scheduler that produces a human-style solving path, plus auditing."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field, replace
from time import monotonic

from .intersections import PatternPropagation
from .narrate import Step, build_step, contradiction_zh
from .search import count_solutions, satisfiable
from .state import Contradiction, Event, Reason, State, bits, cell_name
from .simplify import can_simplify, simplify
from .sum_links import compile_links
from .techniques import TECHNIQUES, TRIGGERS
from .unit_inference import solver_units

REFUTATION_LINES_PER_PAGE = 8


@dataclass
class SolveResult:
    status: str  # solved | stuck | invalid
    steps: list[Step]
    values: list[int]
    message: str = ""
    audit: dict = field(default_factory=dict)


class Solver:
    def __init__(self, puzzle, rules, allow_chains: bool = False, on_step=None, solution=None):
        self.puzzle = puzzle
        self.rules = rules
        self.units = solver_units(puzzle, rules)
        self.state = State(puzzle.size, self.units)
        self.constraints = list(rules.constraints)
        self._rewrite_inputs = {}
        self.sum_links = compile_links(self.constraints, puzzle.size)
        self.patterns = PatternPropagation()
        self.state.constraints = self.constraints
        self.allow_chains = allow_chains
        self.on_step = on_step
        self.steps: list[Step] = []
        self.focus: set[int] = set()
        self.invalid: str | None = None
        self.solution = list(solution or [])
        self._prefetched = []
        self._refuter = None
        try:
            for cell, value in puzzle.givens.items():
                self.state.place(cell, value)
        except Contradiction as exc:
            self.invalid = f"题目自相矛盾：{exc}"
        self.initial = self.state.dom.copy()

    def _pre(self):
        return self.state.dom.copy(), self.state.vals.copy()

    def fork_for_replay(self):
        trial = copy(self)
        trial.state = self.state.copy()
        trial.constraints = self.constraints.copy()
        trial.state.constraints = trial.constraints
        trial._rewrite_inputs = self._rewrite_inputs.copy()
        trial.sum_links = [copy(link) for link in self.sum_links]
        trial.patterns = PatternPropagation()
        trial.steps = self.steps.copy()
        trial.on_step = None
        return trial

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
        from .visual_colours import xv_colours
        step = build_step(len(self.steps), events, self.state.n)
        colours = xv_colours(events)
        if colours:
            step.visual["colours"] = colours
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

    def _constraint_gain(self, constraint):
        copy = self.state.copy()
        copy.begin()
        try:
            constraint.prune(copy)
        except Contradiction:
            copy.rollback()
            return (10_000, 0)
        events = copy.end()
        copies = sum(1 for e in events if e.kind == "place")
        elims = sum(1 for e in events if e.kind == "elim")
        return (copies * 50 + elims, len(events))

    def _simplification_step(self):
        for index, rule in enumerate(self.constraints):
            if not can_simplify(rule):
                continue
            signature = tuple((self.state.dom[c], self.state.vals[c]) for c in rule.cells())
            if self._rewrite_inputs.get(index) == signature:
                continue
            self._rewrite_inputs[index] = signature
            replacement = simplify(rule, self.state)
            if replacement is None:
                continue
            target, detail = replacement
            self.constraints[index] = target
            result = self._constraint_step(target)
            if isinstance(result, tuple):
                return result
            if result is None:
                result = Step(len(self.steps), "constraint_simplify", 1, "", "", [])
                result.pre_dom, result.pre_vals = self._pre()
            result.technique = "constraint_simplify"
            result.title = "约束简化"
            result.detail = detail + ("\n" + result.detail if result.events else "")
            result.visual.update(focus=target.cells(), premise=rule.cells())
            return result, None
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

        replacement = self._simplification_step()
        if replacement is not None:
            return replacement

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
        best = None
        best_gain = (-1, -1)
        for constraint in ordered:
            if getattr(constraint, "kind", "") == "custom":
                continue
            gain = self._constraint_gain(constraint)
            if gain > best_gain:
                best_gain = gain
                best = constraint
        if best is not None:
            result = self._constraint_step(best)
            if isinstance(result, tuple):
                return result
            if result is not None:
                return result, None

        for link in self.sum_links:
            if not link.affected(self.state):
                continue
            pre_dom, pre_vals = self._pre()
            self.state.begin()
            try:
                link.apply(self.state)
            except Contradiction as exc:
                self.state.rollback()
                return None, str(exc)
            events = self.state.end()
            if events:
                return self._commit(events, pre_dom, pre_vals), None

        for name, _tier, technique in TECHNIQUES:
            if name in ("naked_single", "hidden_single"):
                continue
            if name == "forcing_chain":
                result = self._pattern_step()
                if result is not None:
                    return result
                if not self.allow_chains:
                    continue
            result = self._technique_step(name, technique)
            if isinstance(result, tuple):
                return result
            if result is not None:
                return result, None
        return None, None

    def _pattern_step(self):
        pre_dom, pre_vals = self._pre()
        self.state.begin()
        try:
            found = self.patterns.find(self.state, self.constraints)
            if found:
                allowed, reason = found
                for cell, mask in allowed.items():
                    self.state.restrict(cell, mask, reason)
        except Contradiction as exc:
            self.state.rollback()
            return None, str(exc)
        events = self.state.end()
        if events:
            return self._commit(events, pre_dom, pre_vals), None
        return None

    def _merge_sibling_singles(self, steps: list[Step]) -> list[Step]:
        """Merge all independent singles directly caused by the same origin.

        Dependent steps may sit between siblings; they stay in place, while the
        direct children are folded into the first child step.
        """
        steps = list(steps)
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
                target = replace(target, events=list(target.events), visual=dict(target.visual))
                steps[direct[0]] = target
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
            if step.index != index:
                steps[index] = replace(step, index=index)
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
            narration={"phase": phase, "cell": cell, "value": value},
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

    def contradiction_step(self, deadline: float, per_candidate: float = 1.2,
                           max_steps: int = 4000):
        import time
        from .search import proof_cost
        self.refutation_limited = False
        # Reserve the assumption, contradiction and combined rollback.
        max_pages = min(32, max_steps - len(self.steps) - 3)
        if max_pages < 1:
            self.refutation_limited = True
            return None
        focus_units = {u for c in self.focus if c < len(self.state.unit_of)
                       for u in self.state.unit_of[c]}

        def near_focus(cell):
            units = set(self.state.unit_of[cell])
            return 0 if cell in self.focus or (units & focus_units) else 1

        weight = [0] * self.state.n2
        for constraint in self.constraints:
            for cell in constraint.cells():
                weight[cell] += 1
        cells = sorted((c for c in range(self.state.n2) if not self.state.vals[c]),
                       key=lambda c: (0 if self.state.dom[c].bit_count() == 2 else 1,
                                      near_focus(c), -weight[c],
                                      self.state.dom[c].bit_count()))
        best = None
        candidates = []
        for cell in cells:
            vals = list(bits(self.state.dom[cell]))
            if len(vals) < 2:
                continue
            if len(vals) > 7 and near_focus(cell) != 0 and weight[cell] < 4:
                continue
            candidates.extend((cell, v) for v in vals)
            if len(candidates) >= 80:
                break
        # Probe a small, ordered window serially. This lets us compare complete
        # proofs by support length instead of accepting whichever worker wins a
        # race, while keeping every individual search bounded.
        from .search import refute_candidate_with_proof
        probe_deadline = time.monotonic() + min(
            2.5, max(0.0, deadline - time.time()),
        )
        attempts = 0
        for cell, value in candidates:
            remaining = probe_deadline - time.monotonic()
            if remaining <= 0 or attempts >= (16 if best else 64):
                break
            attempts += 1
            refuted, proof, cause = refute_candidate_with_proof(
                self.state, self.constraints, cell, value,
                time_limit=min(per_candidate, remaining),
            )
            if not refuted or not proof:
                continue
            cost = proof_cost(proof)
            # Each node adds at most two lines beyond the counted deductions
            # and sub-assumptions. Compare only proofs we can show in full.
            if cost[0] + 2 * cost[2] > max_pages * REFUTATION_LINES_PER_PAGE:
                self.refutation_limited = True
                continue
            score = (
                cost[0], cost[1], cost[2],
                0 if self.state.dom[cell].bit_count() == 2 else 1,
                self.state.dom[cell].bit_count(),
            )
            if best is None or score < best[0]:
                best = (score, cell, value, proof, cause)
            # A very short proof cannot be improved materially by further
            # probes; retain time for applying it and propagating the result.
            if cost[0] <= 2:
                break
        if best is None:
            return None
        _, cell, value, proof, cause = best
        return self.apply_refutation(cell, value, proof, cause)

    def apply_refutation(self, cell, value, proof, cause):
        pre_dom, pre_vals = self._pre()
        values = list(bits(pre_dom[cell]))
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
            narration={"phase": "start", "cell": cell, "value": value},
            branch=True)
        intro.pre_dom, intro.pre_vals = pre_dom, pre_vals
        intro.candidates = [{"cell": cell, "digits": [value]}]
        self.steps.append(intro)
        if self.on_step:
            try: self.on_step(intro)
            except Exception: pass

        def proof_lines(node, indent=""):
            lines = []
            assumption = node.get("assumption")
            if assumption and assumption != (cell, value):
                branch_cell, branch_value = assumption
                lines.append(
                    (f"{indent}再假设 {cell_name(branch_cell, self.state.n)} = {branch_value}：", None,
                     {"kind": "assume", "cell": branch_cell, "value": branch_value})
                )
            support_dom = list(node.get("pre_dom") or self.state.dom)
            reason_labels = {
                "naked_single": "裸单", "hidden_single": "隐性单数",
                "anti_knight": "反骑士", "anti_king": "反王",
                "german_whisper": "德国耳语线", "dutch_whisper": "荷兰耳语线",
                "xv": "XV 和数", "arrow": "箭头和数",
                "ir_support": "通用约束支持", "x_sums": "X-Sums",
                "rule_choice": "规则选择与分配", "full_rank": "Full Rank",
                "subset": "数对/子集", "cage": "杀手数独宫格和",
                "thermo": "温度计递增规则", "renban": "连续数集",
            }
            for event in node.get("events", ()):
                effect = (f"{cell_name(event.cell, self.state.n)} = {event.value}"
                          if event.kind == "place" else
                          f"{cell_name(event.cell, self.state.n)} ≠ {event.value}")
                # Placement evidence can be reconstructed from its candidate
                # mask. For eliminations, retain the exact event and rule name;
                # some variant constraints need relation-wide support data that
                # a single-cell snapshot cannot faithfully reproduce.
                why = (self._why_placed(event, support_dom)
                       if event.kind == "place" else "")
                if event.reason.kind == "unit_peer":
                    by = cell_name(event.reason.data["by"], self.state.n)
                    why = f"{effect}（与 {by} 同行、同列或同区）"
                elif "proof_partner" in event.reason.data:
                    data = event.reason.data
                    partner = cell_name(data["proof_partner"], self.state.n)
                    digits = "、".join(map(str, data["proof_values"]))
                    rule = reason_labels.get(event.reason.kind, event.reason.kind)
                    why = (f"{effect}（{rule}：{partner} 的兼容候选 {digits} 已排除）"
                           if digits else f"{effect}（{rule}：{partner} 没有兼容数字）")
                elif event.reason.kind in ("anti_knight", "anti_king"):
                    data = event.reason.data
                    other = data["b"] if event.cell == data["a"] else data["a"]
                    why = (f"{effect}（{reason_labels[event.reason.kind]}："
                           f"{cell_name(other, self.state.n)} 已填 {event.value}）")
                if event.reason.kind != "assumption":
                    lines.append(
                        (f"{indent}→ {why or effect + '（' + reason_labels.get(event.reason.kind, event.reason.kind) + '）'}", None,
                         {"kind": "event", "event": event.to_dict()})
                    )
                bit = 1 << (event.value - 1)
                if event.kind == "place":
                    support_dom[event.cell] = bit
                else:
                    support_dom[event.cell] &= ~bit
            if node.get("cause"):
                conflict = node.get("visual_conflict")
                lines.append((f"{indent}出现矛盾：{contradiction_zh(node['cause'])}。", conflict,
                              {"kind": "cause", "text": node["cause"], "conflict": conflict}))
            children = node.get("children", ())
            branch_cell = node.get("branch_cell")
            if children and branch_cell is not None:
                options = "、".join(str(child["value"]) for child in children)
                lines.append(
                    (f"{indent}继续分支：{cell_name(branch_cell, self.state.n)} "
                     f"只能取 {options}。", None,
                     {"kind": "branch", "cell": branch_cell, "values": [child["value"] for child in children]})
                )
                for child in children:
                    lines.extend(proof_lines(child["proof"], indent + "  "))
                lines.append((f"{indent}该格所有候选都导致矛盾。", None,
                              {"kind": "branch_end", "cell": branch_cell}))
            for _, _, row in lines:
                row.setdefault("depth", len(indent) // 2)
            return lines

        proof_text = proof_lines(proof)
        if not proof_text:
            proof_text = [(f"假设 {name} = {value} 后立即矛盾：{contradiction_zh(cause)}。", None,
                           {"kind": "cause", "text": cause})]
        chunks = [proof_text[i:i + REFUTATION_LINES_PER_PAGE]
                  for i in range(0, len(proof_text), REFUTATION_LINES_PER_PAGE)]
        pre_dom, pre_vals = self._pre()
        for index, chunk in enumerate(chunks):
            lines = [f"反证推理（{index + 1}/{len(chunks)}）："] + [text for text, _, _ in chunk]
            conflicts = [conflict for _, conflict, _ in chunk if conflict]
            reasoning = Step(
                index=len(self.steps), technique="contradiction", tier=4,
                title=f"反证推理 {index + 1}/{len(chunks)}",
                detail="\n".join(lines), events=[],
                visual={"focus": [], "premise": [],
                        "groups": [{"cells": [cell], "kind": "assumption"}],
                        "links": [], "chips": [], "conflicts": conflicts,
                        "assumption": {"cells": [cell],
                                       "label": f"反证推理：假设 {name}={value}"}},
                branch=True, narration={"phase": "trace", "cell": cell, "value": value,
                                        "page": index + 1, "total": len(chunks),
                                        "rows": [row for _, _, row in chunk]})
            reasoning.pre_dom, reasoning.pre_vals = list(pre_dom), list(pre_vals)
            reasoning.candidates = []
            self.steps.append(reasoning)
            if self.on_step:
                try: self.on_step(reasoning)
                except Exception: pass

        refuted = Step(
            index=len(self.steps), technique="contradiction", tier=4,
            title="反证推翻",
            detail=f"反证推翻：假设 {name} = {value} 的推导出现矛盾：{contradiction_zh(cause)}。",
            events=[], visual={"focus": [], "premise": [],
                               "groups": [{"cells": [cell], "kind": "assumption"}],
                               "links": [], "chips": [],
                               "conflicts": [proof["visual_conflict"]] if proof.get("visual_conflict") else [],
                               "assumption": {"cells": [cell],
                                              "label": f"反证推翻：假设 {name}={value}"}},
            branch=True, narration={"phase": "conflict", "cell": cell, "value": value,
                                    "cause": cause, "conflict": proof.get("visual_conflict")})
        refuted.pre_dom, refuted.pre_vals = pre_dom, pre_vals
        refuted.candidates = []
        self.steps.append(refuted)
        if self.on_step:
            try: self.on_step(refuted)
            except Exception: pass

        forced = next((candidate for candidate in values if candidate != value), None) if len(values) == 2 else None
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
        step.revert = True
        step.title = "反证回退"
        conclusion = (f"排除 {name} 的候选 {value}。" if forced is None
                      else f"{name} 只剩 {forced}，填入 {forced}。")
        step.detail = f"撤销假设 {name} = {value}。{conclusion}"
        step.visual = {"focus": [cell], "premise": [], "groups": [], "links": [], "chips": []}
        self.steps.append(step)
        if self.on_step:
            try: self.on_step(step)
            except Exception: pass
        return step

    def _v_colour_step(self):
        if getattr(self, "_v_colour_done", False):
            return None
        from .v_colour_pattern import target_exclusions
        from . import palette as pal
        pairs = [c for c in self.constraints
                 if getattr(c, "_kind", None) == "xv" and (c.params or {}).get("sum") == 5]
        anti = {}
        for c in self.constraints:
            if getattr(c, "kind", "") == "anti":
                a, b = c.cells()
                anti.setdefault(a, set()).add(b)
                anti.setdefault(b, set()).add(a)
        for target in range(self.state.n2):
            if self.state.vals[target]:
                continue
            peers = anti.get(target, set())
            for i, first in enumerate(pairs):
                for second in pairs[i + 1:]:
                    a, b = first.cells(), second.cells()
                    if target_exclusions(target, a, b, peers) != {1, 2, 3, 4}:
                        continue
                    self._v_colour_done = True
                    left, right = pal.pair_colours(0)
                    step = Step(
                        index=len(self.steps), technique="colour_class", tier=1,
                        title="颜色分类",
                        detail=(f"两组 V 颜色类：{a} / {b}。\n"
                                f"四类覆盖 1–4；目标 R{target // self.state.n + 1}C{target % self.state.n + 1} "
                                "被四格马步攻击，因此不能取 1–4。"),
                        events=[], visual={"focus": [], "premise": [], "groups": [],
                                           "links": [], "chips": [],
                                           "colours": [
                                               {"cells": a, "colour": left},
                                               {"cells": b, "colour": right},
                                           ]})
                    step.pre_dom, step.pre_vals = self._pre()
                    step.candidates = [{"cell": target, "digits": [5, 6, 7, 8, 9]}]
                    return step
        return None

    def _intersection_step(self):
        from .intersections import bfs_unsupported
        if getattr(self, "_intersection_tried", 0) >= 20:
            return None
        self._intersection_tried = getattr(self, "_intersection_tried", 0) + 1
        found = bfs_unsupported(self.state, self.constraints, max_rules=3)
        if not found:
            return None
        cell, value, rules = found[0]
        if self.solution and self.solution[cell] == value:
            self._intersection_disabled = True
            return None
        pre_dom, pre_vals = self._pre()
        self.state.begin()
        try:
            self.state.elim(cell, value, Reason("intersection", {
                "cell": cell, "value": value, "rules": rules,
            }))
        except Contradiction:
            self.state.rollback()
            return None
        events = self.state.end()
        step = self._commit(events, pre_dom, pre_vals)
        if step is None:
            return None
        step.title = "交集约束"
        step.detail = ("联合相关规则检查该候选，发现没有任何一致赋值：\n"
                       + "\n".join(f"参与规则：{rule}" for rule in rules))
        return step

    def _candidate_map_steps(self):
        pre_dom, pre_vals = self._pre()
        signature = tuple(pre_dom)
        if getattr(self, "_candidate_map_signature", None) == signature:
            return None
        cells = [c for c in range(self.state.n2)
                 if not self.state.vals[c] and self.state.dom[c].bit_count() <= 5]
        if not cells:
            return []
        self._candidate_map_signature = signature
        groups = {}
        for cell in cells:
            region = (cell // 27) * 3 + (cell % 9) // 3
            groups.setdefault(region, []).append(cell)
        steps = []
        ordered = sorted(groups)
        for index, region in enumerate(ordered, 1):
            group_cells = groups[region]
            step = Step(
                index=len(self.steps) + len(steps), technique="candidate_map", tier=1,
                title=f"候选标记 {index}/{len(ordered)}",
                detail=f"标出第 {region + 1} 宫候选数不超过 6 的格子。",
                events=[], visual={"focus": group_cells, "premise": [], "groups": [], "links": [], "chips": []})
            step.pre_dom, step.pre_vals = pre_dom, pre_vals
            step.candidates = [{"cell": c, "digits": [v for v in range(1, self.state.n + 1)
                                                     if pre_dom[c] >> (v - 1) & 1]}
                               for c in group_cells]
            steps.append(step)
        return steps

    def _narrowing_step(self):
        for constraint in self.constraints:
            pre_dom, pre_vals = self._pre()
            self.state.begin()
            try:
                changed = constraint.prune(self.state)
            except Contradiction:
                self.state.rollback()
                return None
            events = self.state.end()
            if events:
                step = self._commit(events, pre_dom, pre_vals)
                if step is not None:
                    step.title = "候选缩小"
                    step.detail = f"{constraint.describe()} 继续缩小候选。"
                    return step
        return None

    def add_candidate_map(self, max_steps):
        for step in (self._candidate_map_steps() or [])[:max_steps - len(self.steps)]:
            self.steps.append(step)
            if self.on_step is not None:
                try:
                    self.on_step(step)
                except Exception:
                    pass

    def run(self, max_steps: int = 4000, *, candidate_maps=True, merge_singles=True,
            deadline=None) -> SolveResult:
        if self.invalid:
            return SolveResult("invalid", [], self.state.vals, self.invalid)
        while not self.state.solved:
            if deadline is not None and monotonic() >= deadline:
                return SolveResult("timeout", self.steps, self.state.vals)
            if len(self.steps) >= max_steps:
                return SolveResult("stuck", self.steps, self.state.vals,
                                   f"达到 {max_steps} 步上限，仍未解完")
            step, error = self.next_step()
            if error:
                return SolveResult("invalid", self.steps, self.state.vals, error)
            if step is None:
                step = self._narrowing_step()
                if step is not None:
                    self.steps.append(step)
                    if self.on_step is not None:
                        try:
                            self.on_step(step)
                        except Exception:
                            pass
                    continue
                if candidate_maps:
                    self.add_candidate_map(max_steps)
                return SolveResult(
                    "stuck", self.steps, self.state.vals,
                    "已对全部约束做固定点检查，没有候选可再缩小",
                )
            self.steps.append(step)
            if self.on_step is not None:
                try:
                    self.on_step(step)
                except Exception:
                    pass
        if merge_singles:
            self.steps = self._merge_sibling_singles(self.steps)
        return SolveResult("solved", self.steps, self.state.vals)


# ------------------------------------------------------------------ validation


def check_solution(puzzle, rules, values: list[int]) -> list[str]:
    errors: list[str] = []
    units = solver_units(puzzle, rules)
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
    units = solver_units(puzzle, rules)
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
            # Branch assumptions are deliberately temporary and are never
            # claims that the assumed value is forced on the real board.
            if (event.reason.kind == "contradiction"
                    and (event.reason.data or {}).get("phase") == "start"):
                continue
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
