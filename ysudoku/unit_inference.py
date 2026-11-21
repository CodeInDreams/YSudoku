"""Derive full Sudoku units from explicit pairwise-distinct relationships."""

from itertools import combinations

from .constraints import Cage, Custom, IRSupport, Renban, Thermo
from .constraints_ir import AllDifferent, Sum
from .state import Unit, build_units


def _predicate_groups(node, cells):
    if node.op == "and":
        for child in node.args:
            yield from _predicate_groups(child, cells)
    elif node.op in ("all_different", "ordered", "ne", "lt", "gt"):
        if all(arg.op == "var" for arg in node.args):
            yield [cells[arg.params["index"]] for arg in node.args]


def _distinct_groups(rule):
    if isinstance(rule, Custom):
        yield from _predicate_groups(rule.node, rule.cells())
    elif isinstance(rule, (Renban, Thermo)) or isinstance(rule, Cage) and rule.unique:
        yield rule.cells()
    elif isinstance(rule, IRSupport):
        for relation in rule.relations:
            if isinstance(relation, AllDifferent) or isinstance(relation, Sum) and relation.unique:
                yield relation.cells


def _full_cliques(graph, size):
    """Find maximal cliques of exactly size, using only explicit variant edges."""
    def visit(group, candidates, visited):
        if len(group) + len(candidates) < size or len(group) > size:
            return
        if not candidates and not visited:
            if len(group) == size:
                yield frozenset(group)
            return
        pivot = max(candidates | visited, key=lambda cell: len(candidates & graph[cell]))
        for cell in sorted(candidates - graph[pivot]):
            adjacent = graph[cell]
            yield from visit(group | {cell}, candidates & adjacent, visited & adjacent)
            candidates.remove(cell)
            visited.add(cell)

    return visit(set(), set(graph), set())


def solver_units(puzzle, rules):
    units = build_units(puzzle, (rules.diagonal_main, rules.diagonal_anti),
                        chaos=puzzle.is_chaos)
    graph = {}
    trusted_edges = set()
    for rule in rules.constraints:
        for cells in _distinct_groups(rule):
            for a, b in combinations(sorted(set(cells)), 2):
                graph.setdefault(a, set()).add(b)
                graph.setdefault(b, set()).add(a)
                if not getattr(rule, "hypothesis", False):
                    trusted_edges.add((a, b))

    existing = {frozenset(unit.cells) for unit in units}
    extra = sorted(_full_cliques(graph, puzzle.size), key=lambda cells: tuple(sorted(cells)))
    lines = {frozenset(line.cells): line for line in puzzle.lines}
    distinct_index = 0
    for cells in extra:
        if cells in existing:
            continue
        ordered = sorted(cells)
        hypothesis = any(edge not in trusted_edges for edge in combinations(ordered, 2))
        if line := lines.get(cells):
            units.append(Unit("line", line.id, line.cells, hypothesis))
        else:
            units.append(Unit("distinct", distinct_index, ordered, hypothesis))
            distinct_index += 1
    return units
