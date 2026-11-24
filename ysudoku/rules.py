"""Rule inference and compilation.

The SudokuPad payload only stores *drawing* elements.  The actual rules live in
``metadata.rules`` (the text shown by the "rules" button).  We therefore build a
compact, numbered inventory of every drawn element and ask an LLM to translate
the rule text into a small JSON rule spec that references those ids.  When no
LLM is configured we fall back to heuristics based on colours and keywords.
"""

from __future__ import annotations

from colorsys import rgb_to_hsv
from dataclasses import dataclass, field
import re
from math import dist

from .constraints import (
    AntiPair,
    RegionCount,
    ClassCover,
    Clone,
    Custom,
    Parity,
    RegionSum,
    Sandwich,
    XSums,
    ProductLine,
    IRSupport,
    Skyscraper,
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
from .full_rank import FullRank
from .rule_choice import RuleAlternative, RuleChoice
from .constraints_ir import relation_from_spec
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
        attrs = {"fill": marker.fill, "thickness": round(marker.thickness, 2)}
        if marker.layer == "underlay":
            attrs.update(layer=marker.layer, border=marker.border, texts=marker.texts)
        elements.append(Element(f"marker:{i}", "marker", marker.cells, attrs))

    for i, clue in enumerate(puzzle.xv_clues):
        elements.append(Element(f"xv:{i}", "xv", clue.cells,
                                {"sum": 5 if clue.mark == "V" else 10, "mark": clue.mark}))

    for i, dot in enumerate(puzzle.dots):
        elements.append(Element(f"dot:{i}", "dot", dot.cells, {"fill": dot.fill}))

    for i, clue in enumerate(puzzle.clues):
        if clue.side in ("top", "bottom"):
            cells = [r * puzzle.size + clue.index for r in range(puzzle.size)]
        else:
            cells = [clue.index * puzzle.size + c for c in range(puzzle.size)]
        elements.append(Element(f"clue:{i}", "clue", cells, {
            "value": clue.value, "side": clue.side, "index": clue.index,
        }))

    for i, arrow in enumerate(puzzle.arrows):
        elements.append(Element(f"arrow:{i}", "arrow", [arrow.circle] + arrow.arm,
                                {"circle": arrow.circle, "arm": arrow.arm}))

    # Arrows drawn as "circle at a line end" (SudokuPad's arrow tool draws this).
    used_markers = set()
    for line in puzzle.lines:
        if len(line.cells) < 2:
            continue
        for marker in puzzle.markers:
            if marker.layer != "overlay":
                continue
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
    return (r + 0.5, c + 0.5)


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
    errors: list[str] = field(default_factory=list)

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
    "non_consecutive": "正交相邻格不能填连续数",
    "anti_knight": "反骑士",
    "anti_king": "反国王",
    "diagonal": "对角线数独",
    "disjoint_groups": "Disjoint Groups",
    "custom": "自定义规则（L2）",
    "clone": "克隆（同数）",
    "odd": "奇数",
    "even": "偶数",
    "sandwich": "三明治",
    "skyscraper": "摩天楼",
    "region_sum": "区域和线",
    "region_count": "区域计数",
    "x_sums": "X-Sums（盘外提示）",
    "product": "乘积线",
    "full_rank": "Full Rank（全局排名）",
    "rule_choice": "规则选择与分配",
    "ir": "通用约束关系",
    "modular": "模块 2×2（每宫含 1/4/7、2/5/8、3/6/9）",
    "entropy": "熵 2×2（每宫含低/中/高）",
}


def paired_outside_choices(puzzle, elements):
    text = " ".join(puzzle.rules_text.lower().split())
    if ("every clue number outside the grid appears exactly twice" not in text
            or "one appearance is a full rank clue and the other is an x-sums clue" not in text):
        return []
    pairs = {}
    for element in elements:
        if element.kind == "clue":
            pairs.setdefault(element.attrs["value"], []).append(element)
    if any(len(pair) != 2 for pair in pairs.values()):
        return []
    side_labels = {"left": "左", "right": "右", "top": "上", "bottom": "下"}

    def region(element, value):
        side = element.attrs["side"]
        start = element.cells[-1 if side in ("right", "bottom") else 0]
        return {
            "label": f"{value}（{cell_name(start, puzzle.size)} {side_labels[side]}侧）",
            "options": {"Full Rank": {"kind": "full_rank", "elements": [element.id]},
                        "X-Sum": {"kind": "x_sums", "elements": [element.id]}},
        }

    return [{
        "kind": "rule_choice", "elements": [e.id for e in pair],
        "quotas": {"Full Rank": 1, "X-Sum": 1},
        "regions": [region(element, value) for element in pair],
    } for value, pair in sorted(pairs.items())]


def with_paired_outside_choices(spec, choices):
    if not choices:
        return spec
    claimed = {eid for choice in choices for eid in choice["elements"]}
    rules = []
    for raw in spec.get("rules", []):
        ids = raw.get("elements") or []
        if raw.get("kind") in ("full_rank", "x_sums", "rule_choice") and claimed.intersection(ids):
            if raw.get("kind") == "rule_choice":
                continue
            remainder = [eid for eid in ids if eid not in claimed]
            if not remainder:
                continue
            raw = {**raw, "elements": remainder}
        rules.append(raw)
    return {**spec, "rules": [*rules, *choices]}


def compile_spec(puzzle: Puzzle, elements: list[Element], spec: dict,
                 source: str = "llm", *, nested=False) -> CompiledRules:
    n = puzzle.size
    by_id = {e.id: e for e in elements}
    result = CompiledRules([], source=source)
    used: set[str] = set()

    # X/V overlays are easy for the LLM to miss; always keep every drawn clue.
    spec = dict(spec)
    raw_rules = list(spec.get("rules") or [])
    claimed = {
        str(eid)
        for raw in raw_rules
        for eid in (raw.get("elements") or [])
    }
    for element in elements:
        if not nested and element.kind == "xv" and element.id not in claimed:
            raw_rules.append({
                "kind": "xv", "elements": [element.id],
                "sum": element.attrs.get("sum", 10),
            })
    text_low = (puzzle.rules_text or "").lower()
    if not nested and ("x-sum" in text_low or "x sum" in text_low or "xsum" in text_low):
        from .arrow_xsums import parse_arrows_fitted
        existing = {tuple(r.get("cells") or []) for r in raw_rules}
        for index, item in enumerate(parse_arrows_fitted(puzzle.raw or {}, puzzle, n)):
            cells = tuple(item["cells"])
            if cells in existing:
                continue
            if puzzle.solution:
                vals = puzzle.solution
                first = vals[cells[0]]
                if first <= 0 or sum(vals[c] for c in cells[:first]) != item["total"]:
                    continue
            clue_index = min(index, max(0, len(puzzle.clues) - 1))
            raw_rules.append({
                "kind": "x_sums",
                "elements": [f"clue:{clue_index}"],
                "sum": item["total"],
                "cells": list(cells),
                "side": "arrow",
            })

    spec["rules"] = raw_rules

    for raw in spec.get("rules", []):
        kind = str(raw.get("kind", "")).strip()
        ids = [str(x) for x in raw.get("elements", [])]
        params = {k: v for k, v in raw.items() if k not in ("kind", "elements", "note")}
        if (not nested and kind == "x_sums" and not raw.get("cells")
                and (puzzle.raw or {}).get("arrows")):
            continue
        if kind not in KINDS:
            result.warnings.append(f"未知规则类型 {kind}（已忽略）")
            continue
        if kind == "rule_choice":
            try:
                if nested:
                    raise ValueError("规则选项中不能嵌套规则选择")
                regions = []
                cited = set()
                for item in raw.get("regions") or []:
                    options = {}
                    for name, definition in item["options"].items():
                        branches = definition if isinstance(definition, list) else [definition]
                        built = compile_spec(puzzle, elements, {"rules": branches}, source, nested=True)
                        warnings = [w for w in built.warnings if "未被任何规则使用" not in w
                                    and "条推测规则" not in w]
                        if warnings or not built.constraints:
                            raise ValueError(f"{name}：{'；'.join(warnings) or '没有可编译的约束'}")
                        cited.update(eid for r in built.resolved if r["kind"] != "_ignored"
                                     for eid in r.get("elements", []))
                        options[name] = (built.constraints[0] if len(built.constraints) == 1
                                         else RuleAlternative(built.constraints))
                    regions.append((str(item.get("label") or f"区域{len(regions) + 1}"), options))
                constraint = RuleChoice(regions, raw.get("quotas"))
            except (AttributeError, TypeError, ValueError, KeyError) as exc:
                warning = f"规则选择无效：{exc}"
                result.errors.append(warning)
                continue
            result.constraints.append(constraint)
            selected = list(dict.fromkeys([*ids, *sorted(cited)]))
            used.update(selected)
            result.resolved.append({"kind": kind, "label": KINDS[kind],
                                    "elements": selected, "count": len(regions)})
            continue
        if kind == "ir":
            try:
                relations = [relation_from_spec(item)
                             for item in raw.get("relations", [])]
                if not relations:
                    raise ValueError("IR rule requires at least one relation")
                constraint = IRSupport(relations)
            except (TypeError, ValueError, KeyError) as exc:
                result.warnings.append(f"IR 规则无效：{exc}")
                continue
            result.constraints.append(constraint)
            result.resolved.append({"kind": kind, "label": KINDS[kind],
                                    "elements": ids, "count": len(relations)})
            used.update(ids)
            continue
        if kind == "product":
            total = params.get("total", raw.get("total", 48))
            for element in elements:
                if element.id not in ids or len(element.cells) < 2:
                    continue
                result.constraints.append(ProductLine(element.cells, int(total),
                                                       str(element.attrs.get("color") or "")))
            result.resolved.append({"kind": kind, "label": KINDS[kind],
                                    "elements": list(ids), "count": len(ids)})
            used.update(ids)
            continue
        if kind == "x_sums" and raw.get("cells"):
            total = params.get("sum")
            if total is None:
                result.warnings.append("X-Sums 缺少和")
                continue
            cells = [int(c) for c in raw.get("cells") or []]
            if len(cells) < 2:
                continue
            result.constraints.append(XSums(cells, int(total), str(params.get("side") or "arrow")))
            result.resolved.append({
                "kind": "x_sums", "label": KINDS["x_sums"],
                "elements": ids, "count": 1,
                "params": {"sum": int(total), "side": params.get("side") or "arrow",
                           "cells": len(cells)},
            })
            used.update(ids)
            continue
        if kind == "region_count":
            scope, eids = _resolve_scope(puzzle, elements, raw, result.warnings)
            if not scope:
                continue
            raw_counts = raw.get("counts", raw.get("count"))
            if raw_counts is None:
                result.warnings.append("region_count 缺少 counts")
                continue
            counts = raw_counts if isinstance(raw_counts, (list, tuple)) else [raw_counts]
            try:
                rule = RegionCount(scope, [int(c) for c in counts])
            except ValueError as exc:
                result.warnings.append(f"region_count: {exc}")
                continue
            result.constraints.append(rule)
            result.resolved.append({
                "kind": "region_count", "label": KINDS["region_count"],
                "elements": eids, "count": 1,
                "hypothesis": bool(raw.get("hypothesis")),
            })
            used.update(eids)
            continue
        if kind in ("clone", "odd", "even"):
            scope, eids = _resolve_scope(puzzle, elements, raw, result.warnings)
            if not scope:
                continue
            if kind == "clone":
                if len(scope) < 2:
                    result.warnings.append("clone 至少需要 2 个格子")
                    continue
                objs = [Clone(scope)]
            else:
                objs = [Parity(scope, "odd" if kind == "odd" else "even")]
            for obj in objs:
                result.constraints.append(obj)
                result.resolved.append({
                    "kind": kind, "label": KINDS[kind], "elements": eids,
                    "count": 1, "hypothesis": bool(raw.get("hypothesis")),
                })
            used.update(eids)
            continue
        if kind == "custom":
            obj = _build_custom(puzzle, elements, raw, result.errors)
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

    globals_ = list(spec.get("globals") or [])
    # Older saved specs could express this board-wide rule for just one pair.
    if not nested and _global_non_consecutive(text_low) and not any(
            g.get("kind") == "non_consecutive" for g in globals_):
        globals_.append({"kind": "non_consecutive"})
    for raw in globals_:
        kind = str(raw.get("kind", "")).strip()
        if kind == "anti_knight":
            result.constraints.extend(_anti_pairs(puzzle, "anti_knight", "反骑士"))
            result.resolved.append({"kind": kind, "label": KINDS[kind], "elements": [], "count": 1})
        elif kind == "non_consecutive":
            adjacent = [(cell, other) for cell in range(n * n)
                        for other in ([cell + 1] if cell % n < n - 1 else [])
                        + ([cell + n] if cell // n < n - 1 else [])]
            edges = set(adjacent)
            for con in result.constraints:
                if isinstance(con, Cage) and tuple(sorted(con.cells())) in edges:
                    con.non_consecutive_pair = True
            result.constraints.extend(PairRule(a, b, kind, lambda x, y: abs(x - y) > 1,
                                               KINDS[kind]) for a, b in adjacent)
            result.resolved.append({"kind": kind, "label": KINDS[kind],
                                    "elements": [], "count": len(adjacent)})
        elif kind == "anti_king":
            result.constraints.extend(_anti_pairs(puzzle, "anti_king", "反国王"))
            result.resolved.append({"kind": kind, "label": KINDS[kind], "elements": [], "count": 1})
        elif kind in ("modular", "entropy"):
            n = puzzle.size
            if n < 4:
                result.warnings.append(f"{KINDS[kind]} 需要至少 4×4")
            else:
                if kind == "modular":
                    classes = [set(range(d, n + 1, 3)) for d in (1, 2, 3)]
                else:
                    third = max(1, n // 3)
                    classes = [set(range(1, third + 1)),
                               set(range(third + 1, 2 * third + 1)),
                               set(range(2 * third + 1, n + 1))]
                for r in range(n - 1):
                    for c in range(n - 1):
                        cells = [r * n + c, r * n + c + 1,
                                 (r + 1) * n + c, (r + 1) * n + c + 1]
                        result.constraints.append(ClassCover(cells, classes))
                result.resolved.append({"kind": kind, "label": KINDS[kind],
                                        "elements": [], "count": (n - 1) ** 2})
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

    if puzzle.is_chaos:
        quadruples = [c for c in result.constraints if isinstance(c, Quadruple)]
        for count in result.constraints:
            if isinstance(count, RegionCount):
                for quad in quadruples:
                    count.simplify_with_quadruple(quad)

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
    result.warnings.extend(result.errors)
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


def _resolve_scope(puzzle: Puzzle, elements: list[Element], raw: dict, warnings: list[str]):
    scope_raw = raw.get("scope") or {}
    scope: list[int] = []
    element_ids: list[str] = []
    if isinstance(scope_raw, dict) and scope_raw.get("element"):
        eid = str(scope_raw["element"])
        element_ids.append(eid)
        element = next((e for e in elements if e.id == eid), None)
        if element is None:
            warnings.append(f"规则引用了不存在的元素 {eid}")
            return [], []
        scope = list(element.cells)
    else:
        names = (scope_raw.get("cells") if isinstance(scope_raw, dict) else None) or raw.get("cells") or []
        if not names and raw.get("elements"):
            for eid in raw["elements"]:
                element = next((e for e in elements if e.id == str(eid)), None)
                if element:
                    element_ids.append(element.id)
                    scope.extend(element.cells)
        else:
            for name in names:
                cell = _cell_from_name(puzzle, name)
                if cell is None:
                    warnings.append(f"格子名无效：{name}")
                    return [], []
                scope.append(cell)
    if not element_ids and raw.get("elements"):
        element_ids = [str(e) for e in raw["elements"]]
    return scope, element_ids


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

    by_id = {e.id: e for e in elements}

    def element_index(eid):
        element = by_id.get(eid)
        if element is None or len(element.cells) != 1:
            raise predicate_mod.PredicateError(f"{eid} must reference one cell")
        cell = element.cells[0]
        if cell not in scope:
            raise predicate_mod.PredicateError(
                f"{eid} ({cell_name(cell, puzzle.size)}) is outside this rule's scope"
            )
        if eid not in element_ids:
            element_ids.append(eid)
        return scope.index(cell)

    try:
        node = predicate_mod.parse(raw_pred, element_index=element_index)
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
        if len(cells) > 2 and cells[0] == cells[-1]:
            cells = cells[:-1]
        if len(cells) < 2:
            raise ValueError("Renban 太短")
        if len(set(cells)) != len(cells):
            raise ValueError("Renban 经过同一格多次")
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

    if kind == "sandwich":
        total = params.get("sum")
        if total is None:
            raise ValueError("三明治缺少 sum")
        return [Sandwich(cells, int(total))]

    if kind == "skyscraper":
        clue = params.get("clue")
        if clue is None:
            raise ValueError("摩天楼缺少 clue")
        direction = str(params.get("direction", "left")).lower()
        return [Skyscraper(cells, int(clue), direction)]

    if kind == "x_sums":
        total = params.get("sum", element.attrs.get("value") if element.attrs else None)
        if total is None:
            raise ValueError("X-Sums 缺少和")
        side = str(params.get("side") or (element.attrs or {}).get("side") or "top")
        return [XSums(cells, int(total), side)]

    if kind == "full_rank":
        if element.kind != "clue":
            raise ValueError("Full Rank 需要盘外数字")
        side = element.attrs["side"]
        ordered = cells[::-1] if side in ("right", "bottom") else cells
        return [FullRank(ordered, int(params.get("rank", element.attrs["value"])), side, n)]

    if kind == "region_sum":
        if not puzzle.regions:
            warnings.append("区域和线需要区域定义（混沌构造暂不支持）")
            return []
        region_of = {}
        for index, region in enumerate(puzzle.regions):
            for cell in region:
                region_of[cell] = index
        return [RegionSum(cells, region_of)]

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
RED = {"#ff0000", "#f00", "#dc143c", "#e00000"}


def _red_line(colour):
    if not re.fullmatch(r"#[0-9a-f]{6}(?:[0-9a-f]{2})?", colour):
        return colour in RED
    hue, saturation, brightness = rgb_to_hsv(*(v / 255 for v in bytes.fromhex(colour[1:7])))
    return min(hue, 1 - hue) <= 0.05 and saturation >= 0.35 and brightness >= 0.25


def _pink_line(colour):
    if not re.fullmatch(r"#[0-9a-f]{6}(?:[0-9a-f]{2})?", colour):
        return False
    hue, saturation, brightness = rgb_to_hsv(*(v / 255 for v in bytes.fromhex(colour[1:7])))
    return 0.72 <= hue <= 0.96 and saturation >= 0.15 and brightness >= 0.5


def _has(text: str, *words: str) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _global_non_consecutive(text):
    sentences = {"orthogonally adjacent cells may not contain consecutive digits",
                 "orthogonally adjacent cells cannot contain consecutive digits"}
    return any(line.strip().lower().removeprefix("non-consecutive:").strip().rstrip(".")
               in sentences for line in text.splitlines())


def heuristic_spec(puzzle: Puzzle, elements: list[Element]) -> dict:
    """Colour/keyword based fallback when no LLM is available."""
    text = puzzle.rules_text or ""
    rules: list[dict] = []
    globals_: list[dict] = [{"kind": "non_consecutive"}] if _global_non_consecutive(text) else []
    warnings: list[str] = []

    if _has(text, "product") and _has(text, "line"):
        line_ids = [e.id for e in elements if e.kind == "line" and len(e.cells) >= 2]
        if line_ids:
            import re as _re
            match = _re.search(r"multiply\s+to\s+(\d+)|product\s+(\d+)", text, _re.I)
            total = int(match.group(1) or match.group(2)) if match else 48
            rules.append({"kind": "product", "elements": line_ids, "total": total})

    cage_ids = [e.id for e in elements if e.kind == "cage" and e.attrs.get("sum") is not None]
    typed_fpuzzles = (puzzle.raw or {}).get("format") == "fpuz"
    if cage_ids and (typed_fpuzzles or _has(text, "killer", "cage", "sum", "笼")):
        rules.append({"kind": "cage", "elements": cage_ids})

    circle_ids = [e.id for e in elements if e.kind == "circle" and e.attrs.get("texts")]
    if circle_ids and _has(text, "quadruple", "quadruples", "四"):
        rules.append({"kind": "quadruple", "elements": circle_ids})

    if puzzle.is_chaos:
        low = " ".join(text.lower().split())
        for element in elements:
            if element.kind != "circle":
                continue
            fill = (element.attrs.get("fill") or "").lower()
            if (fill in ("#fff", "#ffffff", "#ffffffff") and
                    "white circle with a thin outline must either belong to the same region or four distinct regions" in low):
                counts = [1, 4]
            elif (fill[:7] == "#dddddd" and
                  "grey circle with a thick outline must belong to exactly three distinct regions" in low):
                counts = [3]
            else:
                continue
            rules.append({"kind": "region_count", "elements": [element.id], "counts": counts})

    for element in elements:
        if element.kind == "xv":
            rules.append({"kind": "xv", "elements": [element.id],
                          "sum": element.attrs["sum"]})

    dot_ids = [e.id for e in elements if e.kind == "dot"]
    if dot_ids and (typed_fpuzzles or _has(text, "kropki", "dot", "consecutive", "ratio", "consecutiv")):
        for dot in elements:
            if dot.kind != "dot":
                continue
            variant = "black" if "#000000" in dot.attrs.get("fill", "") else "white"
            rules.append({"kind": "kropki", "elements": [dot.id], "variant": variant})

    lines = [e for e in elements if e.kind == "line" and len(e.cells) >= 2]

    def lines_with(colors: set[str]) -> list[str]:
        return [e.id for e in lines if e.attrs.get("color", "")[:7] in colors]

    between_declared = re.search(r"\bbetween[ -]?lines?\b", text, re.I)
    between_lines = []
    if between_declared:
        ends = {e.cells[0] for e in elements if e.kind == "marker" and len(e.cells) == 1}
        between_lines = [e.id for e in lines if len(e.cells) >= 3
                         and e.cells[0] in ends and e.cells[-1] in ends]

    if _has(text, "whisper"):
        kind = "dutch_whisper" if _has(text, "dutch") else "german_whisper"
        if re.search(r"\bwhispers?\b[^.\n;]*?\b(?:on|along)\s+(?:the\s+)?red\s+lines?\b", text, re.I):
            ids = [e.id for e in lines if _red_line(e.attrs.get("color", ""))]
        else:
            ids = lines_with(GREEN) or [e.id for e in lines if _has(text, "german", "whisper")]
        if ids:
            rules.append({"kind": kind, "elements": ids})
    if _has(text, "renban"):
        pink = [e.id for e in lines if _pink_line(e.attrs.get("color", ""))]
        ids = (pink if _has(text, "pink line") else []) or lines_with(PURPLE) or [
            e.id for e in lines if e.id not in between_lines
        ]
        if ids:
            rules.append({"kind": "renban", "elements": ids})
    if _has(text, "palindrome"):
        greys = GREY | {"#aaaaaa"}
        ids = [eid for eid in lines_with(greys) if eid not in between_lines] or [
            e.id for e in lines if e.id not in between_lines
        ]
        if ids:
            rules.append({"kind": "palindrome", "elements": ids})
    if between_declared:
        ids = between_lines or [e.id for e in lines if len(e.cells) >= 3]
        if ids:
            rules.append({"kind": "between", "elements": ids})
    consecutive_named = re.search(r"(?<!non-)(?<!non )\bconsecutive[ -]lines?\b", text, re.I)
    consecutive_only = (_has(text, "consecutive")
                        and not _has(text, "renban", "kropki", "dot", "non-consecutive"))
    if consecutive_named or consecutive_only:
        ids = lines_with(ORANGE | GREEN) or [e.id for e in lines]
        if ids:
            rules.append({"kind": "consecutive", "elements": ids})

    arrows = [e.id for e in elements if e.kind == "arrow"]
    if arrows and _has(text, "arrow", "箭头"):
        rules.append({"kind": "arrow", "elements": arrows})

    if _has(text, "anti-knight", "anti knight", "anti-knight"):
        globals_.append({"kind": "anti_knight"})
    if _has(text, "anti-king", "anti king"):
        globals_.append({"kind": "anti_king"})
    clue_elements = [e for e in elements if e.kind == "clue"]
    if clue_elements:
        low = text.lower()
        has_rank = _has(text, "full rank", "full-rank")
        has_xsum = _has(text, "x-sums", "x sums", "xsum", "x-sums clue")
        if has_rank or has_xsum:
            if has_rank and has_xsum:
                choices = paired_outside_choices(puzzle, elements)
                if choices:
                    rules.extend(choices)
                else:
                    warnings.append("盘外提示同时涉及 Full Rank 与 X-Sums，未识别出类型分配方式")
            elif has_xsum:
                for element in clue_elements:
                    rules.append({"kind": "x_sums", "elements": [element.id],
                                  "sum": element.attrs["value"], "side": element.attrs["side"]})
            elif has_rank:
                for element in clue_elements:
                    rules.append({"kind": "full_rank", "elements": [element.id]})
        elif _has(text, "sandwich", "between 1 and 9", "between the 1 and the 9",
                  "digits between 1 and 9", "sum of the digits between",
                  "between 1 and 6", "digits between 1 and 6"):
            for element in clue_elements:
                rules.append({"kind": "sandwich", "elements": [element.id],
                              "sum": element.attrs["value"]})
        elif _has(text, "skyscraper"):
            for element in clue_elements:
                side = element.attrs["side"]
                if side in ("left", "right"):
                    rules.append({"kind": "skyscraper", "elements": [element.id],
                                  "clue": element.attrs["value"], "direction": side})
    if _has(text, "modular") or _has(text, "modularity"):
        globals_.append({"kind": "modular"})
    if _has(text, "entropy"):
        globals_.append({"kind": "entropy"})
    if _has(text, "diagonal") and not _has(text, "little killer"):
        direction = "both"
        if _has(text, "main diagonal") and not _has(text, "both"):
            direction = "main"
        elif _has(text, "anti-diagonal", "anti diagonal"):
            direction = "anti"
        globals_.append({"kind": "diagonal", "direction": direction})

    if _has(text, "x-sum", "x-sums", "x sums", "xsum"):
        from .arrow_xsums import parse_arrows
        for index, item in enumerate(parse_arrows(puzzle.raw or {}, puzzle.size)):
            clue_index = min(index, max(0, len(puzzle.clues) - 1))
            rules.append({
                "kind": "x_sums",
                "elements": [f"clue:{clue_index}"],
                "sum": item["total"],
                "cells": item["cells"],
                "side": "arrow",
            })

    return {"rules": rules, "globals": globals_, "notes": "heuristic", "warnings": warnings}
