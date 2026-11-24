"""Deduce written digits and effective values on a shared Sudoku grid."""

from copy import copy
from colorsys import rgb_to_hsv
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import permutations, product
import re
from time import monotonic

from .constraints import PairRule, Renban, _matching_masks, consecutive_windows
from .narrate import Step
from .solve import SolveResult
from .state import Contradiction, Event, Reason, bits, build_units, cell_name


WRITTEN, EFFECTIVE, MODE, LIAR_DIGIT, LIAR_VALUE = range(5)
HONEST, LIAR = 1, 2


def liar_value_spec(puzzle, inventory):
    """Recognise the supported liar-cell rules and explicitly select value clues."""
    text = puzzle.rules_text.lower()
    layout = r"\b(?:each|every) row,?\s+column,?\s+and\s+(?:3x3\s+)?box\s+(?:contains|has)\s+(?:exactly\s+)?one liar cell\b"
    different = r"\b(?:each|every) liar cell (?:has|contains) a different (digit|value)\b"
    if (puzzle.is_chaos or puzzle.clues or puzzle.circles or puzzle.arrows
            or puzzle.size > 9 or any(cage.total is not None for cage in puzzle.cages)
            or len(puzzle.box_regions()) != puzzle.size
            or (puzzle.regions and not puzzle.is_standard_boxes)
            or not re.search(layout, text) or set(re.findall(different, text)) != {"digit", "value"}):
        return None
    # The current importer covers explicitly labelled conventional value clues.
    # Leave combined variants with additional rule sections unsupported.
    sections = tuple(re.split(r"\n\s*\n", text))
    heads = ("normal sudoku", "liar cells:", "•", "renban lines:", "black dots:", "white dots:", "x:", "v:", "notes:")
    if any(not section.lstrip().startswith(heads) for section in sections):
        return None
    shapes = {}
    entries = []
    for item in inventory:
        if item.kind == "line" and len(item.cells) > 1:
            colour = item.attrs.get("color", "")
            if colour[:7] in ("#ffffff", "#000000"):
                shapes.setdefault(tuple(item.cells), [])
                continue
            try:
                hue, saturation, _ = rgb_to_hsv(*(int(colour[i:i+2], 16) / 255 for i in (1, 3, 5)))
            except ValueError:
                return None
            if not 0.72 <= hue <= 0.96 or saturation < 0.15 or "renban lines:" not in text:
                return None
            shapes.setdefault(tuple(item.cells), []).append(item.id)
        elif item.kind == "dot":
            colour = item.attrs.get("fill", "")[:7]
            if colour == "#000000" and "black dots:" in text:
                entries.append({"kind": "kropki", "elements": [item.id], "variant": "black"})
            elif colour == "#ffffff" and "white dots:" in text:
                entries.append({"kind": "kropki", "elements": [item.id], "variant": "white"})
            else:
                return None
        elif item.kind == "xv":
            mark = item.attrs["mark"].lower()
            if f"\n{mark}:" not in text:
                return None
            entries.append({"kind": "xv", "elements": [item.id], "sum": item.attrs["sum"]})
    if any(not ids for ids in shapes.values()):
        return None
    entries.extend({"kind": "renban", "elements": [ids[0]]} for ids in shapes.values())
    return {"rules": entries, "globals": [], "model": "liar_values"}


def _different(left, right):
    """Keep digits with at least one different partner."""
    return left if right.bit_count() > 1 else (left & ~right if right else 0)


def _cell_options(domains):
    written, effective, mode, liar_digit, liar_value = domains
    honest = written & effective if mode & HONEST else 0
    left, right = written & liar_digit, effective & liar_value
    return honest, _different(left, right) if mode & LIAR else 0, _different(right, left) if mode & LIAR else 0


def _project(honest, left, right):
    return (honest | left, honest | right,
            (HONEST if honest else 0) | (LIAR if left and right else 0), left, right)


@lru_cache(maxsize=16384)
def _unit_options(options, full):
    """Try each possible liar position and support every compatible Sudoku matching."""
    supported = [[0, 0, 0] for _ in options]
    masks = [honest for honest, _, _ in options]
    for liar, (honest, left, right) in enumerate(options):
        if not left:
            continue
        masks[liar] = left
        matching = _matching_masks(tuple(masks), full)
        masks[liar] = honest
        if matching is None:
            continue
        for pos, mask in enumerate(matching):
            if pos == liar:
                supported[pos][1] |= mask
                supported[pos][2] |= _different(right, mask)
            else:
                supported[pos][0] |= mask
    return tuple(_project(*row) for row in supported)


@dataclass(frozen=True)
class Deduction:
    kind: str
    cells: tuple
    label: str = ""
    other: str | tuple = ""


def _clue_groups(constraints, n):
    """Compile small overlapping value clues into tables of compatible tuples."""
    pairs = [rule for rule in constraints if isinstance(rule, PairRule)]
    groups = {}
    for anchor in constraints:
        cells = list(anchor.cells())
        rules = []
        for rule in pairs:
            if rule is anchor or not set(cells).intersection(rule.cells()):
                continue
            if len(set(cells).union(rule.cells())) <= 7:
                rules.append(rule)
                cells.extend(c for c in rule.cells() if c not in cells)
        if not rules or len(cells) > 7:
            continue
        rules.insert(0, anchor)
        # Include other clues entirely in this scope.
        rules.extend(rule for rule in constraints
                     if rule not in rules and set(rule.cells()).issubset(cells))
        key = frozenset(rules)
        if key in groups:
            continue
        anchor_size = len(anchor.cells())
        if isinstance(anchor, Renban):
            seeds = (vals for window in consecutive_windows(anchor_size, n)
                     for vals in permutations(window))
        else:
            seeds = ((a, b) for a, b in product(range(1, n + 1), repeat=2) if anchor.ok(a, b))
        indexes = {cell: pos for pos, cell in enumerate(cells)}
        checks = [[] for _ in cells]
        for rule in rules[1:]:
            positions = tuple(indexes[c] for c in rule.cells())
            if isinstance(rule, PairRule):
                check = lambda values, p=positions, ok=rule.ok: ok(values[p[0]], values[p[1]])
            else:
                def check(values, p=positions):
                    digits = {values[i] for i in p}
                    return len(digits) == len(p) and max(digits) - min(digits) == len(p) - 1
            checks[max(max(positions), anchor_size - 1)].append(check)
        table = []
        budget = 65_536

        def extend(values):
            nonlocal budget
            budget -= 1
            if not all(check(values) for check in checks[len(values) - 1]):
                return
            if len(values) == len(cells):
                table.append(tuple(1 << (digit - 1) for digit in values))
                return
            for digit in range(1, n + 1):
                if budget <= 0 or len(table) > 4096:
                    return
                extend((*values, digit))

        for seed in seeds:
            extend(seed)
            if budget <= 0 or len(table) > 4096:
                break
        else:
            groups[key] = tuple(cells), tuple(table)
    return tuple(groups.values())


def _joint_support(cells, table, peers):
    adjacent = [sum(1 << j for j, b in enumerate(cells) if i != j and (a, b) in peers)
                for i, a in enumerate(cells)]
    modes = []
    for mask in range(1 << len(cells)):
        liars = [i for i in range(len(cells)) if mask & (1 << i)]
        if all(not (adjacent[i] & mask) for i in liars):
            honest = [i for i in range(len(cells)) if not mask & (1 << i)]
            others = [[j for j in honest if adjacent[i] & (1 << j)] for i in liars]
            modes.append((liars, honest, others))

    @lru_cache(maxsize=256)
    def support(options):
        retained = [[0, 0, 0] for _ in cells]
        for liars, honest, others in modes:
            allowed = [left if index in liars else same for index, (same, _, left) in enumerate(options)]
            if not all(allowed):
                continue
            for values in table:
                if any(not (value & mask) for value, mask in zip(values, allowed)):
                    continue
                if any(values[i] == values[j] for i in honest for j in honest
                       if i < j and adjacent[i] & (1 << j)):
                    continue
                written = []
                for i, neighbors in zip(liars, others):
                    blocked = values[i]
                    for j in neighbors:
                        blocked |= values[j]
                    written.append(options[i][1] & ~blocked)
                if not all(written):
                    continue
                for i in honest:
                    retained[i][0] |= values[i]
                for i, mask in zip(liars, written):
                    retained[i][1] |= mask
                    retained[i][2] |= values[i]
        return tuple(_project(*row) for row in retained)

    return support


@lru_cache(maxsize=4096)
def _pair_support(rule, options, same_unit):
    modes = [((honest, HONEST), (right, LIAR)) for honest, _, right in options]
    support = [[0, 0], [0, 0]]
    for (mask_a, mode_a), (mask_b, mode_b) in product(*modes):
        if same_unit and mode_a == mode_b == LIAR:
            continue
        for x, y in product(bits(mask_a), bits(mask_b)):
            if rule.ok(x, y) and (not same_unit or x != y or mode_a != mode_b):
                support[0][mode_a == LIAR] |= 1 << (x - 1)
                support[1][mode_b == LIAR] |= 1 << (y - 1)
    return tuple(_project(honest, _different(left, right), right)
                 for (_, left, _), (honest, right) in zip(options, support))


class DualValues:
    """Maintain the two domains and the conditional candidates of a liar cell."""

    def __init__(self, puzzle, constraints):
        n = puzzle.size
        self.n = n
        self.full = (1 << n) - 1
        self.units = build_units(puzzle)
        self.unit_groups = [tuple(unit for unit in self.units if unit.kind == kind)
                            for kind in ("row", "col", "region")]
        self.constraints = constraints
        self.dom = [(self.full, self.full, HONEST | LIAR, self.full, self.full)
                    for _ in puzzle.cells]
        for cell, digit in puzzle.givens.items():
            self.dom[cell] = (1 << (digit - 1), *self.dom[cell][1:])
        self.peers = set()
        for unit in self.units:
            self.peers.update(product(unit.cells, repeat=2))
        self.clue_cells = {cell for rule in constraints for cell in rule.cells()}
        self.clue_groups = [(cells, _joint_support(cells, table, self.peers))
                            for cells, table in _clue_groups(constraints, n)]
        intersections = []
        for source in self.units:
            for target in self.units:
                shared = set(source.cells).intersection(target.cells)
                if source is not target and len(shared) > 1:
                    intersections.append((source, target, shared,
                                          tuple(c for c in target.cells if c not in shared)))
        self.checks = [
            *((DualValues._clue, (rule,)) for rule in self.constraints),
            *((DualValues._unit, (unit,)) for unit in self.units),
            *((DualValues._liar_set, (group, layer))
              for group in self.unit_groups for layer in (LIAR_DIGIT, LIAR_VALUE)),
            *((DualValues._joint, args) for args in self.clue_groups),
            *((DualValues._locked, args) for args in intersections),
        ]
        self.last_check = None

    def _apply(self, cells, support, reason):
        changed = []
        for cell, allowed in zip(cells, support):
            narrowed = tuple(old & new for old, new in zip(self.dom[cell], allowed))
            narrowed = _project(*_cell_options(narrowed))
            if not all(narrowed[:3]):
                raise DualContradiction(reason, cell)
            if narrowed != self.dom[cell]:
                changed.append((cell, narrowed))
        for cell, narrowed in changed:
            self.dom[cell] = narrowed
        return reason if changed else None

    def _unit(self, unit):
        cells = tuple(unit.cells)
        support = _unit_options(tuple(_cell_options(self.dom[c]) for c in cells), self.full)
        return self._apply(cells, support, Deduction("unit", cells, unit.label))

    def _liar_set(self, group, layer):
        masks = []
        for unit in group:
            allowed = 0
            for cell in unit.cells:
                allowed |= _cell_options(self.dom[cell])[1 if layer == LIAR_DIGIT else 2]
            masks.append(allowed)
        matching = _matching_masks(tuple(masks), self.full)
        cells = tuple(cell for unit in group for cell in unit.cells)
        reason = Deduction("liar_set", cells, group[0].kind, "digit" if layer == LIAR_DIGIT else "value")
        if matching is None:
            raise DualContradiction(reason)
        allowed = []
        for unit, mask in zip(group, matching):
            for cell in unit.cells:
                honest, left, right = _cell_options(self.dom[cell])
                if layer == LIAR_DIGIT:
                    left &= mask
                else:
                    right &= mask
                allowed.append(_project(honest, _different(left, right), _different(right, left)))
        return self._apply(cells, allowed, reason)

    def _clue(self, rule):
        cells = tuple(rule.cells())
        if isinstance(rule, PairRule):
            a, b = cells
            reason = Deduction("pair", cells, rule._kind,
                               ("black" if rule.params.get("variant") == "black" else "white")
                               if rule._kind == "kropki" else str(rule.params["sum"]))
            options = tuple(_cell_options(self.dom[c]) for c in cells)
            return self._apply(cells, _pair_support(rule, options, (a, b) in self.peers), reason)

        reason = Deduction("renban", cells)
        domains = tuple(self.dom[c][EFFECTIVE] for c in cells)
        support = [0] * len(cells)
        for window in consecutive_windows(len(cells), self.n):
            matching = _matching_masks(domains, sum(1 << (d - 1) for d in window))
            if matching is not None:
                support = [a | b for a, b in zip(support, matching)]
        allowed = [(self.full, values, HONEST | LIAR, self.full, self.full) for values in support]
        return self._apply(cells, allowed, reason)

    def _joint(self, cells, support):
        reason = Deduction("joint", cells)
        options = tuple(_cell_options(self.dom[c]) for c in cells)
        return self._apply(cells, support(options), reason)

    def _locked(self, source, target, shared, outside):
        for layer, full in ((MODE, HONEST | LIAR), (WRITTEN, self.full)):
            confined, elsewhere = 0, 0
            for cell in source.cells:
                if cell in shared:
                    confined |= self.dom[cell][layer]
                else:
                    elsewhere |= self.dom[cell][layer]
            removed = (LIAR if layer == MODE else full) & confined & ~elsewhere
            if removed and any(self.dom[c][layer] & removed for c in outside):
                support = [self.full, self.full, HONEST | LIAR, self.full, self.full]
                support[layer] = full & ~removed
                reason = Deduction("locked", tuple(dict.fromkeys(source.cells + target.cells)), source.label,
                                   (target.label, "liar" if layer == MODE else tuple(bits(removed))))
                return self._apply(outside, [support] * len(outside), reason)
        return None

    def _check(self, index):
        self.last_check = index
        check, args = self.checks[index]
        return check(self, *args)

    def next_deduction(self):
        for index in range(len(self.checks)):
            if change := self._check(index):
                return change
        return None

    def _assume(self, cell, layer, bit):
        clone = copy(self)
        clone.dom = self.dom.copy()
        clone.last_check = None
        allowed = list(clone.dom[cell])
        allowed[layer] = bit
        clone._apply((cell,), (allowed,), Deduction("assume", (cell,)))
        return clone

    def _shorten_proof(self, assumption, proof, conflict_index, conflict, deadline):
        """Drop pieces of a propagation trace only when it still proves the contradiction."""
        if len(proof) <= 4 or conflict_index is None:
            return proof, conflict
        deadline = min(deadline, monotonic() + 0.25)
        size = len(proof) // 2
        while size and monotonic() < deadline:
            start = 0
            while start + size <= len(proof) and monotonic() < deadline:
                cell, layer, digit = assumption
                trial = self._assume(cell, layer, 1 << (digit - 1))
                check_ids = [index for index, _, _ in proof[:start] + proof[start + size:]]
                replacement = []
                try:
                    for index in (*check_ids, conflict_index):
                        before = trial.dom.copy()
                        if reason := trial._check(index):
                            replacement.append((index, reason, _facts(before, trial.dom)))
                except DualContradiction as exc:
                    if len(replacement) < len(proof):
                        proof, conflict, conflict_index = replacement, exc, trial.last_check
                        continue
                start += size
            size //= 2
        return proof, conflict

    def refute(self, deadline):
        """Test the smallest clue-linked domains after direct deductions stall."""
        liar_positions = [self.n] * len(self.dom)
        for unit in self.units:
            hosts = [cell for cell in unit.cells if self.dom[cell][MODE] & LIAR]
            for cell in hosts:
                liar_positions[cell] = min(liar_positions[cell], len(hosts))
        options = []
        for cell, domain in enumerate(self.dom):
            for layer in (WRITTEN, EFFECTIVE, MODE):
                mask = domain[layer]
                if mask.bit_count() < 2 or (cell not in self.clue_cells and layer != MODE):
                    continue
                tight = layer == MODE and liar_positions[cell] == 2
                options.extend((not tight, mask.bit_count(), cell not in self.clue_cells, layer, cell, digit)
                               for digit in bits(mask))
        best = None
        for attempt, (_, _, _, layer, cell, digit) in enumerate(sorted(options)[:160]):
            if monotonic() >= deadline or best and (len(best[2]) <= 4 or attempt >= best[0] + 10):
                break
            bit = 1 << (digit - 1)
            assumption = (cell, layer, digit)
            clone = None
            trace = []
            try:
                clone = self._assume(cell, layer, bit)
                for _ in range(140):
                    if monotonic() >= deadline:
                        break
                    before = clone.dom.copy()
                    reason = clone.next_deduction()
                    if reason is None:
                        break
                    trace.append((clone.last_check, reason, _facts(before, clone.dom)))
            except DualContradiction as exc:
                used = set(exc.reason.cells)
                proof = []
                for index, reason, facts in reversed(trace):
                    affected = {fact["cell"] for fact in facts}
                    if used.intersection(affected):
                        used.update(reason.cells)
                        proof.append((index, reason, facts))
                if best is None or len(proof) < len(best[2]):
                    best = (attempt, assumption, list(reversed(proof)),
                            clone.last_check if clone is not None else None, exc)
        if best is None:
            return None
        _, assumption, trace, conflict_index, exc = best
        trace, exc = self._shorten_proof(assumption, trace, conflict_index, exc, deadline)
        cell, layer, digit = assumption
        allowed = list(self.dom[cell])
        allowed[layer] &= ~(1 << (digit - 1))
        reason = Deduction("refutation", (cell,))
        self._apply((cell,), (allowed,), reason)
        return reason, {
            "assumption": assumption,
            "trace": [{"reason": asdict(reason), "facts": facts} for _, reason, facts in trace],
            "conflict": asdict(exc.reason), "conflict_cell": exc.cell,
        }

    def solved(self):
        return all(w.bit_count() == v.bit_count() == 1 for w, v, *_ in self.dom)

    def verified(self):
        if not self.solved():
            return False
        written, values = ([dom[layer].bit_length() for dom in self.dom]
                           for layer in (WRITTEN, EFFECTIVE))
        liars = {c for c, (w, v) in enumerate(zip(written, values)) if w != v}
        return (all(len(liars.intersection(unit.cells)) == 1
                    and len({written[c] for c in unit.cells}) == self.n for unit in self.units)
                and len({written[c] for c in liars}) == len({values[c] for c in liars}) == self.n
                and all(rule.check(values) for rule in self.constraints))


class DualContradiction(Contradiction):
    def __init__(self, reason, cell=None):
        self.reason, self.cell = reason, cell
        super().__init__(reason.kind)


def _reason_text(reason, n, lang):
    locations = " / ".join(cell_name(c, n) for c in reason.cells) if len(reason.cells) <= n else ""
    if lang == "en":
        if reason.kind == "locked":
            from .step_locale import _unit
            target, digits = reason.other
            role = "the liar cell" if digits == "liar" else f"written digit(s) {', '.join(map(str, digits))}"
            return f"In {_unit(reason.label)}, {role} must be in the overlap with {_unit(target)}. Exclude those candidates elsewhere in {_unit(target)}."
        if reason.kind == "unit":
            from .step_locale import _unit
            return f"In {_unit(reason.label)}, written digits are all different and exactly one cell has a different effective value."
        if reason.kind == "liar_set":
            groups = {"row": "rows", "col": "columns", "region": "regions"}
            role = "written digit" if reason.other == "digit" else "effective value"
            return f"Across the {groups[reason.label]}, each liar cell must use a different {role}. Match each unit to a distinct candidate."
        if reason.kind == "renban":
            return f"Renban at {locations} requires consecutive, distinct effective values."
        if reason.kind == "joint":
            return f"Combine the clues at {locations}. Cells in the same unit cannot both lie, and honest peers must have different values."
        if reason.kind == "assume":
            return "The assumed candidate has no compatible digit and value."
        if reason.label == "xv":
            return f"The effective values at {locations} add to {reason.other}. Equal values in a shared unit require one liar."
        return (f"The black dot at {locations} requires one effective value to be twice the other."
                if reason.other == "black" else f"The white dot at {locations} requires effective values to differ by 1.")
    if reason.kind == "unit":
        return f"{reason.label}的填写数字互异，并且恰有一格的实际值和填写数字不同。保留满足这两个条件的搭配。"
    if reason.kind == "locked":
        target, digits = reason.other
        role = "说谎格" if digits == "liar" else f"数字 {'、'.join(map(str, digits))}"
        return f"{reason.label}的{role}只能在与{target}的交叉处，因此可以从{target}其余格排除。"
    if reason.kind == "liar_set":
        group = {"row": "行", "col": "列", "region": "宫"}[reason.label]
        layer = "填写数字" if reason.other == "digit" else "实际值"
        return f"每{group}恰有一个说谎格。所有说谎格的{layer}互异，因此各{group}必须能分配到不同候选。"
    if reason.kind == "renban":
        return f"{locations} 的 Renban 要求实际值互异并组成一组连续数。"
    if reason.kind == "joint":
        return f"联合检查 {locations} 的提示。同单元不能有两个说谎格，诚实格的实际值也不能相同。"
    if reason.kind == "assume":
        return "该假设下，填写数字和实际值无法搭配。"
    if reason.label == "xv":
        return f"{locations} 的实际值之和为 {reason.other}。若两格同单元且实际值相同，两者必须有一格说谎。"
    return (f"{locations} 间的黑点要求实际值是两倍关系。"
            if reason.other == "black" else f"{locations} 间的白点要求实际值相差 1。")


def _facts(before, after):
    facts = []
    for cell, domain in enumerate(after):
        if domain == before[cell]:
            continue
        written, value, mode, liar_digit, liar_value = domain
        old_written, old_value, old_mode, old_digit, old_liar_value = before[cell]
        facts.append({
            "cell": cell, "digits": list(bits(written)) if written != old_written else [],
            "values": list(bits(value)) if value != old_value else [],
            "mode": mode if mode != old_mode else 0,
            "liar_digits": list(bits(liar_digit)) if mode & LIAR and liar_digit != old_digit else [],
            "liar_values": list(bits(liar_value)) if mode & LIAR and liar_value != old_liar_value else [],
        })
    return facts


def _step(index, before, board, reason, proof):
    facts = _facts(before, board.dom)
    cells = [fact["cell"] for fact in facts]
    events, candidates = [], []
    for cell in cells:
        written, effective, mode, *_ = board.dom[cell]
        old_written = before[cell][WRITTEN]
        if written != old_written:
            if written.bit_count() == 1:
                events.append(Event("place", cell, written.bit_length(), Reason("dual_value"), old_written))
            else:
                events.extend(Event("elim", cell, d, Reason("dual_value"), old_written)
                              for d in bits(old_written & ~written))
        candidates.append({"cell": cell, "digits": list(bits(written)),
                           "effective": list(bits(effective)), "liar_mode": mode})
    narration = {"dual_reason": asdict(reason), "facts": facts, "proof": proof}
    scope = reason.cells if len(reason.cells) <= board.n else ()
    visual = {"focus": cells, "premise": [c for c in scope if c not in cells]}
    if proof:
        conflict_cell = proof["conflict_cell"]
        visual["conflicts"] = [{"scope": proof["conflict"]["cells"],
                                "cells": [] if conflict_cell is None else [conflict_cell]}]
    return Step(index, "dual_value", 4 if proof else 2, "双值反证" if proof else "双值推理",
                describe_step(narration, board.n, "zh"), events, visual=visual,
                pre_dom=[dom[WRITTEN] for dom in before], candidates=candidates, narration=narration)


def _fact_lines(facts, n, lang):
    labels = ("written digit", "effective value", "liar digit", "liar value") if lang == "en" else ("填写数字", "实际值", "若说谎，填写数字", "若说谎，实际值")
    for fact in facts:
        parts = []
        if fact["mode"]:
            parts.append(("is a liar" if fact["mode"] == LIAR else "is honest") if lang == "en"
                         else ("是说谎格" if fact["mode"] == LIAR else "是诚实格"))
        for key, label in zip(("digits", "values", "liar_digits", "liar_values"), labels):
            if digits := fact[key]:
                parts.append(f"{label} ∈ {{{', '.join(map(str, digits))}}}")
        yield f"{cell_name(fact['cell'], n)} " + (", " if lang == "en" else "，").join(parts)


def describe_step(evidence, n, lang, *, show_trace=False):
    reason = Deduction(**evidence["dual_reason"])
    proof = evidence["proof"]
    if proof:
        cell, layer, digit = proof["assumption"]
        name = cell_name(cell, n)
        if lang == "en":
            fact = ("is honest" if digit == 1 else "is a liar") if layer == MODE else (
                f"has {'written digit' if layer == WRITTEN else 'effective value'} {digit}")
            lines = [f"Assume {name} {fact}."]
        else:
            fact = ("是诚实格" if digit == 1 else "是说谎格") if layer == MODE else (
                f"{'填写数字' if layer == WRITTEN else '实际值'}为 {digit}")
            lines = [f"假设 {name} {fact}。"]
        if show_trace:
            for entry in proof["trace"]:
                reason = Deduction(**entry["reason"])
                lines.append(_reason_text(reason, n, lang))
                lines.extend(_fact_lines(entry["facts"], n, lang))
        conflict = _reason_text(Deduction(**proof["conflict"]), n, lang)
        lines.append((f"Contradiction. {conflict} No compatible assignment remains."
                      if lang == "en" else f"出现矛盾。{conflict} 此时已无可行搭配，排除假设。"))
    else:
        lines = [_reason_text(reason, n, lang)]
    if not proof or show_trace:
        lines.extend(_fact_lines(evidence["facts"], n, lang))
    return "\n".join(lines)


def solve_dual(puzzle, constraints, max_steps, allow_chains=True, on_step=None):
    board = DualValues(puzzle, constraints)
    initial = [dom[WRITTEN] for dom in board.dom]
    steps = []
    status, message = "stuck", ""
    deadline = monotonic() + 15
    try:
        while len(steps) < max_steps:
            before = board.dom.copy()
            reason = board.next_deduction()
            proof = None
            if reason is None:
                if board.solved() or not allow_chains:
                    break
                refutation = board.refute(deadline)
                if refutation is None:
                    break
                reason, proof = refutation
            step = _step(len(steps), before, board, reason, proof)
            steps.append(step)
            if on_step is not None:
                try:
                    on_step(step)
                except Exception:
                    pass
    except DualContradiction as exc:
        status, message = "invalid", _reason_text(exc.reason, board.n, "zh")
    else:
        if board.verified():
            status = "solved"
    written, effective = ([dom[layer].bit_length() if dom[layer].bit_count() == 1 else 0
                           for dom in board.dom] for layer in (WRITTEN, EFFECTIVE))
    return SolveResult(status, steps, written, message), initial, effective
