"""Propagate alternatives and optional exact usage counts across regions."""

from .constraints import Constraint
from .state import Contradiction, Reason


def _matching(options, quotas, forced=None, witness=None):
    if quotas is None:
        return all(options)
    slots = [name for name, count in quotas.items() for _ in range(count)]
    allowed = list(options)
    if forced is not None:
        region, name = forced
        allowed[region] = {name}
    owner = {}

    def assign(region, visited):
        for slot, name in enumerate(slots):
            if slot in visited or name not in allowed[region]:
                continue
            visited.add(slot)
            if slot not in owner or assign(owner[slot], visited):
                owner[slot] = region
                return True
        return False

    for region in sorted(range(len(options)), key=lambda i: len(allowed[i])):
        visited = set()
        if assign(region, visited):
            continue
        if witness is not None:
            # No augmenting path: these regions can only occupy the visited slots.
            witness.update(regions=sorted({region, *(owner[slot] for slot in visited)}),
                           slots=len(visited))
        return False
    return True


class RuleAlternative(Constraint):
    """One selectable rule can be a conjunction of existing constraints."""

    def __init__(self, constraints):
        self.constraints = constraints
        self.scope = sorted({cell for rule in constraints for cell in rule.cells()})

    def cells(self):
        return self.scope

    def check(self, values):
        return all(rule.check(values) for rule in self.constraints)

    def to_dict(self):
        return {"kind": "and", "rules": [rule.to_dict() for rule in self.constraints]}

    def prune(self, st):
        changed = False
        while True:
            results = [rule.prune(st) for rule in self.constraints]
            if not any(results):
                return changed
            changed = True


class RuleChoice(Constraint):
    kind = "rule_choice"

    def __init__(self, regions, quotas=None):
        self.regions = [(label, dict(options)) for label, options in regions]
        self.quotas = dict(quotas) if quotas is not None else None
        if not self.regions or any(not options for _, options in self.regions):
            raise ValueError("每个区域至少需要一种可选规则")
        self.scopes = [sorted({cell for rule in options.values() for cell in rule.cells()})
                       for _, options in self.regions]
        if self.quotas is not None:
            names = {name for _, options in self.regions for name in options}
            if (set(self.quotas) != names
                    or any(type(count) is not int or count < 0 for count in self.quotas.values())
                    or sum(self.quotas.values()) != len(self.regions)):
                raise ValueError("规则使用次数必须覆盖所有规则，且合计等于区域数")

    def cells(self):
        return sorted(set().union(*self.scopes))

    def describe(self):
        return "规则分配" if self.quotas is not None else "规则择一"

    def to_dict(self):
        return {"kind": self.kind, "quotas": self.quotas, "regions": [
            {"label": label, "options": {name: rule.to_dict() for name, rule in options.items()}}
            for label, options in self.regions
        ]}

    def check(self, values):
        return _matching([{name for name, rule in options.items()
                           if not all(values[c] for c in rule.cells()) or rule.check(values)}
                          for _, options in self.regions], self.quotas)

    def prune(self, st):
        # An alternative is supported by its current local rules. In particular,
        # an inconclusive propagation is kept as a possibility.
        tables, rejected = [], []
        for _, options in self.regions:
            table, failures = {}, {}
            for name, rule in options.items():
                trial = st.copy()
                try:
                    if all(st.vals[c] for c in rule.cells()) and not rule.check(st.vals):
                        raise Contradiction(f"确定的数字不符合「{rule.describe()}」")
                    rule.prune(trial)
                except Contradiction as exc:
                    failures[name] = str(exc)
                else:
                    table[name] = trial.dom
            tables.append(table)
            rejected.append(failures)
        possible = [set(table) for table in tables]
        if not _matching(possible, self.quotas):
            raise Contradiction("各区域剩余的规则选项无法满足使用次数"
                                if self.quotas is not None else "某一区域没有可行的规则")
        supported, witnesses = [], []
        for i, table in enumerate(tables):
            names, failures = [], {}
            for name in table:
                witness = {}
                if _matching(possible, self.quotas, (i, name), witness):
                    names.append(name)
                else:
                    failures[name] = witness
            supported.append(names)
            witnesses.append(failures)
        reason = Reason(self.kind, {
            "regions": [{"label": label, "cells": self.scopes[i],
                         "rejected": rejected[i],
                         "unmatched": [name for name in tables[i] if name not in supported[i]],
                         "witnesses": witnesses[i],
                         "remaining": supported[i]}
                        for i, (label, _) in enumerate(self.regions)],
            "quotas": self.quotas,
        })
        changed = False
        for scope, table, names in zip(self.scopes, tables, supported):
            for cell in scope:
                allowed = 0
                for name in names:
                    allowed |= table[name][cell]
                changed |= st.restrict(cell, allowed, reason)
        return changed
