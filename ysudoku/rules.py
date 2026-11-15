"""Rule inference and compilation.

The SudokuPad payload only stores *drawing* elements.  The actual rules live in
``metadata.rules`` (the text shown by the "rules" button).  We therefore build a
compact, numbered inventory of every drawn element and ask an LLM to translate
the rule text into a small JSON rule spec that references those ids.  When no
LLM is configured we fall back to heuristics based on colours and keywords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import dist

from .constraints import (
    AntiPair,
    Custom,
    Arrow,
    Between,
    Cage,
    Constraint,
    PairRule,
    Palindrome,
    Quadruple,
    Renban,
    SumLine,
    Thermo,
)
from .model import Puzzle
from . import predicate as predicate_mod
from .state import cell_name

# ------------------------------------------------------------------ inventory


@dataclass
class Element:
    id: str
    kind: str
    cells: list[int]
    attrs: dict = field(default_factory=dict)

    def to_json(self, n: int) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "cells": [cell_name(c, n) for c in self.cells],
        }
        data.update(self.attrs)
        return data


def build_inventory(puzzle: Puzzle) -> list[Element]:
    n = puzzle.size
    elements: list[Element] = []

    for i, cage in enumerate(puzzle.cages):
        if not cage.cells:
            continue
        elements.append(Element(f"cage:{i}", "cage", cage.cells,
                                {"sum": cage.total} if cage.total is not None else {}))

    for i, line in enumerate(puzzle.lines):
        if not line.cells:
            continue
        elements.append(Element(f"line:{i}", "line", line.cells,
                                {"color": line.color, "thickness": round(line.thickness, 2)}))

    for i, circle in enumerate(puzzle.circles):
        elements.append(Element(f"circle:{i}", "circle", circle.cells, {
            "fill": circle.fill,
            "border": circle.border,
            "thickness": round(circle.thickness, 2),
            "texts": circle.texts,
        }))

    for i, marker in enumerate(puzzle.markers):
        elements.append(Element(f"marker:{i}", "marker", marker.cells,
                                {"fill": marker.fill, "thickness": round(marker.thickness, 2)}))

    for i, dot in enumerate(puzzle.dots):
        elements.append(Element(f"dot:{i}", "dot", dot.cells, {"fill": dot.fill}))

    for i, arrow in enumerate(puzzle.arrows):
        elements.append(Element(f"arrow:{i}", "arrow", [arrow.circle] + arrow.arm,
                                {"circle": arrow.circle, "arm": arrow.arm}))

    # Arrows drawn as "circle at a line end" (SudokuPad's arrow tool draws this).
    used_markers = set()
    for line in puzzle.lines:
        if len(line.cells) < 2:
            continue
        for marker in puzzle.markers:
            if marker.cells[0] in (line.cells[0], line.cells[-1]) and dist(
                marker.center, _cell_center(marker.cells[0], n)
            ) < 0.45:
                used_markers.add(marker.id)
                elements.append(Element(
                    f"arrow:{marker.id}", "arrow", line.cells,
                    {"circle": marker.cells[0], "arm": [c for c in line.cells if c != marker.cells[0]]},
                ))
                break

    return elements


def _cell_center(cell: int, n: int) -> tuple[float, float]:
    r, c = divmod(cell, n)
    return (c + 0.5, r + 0.5)


# ------------------------------------------------------------------ spec


@dataclass
class RuleSpec:
    kind: str
    elements: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    note: str = ""

    def to_json(self) -> dict:
        data = {"kind": self.kind, "elements": self.elements}
        data.update(self.params)
        if self.note:
            data["note"] = self.note
        return data


@dataclass
class CompiledRules:
    constraints: list[Constraint]
    diagonal_main: bool = False
    diagonal_anti: bool = False
    resolved: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = "heuristic"

    def describe(self) -> list[dict]:
        return self.resolved


KINDS = {
    "cage": "杀手笼求和",
    "thermo": "温度计递增",
    "arrow": "箭头（圈=箭身和）",
    "kropki": "黑白点（连续/2倍）",
    "xv": "XV（和5/10）",
    "quadruple": "四格提示",
    "palindrome": "回文线",
    "renban": "Renban 连续数组",
    "german_whisper": "德式 whisper（差≥5）",
    "dutch_whisper": "荷式 whisper（差≥4）",
    "between": "之间线",
    "consecutive": "连续线",
    "little_killer": "小杀手斜线求和",
    "anti_knight": "反骑士",
    "anti_king": "反国王",
    "diagonal": "对角线数独",
    "disjoint_groups": "Disjoint Groups",
    "custom": "自定义规则（L2）",
}


def compile_spec(puzzle: Puzzle, elements: list[Element], spec: dict,
                 source: str = "llm") -> CompiledRules:
    n = puzzle.size
    by_id = {e.id: e for e in elements}
    result = CompiledRules([], source=source)
    used: set[str] = set()

    for raw in spec.get("rules", []):
        kind = str(raw.get("kind", "")).strip()
        ids = [str(x) for x in raw.get("elements", [])]
        params = {k: v for k, v in raw.items() if k not in ("kind", "elements", "note")}
        if kind not in KINDS:
            result.warnings.append(f"未知规则类型 {kind}（已忽略）")
            continue
        if kind == "custom":
            obj = _build_custom(puzzle, elements, raw, result.warnings)
            if obj is not None:
                result.constraints.append(obj["constraint"])
                used.update(obj.get("elements", []))
                result.resolved.append({
                    "kind": "custom",
                    "label": obj["label"],
                    "elements": obj.get("elements", []),
                    "count": 1,
                    "hypothesis": bool(raw.get("hypothesis")),
                    "cite": raw.get("cite", ""),
                })
            continue
        if not ids:
            result.warnings.append(f"规则 {kind} 没有引用任何元素（已忽略）")
            continue
        label = KINDS[kind]
        built = 0
        for eid in ids:
            element = by_id.get(eid)
            if element is None:
                result.warnings.append(f"规则 {kind} 引用了不存在的元素 {eid}")
                continue
            used.add(eid)
            try:
                objs = _build_rule(puzzle, kind, element, params, result.warnings)
            except ValueError as exc:
                result.warnings.append(f"{kind}/{eid}: {exc}")
                continue
            for obj in objs:
                result.constraints.append(obj)
                built += 1
        if built:
            result.resolved.append({
                "kind": kind, "label": label, "elements": ids,
                "count": built, "params": params, "note": raw.get("note", ""),
            })

    for raw in spec.get("globals", []):
        kind = str(raw.get("kind", "")).strip()
        if kind == "anti_knight":
            result.constraints.extend(_anti_pairs(puzzle, "anti_knight", "反骑士"))
            result.resolved.append({"kind": kind, "label": KINDS[kind], "elements": [], "count": 1})
        elif kind == "anti_king":
            result.constraints.extend(_anti_pairs(puzzle, "anti_king", "反国王"))
            result.resolved.append({"kind": kind, "label": KINDS[kind], "elements": [], "count": 1})
        elif kind == "diagonal":
            direction = str(raw.get("direction", "both"))
            result.diagonal_main |= direction in ("main", "both")
            result.diagonal_anti |= direction in ("anti", "both")
            result.resolved.append({"kind": kind, "label": KINDS[kind], "elements": [], "count": 1,
                                    "params": {"direction": direction}})
        elif kind == "disjoint_groups":
            result.warnings.append("Disjoint Groups 暂未实现")
        elif kind in KINDS:
            result.warnings.append(f"全局规则 {kind} 暂未实现")
        else:
            result.warnings.append(f"未知全局规则 {kind}")

    ignored = [e for e in elements if e.id not in used]
    for e in ignored:
        if e.kind == "cage" and not e.attrs.get("sum"):
            continue
        if e.kind == "line" and not e.cells:
            continue
        result.warnings.append(f"元素 {e.id} 未被任何规则使用（可能只是装饰）")

    result.resolved.append({
        "kind": "_ignored", "elements": [e.id for e in ignored],
    })
    hypotheses = [r for r in result.resolved if r.get("hypothesis")]
    if hypotheses:
        result.warnings.append(
            f"包含 {len(hypotheses)} 条推测规则（LLM 自定义谓词），相关步骤会标注【推测规则】"
        )
    return result


def _cell_from_name(puzzle: Puzzle, name: str) -> int | None:
    text = str(name).strip().upper()
    if text.startswith("R") and "C" in text:
        try:
            r, c = text[1:].split("C")
            r, c = int(r) - 1, int(c) - 1
        except ValueError:
            return None
        if 0 <= r < puzzle.size and 0 <= c < puzzle.size:
            return r * puzzle.size + c
    return None


def _build_custom(puzzle: Puzzle, elements: list[Element], raw: dict, warnings: list[str]):
    scope_raw = raw.get("scope") or {}
    scope: list[int] = []
    element_ids: list[str] = []
    if isinstance(scope_raw, dict) and scope_raw.get("element"):
        eid = str(scope_raw["element"])
        element_ids.append(eid)
        element = next((e for e in elements if e.id == eid), None)
        if element is None:
            warnings.append(f"custom 引用了不存在的元素 {eid}")
            return None
        scope = list(element.cells)
    elif isinstance(scope_raw, dict) and scope_raw.get("cells"):
        for name in scope_raw["cells"]:
            cell = _cell_from_name(puzzle, name)
            if cell is None:
                warnings.append(f"custom 的格子名无效：{name}")
                return None
            scope.append(cell)
    elif raw.get("cells"):
        for name in raw["cells"]:
            cell = _cell_from_name(puzzle, name)
            if cell is None:
                warnings.append(f"custom 的格子名无效：{name}")
                return None
            scope.append(cell)
    else:
        warnings.append("custom 缺少 scope.cells 或 scope.element")
        return None
    if not 2 <= len(scope) <= 6:
        warnings.append(f"custom 作用域必须 2..6 格，实际 {len(scope)}")
        return None
    raw_pred = raw.get("predicate")
    if not isinstance(raw_pred, dict):
        warnings.append("custom 缺少 predicate")
        return None
    try:
        node = predicate_mod.parse(raw_pred)
    except predicate_mod.PredicateError as exc:
        warnings.append(f"custom predicate 无效：{exc}")
        return None
    used_vars = predicate_mod.variables(node)
    if any(index >= len(scope) for index in used_vars):
        warnings.append("custom predicate 的 var 下标越界")
        return None
    cite = str(raw.get("cite", "")).strip()
    hypothesis = bool(raw.get("hypothesis", False))
    obj = Custom(scope, node, cite=cite, hypothesis=hypothesis)
    return {
        "constraint": obj,
        "elements": element_ids,
        "label": cite or "自定义谓词",
    }


def _build_rule(puzzle: Puzzle, kind: str, element: Element, params: dict,
                warnings: list[str]) -> list[Constraint]:
    n = puzzle.size
    cells = element.cells

    if kind == "cage":
        if element.kind != "cage":
            raise ValueError("不是一个笼")
        total = element.attrs.get("sum")
        if total is None:
            raise ValueError("笼没有和")
        return [Cage(cells, int(total))]

    if kind == "thermo":
        if len(cells) < 2:
            raise ValueError("温度计太短")
        return [Thermo(cells)]

    if kind == "arrow":
        if element.kind == "arrow":
            circle = int(element.attrs["circle"])
            arm = list(element.attrs["arm"])
            return [Arrow(circle, arm)]
        raise ValueError("不是箭头元素")

    if kind == "kropki":
        if element.kind != "dot":
            raise ValueError("不是圆点元素")
        variant = str(params.get("variant", "auto")).lower()
        fill = element.attrs.get("fill", "#000000").lower()
        if variant == "auto":
            variant = "black" if fill in ("#000000", "#000") else "white"
        a, b = cells
        if variant == "black":
            return [PairRule(a, b, "kropki", lambda x, y: x == 2 * y or y == 2 * x,
                             f"黑点（{cell_name(a, n)}/{cell_name(b, n)} 成 1:2）", variant="black")]
        return [PairRule(a, b, "kropki", lambda x, y: abs(x - y) == 1,
                         f"白点（{cell_name(a, n)}/{cell_name(b, n)} 连续）", variant="white")]

    if kind == "xv":
        if len(cells) != 2:
            raise ValueError("XV 需要两个格子")
        total = int(params.get("sum", 10))
        a, b = cells
        return [PairRule(a, b, "xv", lambda x, y: x + y == total,
                         f"XV（{cell_name(a, n)}/{cell_name(b, n)} 和为 {total}）", sum=total)]

    if kind == "quadruple":
        digits = []
        for text in element.attrs.get("texts", []):
            if str(text).isdigit():
                digits.append(int(text))
        if not digits:
            raise ValueError("圆圈内没有数字")
        if len(cells) != 4:
            raise ValueError("四格提示需要 4 个格子")
        return [Quadruple(cells, digits)]

    if kind == "palindrome":
        if len(cells) < 2:
            raise ValueError("回文线太短")
        return [Palindrome(cells)]

    if kind == "renban":
        if len(cells) < 2:
            raise ValueError("Renban 太短")
        return [Renban(cells)]

    if kind in ("german_whisper", "dutch_whisper", "consecutive"):
        if len(cells) < 2:
            raise ValueError("线太短")
        diff = 5 if kind == "german_whisper" else 4 if kind == "dutch_whisper" else 1
        if kind == "consecutive":
            ok = lambda x, y: abs(x - y) == 1
            label = f"连续线（{len(cells)} 格）"
        else:
            ok = lambda x, y, d=diff: abs(x - y) >= d
            label = f"{KINDS[kind]}（{len(cells)} 格）"
        return [PairRule(cells[i], cells[i + 1], kind, ok, label, diff=diff)
                for i in range(len(cells) - 1)]

    if kind == "between":
        if len(cells) < 3:
            raise ValueError("之间线太短")
        return [Between(cells)]

    if kind == "little_killer":
        total = params.get("sum")
        if total is None:
            raise ValueError("小杀手缺少和")
        return [SumLine(cells, int(total))]

    raise ValueError(f"无法构建 {kind}")


def _anti_pairs(puzzle: Puzzle, kind: str, label: str) -> list[Constraint]:
    n = puzzle.size
    out: list[Constraint] = []
    if kind == "anti_knight":
        offsets = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]
    else:
        offsets = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]
    for r in range(n):
        for c in range(n):
            for dr, dc in offsets:
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    a, b = r * n + c, rr * n + cc
                    if a < b:
                        out.append(AntiPair(a, b, kind, label))
    return out


# ------------------------------------------------------------------ heuristics


GREEN = {"#00ff00", "#00cc00", "#0f0", "#00aa00", "#32cd32"}
PURPLE = {"#ff00ff", "#9b30ff", "#8000ff", "#9400d3", "#da70d6"}
BLUE = {"#0000ff", "#0096ff", "#00bfff", "#1e90ff", "#4169e1"}
GREY = {"#808080", "#a8a8a8", "#c0c0c0", "#999999", "#a0a0a0"}
ORANGE = {"#ffa500", "#ff8c00", "#ff7f00"}
RED = {"#ff0000", "#dc143c", "#e00000"}


def _has(text: str, *words: str) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def heuristic_spec(puzzle: Puzzle, elements: list[Element]) -> dict:
    """Colour/keyword based fallback when no LLM is available."""
    text = puzzle.rules_text or ""
    rules: list[dict] = []
    globals_: list[dict] = []

    cage_ids = [e.id for e in elements if e.kind == "cage" and e.attrs.get("sum") is not None]
    if cage_ids and _has(text, "killer", "cage", "sum", "笼"):
        rules.append({"kind": "cage", "elements": cage_ids})

    circle_ids = [e.id for e in elements if e.kind == "circle" and e.attrs.get("texts")]
    if circle_ids and _has(text, "quadruple", "quadruples", "四"):
        rules.append({"kind": "quadruple", "elements": circle_ids})

    dot_ids = [e.id for e in elements if e.kind == "dot"]
    if dot_ids and _has(text, "kropki", "dot", "consecutive", "ratio", "consecutiv"):
        for dot in elements:
            if dot.kind != "dot":
                continue
            variant = "black" if "#000000" in dot.attrs.get("fill", "") else "white"
            rules.append({"kind": "kropki", "elements": [dot.id], "variant": variant})

    lines = [e for e in elements if e.kind == "line" and len(e.cells) >= 2]

    def lines_with(colors: set[str]) -> list[str]:
        return [e.id for e in lines if e.attrs.get("color", "") in colors]

    if _has(text, "whisper"):
        ids = lines_with(GREEN) or [e.id for e in lines if _has(text, "german", "whisper")]
        if ids:
            kind = "dutch_whisper" if _has(text, "dutch") else "german_whisper"
            rules.append({"kind": kind, "elements": ids})
    if _has(text, "renban"):
        ids = lines_with(PURPLE) or [e.id for e in lines]
        if ids:
            rules.append({"kind": "renban", "elements": ids})
    if _has(text, "palindrome"):
        ids = lines_with(GREY) or [e.id for e in lines]
        if ids:
            rules.append({"kind": "palindrome", "elements": ids})
    if _has(text, "between"):
        ids = [e.id for e in lines if len(e.cells) >= 3]
        if ids:
            rules.append({"kind": "between", "elements": ids})
    if _has(text, "consecutive") and not _has(text, "kropki"):
        ids = lines_with(ORANGE + GREEN) or [e.id for e in lines]
        if ids:
            rules.append({"kind": "consecutive", "elements": ids})

    arrows = [e.id for e in elements if e.kind == "arrow"]
    if arrows and _has(text, "arrow", "箭头"):
        rules.append({"kind": "arrow", "elements": arrows})

    if _has(text, "anti-knight", "anti knight", "anti-knight"):
        globals_.append({"kind": "anti_knight"})
    if _has(text, "anti-king", "anti king"):
        globals_.append({"kind": "anti_king"})
    if _has(text, "diagonal") and not _has(text, "little killer"):
        direction = "both"
        if _has(text, "main diagonal") and not _has(text, "both"):
            direction = "main"
        elif _has(text, "anti-diagonal", "anti diagonal"):
            direction = "anti"
        globals_.append({"kind": "diagonal", "direction": direction})

    return {"rules": rules, "globals": globals_, "notes": "heuristic"}
