"""Shorten a deduction path by retrying it with fewer proved assumptions."""

import time
from itertools import combinations

from .search import refute_candidate_with_proof
from .state import Contradiction, Reason, bits, cell_name


def shorten_path(path, costs, replay, score, *, seconds=6.0, max_trials=24):
    """Try omitting whole proofs, keeping only shorter paths with the same endpoint.

    The replay callback verifies the endpoint and reports the proofs it actually
    used. Within the budget, revisit earlier failed deletions after an improvement.
    """
    deadline = time.monotonic() + seconds
    tried = set()
    for _ in range(max_trials):
        if time.monotonic() >= deadline:
            break
        choices = tuple(costs)
        omitted = next((choice for choice in sorted(choices, key=costs.get, reverse=True)
                        if (choices, choice) not in tried), None)
        if omitted is None:
            break
        tried.add((choices, omitted))
        current_score = score(path, costs)
        trial = replay([choice for choice in choices if choice != omitted],
                       deadline, current_score[-1])
        if trial is not None and score(*trial) < current_score:
            path, costs = trial
    return path


def _digit_score(path, costs):
    displayed = path._merge_sibling_singles(path.steps) if path.state.solved else path.steps
    return len(displayed), sum(costs.values()), len(costs), len(path.steps)


def _shorten_digits(checkpoint, solver, costs):
    end_values, end_domains = solver.state.vals, solver.state.dom
    max_proof_steps = sum(costs.values())
    proved = {}

    def replay(choices, deadline, max_steps):
        trial = checkpoint.fork_for_replay()
        used = {}
        for cell, value in choices:
            if trial.state.vals[cell] or not trial.state.has(cell, value):
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0 or len(trial.steps) + 4 > max_steps:
                return None
            key = (cell, value, tuple(trial.state.dom), tuple(trial.state.vals),
                   tuple(trial.constraints))
            if key not in proved:
                refuted, proof, cause = refute_candidate_with_proof(
                    trial.state, trial.constraints, cell, value, time_limit=min(1.2, remaining),
                )
                if not refuted or not proof:
                    # Continue with the remaining independently provable choices.
                    continue
                if len(proved) < 128:
                    proved[key] = proof, cause
            else:
                proof, cause = proved[key]
            start = len(trial.steps)
            try:
                trial.apply_refutation(cell, value, proof, cause)
            except Contradiction:
                return None
            used[cell, value] = len(trial.steps) - start
            if sum(used.values()) > max_proof_steps:
                return None
            result = trial.run(max_steps, candidate_maps=False, merge_singles=False,
                               deadline=deadline)
            if result.status not in ("solved", "stuck"):
                return None
            if result.status == "solved":
                break
        if trial.state.vals != end_values or trial.state.dom != end_domains:
            return None
        return trial, used

    return shorten_path(solver, costs, replay, _digit_score)


def refute_equal_bivalue(solver, deadline):
    """Try the two candidates of cells already linked by an equality clue."""
    from .intersections import _equal_groups

    checked = set()
    for rule in solver.constraints:
        for group in _equal_groups(rule):
            if len(group) < 2 or any(c in checked for c in group):
                continue
            checked.update(group)
            cell = group[0]
            mask = solver.state.dom[cell]
            if mask.bit_count() != 2 or any(solver.state.dom[c] != mask for c in group):
                continue
            for value in bits(mask):
                if time.monotonic() >= deadline:
                    return None
                trial = solver.fork_for_replay()
                trial.steps = []
                try:
                    trial.state.place(cell, value)
                except Contradiction:
                    continue
                result = trial.run(max_steps=18, candidate_maps=False, merge_singles=False,
                                   deadline=deadline)
                if result.status != "invalid":
                    continue
                before, values = solver._pre()
                forced = next(digit for digit in bits(mask) if digit != value)
                solver.state.begin()
                solver.state.place(cell, forced, Reason("equal_bivalue", {"cells": list(group)}))
                step = solver._commit(solver.state.end(), before, values)
                names = "、".join(cell_name(c, solver.state.n) for c in group)
                step.technique, step.title, step.tier = "equal_bivalue", "同值格双候选反证", 4
                step.detail = (f"{names} 必须同值。假设它们为 {value}，逐步推导后出现矛盾。"
                               f"{result.message}。所以它们只能为 {forced}。")
                step.visual["groups"] = [{"cells": list(group), "kind": "pair"}]
                step.visual["focus"] = list(group)
                step.narration = {"cells": list(group), "assumed": value, "forced": forced,
                                  "cause": result.message, "trace": result.steps}
                solver.steps.append(step)
                return step
    return None


def finish_with_refutations(solver, result, max_steps, warnings):
    """Discover a path, then publish only the suffix that survives replay."""
    from .between_cases import apply_between_cases
    checkpoint = solver.fork_for_replay()
    on_step, solver.on_step = solver.on_step, None
    deadline = time.time() + 25.0
    costs = {}
    while (result.status == "stuck" and len(solver.steps) < max_steps
           and time.time() < deadline):
        start = len(solver.steps)
        if refute_equal_bivalue(solver, time.monotonic() + min(3, deadline - time.time())):
            result = solver.run(max_steps, candidate_maps=False, merge_singles=False)
            continue
        if apply_between_cases(solver, time.monotonic() + min(12, deadline - time.time())):
            result = solver.run(max_steps, candidate_maps=False, merge_singles=False)
            continue
        step = solver.contradiction_step(deadline, max_steps=max_steps)
        if step is None:
            warnings.append("找到的反证过长，未能在步骤预算内展示完整证明"
                            if solver.refutation_limited else
                            "反证尝试未能在预算内找到可排除的候选")
            break
        assumption = step.events[0].reason.data
        costs[assumption["cell"], assumption["value"]] = len(solver.steps) - start
        result = solver.run(max_steps, candidate_maps=False, merge_singles=False)
    else:
        if result.status == "stuck" and len(solver.steps) < max_steps:
            warnings.append("反证尝试达到时间上限，题目仍未解完")

    if costs and result.status in ("solved", "stuck"):
        solver = _shorten_digits(checkpoint, solver, costs)
    if on_step is not None:
        for step in solver.steps[len(checkpoint.steps):]:
            try:
                on_step(step)
            except Exception:
                pass
    solver.on_step = on_step
    if result.status == "solved":
        solver.steps = solver._merge_sibling_singles(solver.steps)
    elif result.status == "stuck":
        solver.add_candidate_map(max_steps)
    result.steps, result.values = solver.steps, solver.state.vals
    return solver, result


def _region_endpoint(fragments):
    roots = sorted(fragments.groups, key=lambda root: min(fragments.groups[root]))
    groups = [tuple(sorted(fragments.groups[root])) for root in roots]
    apart = [fragments.blocked(a, b) for a, b in combinations(roots, 2)]
    counts = []
    for clue in fragments.all_count_clues:
        hosts = list(dict.fromkeys(fragments.owner[c] for c in clue.cells()))
        allowed = set(clue.counts)
        if len(hosts) <= 4:
            allowed.intersection_update(map(len, fragments.local_partitions(hosts)))
        counts.append(allowed)
    return (fragments.state.vals, fragments.state.dom, groups, apart, counts,
            fragments.corner_choices)


def finish_regions(solver, rules, make_steps):
    from .chaos_regions import region_steps

    checkpoint = solver.fork_for_replay()
    on_step = solver.on_step
    costs = {}
    published = 0

    def publish_prefix(step):
        nonlocal published
        if not costs:
            on_step(step)
            published += 1

    if on_step is not None:
        solver.on_step = publish_prefix
    fragments = region_steps(solver, rules, solver.steps, refutations=costs)
    if costs:
        endpoint = _region_endpoint(fragments)

        def replay(choices, deadline, max_steps):
            trial = checkpoint.fork_for_replay()
            trial.steps = make_steps(trial.state)
            used = {}
            try:
                regions = region_steps(trial, rules, trial.steps, refutations=used,
                                       replay=iter(choices), deadline=deadline, max_steps=max_steps)
            except (Contradiction, TimeoutError):
                return None
            if _region_endpoint(regions) == endpoint:
                return (trial, regions), used
            return None

        def score(path, used):
            length = len(path[0].steps)
            return length, sum(used.values()), len(used), length

        solver, fragments = shorten_path((solver, fragments), costs, replay, score)
    solver.on_step = on_step
    if on_step is not None:
        for step in solver.steps[published:]:
            on_step(step)
    return solver, fragments
