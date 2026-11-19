"""Propagate equations left after cancelling cells shared by two sum clues."""

from dataclasses import dataclass
from itertools import combinations

from .constraints_ir import Sum
from .state import Contradiction, Reason, bits, cell_name


def _equation(terms, total, n):
    positive = []
    negative = []
    for cell, coeff in terms:
        name = cell_name(cell, n)
        (positive if coeff > 0 else negative).append(
            name if abs(coeff) == 1 else f"{abs(coeff)}×{name}")
    if total or not negative:
        (negative if total >= 0 else positive).append(str(abs(total)))
    return " + ".join(positive or ["0"]) + " = " + " + ".join(negative or ["0"])


def _sources(constraints):
    for con in constraints:
        if con.kind == "arrow":
            terms = [(c, 1) for c in con.arm] + [(con.circle, -1)]
            if len(dict(terms)) == len(terms):
                yield "箭头", dict(terms), 0
        elif con.kind == "cage" and len(set(con.cells())) == len(con.cells()):
            yield "笼和", dict.fromkeys(con.cells(), 1), con.total
        elif getattr(con, "_kind", "") == "xv" and con.a != con.b:
            total = con.params["sum"]
            yield {5: "V", 10: "X"}.get(total, "配对和"), dict.fromkeys(con.cells(), 1), total
        elif con.kind == "ir_support":
            for relation in con.relations:
                if isinstance(relation, Sum):
                    yield "和数", dict.fromkeys(relation.cells, 1), relation.total


@dataclass
class SumLink:
    terms: tuple
    total: int
    premises: tuple
    shared: tuple
    last_domains: tuple = ()

    def affected(self, state):
        return self.last_domains != tuple(state.dom[c] for c, _ in self.terms)

    def apply(self, state):
        masks = tuple(state.dom[c] for c, _ in self.terms)
        contributions = [[(v, coeff * v) for v in bits(mask)]
                         for (_, coeff), mask in zip(self.terms, masks)]
        prefix = [{0}]
        for choices in contributions:
            prefix.append({s + term for s in prefix[-1] for _, term in choices})
        if self.total not in prefix[-1]:
            raise Contradiction("共享格组消去后，剩余候选无法满足和数关系")
        suffix = {0}
        allowed = []
        for i in reversed(range(len(self.terms))):
            choices = contributions[i]
            allowed.append(sum(1 << (v - 1) for v, term in choices
                               if any(self.total - term - s in suffix for s in prefix[i])))
            suffix = {s + term for s in suffix for _, term in choices}
        pairs = []
        if len(self.terms) == 2:
            pairs = [(x, y) for x, left in contributions[0] for y, right in contributions[1]
                     if left + right == self.total]
        reason = Reason("sum_link", {
            "pairs": pairs,
            "premises": self.premises, "shared": self.shared,
            "equation": _equation(self.terms, self.total, state.n),
            "domains": [(c, list(bits(mask))) for (c, _), mask in zip(self.terms, masks)],
        })
        for (cell, _), mask in zip(self.terms, reversed(allowed)):
            state.restrict(cell, mask, reason)
        self.last_domains = tuple(state.dom[c] for c, _ in self.terms)


def compile_links(constraints, n):
    sources = list(_sources(constraints))
    links = {}
    for (name, left, a), (other, right, b) in combinations(sources, 2):
        shared = sorted(c for c in left.keys() & right.keys() if left[c] == right[c])
        if not shared:
            continue
        terms = [(c, left.get(c, 0) - right.get(c, 0)) for c in sorted(left.keys() | right.keys())]
        terms = [(c, coeff) for c, coeff in terms if coeff]
        if not terms:
            continue
        sign = 1 if terms[0][1] > 0 else -1
        terms = tuple((c, coeff * sign) for c, coeff in terms)
        total = (a - b) * sign
        premises = (name + " " + _equation(left.items(), a, n),
                    other + " " + _equation(right.items(), b, n))
        key = terms, total
        if key not in links or len(shared) < len(links[key].shared):
            links[key] = SumLink(terms, total, premises, tuple(shared))
    return sorted(links.values(), key=lambda link: len(link.terms))
