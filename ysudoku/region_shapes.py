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


MAX_EXPLAINED_SHAPES = 4


def region_shapes(board, root, clues, limit=7500, *, masks=None, allowed=None,
                  max_shapes=None, case_pockets=None):
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
                if max_shapes is not None and len(layers[board.n]) > max_shapes:
                    return None
                visited += 1
                if visited > limit:
                    return None
    domains = board.state.dom
    full = board.state.full
    result = set()
    if case_pockets is not None:
        case_pockets.update(dict.fromkeys(layers[board.n], 0))
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
            if case_pockets is not None:
                case_pockets[shape] = min((piece for piece in board.uncovered_components(shape)
                                           if piece.bit_count() % board.n), key=int.bit_count)
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
    masks = {root: _mask(group) for root, group in board.groups.items()}
    placements = {}
    relevant = board.expand(_mask(c for root in board.colours for c in board.groups[root]))
    relevant |= _mask({cell for clue in clues for cell in clue.cells()})

    coloured = sorted(board.colours, key=lambda root: (-len(board.groups[root]), root))
    frontier = sorted(
        (reach.bit_count(), root, reach)
        for root in masks.keys() - board.colours.keys() if relevant & masks[root]
        if (reach := _growth_space(board, root, masks))
    )
    roots = [(root, None, 7500) for root in coloured]
    roots += [(root, reach, 2500) for _, root, reach in frontier[:16]]
    for root, reach, budget in roots:
        shapes = region_shapes(board, root, clues, limit=budget, masks=masks, allowed=reach,
                               max_shapes=MAX_EXPLAINED_SHAPES)
        if shapes is None:
            continue
        if not shapes:
            raise Contradiction(f"{cell_name(root, board.n)} 所在片区无法组成一个连通的 {board.n} 格区域。")
        proof = _local_consequence(board, root, shapes, masks[root])
        if proof:
            return proof
        if root in board.colours:
            placements[root] = shapes
    return separated_shape_anchors(board, placements)


def _case_list(shapes):
    return [[c - 1 for c in bits(shape)] for shape in sorted(shapes)]


def _local_consequence(board, root, shapes, owned):
    if owned.bit_count() == board.n:
        return None
    common, union = board.board, 0
    for shape in shapes:
        common &= shape
        union |= shape
    same = sorted({board.owner[c - 1] for c in bits(common & ~owned)})
    apart = sorted({board.owner[c - 1] for c in bits(board.expand(owned) & ~union)
                    if not board.blocked(root, board.owner[c - 1])})
    targets = same or apart
    if not targets:
        return None

    evidence = {"shape_cases": _case_list({shape & ~owned for shape in shapes}),
                "fragment": sorted(board.groups[root]), "targets": targets, "same": bool(same)}
    focus = sorted(board.groups[root].union(*(board.groups[c] for c in targets)))
    for other in targets:
        if same:
            board.merge(board.owner[root], board.owner[other])
        else:
            board.apart(root, other)
    return RegionShapeProof(focus, explain_shape_cases(evidence, board.n), evidence=evidence)


def separated_shape_anchors(board, placements):
    """Two fragments can share a region only if their shape lists intersect."""
    ordered = sorted(placements, key=lambda root: (len(placements[root]), root))
    comparisons = []
    used_cases = {}
    for index, root in enumerate(ordered):
        shapes = placements[root]
        for other in ordered[index + 1:]:
            if board.blocked(root, other) or not shapes.isdisjoint(placements[other]):
                continue
            cases = used_cases | {root: shapes, other: placements[other]}
            if sum(map(len, cases.values())) > MAX_EXPLAINED_SHAPES:
                continue
            used_cases = cases
            comparisons.append({"anchor": root, "targets": [other]})
    if not comparisons:
        return None

    evidence = {"shape_comparisons": comparisons,
                "shared_region_cases": [{"anchor": root, "cases": _case_list(shapes)}
                                        for root, shapes in used_cases.items()]}
    for comparison in comparisons:
        board.apart(comparison["anchor"], comparison["targets"][0])
    return RegionShapeProof(sorted(used_cases), explain_shape_cases(evidence, board.n),
                            "比较片区的少量可行形状", evidence)


def explain_shape_cases(evidence, n, lang="zh"):
    english = lang == "en"
    joiner = ", " if english else "、"
    alternatives = " or " if english else " 或 "

    def names(cells):
        return joiner.join(cell_name(c, n) for c in cells)

    def cases(groups):
        return alternatives.join(f"[{names(cells)}]" for cells in groups)

    if "shape_cases" in evidence:
        fragment = names(evidence["fragment"])
        options = cases(evidence["shape_cases"])
        targets = names(evidence["targets"])
        if english:
            intro = (f"To complete the {n}-cell region containing {fragment}, "
                     f"the rules leave these choices for its additional cells: {options}.")
            conclusion = (f"Every choice includes {targets}, so they are in the same region as the fragment."
                          if evidence["same"] else
                          f"Every choice excludes {targets}, so those fragments are in other regions.")
        else:
            intro = f"要把 {fragment} 补成 {n} 格区域，按规则只能补入以下格组：{options}。"
            conclusion = (f"每种都包含 {targets}，所以它们与该片区同区。" if evidence["same"]
                          else f"每种都避开 {targets}，所以这些片区与它异区。")
        return f"{intro}\n{conclusion}"

    lines = [f"Two fragments in the same region must have the same {n}-cell shape."
             if english else f"两个片区如果同区，就必须能补成同一个 {n} 格形状。"]
    for item in evidence["shared_region_cases"]:
        anchor = names([item["anchor"]])
        options = cases(item["cases"])
        lines.append(f"Possible shapes at {anchor}: {options}." if english
                     else f"{anchor} 所在片区的可行形状：{options}。")
    for item in evidence["shape_comparisons"]:
        a, b = names([item["anchor"]]), names(item["targets"])
        lines.append(f"{a} and {b} share no shape, so they are in different regions." if english
                     else f"{a} 和 {b} 没有相同的可行形状，因此异区。")
    return "\n".join(lines)
