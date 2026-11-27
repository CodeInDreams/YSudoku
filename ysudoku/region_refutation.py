"""Refute one allowed region count using only local upper bounds on region size."""

from copy import copy
from itertools import combinations
from time import monotonic

from .region_shapes import region_shapes
from .state import Contradiction, bits, cell_name


def _fork(base):
    # Domains are read-only in this proof. Geometry caches depend only on the board.
    trial = copy(base)
    trial.owner = base.owner.copy()
    trial.groups = {a: group.copy() for a, group in base.groups.items()}
    trial.colours = base.colours.copy()
    trial.separate = base.separate.copy()
    return trial


def region_growth(f, clues, *, pair=None, conflict_only=False, assumption=None, lang="zh"):
    """If m clue cells span at least k regions, one region can use at most m-k+1 of them."""
    english = lang == "en"
    masks = {a: sum(1 << c for c in group) for a, group in f.groups.items()}
    sources = [None, *(c for c in clues if min(c.counts) > 1 and len(c.cells()) <= 4)]
    roots = [f.owner[pair[0]]] if pair else masks
    for a in roots:
        owned = masks[a]
        allowed = f.board
        for b, mask in masks.items():
            if a != b and f.blocked(a, b):
                allowed &= ~mask
        name = cell_name(a, f.n)
        for clue in sources:
            alternatives = [allowed]
            premise = ""
            if clue:
                cells = clue.cells()
                slots = [1 << c for c in cells if allowed & (1 << c)]
                limit = len(cells) - min(clue.counts) + 1
                if len(slots) <= limit:
                    continue
                alternatives = [allowed & ~(sum(slots) ^ sum(keep))
                                for keep in combinations(slots, limit)]
                if clue is not assumption:
                    start = cell_name(cells[0], f.n)
                    premise = (f"A region can use at most {limit} cells of the circle starting at {start}. "
                               if english else f"以 {start} 起的圈内，同一区域至多占 {limit} 格。")

            def capacity(mask):
                if owned & ~mask:
                    return 0
                reach = f.reachable(owned, mask)
                return 0 if owned & ~reach else reach.bit_count()

            sizes = [capacity(mask) for mask in alternatives]
            largest = max(sizes)
            if largest < f.n:
                if english:
                    if largest == 0:
                        raise Contradiction(f"{premise}The known cells of {name}'s region cannot connect.")
                    if largest == 1 and owned.bit_count() == 1 and not clue:
                        neighbours = f.expand(owned)
                        names = ", ".join(cell_name(c, f.n) for c in range(f.n*f.n) if neighbours & (1 << c))
                        raise Contradiction(f"All orthogonal neighbours of {name} ({names}) are in other regions. "
                                            f"Its region has only one cell and needs {f.n}.")
                    raise Contradiction(f"{premise}The region containing {name} can reach at most "
                                        f"{largest} cells and needs {f.n}.")
                if largest == 0:
                    raise Contradiction(f"{premise}{name} 所在片区的已知格无法连成一个 {f.n} 格区域。")
                if largest == 1 and owned.bit_count() == 1 and not clue:
                    neighbours = f.expand(owned)
                    names = "、".join(cell_name(c, f.n) for c in range(f.n*f.n) if neighbours & (1 << c))
                    raise Contradiction(f"{name} 的正交邻格 {names} 全都与它异区，它只能占 1 格，达不到 {f.n} 格。")
                raise Contradiction(f"{premise}{name} 所在区域最多能连到 {largest} 格，达不到 {f.n} 格。")
            if conflict_only:
                continue
            viable = [mask for mask, size in zip(alternatives, sizes) if size >= f.n]
            if pair:
                candidates = [f.owner[pair[1]]]
            else:
                boundary = f.expand(owned) & allowed & ~owned
                candidates = [b for b, mask in masks.items() if boundary & mask]
            for b in candidates:
                if a == b:
                    continue
                bound = max(capacity(mask & ~masks[b]) for mask in viable)
                if bound < f.n:
                    other = cell_name(b, f.n)
                    if english:
                        return (a, b), (f"{premise}Without the fragment at {other}, the region at {name} "
                                        f"can reach only {bound} cells. The two fragments must share a region.")
                    return (a, b), (f"{premise}{name} 所在区域若避开 {other} 所在片区，"
                                     f"最多能连到 {bound} 格，因此两者必须同区。")
    return None


MAX_FORCED_MERGES = 16


def _trial(base, clues, actions=None, *, assumption=None, max_merges=MAX_FORCED_MERGES, lang="zh"):
    """Discover forced merges, or replay a subsequence to trim the certificate."""
    f = _fork(base)
    merges, reasons = [], []
    try:
        for i in range((max_merges if actions is None else len(actions)) + 1):
            while True:
                choice = f.propagate_choices(lang=lang)
                if choice:
                    reasons.append(choice[1])
                    continue
                change = next(((clue, v) for clue in clues if (v := f.clue(clue, lang=lang))), None)
                if not change:
                    break
                clue, (cells, detail) = change
                if clue is not assumption:
                    start = cell_name(cells[0], f.n)
                    if lang == "en":
                        counts = " or ".join(map(str, clue.counts))
                        reasons.append(f"The circle starting at {start} spans {counts} regions. {detail}")
                    else:
                        counts = " 或 ".join(map(str, clue.counts))
                        reasons.append(f"以 {start} 起的圈要求 {counts} 区。{detail}")
            if actions is None:
                region_growth(f, clues, conflict_only=True, assumption=assumption, lang=lang)
                if i == max_merges:
                    return None
                found = region_growth(f, clues, assumption=assumption, lang=lang)
                if not found:
                    return None
            else:
                if i == len(actions):
                    region_growth(f, clues, conflict_only=True, assumption=assumption, lang=lang)
                    return None
                found = region_growth(f, clues, pair=actions[i], assumption=assumption, lang=lang)
                if not found:
                    continue
            pair, detail = found
            merges.append(pair)
            reasons.append(detail)
            f.merge(*pair)
    except Contradiction as exc:
        return merges, [*reasons, str(exc)]


def refute_count(fragments, clues, target=None):
    best = None
    for index, clue in enumerate(clues):
        if len(clue.counts) < 2:
            continue
        for count in reversed(clue.counts):
            if target is not None and (index, count) != target:
                continue
            assumed = copy(clue)
            assumed.counts = [count]
            trial_clues = [assumed, *clues[:index], *clues[index+1:]]
            proof = _trial(fragments, trial_clues, assumption=assumed)
            if proof is None:
                continue
            actions, reasons = proof
            # Delete a premise only when the remaining proof actually replays.
            for pair in reversed(actions.copy()):
                if pair not in actions:
                    continue
                pos = actions.index(pair)
                shorter = _trial(fragments, trial_clues, actions[:pos] + actions[pos+1:], assumption=assumed)
                if shorter is not None and len(shorter[1]) <= len(reasons):
                    actions, reasons = shorter
            if best is None or len(reasons) < len(best[2]):
                best = index, count, reasons
    return best


def refute_border(fragments, clues, *, deadline=None):
    """Try one nearby border at a time, using only short region-capacity chains."""
    masks = {root: sum(1 << c for c in group) for root, group in fragments.groups.items()}
    candidates = {}
    for a in fragments.colours:
        owned = masks[a]
        allowed = fragments.board
        for b, mask in masks.items():
            if a != b and fragments.blocked(a, b):
                allowed &= ~mask
        frontier = fragments.expand(owned) & allowed & ~owned
        for b, mask in masks.items():
            if mask & frontier:
                size = fragments.reachable(owned, allowed & ~mask).bit_count()
                pair = tuple(sorted((a, b)))
                candidates[pair] = min(size, candidates.get(pair, size))
    for a, b in sorted(candidates, key=lambda pair: (candidates[pair], pair))[:12]:
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        trial = _fork(fragments)
        trial.apart(a, b)
        proof = _trial(trial, clues, max_merges=4)
        if proof is None:
            continue
        actions, reasons = _trim_growth_trial(trial, clues, proof)
        if len(reasons) <= 5:
            _, en = _trial(trial, clues, actions, lang="en")
            return (a, b), reasons, en
    return None


def _trim_growth_trial(trial, clues, proof):
    actions, reasons = proof
    for pos in range(len(actions) - 1, -1, -1):
        shorter = _trial(trial, clues, actions[:pos] + actions[pos+1:])
        if shorter is not None and len(shorter[1]) < len(reasons):
            actions, reasons = shorter
    return actions, reasons


def refute_border_shape(fragments, clues, *, deadline=None):
    """Check a border when at most six local completions fit behind it."""
    n = fragments.n
    masks = {root: sum(1 << cell for cell in group) for root, group in fragments.groups.items()}
    candidates = []
    for root in fragments.colours:
        owned = masks[root]
        size = owned.bit_count()
        if not max(2, n - 4) <= size < n:
            continue
        neighbours = {fragments.owner[cell - 1] for cell in bits(fragments.expand(owned) & ~owned)}
        candidates.extend((-size, root, other) for other in neighbours if not fragments.blocked(root, other))
    for _, a, b in sorted(candidates)[:12]:
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        trial = _fork(fragments)
        trial.apart(a, b)
        pockets = {}
        shapes = region_shapes(trial, a, clues, limit=512, masks=masks, max_shapes=6, case_pockets=pockets)
        if shapes is None or len(shapes) != 1:
            continue
        shape, = shapes
        if any(not piece for other, piece in pockets.items() if other != shape):
            continue
        extra = shape & ~masks[a]
        for root in sorted({trial.owner[cell - 1] for cell in bits(extra)}):
            trial.merge(trial.owner[a], trial.owner[root])
        proof = _trial(trial, clues, max_merges=6)
        if proof is None:
            continue
        actions, reasons = _trim_growth_trial(trial, clues, proof)
        if len(reasons) > 8:
            continue
        _, english = _trial(trial, clues, actions, lang="en")
        rejected = [(case & ~masks[a], piece) for case, piece in sorted(pockets.items()) if case != shape]
        return ((a, b), _shape_cases(extra, rejected, n) + reasons,
                _shape_cases(extra, rejected, n, lang="en") + english)
    return None


def _shape_cases(extra, rejected, n, lang="zh"):
    english = lang == "en"
    sep = ", " if english else "、"

    def names(mask):
        return sep.join(cell_name(cell - 1, n) for cell in bits(mask))

    lines = []
    common = extra
    if rejected:
        groups = {}
        for case, pocket in rejected:
            common &= case
            groups.setdefault(pocket, []).append(case)
        if common:
            fixed = names(common)
            lines.append(f"With the known borders and circle clues, every extension includes {fixed}."
                         if english else f"按已知边界和圈域限制，所有补法都要加上 {fixed}。")
        for pocket, cases in groups.items():
            size = pocket.bit_count()
            witness = names(pocket) if size < n else cell_name((pocket & -pocket).bit_length() - 1, n)
            choices = (" or " if english else " 或 ").join(f"[{names(case & ~common)}]" for case in cases)
            capacity = "one cell" if size == 1 else f"{size} cells"
            lines.append(f"Adding {choices} cuts off {capacity} ({witness}), which cannot be split into {n}-cell regions."
                         if english else f"再加 {choices} 会切出 {size} 格空地（{witness}），无法分成 {n} 格区域。")
    remaining = names(extra & ~common) if rejected else names(extra)
    lines.append(f"The only remaining extension adds {remaining}." if english
                 else f"唯一剩下的补法是加上 {remaining}。")
    return lines
