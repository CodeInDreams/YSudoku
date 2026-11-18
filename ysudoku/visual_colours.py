"""Assign visual colour pairs to XV/V steps."""

from . import palette as p

HEX = {
    p.BLUE: "#8ab4e8",
    p.GREEN: "#a9d18e",
    p.YELLOW: "#ffe699",
    p.ORANGE: "#f4b183",
    p.RED: "#e06666",
    p.PURPLE: "#b4a7d6",
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
