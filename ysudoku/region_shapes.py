"""Local support for a single region of a fixed-size partition."""

from .constraints_ir import AllDifferent
from .state import Contradiction, bits, cell_name


def _mask(cells):
    return sum(1 << c for c in cells)


def region_shapes(board, root, clues, limit=7500):
    """Return all surviving shapes, or None if the local budget is exhausted."""
    owned = _mask(board.groups[root])
    masks = {r: _mask(cells) for r, cells in board.groups.items()}
    allowed = board.board
    for other, mask in masks.items():
        if other != root and board.blocked(root, other):
            allowed &= ~mask
    allowed = board.reachable(owned, allowed)
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
    domains = dict(enumerate(board.state.dom))
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
        cells = [c - 1 for c in bits(shape)]
        if board.minimum_size(cells) != board.n:
            continue
        if not AllDifferent(cells).possible(domains):
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
    union_fits = {}
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
                union = shape | other_shape
                if union not in union_fits:
                    cells = [c - 1 for c in bits(union)]
                    union_fits[union] = board.minimum_size(cells) == 2 * board.n
                return union_fits[union]

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
            return sorted(board.groups[board.owner[root]]), (
                f"{name} 所在片区可扩成 {len(shapes)} 种连通的 {board.n} 格区域。"
                f"按格数、已知边界、圈域提示和数字互异筛选，{premise}每种都包含 {cells}，所以这些格必须同区。")
        boundary = board.expand(_mask(group)) & ~union
        excluded = sorted({board.owner[c - 1] for c in bits(boundary)
                           if not board.blocked(root, board.owner[c - 1])})
        if excluded:
            for other in excluded:
                board.apart(root, other)
            cells = "、".join(cell_name(c, board.n) for c in excluded)
            return sorted(group | set(excluded)), (
                f"{name} 所在片区有 {len(shapes)} 种可行的连通区域形状，{premise}其中都避开 {cells}，"
                "因此可以确定这些邻格与该片区异区。")
    return None
