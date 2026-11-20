"""Assign visual colour pairs to XV/V steps."""

from . import palette as p

HEX = {
    p.BLUE: "#3d99f5",
    p.GREEN: "#b3e56a",
    p.YELLOW: "#fceb3f",
    p.ORANGE: "#e49632",
    p.RED: "#f53a37",
    p.PURPLE: "#e87cf1",
}


def xv_colours(events):
    """Return [{cells:[a,b], colour, hex}] for XV events in a step."""
    out = []
    seen = set()
    for event in events:
        if event.reason.kind != "xv":
            continue
        data = event.reason.data or {}
        a, b = data.get("a"), data.get("b")
        if a is None or b is None or (a, b) in seen:
            continue
        seen.add((a, b))
        left, right = p.pair_colours(len(out))
        out.append({"cells": [a], "colour": left, "hex": HEX.get(left)})
        out.append({"cells": [b], "colour": right, "hex": HEX.get(right)})
    return out
