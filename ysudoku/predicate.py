"""Typed predicate AST for LLM-authored rules (L2).

The model never writes code: it composes a small set of nodes.  The engine
evaluates them, prunes by enumeration (scope is small), and can explain them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any, Callable

from .state import bits


class PredicateError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    op: str
    args: tuple["Node", ...] = ()
    params: dict[str, Any] = field(default_factory=dict, hash=False)

    def to_json(self) -> dict:
        data: dict[str, Any] = {"op": self.op}
        if self.args:
            data["args"] = [a.to_json() for a in self.args]
        data.update(self.params)
        return data


_BINARY = {"add", "sub", "mul", "mod", "eq", "ne", "lt", "le", "gt", "ge"}
_COMPARE = {"eq", "ne", "lt", "le", "gt", "ge"}


def parse(raw: dict, *, element_index: Callable[[str], int] | None = None) -> Node:
    if not isinstance(raw, dict):
        raise PredicateError("predicate must be an object")
    op = str(raw.get("op", ""))
    if op == "const":
        try:
            return Node("const", (), {"value": int(raw["value"])})
        except (KeyError, TypeError, ValueError) as exc:
            raise PredicateError("const needs an integer value") from exc
    if op == "var":
        if "element" in raw:
            if element_index is None or "index" in raw:
                raise PredicateError("var must use either an element reference or an index")
            return Node("var", (), {"index": element_index(str(raw["element"]))})
        try:
            index = int(raw["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PredicateError("var needs an integer index") from exc
        if index < 0:
            raise PredicateError("var index must be >= 0")
        return Node("var", (), {"index": index})

    args = [parse(a, element_index=element_index) for a in raw.get("args", [])]
    if op in _BINARY and len(args) != 2:
        raise PredicateError(f"{op} needs exactly 2 arguments")
    if op in {"abs", "not"} and len(args) != 1:
        raise PredicateError(f"{op} needs exactly 1 argument")
    if op in {"sum", "min", "max", "count_distinct", "all_different", "ordered",
              "and", "or", "count_digit"} and len(args) < 1:
        raise PredicateError(f"{op} needs at least 1 argument")
    if op in {"all_different", "ordered"} and len(args) < 2:
        raise PredicateError(f"{op} needs at least 2 arguments")
    if op not in _BINARY | {"abs", "not", "sum", "min", "max", "count_distinct",
                            "all_different", "ordered", "and", "or", "count_digit"}:
        raise PredicateError(f"unsupported op: {op}")

    params: dict[str, Any] = {}
    if op == "count_digit":
        try:
            params["digit"] = int(raw["digit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PredicateError("count_digit needs an integer digit") from exc
    return Node(op, tuple(args), params)


def _eval(node: Node, values: list[int]) -> Any:
    if node.op == "const":
        return node.params["value"]
    if node.op == "var":
        return values[node.params["index"]]
    if node.op == "count_digit":
        digit = node.params["digit"]
        return sum(1 for arg in node.args if _eval(arg, values) == digit)
    if node.op == "count_distinct":
        return len({_eval(arg, values) for arg in node.args})
    if node.op == "all_different":
        vals = [_eval(arg, values) for arg in node.args]
        return len(set(vals)) == len(vals)
    if node.op == "ordered":
        vals = [_eval(arg, values) for arg in node.args]
        return all(a < b for a, b in zip(vals, vals[1:]))
    if node.op == "and":
        return all(bool(_eval(arg, values)) for arg in node.args)
    if node.op == "or":
        return any(bool(_eval(arg, values)) for arg in node.args)
    if node.op == "not":
        return not bool(_eval(node.args[0], values))

    vals = [_eval(arg, values) for arg in node.args]
    op = node.op
    if op == "add":
        return vals[0] + vals[1]
    if op == "sub":
        return vals[0] - vals[1]
    if op == "mul":
        return vals[0] * vals[1]
    if op == "mod":
        return vals[0] % vals[1] if vals[1] else 0
    if op == "abs":
        return abs(vals[0])
    if op == "sum":
        return sum(vals)
    if op == "min":
        return min(vals)
    if op == "max":
        return max(vals)
    if op == "eq":
        return vals[0] == vals[1]
    if op == "ne":
        return vals[0] != vals[1]
    if op == "lt":
        return vals[0] < vals[1]
    if op == "le":
        return vals[0] <= vals[1]
    if op == "gt":
        return vals[0] > vals[1]
    if op == "ge":
        return vals[0] >= vals[1]
    raise PredicateError(f"unsupported op: {op}")


def evaluate(node: Node, values: list[int]) -> bool:
    return bool(_eval(node, values))


def variables(node: Node) -> set[int]:
    if node.op == "var":
        return {node.params["index"]}
    out: set[int] = set()
    for arg in node.args:
        out |= variables(arg)
    return out


def format_node(node: Node, names: list[str] | None = None) -> str:
    """Human-readable form used in explanations."""
    if node.op == "const":
        return str(node.params["value"])
    if node.op == "var":
        index = node.params["index"]
        return names[index] if names and index < len(names) else f"v{index}"
    if node.op == "count_digit":
        return f"count({node.params['digit']})"
    if node.op == "count_distinct":
        return "distinct(" + ", ".join(format_node(a, names) for a in node.args) + ")"
    if node.op == "all_different":
        return "all_different(" + ", ".join(format_node(a, names) for a in node.args) + ")"
    if node.op == "ordered":
        return "ordered(" + ", ".join(format_node(a, names) for a in node.args) + ")"
    if node.op == "not":
        return "not(" + format_node(node.args[0], names) + ")"
    if node.op == "and":
        return "(" + " and ".join(format_node(a, names) for a in node.args) + ")"
    if node.op == "or":
        return "(" + " or ".join(format_node(a, names) for a in node.args) + ")"
    symbol = {
        "add": "+", "sub": "-", "mul": "*", "mod": "%", "eq": "==", "ne": "!=",
        "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
    }.get(node.op)
    if symbol:
        return f"({format_node(node.args[0], names)} {symbol} {format_node(node.args[1], names)})"
    return f"{node.op}(" + ", ".join(format_node(a, names) for a in node.args) + ")"


def prune_by_enumeration(domains: list[int], node: Node, *, limit: int = 80_000):
    """Return per-position supported value masks, or None if too large."""
    total = 1
    for dom in domains:
        total *= dom.bit_count()
        if total > limit:
            return None
    supported = [0] * len(domains)
    options = [list(bits(dom)) for dom in domains]
    for combo in product(*options):
        if evaluate(node, list(combo)):
            for i, value in enumerate(combo):
                supported[i] |= 1 << (value - 1)
    return supported
