"""Propagate alternatives and optional exact usage counts across regions."""

from collections import Counter
from itertools import product

from .constraints import Constraint
from .state import Contradiction, Reason

MAX_JOINT_ASSIGNMENTS = 16
MAX_JOINT_CELLS = 24
MAX_JOINT_ROUNDS = 5


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
        self.scope = sorted(set().union(*self.scopes))
        if self.quotas is not None:
            names = {name for _, options in self.regions for name in options}
            if (set(self.quotas) != names
                    or any(type(count) is not int or count < 0 for count in self.quotas.values())
                    or sum(self.quotas.values()) != len(self.regions)):
                raise ValueError("规则使用次数必须覆盖所有规则，且合计等于区域数")

    def cells(self):
        return self.scope

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

    def _joint(self, st, supported):
        count = 1
        for names in supported:
            count *= len(names)
            if count > MAX_JOINT_ASSIGNMENTS:
                return None
        if len(self.scope) > MAX_JOINT_CELLS:
            return None

        branches, rejected = [], []
        for names in product(*supported):
            if self.quotas is not None and Counter(names) != Counter(self.quotas):
                continue
            trial = st.copy()
            rules = [options[name] for (_, options), name in zip(self.regions, names)]
            premises = {}
            try:
                for _ in range(MAX_JOINT_ROUNDS):
                    changed = False
                    for index, rule in enumerate(rules):
                        trial.record = st.record
                        trial.events = []
                        changed |= rule.prune(trial)
                        for event in trial.events:
                            hook = getattr(rule, "choice_premise", None)
                            premise = hook(event) if hook else None
                            if premise:
                                premises[index] = premise
                        trial.record = False
                    for cell in self.scope:
                        if not trial.vals[cell] and trial.dom[cell].bit_count() == 1:
                            changed |= trial.place(cell, trial.dom[cell].bit_length())
                    if not changed:
                        break
                if any(all(trial.vals[c] for c in rule.cells()) and not rule.check(trial.vals)
                       for rule in rules):
                    raise Contradiction("分配后确定的数字不符合所选规则")
            except Contradiction as exc:
                if st.record:
                    rejected.append({"rules": names, "reason": str(exc)})
                continue
            facts = [[cell, trial.dom[cell].bit_length()] for cell in self.scope
                     if trial.dom[cell].bit_count() == 1 and st.dom[cell].bit_count() > 1]
            branches.append((trial.dom, {"rules": names, "premises": list(premises.values()), "facts": facts}))
        if not branches:
            raise Contradiction("所有符合规则使用次数的分配都与当前候选冲突")
        return branches, rejected

    def _shared_occupancy(self, st, branches, allowed):
        common = None
        for domains, _ in branches:
            branch = {}
            for cell in self.scope:
                mask = domains[cell]
                if mask.bit_count() == 1:
                    for index in st.unit_of[cell]:
                        branch.setdefault((index, mask), set()).add(cell)
            if common is None:
                common = branch
            else:
                common = {key: hosts | branch[key] for key, hosts in common.items() if key in branch}
        locks = []
        for (index, digit), hosts in common.items():
            unit = st.units[index]
            targets = [cell for cell in unit.cells if cell not in hosts and st.dom[cell] & digit]
            if not targets:
                continue
            for cell in targets:
                allowed[cell] = allowed.get(cell, st.dom[cell]) & ~digit
            if len(hosts) > 1:
                locks.append({"unit": unit.label, "unit_cells": unit.cells,
                              "hosts": sorted(hosts), "digit": digit.bit_length()})
        return locks

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
        allowed = {}
        joint = self._joint(st, supported)
        if joint is None:
            for scope, table, names in zip(self.scopes, tables, supported):
                for cell in scope:
                    mask = 0
                    for name in names:
                        mask |= table[name][cell]
                    allowed[cell] = allowed.get(cell, st.dom[cell]) & mask
        else:
            branches, failures = joint
            for cell in self.scope:
                mask = 0
                for domains, _ in branches:
                    mask |= domains[cell]
                allowed[cell] = mask
            locks = self._shared_occupancy(st, branches, allowed)
            for i, region in enumerate(reason.data["regions"]):
                region["remaining"] = list(dict.fromkeys(evidence["rules"][i] for _, evidence in branches))
            reason.data.update(assignments=[evidence for _, evidence in branches],
                               failures=failures, occupancy=locks)
        changed = False
        for cell, mask in allowed.items():
            changed |= st.restrict(cell, mask, reason)
        return changed
