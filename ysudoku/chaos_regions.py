"""Proven region fragments. A colour names a fragment, not a final region ID."""

from copy import copy
from itertools import combinations

from .colour_map import ColourMap, MAX_COLOURS_PER_CELL
from .narrate import Step
from .region_shapes import shape_deduction
from .region_refutation import refute_count, region_growth
from .state import Contradiction, Reason, cell_name
from .visual_colours import HEX

SWATCHES = {**HEX, **dict(enumerate((
    "#cc3311", "#117733", "#0044c4", "#ee99aa", "#ffff19",
    "#f046f0", "#a05a1e", "#33bbee", "#911eb4",
), 9))}

RGB = {colour: tuple(bytes.fromhex(hex_value[1:])) for colour, hex_value in SWATCHES.items()}
MIN_ADJACENT_DISTANCE = 85 ** 2


def colour_distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(RGB[a], RGB[b]))


class RegionFragments:
    def __init__(self, state):
        self.state = state
        self.n = n = state.n
        self.groups = {i: {i} for i in range(n*n)}
        self.owner = list(self.groups)
        self.separate = set()
        self.corner_choices = {}
        self.colours = {}
        self.display_colours = {}
        self.geometry = {}
        self.board = (1 << (n*n)) - 1
        self.left = sum(1 << (i*n) for i in range(n))
        self.right = self.left << (n-1)

    def mark(self, root):
        if root not in self.colours:
            free = next((c for c in SWATCHES if c not in self.colours.values()), None)
            if free is not None:
                self.colours[root] = free

    def apart(self, a, b):
        if a == b:
            raise Contradiction("同一片区被要求属于不同区域")
        self.separate.add(tuple(sorted((a, b))))

    def blocked(self, a, b):
        if tuple(sorted((a, b))) in self.separate:
            return True
        left, right = self.groups[a], self.groups[b]
        if len(left) + len(right) > self.n:
            return True
        digits = {self.state.dom[c] for c in left if self.state.dom[c].bit_count() == 1}
        if any(self.state.dom[c] in digits for c in right):
            return True
        union = frozenset(left | right)
        if union not in self.geometry:
            # Every other region must fit entirely inside one connected piece
            # of the complement. Its size is a multiple of n in each piece.
            coords = [divmod(c, self.n) for c in union]
            far = any(abs(r-i) + abs(c-j) >= self.n
                      for (r, c), (i, j) in combinations(coords, 2))
            self.geometry[union] = far or self.minimum_size(union) > self.n
        return self.geometry[union]

    def minimum_size(self, group):
        outside = self.board ^ sum(1 << c for c in group)
        minimum = len(group)
        while outside:
            piece = outside & -outside
            while True:
                more = piece | (self.expand(piece) & outside)
                if more == piece:
                    break
                piece = more
            minimum += piece.bit_count() % self.n
            outside ^= piece
        return minimum

    def merge(self, a, b):
        if self.blocked(a, b):
            raise Contradiction("合并会违反区域格数、同区互异或圈域提示")
        if b in self.colours and (a not in self.colours or self.colours[b] < self.colours[a]):
            a, b = b, a
        for cell in self.groups[b]:
            self.owner[cell] = a
        self.groups[a].update(self.groups.pop(b))
        self.colours.pop(b, None)
        self.mark(a)
        self.separate = {tuple(sorted(a if v == b else v for v in pair)) for pair in self.separate}

    def expand(self, mask):
        return ((mask & ~self.left) >> 1 | (mask & ~self.right) << 1
                | mask >> self.n | mask << self.n) & self.board

    def reachable(self, owned, allowed):
        # Every pair in a connected N-cell region is at most N-1 edges apart.
        possible = allowed
        pending = owned
        while pending:
            bit = pending & -pending
            pending ^= bit
            seen = bit
            for _ in range(self.n - 1):
                wider = seen | (self.expand(seen) & allowed)
                if wider == seen:
                    break
                seen = wider
            possible &= seen
        return possible

    def capacity(self):
        masks = {r: sum(1 << c for c in group) for r, group in self.groups.items()}
        for a, owned in masks.items():
            allowed = self.board
            for b, mask in masks.items():
                if a != b and self.blocked(a, b):
                    allowed &= ~mask
            reach = self.reachable(owned, allowed)
            if owned & ~reach or reach.bit_count() < self.n:
                raise Contradiction(f"{cell_name(a, self.n)} 所在区域无法连成 {self.n} 格")
            # Any route out of the current fragment uses a boundary cell.
            boundary = self.expand(owned) & reach & ~owned
            while boundary:
                bit = boundary & -boundary
                boundary ^= bit
                b = self.owner[bit.bit_length()-1]
                without = self.reachable(owned, allowed & ~masks[b])
                if owned & ~without or without.bit_count() < self.n:
                    detail = (f"{cell_name(a, self.n)} 所在区域若绕开 {cell_name(b, self.n)} 所在片区，"
                              f"可连通范围最多只有 {without.bit_count()} 格。"
                              if without.bit_count() < self.n else
                              f"绕开 {cell_name(b, self.n)} 所在片区，{cell_name(a, self.n)} 所在区域的已知格无法连通。")
                    return a, b, detail + "两个片区必须同区。"
        return None

    def replace_corner_clue(self, rule):
        cells = rule.cells()
        if rule.counts != [3] or len(set(cells)) != 4 or self.n < 2:
            return None
        for corner in (0, self.n - 1, self.n * (self.n - 1), self.n**2 - 1):
            if corner not in cells:
                continue
            neighbours = self.expand(1 << corner)
            exits = tuple(c for c in cells if neighbours & (1 << c))
            if len(exits) != 2:
                continue
            diagonal = next(c for c in cells if c != corner and c not in exits)
            if not all(self.expand(1 << c) & (1 << diagonal) for c in exits):
                continue
            # Connectivity supplies the disjunction. Exactly three regions
            # then makes the other three cells pairwise different.
            anchors = (*exits, diagonal)
            for a, b in combinations(anchors, 2):
                self.apart(self.owner[a], self.owner[b])
            self.apart(self.owner[corner], self.owner[diagonal])
            for c in anchors:
                self.mark(self.owner[c])
            self.corner_choices[corner] = anchors
            left, right = (cell_name(c, self.n) for c in exits)
            return (f"{cell_name(corner, self.n)} 在盘角，要连成 {self.n} 格区域，必须与 {left} 或 {right} 同区。"
                    f"四格跨三区，只能有一对同区，所以 {left}、{right}、{cell_name(diagonal, self.n)} 两两异区。"
                    "角格的两种颜色表示二选一。绿线是已确定的边界。两条黄线中恰有一条会成为边界，排除的边界会变红。")
        return None

    def propagate_choices(self):
        for cell, (left, right, _) in self.corner_choices.items():
            root = self.owner[cell]
            targets = [self.owner[left], self.owner[right]]
            if root in targets:
                continue
            viable = [b for b in targets if not self.blocked(root, b)]
            if not viable:
                raise Contradiction(f"{cell_name(cell, self.n)} 的两个同区出口都被排除")
            if len(viable) == 1:
                other, = viable
                self.merge(root, other)
                return [cell, left, right], (f"{cell_name(cell, self.n)} 的两个出口只剩"
                                             f" {cell_name(other, self.n)} 所在片区，因此必须同区。")
        return None

    def region_palette(self):
        """Choose distinct swatches for visible fragments that touch."""
        display = {root: colour for root, colour in self.display_colours.items() if root in self.colours}
        adjacent = {root: set() for root in self.colours}
        for cell, root in enumerate(self.owner):
            if root not in adjacent:
                continue
            for other in (cell + 1, cell + self.n):
                if other >= len(self.owner) or not self.expand(1 << cell) & (1 << other):
                    continue
                peer = self.owner[other]
                if root != peer and peer in adjacent:
                    adjacent[root].add(peer)
                    adjacent[peer].add(root)
        for root, original in self.colours.items():
            current = display.get(root)
            neighbours = [display[peer] for peer in adjacent[root] if peer in display]
            free = [colour for colour in SWATCHES if colour not in display.values()]
            preferred = current if current is not None else (original if original in free else free[0])
            alternatives = [preferred, *(colour for colour in free if colour != preferred)]
            display[root] = next(
                (colour for colour in alternatives if all(
                    colour_distance(colour, other) >= MIN_ADJACENT_DISTANCE for other in neighbours
                )),
                preferred,
            )
        self.display_colours = display
        return display

    def snapshot(self):
        palette = self.region_palette()
        groups = [{"region": True, "colour": colour, "hex": SWATCHES[colour], "cells": sorted(self.groups[root])}
                  for root, colour in palette.items()]
        pairs = [{"a": ca, "b": cb, "possible": not self.blocked(a, b)}
                 for (a, ca), (b, cb) in combinations(palette.items(), 2)]
        options, edges = {}, []
        for cell, (a, b, diagonal) in self.corner_choices.items():
            owned = self.owner[cell]
            targets = [self.owner[a], self.owner[b]]
            if owned not in targets and all(r in palette for r in targets):
                options.setdefault(owned, {"cells": sorted(self.groups[owned]),
                                           "colours": [palette[r] for r in targets]})
            for anchor in (a, b):
                edges.append({"cells": [anchor, diagonal], "status": "confirmed"})
                target = self.owner[anchor]
                if target == owned:
                    status = "excluded"
                else:
                    status = "confirmed" if self.blocked(owned, target) else "candidate"
                edges.append({"cells": [cell, anchor], "status": status})
        drawn = {tuple(sorted(edge["cells"])) for edge in edges}
        for cell, root in enumerate(self.owner):
            for other in (cell + 1, cell + self.n):
                if (other >= len(self.owner) or not self.expand(1 << cell) & (1 << other)
                        or (cell, other) in drawn):
                    continue
                peer = self.owner[other]
                # Keep the corner clue's explanatory strokes, drawn above.
                # An ordinary edge adds nothing between two single-colour pieces.
                visible = (root in palette or peer in palette)
                both_single = (root in palette and peer in palette
                               and root not in options and peer not in options)
                if root != peer and visible and not both_single and self.blocked(root, peer):
                    edges.append({"cells": [cell, other], "status": "confirmed"})
        progress = {"complete": sum(len(g) == self.n for g in self.groups.values()),
                    "total": len(self.owner) // self.n,
                    "coloured": sum(len(self.groups[r]) for r in self.colours if r not in options)}
        return {"colours": groups, "region_pairs": pairs, "region_options": list(options.values()),
                "region_edges": edges, "region_progress": progress}

    def clue(self, rule):
        cells = rule.cells()
        roots = list(dict.fromkeys(self.owner[c] for c in cells))
        distinct = len(cells) in rule.counts and rule.counts == [len(cells)]
        one = rule.counts == [1]
        pairs = list(combinations(roots, 2))
        if rule.counts == [1, len(cells)]:
            distinct = any(self.blocked(a, b) for a, b in pairs)
            one = len(roots) < len(cells)
        if distinct:
            if len(roots) != len(cells) or one and len(cells) > 1:
                raise Contradiction("圈内的同区关系与区域数冲突")
            if all(tuple(sorted(pair)) in self.separate for pair in pairs):
                return None
            for a, b in pairs:
                self.apart(a, b)
            for a in roots:
                self.mark(a)
            return cells, "圈内每格各属一个区域，以不同颜色标出这些已确定互异的片区。"
        if one and pairs:
            for b in roots[1:]:
                self.merge(self.owner[cells[0]], b)
            return cells, "圈内只能有一个区域，因此这些格必须同区。"
        if 1 < len(roots) < len(cells) and rule.counts == [len(roots)]:
            if any(not self.blocked(a, b) for a, b in pairs):
                for a, b in pairs:
                    self.apart(a, b)
                for a in roots:
                    self.mark(a)
                hosts = "、".join(cell_name(next(c for c in cells if self.owner[c] == a), self.n)
                                 for a in roots)
                return cells, f"已有格子同区，圈内只剩 {len(roots)} 个片区。要满足区域数，{hosts} 必须两两异区。"
            return None
        # For small circles, intersect the local partitions still allowed by
        # their count and the proven pair relations (e.g. a three-region clue).
        if len(roots) <= 4 and not one and not distinct:
            partitions = [[]]
            for root in roots:
                more = []
                for blocks in partitions:
                    for index, block in enumerate(blocks):
                        if all(not self.blocked(root, other) for other in block):
                            more.append(blocks[:index] + [block + [root]] + blocks[index+1:])
                    more.append(blocks + [[root]])
                partitions = more
            patterns = [p for p in partitions if len(p) in rule.counts]
            if not patterns:
                raise Contradiction("圈内没有满足区域数的分组")
            for a, b in pairs:
                together = [any(a in block and b in block for block in p) for p in patterns]
                names = f"{cell_name(a, self.n)} 和 {cell_name(b, self.n)}"
                if all(together):
                    self.merge(a, b)
                    return cells, f"这个圈的所有可行分组都要求 {names} 同区。"
                if not any(together) and not self.blocked(a, b):
                    self.apart(a, b)
                    self.mark(a)
                    self.mark(b)
                    return cells, f"这个圈的所有可行分组都要求 {names} 不同区。"
        return None


def region_steps(solver, rules, steps):
    state = solver.state
    fragments = RegionFragments(state)
    solver.allow_chains = False  # Construct regions from deductions before the separate search fallback.
    clues = [copy(c) for c in rules.constraints if c.kind == "region_count"]
    fragments.count_clues = clues
    for clue, step in zip(clues.copy(), steps):
        detail = fragments.replace_corner_clue(clue)
        if detail:
            clues.remove(clue)
            step.title = "角格的两个同区出口"
            step.detail = detail
        observation = None if detail else fragments.clue(clue)
        if observation:
            step.detail += "\n" + observation[1]
        step.visual.update(fragments.snapshot())
        if solver.on_step:
            solver.on_step(step)
    while True:
        pre_dom, pre_vals = state.dom.copy(), state.vals.copy()
        observation = fragments.propagate_choices()
        if not observation:
            for clue in clues:
                detail = fragments.replace_corner_clue(clue)
                if detail:
                    clues.remove(clue)
                    observation = clue.cells(), detail
                    break
                observation = fragments.clue(clue)
                if observation:
                    break
        events = []
        if not observation:
            relation = fragments.capacity()
            if relation:
                a, b, detail = relation
                cells = sorted(fragments.groups[a] | fragments.groups[b])
                fragments.merge(a, b)
                observation = cells, detail
        if not observation:
            for cells in fragments.groups.values():
                if len(cells) < 2:
                    continue
                state.begin()
                for c in sorted(cells):
                    if state.dom[c].bit_count() != 1:
                        continue
                    digit = state.dom[c].bit_length()
                    for peer in sorted(cells - {c}):
                        if state.has(peer, digit):
                            state.elim(peer, digit, Reason("region_peer", {"by": c, "value": digit}))
                events = state.end()
                if events:
                    observation = sorted(cells), "同一区域内数字互异。" + "；".join(
                        f"{cell_name(e.reason.data['by'], state.n)} 已确定为 {e.value}，"
                        f"{cell_name(e.cell, state.n)} 排除 {e.value}" for e in events)
                    break
        if not observation and any(min(c.counts) > 1 for c in clues):
            forced = region_growth(fragments, clues)
            if forced:
                (a, b), detail = forced
                cells = sorted(fragments.groups[a] | fragments.groups[b])
                fragments.merge(a, b)
                observation = cells, detail
        if observation:
            cells, detail = observation
            step = Step(len(steps), "chaos_region", 2, "混沌区域推理", detail, events,
                        visual={"focus": cells}, pre_dom=pre_dom, pre_vals=pre_vals)
        else:
            step, error = solver.next_step()
            if error:
                raise Contradiction(error)
            if step is None:
                proof = refute_count(fragments, clues)
                if proof:
                    index, count, reasons = proof
                    clue = clues[index]
                    clue.counts = [k for k in clue.counts if k != count]
                    cells = clue.cells()
                    remaining = " 或 ".join(map(str, clue.counts))
                    detail = [f"假设以 {cell_name(cells[0], state.n)} 起的圈跨 {count} 个区域，"
                              f"则每个区域至多占圈内 {len(cells) - count + 1} 格。",
                              *reasons, f"排除 {count} 区，此圈只剩 {remaining} 区。"]
                    step = Step(len(steps), "constraint_simplify", 2, f"区域数反证：排除 {count} 区",
                                "\n".join(detail), [], visual={"focus": cells}, pre_dom=pre_dom, pre_vals=pre_vals)
                else:
                    shape = shape_deduction(fragments, clues)
                    if not shape:
                        break
                    cells, detail = shape
                    step = Step(len(steps), "chaos_region", 2, "区域形状推理", detail, [],
                                visual={"focus": cells}, pre_dom=pre_dom, pre_vals=pre_vals)
            step.index = len(steps)
        snapshot = fragments.snapshot()
        # Region labels take one slot; preserve other annotations up to the
        # existing per-cell limit as well.
        marks = ColourMap(state.n)
        for item in snapshot["colours"]:
            for cell in item["cells"]:
                marks.add(cell, item["colour"])
        for option in snapshot["region_options"]:
            for cell in option["cells"]:
                for colour in option["colours"]:
                    if len(marks.colours(cell)) < MAX_COLOURS_PER_CELL:
                        marks.add(cell, colour)
        for item in step.visual.get("colours", []):
            cells = []
            for cell in item["cells"]:
                existing = marks.colours(cell)
                if item["colour"] not in existing and len(existing) < MAX_COLOURS_PER_CELL:
                    marks.add(cell, item["colour"])
                    cells.append(cell)
            if cells:
                snapshot["colours"].append(dict(item, cells=cells))
        step.visual.update(snapshot)
        steps.append(step)
        if solver.on_step:
            solver.on_step(step)
    return fragments
