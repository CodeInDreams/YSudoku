"""Refute one allowed region count using only local upper bounds on region size."""

from copy import copy
from itertools import combinations

from .state import Contradiction, cell_name


def _fork(base):
    # Domains are read-only in this proof. Geometry caches depend only on the board.
    trial = copy(base)
    trial.owner = base.owner.copy()
    trial.groups = {a: group.copy() for a, group in base.groups.items()}
    trial.colours = base.colours.copy()
    trial.separate = base.separate.copy()
    return trial


def region_growth(f, clues, *, pair=None, conflict_only=False, assumption=None):
    """If m clue cells span at least k regions, one region can use at most m-k+1 of them."""
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
                    premise = f"以 {cell_name(cells[0], f.n)} 起的圈内，同一区域至多占 {limit} 格。"

            def capacity(mask):
                if owned & ~mask:
                    return 0
                reach = f.reachable(owned, mask)
                return 0 if owned & ~reach else reach.bit_count()

            sizes = [capacity(mask) for mask in alternatives]
            if max(sizes) < f.n:
                if max(sizes) == 0:
                    raise Contradiction(f"{premise}{name} 所在片区的已知格无法连成一个 {f.n} 格区域。")
                if max(sizes) == 1 and owned.bit_count() == 1 and not clue:
                    neighbours = f.expand(owned)
                    names = "、".join(cell_name(c, f.n) for c in range(f.n*f.n) if neighbours & (1 << c))
                    raise Contradiction(f"{name} 的正交邻格 {names} 全都与它异区，它只能占 1 格，达不到 {f.n} 格。")
                raise Contradiction(f"{premise}{name} 所在区域最多能连到 {max(sizes)} 格，达不到 {f.n} 格。")
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
                    return (a, b), (f"{premise}{name} 所在区域若避开 {other} 所在片区，"
                                     f"最多能连到 {bound} 格，因此两者必须同区。")
    return None


MAX_FORCED_MERGES = 16


def _trial(base, clues, actions=None):
    """Discover forced merges, or replay a subsequence to trim the certificate."""
    f = _fork(base)
    merges, reasons = [], []
    try:
        for i in range((MAX_FORCED_MERGES if actions is None else len(actions)) + 1):
            while True:
                choice = f.propagate_choices()
                if choice:
                    reasons.append(choice[1])
                    continue
                change = next(((clue, v) for clue in clues if (v := f.clue(clue))), None)
                if not change:
                    break
                clue, (cells, detail) = change
                if clue is not clues[0]:
                    counts = " 或 ".join(map(str, clue.counts))
                    reasons.append(f"以 {cell_name(cells[0], f.n)} 起的圈要求 {counts} 区。{detail}")
            if actions is None:
                region_growth(f, clues, conflict_only=True, assumption=clues[0])
                if i == MAX_FORCED_MERGES:
                    return None
                found = region_growth(f, clues, assumption=clues[0])
                if not found:
                    return None
            else:
                if i == len(actions):
                    region_growth(f, clues, conflict_only=True, assumption=clues[0])
                    return None
                found = region_growth(f, clues, pair=actions[i], assumption=clues[0])
                if not found:
                    continue
            pair, detail = found
            merges.append(pair)
            reasons.append(detail)
            f.merge(*pair)
    except Contradiction as exc:
        return merges, [*reasons, str(exc)]


def refute_count(fragments, clues):
    best = None
    for index, clue in enumerate(clues):
        if len(clue.counts) < 2:
            continue
        for count in reversed(clue.counts):
            assumed = copy(clue)
            assumed.counts = [count]
            trial_clues = [assumed, *clues[:index], *clues[index+1:]]
            proof = _trial(fragments, trial_clues)
            if proof is None:
                continue
            actions, reasons = proof
            # Delete a premise only when the remaining proof actually replays.
            for pair in reversed(actions.copy()):
                if pair not in actions:
                    continue
                pos = actions.index(pair)
                shorter = _trial(fragments, trial_clues, actions[:pos] + actions[pos+1:])
                if shorter is not None and len(shorter[1]) <= len(reasons):
                    actions, reasons = shorter
            if best is None or len(reasons) < len(best[2]):
                best = index, count, reasons
    return best
