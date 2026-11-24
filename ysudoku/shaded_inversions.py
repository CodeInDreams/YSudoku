"""Sudoku with two connected shades and outside inversion counts."""

import re
from functools import lru_cache
from math import isqrt
from time import monotonic

from . import palette
from .narrate import Step, _effect_lines, _unit_visual
from .shade_layout import ShadeLayout, ShadeTable, cell_mask, indexes
from .solve import SolveResult
from .state import Contradiction, Reason, bits, cell_name
from .visual_colours import HEX

LIGHT, DARK = 1, 2
LINE_STATE_LIMIT = 180_000


def recognizes_shaded_inversions(text):
    text = " ".join(text.lower().split())
    return all(re.search(pattern, text) for pattern in (
        r"\btwo orthogonally connected regions\b", r"\bshade one of them\b",
        r"\bno 2\s*[x×]\s*2\b.*\bone region\b", r"\b(?:any )?two shaded digits\b",
        r"\bnearer digit is greater\b",
    ))


def clue_cells(n, clue):
    if clue.side in ("left", "right"):
        cells = tuple(clue.index * n + c for c in range(n))
    else:
        cells = tuple(r * n + clue.index for r in range(n))
    return cells[::-1] if clue.side in ("right", "bottom") else cells


def minimum_shaded(total):
    if not total:
        return 0
    k = (1 + isqrt(1 + 8 * total)) // 2
    return k if k * (k - 1) // 2 == total else k + 1


class LineBudgetExceeded(Exception):
    pass


@lru_cache(maxsize=384)
def _line_analysis(light, dark, total):
    """Track assigned digits, the shaded subset, and inversions counted so far."""
    n = len(light)
    track_patterns = n <= 9
    remaining_shades = [0] * (n + 1)
    for i in reversed(range(n)):
        remaining_shades[i] = remaining_shades[i + 1] + bool(dark[i])

    def transitions(i, used, shaded, inversions):
        pending = (light[i] | dark[i]) & ~used
        while pending:
            bit = pending & -pending
            pending ^= bit
            if dark[i] & bit:
                yield bit, DARK, (i + 1, used | bit, shaded | bit,
                                   inversions + (shaded & ~(bit - 1)).bit_count())
            if light[i] & bit:
                yield bit, LIGHT, (i + 1, used | bit, shaded, inversions)

    nodes = 0

    @lru_cache(maxsize=None)
    def feasible(i, used, shaded, inversions):
        nonlocal nodes
        nodes += 1
        if nodes > LINE_STATE_LIMIT:
            raise LineBudgetExceeded
        slots = remaining_shades[i]
        maximum = inversions + shaded.bit_count() * slots + slots * (slots - 1) // 2
        if not inversions <= total <= maximum:
            return False
        if i == n:
            return True
        return any(feasible(*next_state) for _, _, next_state in transitions(i, used, shaded, inversions))

    initial = (0, 0, 0, 0)
    try:
        if not feasible(*initial):
            return (), (), 0
        frontier = {initial: 1}
        light_support, dark_support = [0] * n, [0] * n
        for i in range(n):
            next_frontier = {}
            for state, history in frontier.items():
                for digit, shade, next_state in transitions(*state):
                    if feasible(*next_state):
                        support = dark_support if shade == DARK else light_support
                        support[i] |= digit
                        pattern = history << (1 << i) if track_patterns and shade == DARK else history
                        next_frontier[next_state] = next_frontier.get(next_state, 0) | pattern
            frontier = next_frontier
    except LineBudgetExceeded:
        # A partial traversal cannot establish that a candidate has no support.
        return light, dark, None
    finally:
        feasible.cache_clear()
    patterns = 0
    for history in frontier.values():
        patterns |= history
    return tuple(light_support), tuple(dark_support), patterns if track_patterns else None


def line_support(light, dark, total):
    return _line_analysis(light, dark, total)[:2]


line_support.cache_clear = _line_analysis.cache_clear


class Shading:
    def __init__(self, n):
        self.masks = [LIGHT | DARK] * (n * n)
        full = (1 << n) - 1
        self.digits = [(full, full)] * (n * n)
        self.squares = [(i, i + 1, i + n, i + n + 1)
                        for i in range(n * n) if i // n < n - 1 and i % n < n - 1]
        self.neighbours = []
        for i in range(n * n):
            r, c = divmod(i, n)
            self.neighbours.append(tuple(rr * n + cc for rr, cc in
                                         ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
                                         if 0 <= rr < n and 0 <= cc < n))

    def restrict(self, cell, allowed):
        mask = self.masks[cell] & allowed
        if not mask:
            raise Contradiction("该格无可用颜色")
        self.masks[cell] = mask

    def square(self, cells):
        for shade in (LIGHT, DARK):
            fixed = [c for c in cells if self.masks[c] == shade]
            if len(fixed) == 4:
                raise Contradiction("出现单色 2×2")
            if len(fixed) == 3:
                other = next(c for c in cells if c not in fixed)
                if self.masks[other] & shade:
                    self.restrict(other, (LIGHT | DARK) ^ shade)
                    return ("square", cells, shade)
            for left, right in ((0, 3), (1, 2)):
                if any(self.masks[cells[i]] != shade for i in (left, right)):
                    continue
                other_shade = (LIGHT | DARK) ^ shade
                others = [cells[i] for i in range(4) if i not in (left, right)]
                if self.masks[others[0]] == other_shade and self.masks[others[1]] & other_shade:
                    self.restrict(others[1], shade)
                    return ("alternating", cells, shade)
                if self.masks[others[1]] == other_shade and self.masks[others[0]] & other_shade:
                    self.restrict(others[0], shade)
                    return ("alternating", cells, shade)

    def reachable(self, seed, shade, omit=None):
        seen = {seed}
        stack = [seed]
        while stack:
            for cell in self.neighbours[stack.pop()]:
                if cell not in seen and cell != omit and self.masks[cell] & shade:
                    seen.add(cell)
                    stack.append(cell)
        return seen

    def connected(self, shade):
        forced = {cell for cell, mask in enumerate(self.masks) if mask == shade}
        possible = {cell for cell, mask in enumerate(self.masks) if mask & shade}
        if not possible:
            raise Contradiction("一种颜色没有可选的格子")
        if len(possible) == 1 and not forced:
            cell = next(iter(possible))
            self.restrict(cell, shade)
            return ("nonempty", (cell,), shade)
        if not forced:
            return None
        seed = min(forced)
        reachable = self.reachable(seed, shade)
        if not forced <= reachable:
            raise Contradiction("同色格无法正交连通")
        isolated = sorted(possible - reachable)
        if isolated:
            for cell in isolated:
                self.restrict(cell, (LIGHT | DARK) ^ shade)
            return ("connect", tuple(sorted(forced)), shade)
        if len(forced) >= 2:
            for cell in sorted(possible - forced):
                if not forced <= self.reachable(seed, shade, omit=cell):
                    self.restrict(cell, shade)
                    return ("bridge", tuple(sorted(forced)), shade)
        return None

    def deduction(self, clues):
        for cells in self.squares:
            if reason := self.square(cells):
                return reason
        for shade in (LIGHT, DARK):
            if reason := self.connected(shade):
                return reason
        for cells, total in clues:
            possible = [c for c in cells if self.masks[c] & DARK]
            minimum = minimum_shaded(total)
            if len(possible) < minimum:
                raise Contradiction(f"提示 {total} 至少需要 {minimum} 个深色格")
            if len(possible) == minimum and any(self.masks[c] != DARK for c in possible):
                for cell in possible:
                    self.restrict(cell, DARK)
                return ("minimum", cells, total)
        return None

    def solved(self):
        return all(mask in (LIGHT, DARK) for mask in self.masks)

    def valid(self):
        for shade in (LIGHT, DARK):
            cells = {i for i, mask in enumerate(self.masks) if mask == shade}
            if not cells or self.reachable(min(cells), shade) != cells:
                return False
        return all(len({self.masks[c] for c in cells}) > 1 for cells in self.squares)


def _line_domains(state, shading, cells):
    return tuple(tuple(state.dom[c] & shading.digits[c][index] if shading.masks[c] & shade else 0
                       for c in cells) for index, shade in enumerate((LIGHT, DARK)))


def _propagate_line(state, shading, cells, total):
    light, dark = _line_domains(state, shading, cells)
    light_support, dark_support = line_support(light, dark, total)
    if not light_support:
        raise Contradiction(f"盘外提示 {total} 无可行搭配")
    events = Reason("shaded_inversions", {"cells": cells, "total": total})
    conditional = []
    for cell, light_mask, dark_mask, prior_light, prior_dark in zip(cells, light_support, dark_support, light, dark):
        state.restrict(cell, light_mask | dark_mask, events)
        shading.restrict(cell, (LIGHT if light_mask else 0) | (DARK if dark_mask else 0))
        if (light_mask, dark_mask) != (prior_light, prior_dark):
            conditional.append((cell, light_mask, dark_mask))
        shading.digits[cell] = light_mask, dark_mask
    return conditional


def _layout_deduction(state, shading, clues, deadline):
    if state.n > 9:
        return None
    tables, bounds, evidence = [], [], []
    for cells, total in clues:
        light, dark = _line_domains(state, shading, cells)
        _, _, allowed = _line_analysis(light, dark, total)
        minimum = minimum_shaded(total)
        required = cell_mask(i for i, mask in enumerate(light) if not mask)
        possible = cell_mask(i for i, mask in enumerate(dark) if mask)
        by_count = [mask for mask in range(1 << len(cells))
                    if mask.bit_count() >= minimum and mask & required == required and not mask & ~possible]
        if allowed == 0 or not by_count:
            raise Contradiction(f"提示 {total} 没有可行染色")
        if allowed is None:
            bounds.append((cells, minimum))
            variants = len(by_count)
        else:
            tables.append(ShadeTable.build(cells, indexes(allowed)))
            variants = allowed.bit_count()
        evidence.append({"cells": cells, "clue": total, "patterns": variants})
    layout = ShadeLayout(state.n, shading.squares, shading.neighbours, tables, bounds)
    dark = cell_mask(c for c, mask in enumerate(shading.masks) if mask == DARK)
    light = cell_mask(c for c, mask in enumerate(shading.masks) if mask == LIGHT)
    witness, _ = layout.search(dark, light, deadline)
    if witness is None:
        return None
    if not witness:
        raise Contradiction("各盘外提示与双色连通没有共同染色")
    flexible = 0
    proofs = []
    for cell in indexes(layout.full & ~(dark | light)):
        if monotonic() >= deadline:
            break
        bit = 1 << cell
        if flexible & bit:
            continue
        is_dark = bool(witness & bit)
        alternative, nodes = layout.search(dark if is_dark else dark | bit,
                                           light | bit if is_dark else light, deadline, limit=55_000)
        if alternative == 0:
            proofs.append({"cell": cell, "rejected": LIGHT if is_dark else DARK, "checks": nodes})
            if is_dark:
                dark |= bit
            else:
                light |= bit
        elif alternative is not None:
            flexible |= witness ^ alternative
    if not proofs:
        return None
    for proof in proofs:
        shading.restrict(proof["cell"], (LIGHT | DARK) ^ proof["rejected"])
    return {"trials": proofs, "clues": evidence}


def _colour_snapshot(shading):
    return [{"colour": index, "hex": HEX[index], "cells": [
        c for c, mask in enumerate(shading.masks) if mask == shade
    ]} for index, shade in ((palette.YELLOW, LIGHT), (palette.BLUE, DARK))]


def shade_step_text(evidence, n, lang, *, show_trials=False):
    kind, scope, amount = evidence["shade_reason"]
    cells = evidence["shade_changes"]
    english = lang == "en"
    shade = ("shaded" if amount == DARK else "unshaded") if english else ("深色" if amount == DARK else "浅色")
    texts = {
        "square": ("A 2×2 cannot be entirely the same colour." if english else "2×2 方块不能全部同色。"),
        "alternating": ("The two colours cannot alternate around a 2×2. Connecting both diagonal pairs would require the paths to cross."
                        if english else "2×2 的两种颜色不能交错，否则两条连接对角同色格的路径必须相交。"),
        "connect": (f"These cells cannot connect to the confirmed {shade} cells."
                    if english else f"这些格无法连接到已确认的{shade}格。"),
        "bridge": (f"The confirmed {shade} cells must connect through this cell."
                   if english else f"已确认的{shade}格必须通过这一格才能连通。"),
        "nonempty": (f"This is the only cell that can be {shade}." if english else f"只有这一格可以是{shade}。"),
        "line": (f"From the clue side, count a pair only when both cells are shaded and the nearer digit is larger. Exactly {amount} pairs are required."
                 if english else f"从提示一侧看，只有两格都着深色且近格数字更大才计一对。必须正好有 {amount} 对，保留支持这个数的数字与颜色。"),
        "minimum": (f"The clue {amount} requires at least {minimum_shaded(amount)} shaded cells. With fewer cells there are too few pairs, even in descending order."
                    if english else f"提示 {amount} 至少需要 {minimum_shaded(amount)} 个深色格。格数再少，即使数字完全降序也凑不够 {amount} 对。"),
        "layout": ("Combine possible colour patterns for the outside clues. Each 2×2 must be mixed, both colours must stay connected, and their runs cannot alternate around the perimeter."
                   if english else "联合检查各盘外提示允许的染色模式。每个 2×2 必须包含两色，两色都要保持连通，且外边缘不能出现两色交替的四段。"),
    }
    detail = [texts[kind]]
    for mask in (DARK, LIGHT):
        names = ", ".join(cell_name(c, n) for c, colour in cells if colour == mask)
        if names:
            label = ("Shaded" if mask == DARK else "Unshaded") if english else ("深色" if mask == DARK else "浅色")
            detail.append(f"{label} · {names}")
    for cell, light, dark in evidence.get("conditional", []):
        if light and dark and light != dark:
            left, right = (", ".join(map(str, bits(mask))) for mask in (light, dark))
            detail.append(f"{cell_name(cell, n)} " + (
                f"unshaded {{{left}}}, shaded {{{right}}}" if english else f"浅色 {{{left}}}，深色 {{{right}}}"))
    if layout := evidence.get("layout"):
        tight = sorted(layout["clues"], key=lambda clue: clue["patterns"])[:3]
        for clue in tight:
            first, last = (cell_name(c, n) for c in (clue["cells"][0], clue["cells"][-1]))
            detail.append(f"{first}–{last} · {clue['clue']} · " + (
                f"{clue['patterns']} allowed colour patterns" if english else f"{clue['patterns']} 种可行染色模式"))
        detail.append("Every colour excluded on this step was checked to contradiction."
                      if english else "本步排除的颜色在上述条件下都没有可行布局。")
        if show_trials:
            for trial in layout["trials"]:
                assumed = ("shaded" if trial["rejected"] == DARK else "unshaded") if english else (
                    "深色" if trial["rejected"] == DARK else "浅色")
                name = cell_name(trial["cell"], n)
                count = trial["checks"]
                detail.append(f"If {name} is {assumed}, no compatible layout remains after checking {count} states."
                              if english else f"若 {name} 为{assumed}，检查 {count} 个状态后排除所有布局。")
    return "\n".join(detail)


def solve_shaded(solver, max_steps):
    n, state = solver.state.n, solver.state
    shading = Shading(n)
    clues = sorted(((clue_cells(n, clue), clue.value) for clue in solver.puzzle.clues),
                   key=lambda item: -item[1])
    highlighted = iter((cells, total) for cells, total in clues if minimum_shaded(total) > n // 2)
    layout_deadline = None
    while not solver.invalid and len(solver.steps) < max_steps:
        pre_dom, pre_vals = solver._pre()
        before = shading.masks.copy()
        try:
            introduction = next(highlighted, None)
            reason = ("minimum", *introduction) if introduction else shading.deduction(clues)
            events = []
            conditional = []
            layout = None
            if reason is None:
                for cells, total in clues:
                    state.begin()
                    conditional = _propagate_line(state, shading, cells, total)
                    events = state.end()
                    if events or conditional or before != shading.masks:
                        reason = ("line", cells, total)
                        break
            if reason is None:
                step, error = solver.next_step()
                if error:
                    raise Contradiction(error)
                if step is None:
                    if not solver.allow_chains:
                        break
                    if layout_deadline is None:
                        layout_deadline = monotonic() + 65
                    deadline = min(layout_deadline, monotonic() + 30)
                    layout = _layout_deduction(state, shading, clues, deadline)
                    if not layout:
                        break
                    tight = min(layout["clues"], key=lambda clue: clue["patterns"])
                    reason = ("layout", tight["cells"], 0)
            if reason is not None:
                changed = [(c, mask) for c, mask in enumerate(shading.masks) if mask != before[c]]
                focus = sorted({c for c, _ in changed} | {e.cell for e in events} | {c for c, *_ in conditional})
                evidence = {"shade_reason": reason, "shade_changes": changed, "conditional": conditional,
                            "layout": layout}
                detail = shade_step_text(evidence, n, "zh")
                if events:
                    detail += "\n" + "\n".join(_effect_lines(events, n))
                step = Step(len(solver.steps), "shaded_inversions", 2, "染色与逆序对", detail,
                            events, _unit_visual(list(reason[1]), focus), pre_dom, pre_vals,
                            solver._candidates(events, pre_dom), narration=evidence)
        except Contradiction as exc:
            solver.invalid = str(exc)
            break
        step.visual["colours"] = _colour_snapshot(shading)
        solver.steps.append(step)
        if solver.on_step:
            solver.on_step(step)
    if solver.invalid:
        status, message = "invalid", solver.invalid
    elif state.solved and shading.solved():
        if not shading.valid():
            return SolveResult("invalid", solver.steps, state.vals, "染色不符合区域规则"), shading.masks
        for cells, total in clues:
            values = [state.vals[c] for c in cells if shading.masks[c] == DARK]
            if sum(a > b for i, a in enumerate(values) for b in values[i + 1:]) != total:
                return SolveResult("invalid", solver.steps, state.vals, "深色逆序对数不符"), shading.masks
        status, message = "solved", ""
    else:
        status, message = "stuck", "当前染色与数字候选达到固定点，尚未完全确定。"
    return SolveResult(status, solver.steps, state.vals, message), shading.masks
