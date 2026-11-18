"""Joint V-pair class pattern.

Two disjoint V=5 pairs use four distinct colour classes; because the only
pairs summing to five are {1,4} and {2,3}, the four classes cover 1..4.
If a target is an anti-knight/king peer of all four endpoints, it cannot be
1..4.
"""


def covered_digits(pair_a, pair_b):
    a, b = set(pair_a), set(pair_b)
    if len(a) != 2 or len(b) != 2 or a & b:
        return set()
    return {1, 2, 3, 4}


def target_exclusions(target, pair_a, pair_b, anti_peers):
    a, b = set(pair_a), set(pair_b)
    if a & b:
        return set()
    if not (a | b) <= set(anti_peers):
        return set()
    return covered_digits(pair_a, pair_b)
