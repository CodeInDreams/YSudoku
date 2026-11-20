"""Replace a finite local relation only after proving equality on current domains."""

from itertools import product
from math import prod

from .constraints import Arrow, Cage, ExactDigits, IRSupport
from .constraints_ir import Sum, TupleRelation
from .state import bits, cell_name


# Only richer arithmetic or table relations can lower to one multiset.
# Neither the target nor Sudoku units are rewrite sources.
def can_simplify(rule):
    if type(rule) is IRSupport:
        return any(isinstance(r, (Sum, TupleRelation)) for r in rule.relations)
    return type(rule) in (Cage, Arrow)


def simplify(rule, state):
    if not can_simplify(rule):
        return None
    scope = rule.cells()
    cells = [c for c in scope if not state.vals[c]]
    if not 1 <= len(cells) <= 4 or len(scope) != len(set(scope)):
        return None
    domains = [tuple(bits(state.dom[c])) for c in cells]
    if prod(map(len, domains)) > 1024:
        return None

    # The first valid tuple proposes a multiset. Check BOTH directions,
    # including permutations rejected by a directional source constraint.
    values = state.vals.copy()
    digits = None
    legal = set()
    for assignment in product(*domains):
        for c, v in zip(cells, assignment):
            values[c] = v
        if not rule.check(values):
            continue
        if isinstance(rule, Cage) and rule.non_consecutive_pair:
            if abs(values[scope[0]] - values[scope[1]]) == 1:
                continue
        bag = tuple(sorted(assignment))
        if digits is not None and bag != digits:
            return None
        digits = bag
        legal.add(assignment)
    if not legal or any(tuple(sorted(a)) == digits and a not in legal
                        for a in product(*domains)):
        return None

    target = ExactDigits(cells, digits)
    fixed = [c for c in scope if state.vals[c]]
    facts = "、".join(f"{cell_name(c, state.n)}={state.vals[c]}" for c in fixed)
    detail = rule.describe() + "。"
    if facts:
        detail += f"已知 {facts}。"
    if isinstance(rule, Cage):
        subtraction = "".join(f"−{state.vals[c]}" for c in fixed)
        residual = rule.total - sum(state.vals[c] for c in fixed)
        if fixed:
            detail += f"余下总和为 {rule.total}{subtraction}={residual}。"
        if rule.unique:
            detail += "笼内数字互异。"
        if rule.non_consecutive_pair:
            detail += "两格数字也不能连续。"
    if isinstance(rule, Arrow):
        detail += "圈内数字等于箭身各格之和。"
    if isinstance(rule, IRSupport):
        detail += "同时满足 " + "、".join(r.describe() for r in rule.relations) + "。"
    names = "、".join(cell_name(c, state.n) for c in cells)
    detail += f"在当前候选中，{names} 只有一种数字组合（{'、'.join(map(str, digits))}）。"
    return target, detail
