"""Local support for a single region of a fixed-size partition."""

from dataclasses import dataclass, field
from functools import lru_cache

from .constraints_ir import AllDifferent
from .state import Contradiction, bits, cell_name


@dataclass
class RegionShapeProof:
    cells: list[int]
    detail: str
    title: str = "区域形状推理"
    evidence: dict = field(default_factory=dict)


def _mask(cells):
    return sum(1 << c for c in cells)


def _growth_space(board, root, masks):
    owned = masks[root]
    allowed = board.board
    for other, mask in masks.items():
        if other != root and board.blocked(root, other):
            allowed &= ~mask
    return board.reachable(owned, allowed)


@lru_cache(maxsize=4096)
def _has_distinct_digits(restricted_domains):
    # Unrestricted cells can use any digits left after matching the restricted
    # ones. Every accepted shape has exactly one cell per digit.
    return (not restricted_domains
            or AllDifferent(range(len(restricted_domains))).possible(restricted_domains))


def region_shapes(board, root, clues, limit=7500, *, masks=None, allowed=None):
    """Return all surviving shapes, or None if the local budget is exhausted."""
    if masks is None:
        masks = {r: _mask(cells) for r, cells in board.groups.items()}
    if allowed is None:
        allowed = _growth_space(board, root, masks)
    owned = masks[root]
    if owned & ~allowed:
        return set()
    forced_groups = [mask for mask in masks.values() if mask.bit_count() > 1]
    # A region either misses a clue or contributes one of its distinct regions.
    count_bounds = [(_mask(c.cells()), tuple(c.counts)) for c in clues]
    ceilings = [(mask, mask.bit_count() - min(counts) + 1)
                for mask, counts in count_bounds]
    choices = [(1 << c, (1 << a) | (1 << b))
               for c, (a, b, _) in board.corner_choices.items()]
    layers = [set() for _ in range(board.n + 1)]
    layers[owned.bit_count()].add(owned)
    visited = 0
    for size in range(owned.bit_count(), board.n):
        for shape in layers[size]:
            for cell in bits(board.expand(shape) & allowed & ~shape):
                grown = shape | masks[board.owner[cell - 1]]
                length = grown.bit_count()
                if length > board.n or grown & ~allowed or grown in layers[length]:
                    continue
                if any((grown & mask).bit_count() > cap for mask, cap in ceilings):
                    continue
                layers[length].add(grown)
                visited += 1
                if visited > limit:
                    return None
    domains = board.state.dom
    full = board.state.full
    result = set()
    for shape in layers[board.n]:
        connected = shape & -shape
        while (more := connected | (board.expand(connected) & shape)) != connected:
            connected = more
        if connected != shape:
            continue
        if any(shape & cell and not shape & exits
               for cell, exits in choices):
            continue
        if any(shape & group and shape & group != group for group in forced_groups):
            continue
        if any(not any((2 if shape & mask and mask & ~shape else 1)
                       <= k <= (mask & ~shape).bit_count() + bool(shape & mask)
                       for k in counts) for mask, counts in count_bounds):
            continue
        if board.minimum_cover(shape) != board.n:
            continue
        restricted = tuple(sorted(domains[c - 1] for c in bits(shape) if domains[c - 1] != full))
        if not _has_distinct_digits(restricted):
            continue
        # A complete region cannot contain both ends of a proven border.
        if any(shape & masks[a] and shape & masks[b] for a, b in board.separate):
            continue
        result.add(shape)
    return result


def shape_deduction(board, clues):
    placements = {}
    for root in sorted(board.colours, key=lambda r: (-len(board.groups[r]), r)):
        group = board.groups[root]
        shapes = (region_shapes(board, root, clues) if len(group) < board.n
                  else {_mask(group)})
        if shapes is not None:
            placements[root] = shapes
    for root, shapes in placements.items():
        group = board.groups[root]
        name = cell_name(root, board.n)
        peer_name = ""
        for other, other_shapes in placements.items():
            if root == other:
                continue
            distinct = board.blocked(root, other)
            check_pockets = len(shapes) * len(other_shapes) <= 4096

            def can_coexist(shape, other_shape):
                if shape & other_shape:
                    return not distinct and shape == other_shape
                if not check_pockets:
                    return True
                return board.minimum_cover(shape | other_shape) == 2 * board.n

            filtered = {s for s in shapes if any(can_coexist(s, t) for t in other_shapes)}
            if len(filtered) < len(shapes):
                peer_name = cell_name(other, board.n)
                shapes = filtered
        if not shapes:
            raise Contradiction(f"{name} 所在片区无法组成一个连通的 {board.n} 格区域。")
        if len(group) == board.n:
            continue
        premise = f"并检查与 {peer_name} 等片区能否共存，" if peer_name else ""
        common, union = board.board, 0
        for shape in shapes:
            common &= shape
            union |= shape
        added = [c - 1 for c in bits(common & ~_mask(group))]
        if added:
            for cell in added:
                a, b = board.owner[root], board.owner[cell]
                if a != b:
                    board.merge(a, b)
            cells = "、".join(cell_name(c, board.n) for c in added)
            return RegionShapeProof(sorted(board.groups[board.owner[root]]),
                f"{name} 所在片区可扩成 {len(shapes)} 种连通的 {board.n} 格区域。"
                f"按格数、已知边界、圈域提示和数字互异筛选，{premise}每种都包含 {cells}，所以这些格必须同区。")
        boundary = board.expand(_mask(group)) & ~union
        excluded = sorted({board.owner[c - 1] for c in bits(boundary)
                           if not board.blocked(root, board.owner[c - 1])})
        if excluded:
            for other in excluded:
                board.apart(root, other)
            cells = "、".join(cell_name(c, board.n) for c in excluded)
            return RegionShapeProof(sorted(group | set(excluded)),
                f"{name} 所在片区有 {len(shapes)} 种可行的连通区域形状，{premise}其中都避开 {cells}，"
                "因此可以确定这些邻格与该片区异区。")
    return (frontier_deduction(board, clues, placements)
            or separated_shape_anchors(board, placements))


MAX_FRONTIER_ROOTS = 16
FRONTIER_SHAPE_BUDGET = 2500
MAX_PAIR_CHECKS = 25_000


def frontier_deduction(board, clues, placements):
    """Use local shapes around the frontier of the constructed partition."""
    relevant = board.expand(_mask(c for r in placements for c in board.groups[r]))
    relevant |= _mask({cell for clue in clues for cell in clue.cells()})
    if not relevant:
        return None
    masks = {r: _mask(cells) for r, cells in board.groups.items()}
    peers_by_cost = sorted(placements.items(), key=lambda item: (len(item[1]), item[0]))
    priority = []
    for root in board.groups.keys() - board.colours.keys():
        if relevant & masks[root]:
            reach = _growth_space(board, root, masks)
            priority.append((reach.bit_count(), root, reach))

    for _, root, allowed in sorted(priority)[:MAX_FRONTIER_ROOTS]:
        shapes = region_shapes(board, root, clues, limit=FRONTIER_SHAPE_BUDGET, masks=masks, allowed=allowed)
        if shapes is None:
            continue
        proof = _frontier_consequence(board, root, shapes, masks)
        if proof:
            return proof

        # Prefer a single supporting region. If that is insufficient, combine
        # the independent support checks without exploring a board solution.
        filtered = shapes
        peers = []
        for other, candidates in peers_by_cost:
            if len(shapes) * len(candidates) > MAX_PAIR_CHECKS:
                continue
            common = shapes & candidates
            supports = {shape for shape in shapes if shape in common
                        or any(not shape & candidate for candidate in candidates)}
            if supports == shapes:
                continue
            proof = _frontier_consequence(board, root, supports, masks, [other])
            if proof:
                return proof
            if filtered - supports:
                filtered &= supports
                peers.append(other)
        if peers:
            proof = _frontier_consequence(board, root, filtered, masks, peers)
            if proof:
                return proof
    return None


def _frontier_consequence(board, root, shapes, masks, peers=()):
    name = cell_name(root, board.n)
    if not shapes:
        raise Contradiction(f"{name} 所在区域没有可行的 {board.n} 格形状。")
    common, union = board.board, 0
    for shape in shapes:
        common &= shape
        union |= shape
    same = [c - 1 for c in bits(common & ~masks[root])]
    apart = sorted({board.owner[c - 1] for c in bits(board.expand(masks[root]) & ~union)
                    if not board.blocked(root, board.owner[c - 1])})
    if not same and not apart:
        return None

    target = same or apart
    original = sorted(board.groups[root])
    peer_cells = sorted({c for other in peers for c in board.groups[other]})
    focus = sorted(set(original).union(*(board.groups[board.owner[c]] for c in target)))
    letters = "、".join(cell_name(c, board.n) for c in target)
    premise = f"分别检查与 {'、'.join(cell_name(c, board.n) for c in peers)} 所在片区的形状能否共存后，" if peers else ""
    intro = f"从未染色的 {name} 出发，{premise}有 {len(shapes)} 种可能的 {board.n} 格连通区域。"
    if same:
        for cell in same:
            a, b = board.owner[root], board.owner[cell]
            if a != b:
                board.merge(a, b)
        detail = f"{intro}每种形状都经过 {letters}，这些格必须同区。"
    else:
        for other in apart:
            board.apart(root, other)
        detail = f"{intro}每种形状都避开 {letters}，这些邻格必须异区。"
    return RegionShapeProof(focus, detail, "未染色格的区域形状", {
        "region_anchor": root, "shape_count": len(shapes), "same": bool(same),
        "targets": target, "peers": list(peers), "premise": peer_cells,
    })


def separated_shape_anchors(board, placements):
    """Compare shape lists once, then apply independent distinct-region facts."""
    ordered = sorted(placements, key=lambda root: (len(placements[root]), root))
    comparisons = []
    focus = set()
    for index, root in enumerate(ordered):
        shapes = placements[root]
        excluded = [other for other in ordered[index + 1:]
                    if not board.blocked(root, other) and shapes.isdisjoint(placements[other])]
        if excluded:
            comparisons.append({"anchor": root, "targets": excluded, "shape_count": len(shapes)})
            focus.update((root, *excluded))
    if not comparisons:
        return None

    detail = [f"如果两个片区同区，它们必须能扩成同一个连通的 {board.n} 格形状。"]
    for comparison in comparisons:
        root = comparison["anchor"]
        name = cell_name(root, board.n)
        peers = "、".join(cell_name(c, board.n) for c in comparison["targets"])
        detail.append(f"{name} 的 {comparison['shape_count']} 种形状在 {peers} 的清单里都找不到，"
                      f"因此 {name} 与这些片区分别异区。")
        for other in comparison["targets"]:
            board.apart(root, other)
    return RegionShapeProof(sorted(focus), "\n".join(detail), "比较片区的可行形状",
                            {"shape_comparisons": comparisons})
