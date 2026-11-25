"""Chaos construction: regions are unknown and must be discovered.

This is a *search* solver, not a human-style deduction engine.  It assigns
region membership and digits together and returns the first consistent
solution.  It is deliberately bounded: unsolved boards return ``timeout``
instead of running forever.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache


@lru_cache(maxsize=65536)
def _quad_supports(needs: tuple[int, ...], domains: tuple[int, ...]):
    """Return GAC-supported values for a quadruple's required digit multiset."""
    if not needs:
        return domains
    ordered = sorted(needs, key=lambda d: (
        sum(bool(mask & (1 << (d - 1))) for mask in domains), d
    ))
    if any(not any(mask & (1 << (digit - 1)) for mask in domains)
           for digit in ordered):
        return None

    support = [0] * len(domains)
    placed = [0] * len(domains)

    def visit(index: int, used: int) -> None:
        if index == len(ordered):
            for cell, mask in enumerate(domains):
                support[cell] |= placed[cell] or mask
            return
        bit = 1 << (ordered[index] - 1)
        for cell, mask in enumerate(domains):
            cell_bit = 1 << cell
            if not used & cell_bit and mask & bit:
                placed[cell] = bit
                visit(index + 1, used | cell_bit)
                placed[cell] = 0

    visit(0, 0)
    return tuple(support) if any(support) else None


class _Timeout(Exception):
    pass


@dataclass
class ChaosResult:
    status: str  # solved | timeout | unsupported
    values: list[int]
    regions: list[list[int]] = field(default_factory=list)
    nodes: int = 0
    message: str = ""


def _neighbors(cell: int, n: int):
    r, c = divmod(cell, n)
    if r > 0:
        yield cell - n
    if r + 1 < n:
        yield cell + n
    if c > 0:
        yield cell - 1
    if c + 1 < n:
        yield cell + 1


def solve_chaos(puzzle, constraints, node_limit: int = 1_500_000,
                time_limit: float = 20.0, *, fragments=None, domains=None) -> ChaosResult:
    n = puzzle.size
    if n > 9:
        return ChaosResult("unsupported", [0] * (n * n), message="仅支持 9x9 及以下")
    total = n * n
    neighbors = [tuple(_neighbors(cell, n)) for cell in range(total)]
    neighbor_masks = [sum(1 << nb for nb in cells) for cells in neighbors]
    givens = dict(puzzle.givens)
    values = [0] * total
    region_of = [-1] * total
    region_cells: list[list[int]] = []
    region_cell_masks: list[int] = []
    unassigned_mask = (1 << total) - 1
    region_used: list[int] = []
    row_used = [0] * n
    col_used = [0] * n
    full = (1 << n) - 1
    row_units = [[r * n + c for c in range(n)] for r in range(n)]
    col_units = [[r * n + c for r in range(n)] for c in range(n)]
    latin_units = [(cells, "row", r) for r, cells in enumerate(row_units)] + [
        (cells, "col", c) for c, cells in enumerate(col_units)
    ]
    base_domains = domains if domains is not None else [full] * total
    same_masks = [0] * total
    apart_masks = [0] * total
    if fragments is not None:
        masks = {r: sum(1 << c for c in g) for r, g in fragments.groups.items()}
        for root, cells in fragments.groups.items():
            apart = sum(masks[b] for b in masks if b != root and fragments.blocked(root, b))
            for c in cells:
                same_masks[c] = masks[root] ^ (1 << c)
                apart_masks[c] = apart
    nodes = [0]
    started = time.monotonic()
    region_rules = getattr(fragments, "count_clues",
                           [con for con in constraints
                            if getattr(con, "region_counts", lambda: None)() is not None])
    quadruples = [con for con in constraints
                  if getattr(con, "digit_demands", lambda: None)()]
    quad_needs = []
    for con in quadruples:
        demands = con.digit_demands() or {}
        quad_needs.append(tuple((int(d), int(c)) for d, c in demands.items()
                                if 1 <= d <= n and c > 0))
    quad_by_row = [set() for _ in range(n)]
    quad_by_col = [set() for _ in range(n)]
    for qi, con in enumerate(quadruples):
        for cell in con.cells():
            r, c = divmod(cell, n)
            quad_by_row[r].add(qi)
            quad_by_col[c].add(qi)
    region_rules_by_cell = [[] for _ in range(total)]
    for con in region_rules:
        for cell in con.cells():
            region_rules_by_cell[cell].append(con)
    cage_rules = []
    for con in constraints:
        con_total = getattr(con, "total", None)
        if con.kind == "cage" and con_total is not None:
            cage_rules.append((set(con.cells()), int(con_total), bool(getattr(con, "unique", True))))

    def cages_ok() -> bool:
        for cells, target_sum, unique in cage_rules:
            vals = [values[c] for c in cells if values[c]]
            if unique and len(set(vals)) != len(vals):
                return False
            if len(vals) == len(cells):
                if sum(vals) != target_sum:
                    return False
                continue
            remaining = len(cells) - len(vals)
            if not (sum(vals) + remaining <= target_sum <= sum(vals) + remaining * n):
                return False
        return True

    def region_can_grow(index: int) -> bool:
        """Whether all cells of a partial region can still form one connected region."""
        if len(region_cells[index]) >= n:
            return len(region_cells[index]) == n and _connected(region_cells[index], n)
        owned = region_cell_masks[index]
        seed = owned & -owned
        reachable = seed
        frontier = seed
        allowed = unassigned_mask | owned
        while frontier:
            expanded = 0
            pending = frontier
            while pending:
                bit = pending & -pending
                pending ^= bit
                expanded |= neighbor_masks[bit.bit_length() - 1]
            frontier = expanded & allowed & ~reachable
            reachable |= frontier
        return (owned & ~reachable) == 0 and reachable.bit_count() >= n

    def _connected(cells: list[int], size: int) -> bool:
        wanted = sum(1 << cell for cell in cells)
        if not wanted:
            return False
        seed = wanted & -wanted
        reached = seed
        frontier = seed
        while frontier:
            expanded = 0
            pending = frontier
            while pending:
                bit = pending & -pending
                pending ^= bit
                expanded |= neighbor_masks[bit.bit_length() - 1]
            frontier = expanded & wanted & ~reached
            reached |= frontier
        return reached.bit_count() == size

    def candidate_mask(cell: int) -> int:
        r, c = divmod(cell, n)
        blocked = row_used[r] | col_used[c]
        region = region_of[cell]
        if region >= 0:
            blocked |= region_used[region]
        given = givens.get(cell)
        if given:
            bit = 1 << (given - 1)
            return bit if not blocked & bit else 0
        return base_domains[cell] & ~blocked

    def propagated_domains() -> list[int] | None:
        """Forward-check Latin units and quadruples to a local fixed point."""
        domains = [candidate_mask(cell) if not values[cell]
                   else 1 << (values[cell] - 1) for cell in range(total)]
        changed = True
        while changed:
            changed = False
            for cells, kind, index in latin_units:
                used_mask = row_used[index] if kind == "row" else col_used[index]
                single_bits = 0
                host_count = [0] * n
                host_cell = [-1] * n
                for cell in cells:
                    if values[cell]:
                        continue
                    mask = domains[cell]
                    if mask.bit_count() == 1:
                        if single_bits & mask:
                            return None
                        single_bits |= mask
                    while mask:
                        bit = mask & -mask
                        mask ^= bit
                        digit_index = bit.bit_length() - 1
                        host_count[digit_index] += 1
                        host_cell[digit_index] = cell
                if single_bits:
                    for cell in cells:
                        if (not values[cell] and domains[cell].bit_count() > 1
                                and domains[cell] & single_bits):
                            domains[cell] &= ~single_bits
                            if not domains[cell]:
                                return None
                            changed = True
                missing = full & ~used_mask
                while missing:
                    bit = missing & -missing
                    missing ^= bit
                    digit_index = bit.bit_length() - 1
                    count = host_count[digit_index]
                    if not count:
                        return None
                    if count == 1 and domains[host_cell[digit_index]] != bit:
                        domains[host_cell[digit_index]] = bit
                        changed = True
            for qi, con in enumerate(quadruples):
                cells = con.cells()
                masks = tuple(domains[cell] for cell in cells)
                required = tuple(digit for digit, count in quad_needs[qi]
                                 for _ in range(count))
                support = _quad_supports(required, masks)
                if support is None:
                    return None
                for cell, allowed in zip(cells, support):
                    if values[cell] and not (allowed & domains[cell]):
                        return None
                    if not values[cell] and allowed != domains[cell]:
                        domains[cell] &= allowed
                        changed = True
        return domains

    def region_count_possible(con) -> bool:
        cells = con.cells()
        assigned = {c: region_of[c] for c in cells if region_of[c] >= 0}
        unassigned = [c for c in cells if region_of[c] < 0]
        existing = sorted(set(assigned.values()))
        if not unassigned:
            return len(existing) in con.counts
        usable = [r for r, assigned_cells in enumerate(region_cells)
                  if len(assigned_cells) < n]
        new_slots = max(0, n - len(region_cells))
        new_ids = [-(i + 1) for i in range(min(len(unassigned), new_slots))]
        options = usable + new_ids
        if not options:
            return False
        # The clue observes only the number of distinct labels. Every
        # unassigned cell may reuse a usable label or introduce a new region;
        # the interval below is a safe relaxation and avoids a Cartesian
        # product at every search node.
        extra_labels = len(set(options) - set(existing))
        max_distinct = len(existing) + min(len(unassigned), extra_labels)
        return any(len(existing) <= count <= max_distinct for count in con.counts)

    def check_all() -> bool:
        region_map = {c: region_of[c] for c in range(total)}
        for con in constraints:
            if getattr(con, "region_counts", lambda: None)() is not None:
                if not con.check_regions(values, region_map):
                    return False
            elif not con.check(values):
                return False
        return True

    choices_by_cell = {}
    for corner, (a, b, _) in getattr(fragments, "corner_choices", {}).items():
        for cell in (corner, a, b):
            choices_by_cell.setdefault(cell, []).append((corner, a, b))

    def region_rules_ok(cell: int) -> bool:
        for corner, a, b in choices_by_cell.get(cell, ()):
            labels = [region_of[a], region_of[b]]
            if region_of[corner] >= 0 and -1 not in labels and region_of[corner] not in labels:
                return False
        for con in region_rules_by_cell[cell]:
            if not region_count_possible(con):
                return False
        return True

    def dfs(assigned_count: int):
        nonlocal unassigned_mask
        nodes[0] += 1
        if nodes[0] % 256 == 0 and time.monotonic() - started > time_limit:
            raise _Timeout
        if nodes[0] > node_limit:
            raise _Timeout
        if assigned_count == total:
            if (all(len(cells) == n and _connected(cells, n) for cells in region_cells)
                    and check_all()):
                return list(values), [list(cells) for cells in region_cells]
            return None

        domains = propagated_domains()
        if domains is None:
            return None

        unassigned = [cell for cell in range(total) if region_of[cell] < 0]
        if region_rules or choices_by_cell or quadruples:
            # MRV over propagated domains; circle cells break ties first.
            def pair_count(x: int) -> int:
                mask = domains[x]
                existing = sum(
                    (mask & ~region_used[rr]).bit_count()
                    for rr, cells in enumerate(region_cells) if len(cells) < n
                )
                if len(region_cells) < n:
                    existing += mask.bit_count()
                return existing

            cell = min(unassigned, key=lambda x: (
                pair_count(x), domains[x].bit_count(),
                -len(quad_by_row[x // n] | quad_by_col[x % n]), x
            ))
        else:
            # With no region-specific clues, a simple connected growth order
            # avoids exploring equivalent arbitrary region labelings.
            cell = unassigned[0]
        r, c = divmod(cell, n)
        adjacent = {region_of[nb] for nb in neighbors[cell] if region_of[nb] >= 0}
        if region_rules or choices_by_cell or quadruples:
            options = [rr for rr, cells in enumerate(region_cells) if len(cells) < n]
        else:
            options = [rr for rr in adjacent if len(region_cells[rr]) < n]
        options.sort(key=lambda rr: (rr not in adjacent, -len(region_cells[rr]), rr))
        can_start = len(region_cells) < n
        if can_start:
            options.append(-1)

        for choice in options:
            owned = region_cell_masks[choice] if choice >= 0 else 0
            if owned & apart_masks[cell] or same_masks[cell] & ~unassigned_mask & ~owned:
                continue
            created = False
            if choice == -1:
                choice = len(region_cells)
                region_cells.append([])
                region_cell_masks.append(0)
                region_used.append(0)
                created = True
            region_cells[choice].append(cell)
            cell_bit = 1 << cell
            region_cell_masks[choice] |= cell_bit
            unassigned_mask &= ~cell_bit
            region_of[cell] = choice
            # Connectivity depends on region membership, not on the digit.
            # Occupying a bridge may also strand a different unfinished region.
            if (not region_rules_ok(cell) or not region_can_grow(choice)
                    or any(not region_can_grow(rr) for rr in range(len(region_cells))
                           if rr != choice and len(region_cells[rr]) < n)):
                region_cells[choice].pop()
                region_cell_masks[choice] &= ~cell_bit
                unassigned_mask |= cell_bit
                region_of[cell] = -1
                if created:
                    region_cells.pop()
                    region_cell_masks.pop()
                    region_used.pop()
                continue
            digit_mask = domains[cell] & candidate_mask(cell)
            remaining_digits = digit_mask
            while remaining_digits:
                bit = remaining_digits & -remaining_digits
                remaining_digits ^= bit
                digit = bit.bit_length()
                values[cell] = digit
                row_used[r] |= bit
                col_used[c] |= bit
                region_used[choice] |= bit
                if not cages_ok():
                    row_used[r] &= ~bit
                    col_used[c] &= ~bit
                    region_used[choice] &= ~bit
                    values[cell] = 0
                    continue
                try:
                    result = dfs(assigned_count + 1)
                finally:
                    row_used[r] &= ~bit
                    col_used[c] &= ~bit
                    region_used[choice] &= ~bit
                if result:
                    return result
                values[cell] = 0
            region_cells[choice].pop()
            region_cell_masks[choice] &= ~cell_bit
            unassigned_mask |= cell_bit
            region_of[cell] = -1
            if created:
                region_cells.pop()
                region_cell_masks.pop()
                region_used.pop()
        return None

    try:
        result = dfs(0)
    except _Timeout:
        return ChaosResult("timeout", [0] * total, nodes=nodes[0],
                           message=f"搜索超过预算（{nodes[0]} 结点）")
    if result is None:
        return ChaosResult("unsupported", [0] * total, nodes=nodes[0],
                           message="在预算内没有找到一致解")
    values_out, regions_out = result
    return ChaosResult("solved", values_out, regions_out, nodes=nodes[0],
                       message=f"搜索 {nodes[0]} 个结点后找到一致解")


def check_chaos_solution(puzzle, constraints, values: list[int], regions: list[list[int]]) -> list[str]:
    n = puzzle.size
    total = n * n
    want = set(range(1, n + 1))
    errors: list[str] = []
    if len(values) != total:
        return [f"盘面应有 {total} 格，实际为 {len(values)} 格"]
    for r in range(n):
        if set(values[r * n:(r + 1) * n]) != want:
            errors.append(f"第{r + 1}行不完整")
    for c in range(n):
        if {values[r * n + c] for r in range(n)} != want:
            errors.append(f"第{c + 1}列不完整")
    if len(regions) != n or any(len(reg) != n for reg in regions):
        errors.append("区域数量或大小不对")
    flat_regions = [cell for reg in regions for cell in reg]
    valid_partition = (len(regions) == n and len(flat_regions) == total
                       and set(flat_regions) == set(range(total)))
    if not valid_partition:
        errors.append("区域必须恰好覆盖每格一次")
    region_of = {cell: i for i, reg in enumerate(regions) for cell in reg
                 if 0 <= cell < total}
    if valid_partition:
        for i, reg in enumerate(regions):
            if {values[cell] for cell in reg} != want:
                errors.append(f"区域{i + 1}不是 1..{n} 的排列")
            if not _cells_connected(reg, n):
                errors.append(f"区域{i + 1}不连通")
    for con in constraints:
        if con.kind == "region_count":
            if valid_partition and not con.check_regions(values, region_of):
                errors.append(f"违反规则：{con.describe()}")
        elif not con.check(values):
            errors.append(f"违反规则：{con.describe()}")
    return errors


def _cells_connected(cells: list[int], n: int) -> bool:
    """Check orthogonal connectivity of a region's cell indices."""
    wanted = set(cells)
    if not wanted:
        return False
    seen = {next(iter(wanted))}
    stack = list(seen)
    while stack:
        cell = stack.pop()
        for neighbor in _neighbors(cell, n):
            if neighbor in wanted and neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen == wanted
