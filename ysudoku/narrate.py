"""Turn engine events into Chinese explanations and animation scripts."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import predicate as predicate_mod
from .state import Event, cell_name

TITLES = {
    "naked_single": "唯一候选",
    "hidden_single": "隐性唯一",
    "locked": "区块排除",
    "subset": "数对/三数组",
    "hidden_subset": "隐性数组",
    "x_wing": "X-Wing",
    "xy_wing": "XY-Wing",
    "w_wing": "W-Wing",
    "coloring": "染色法",
    "medusa": "3D Medusa（多数字染色）",
    "forcing_chain": "反证（试探）",
    "custom": "自定义规则（L2）",
    "parity": "奇偶",
    "odd": "奇数",
    "even": "偶数",
    "clone": "克隆",
    "sandwich": "三明治",
    "skyscraper": "摩天楼",
    "region_sum": "区域和线",
    "cage": "杀手笼组合",
    "thermo": "温度计",
    "arrow": "箭头",
    "kropki": "黑白点",
    "xv": "XV",
    "quadruple": "四格提示",
    "palindrome": "回文线",
    "renban": "Renban",
    "german_whisper": "德式 Whisper",
    "dutch_whisper": "荷式 Whisper",
    "between": "之间线",
    "consecutive": "连续线",
    "little_killer": "小杀手",
    "anti_knight": "反骑士",
    "anti_king": "反国王",
    "unit_peer": "同区排除",
    "innie": "45 法则（剩余格）",
    "outie": "45 法则（剩余两格）",
}

TIERS = {
    "cage": 1, "thermo": 1, "arrow": 1, "kropki": 1, "xv": 1, "quadruple": 1,
    "palindrome": 1, "renban": 1, "german_whisper": 1, "dutch_whisper": 1,
    "between": 1, "consecutive": 1, "little_killer": 1, "anti_knight": 1,
    "anti_king": 1, "naked_single": 1, "hidden_single": 1, "innie": 2,
    "outie": 2, "locked": 2,
    "subset": 2, "hidden_subset": 2, "x_wing": 3, "xy_wing": 3, "w_wing": 3,
    "forcing_chain": 4, "custom": 2, "coloring": 3, "parity": 1, "odd": 1, "even": 1,
    "clone": 1, "sandwich": 2, "skyscraper": 2, "region_sum": 2,
}


@dataclass
class Step:
    index: int
    technique: str
    tier: int
    title: str
    detail: str
    events: list[Event]
    visual: dict = field(default_factory=dict)
    pre_dom: list[int] = field(default_factory=list, repr=False)
    pre_vals: list[int] = field(default_factory=list, repr=False)
    audit: str = "unchecked"

    def to_dict(self, n: int) -> dict:
        return {
            "index": self.index,
            "technique": self.technique,
            "tier": self.tier,
            "title": self.title,
            "detail": self.detail,
            "visual": self.visual,
            "audit": self.audit,
            "events": [e.to_dict() for e in self.events],
        }


def _names(cells: list[int], n: int) -> str:
    return "、".join(cell_name(c, n) for c in cells)


def _values(vals: list[int]) -> str:
    return "、".join(str(v) for v in sorted(vals))


def build_step(index: int, events: list[Event], n: int) -> Step:
    primary = next((e for e in events if e.reason.kind != "unit_peer"), events[0])
    kind = primary.reason.kind
    title = TITLES.get(kind, kind)
    detail, visual = _explain(events, primary, n)
    return Step(
        index=index,
        technique=kind,
        tier=TIERS.get(kind, 1),
        title=title,
        detail=detail,
        events=events,
        visual=visual,
    )


# ------------------------------------------------------------------ helpers


def _placements(events: list[Event]) -> list[Event]:
    return [e for e in events if e.kind == "place"]


def _elims(events: list[Event]) -> list[Event]:
    return [e for e in events if e.kind == "elim" and e.reason.kind != "unit_peer"]


def _group_elims(events: list[Event]) -> dict[int, list[int]]:
    grouped: dict[int, list[int]] = {}
    for event in _elims(events):
        grouped.setdefault(event.cell, []).append(event.value)
    return grouped


def _effect_lines(events: list[Event], n: int) -> list[str]:
    lines = []
    for event in _placements(events):
        lines.append(f"{cell_name(event.cell, n)} = {event.value}")
    for cell, values in sorted(_group_elims(events).items()):
        lines.append(f"{cell_name(cell, n)} ≠ {_values(values)}")
    return lines


def _reason(events: list[Event]) -> dict:
    primary = next((e for e in events if e.reason.kind != "unit_peer"), events[0])
    return primary.reason.data


def _constraint_cells(events: list[Event]) -> list[int]:
    primary = next((e for e in events if e.reason.kind != "unit_peer"), events[0])
    data = primary.reason.data
    return list(data.get("cells") or data.get("arm") or [])


def _link(cells: list[int], n: int, color: str, kind: str = "line", dashed: bool = False) -> dict:
    return {
        "points": [[c // n + 0.5, c % n + 0.5] for c in cells],
        "color": color,
        "kind": kind,
        "dashed": dashed,
    }


def _unit_visual(cells: list[int], n: int, focus: list[int] | None = None) -> dict:
    visual: dict = {"groups": [], "links": [], "chips": [], "focus": [], "premise": []}
    if cells:
        visual["groups"].append({"cells": cells, "kind": "unit"})
        visual["premise"] = [c for c in cells if c not in (focus or [])]
    if focus:
        visual["focus"] = list(focus)
    return visual


# ------------------------------------------------------------------ explain


def _explain(events: list[Event], primary: Event, n: int) -> tuple[str, dict]:
    kind = primary.reason.kind
    data = primary.reason.data
    handler = globals().get(f"_explain_{kind}")
    if handler:
        return handler(events, data, n)
    return _explain_generic(events, primary, n)


def _explain_generic(events, primary, n):
    lines = [f"规则：{primary.reason.kind}", "结论："] + _effect_lines(events, n)
    return "\n".join(lines), _basic_visual(events, n)


def _basic_visual(events: list[Event], n: int) -> dict:
    placed = [e.cell for e in events if e.kind == "place"]
    elims = _group_elims(events)
    focus = list(dict.fromkeys(placed + list(elims)))
    return {
        "focus": focus,
        "premise": [],
        "groups": [],
        "links": [],
        "chips": [],
    }


def _explain_naked_single(events, data, n):
    cell, value = data["cell"], data["value"]
    masks = [e for e in events if e.cell == cell]
    before = masks[0].before if masks else 0
    values = [v for v in range(1, n + 1) if before >> (v - 1) & 1]
    detail = (
        f"{cell_name(cell, n)} 的候选数为 {len(values)}：{_values(values)}。\n"
        f"只剩一个候选，因此 {cell_name(cell, n)} = {value}。"
    )
    return detail, _basic_visual(events, n)


def _explain_hidden_single(events, data, n):
    cell, value = data["cell"], data["value"]
    unit_cells = data.get("unit_cells", [])
    others = [c for c in unit_cells if c != cell]
    detail = (
        f"在{data['unit']}中，数字 {value} 只可能出现在 {cell_name(cell, n)}：\n"
        f"其余 {len(others)} 个格子（{_names(others, n)}）都已排除 {value}。\n"
        f"所以 {cell_name(cell, n)} = {value}。"
    )
    visual = _unit_visual(unit_cells, n, focus=[cell])
    visual["chips"].append({"cell": cell, "text": str(value), "kind": "value"})
    return detail, visual


def _explain_locked(events, data, n):
    digit = data["digit"]
    cells = data.get("cells", [])
    target = data.get("target")
    unit = data.get("unit", "")
    if target in ("row", "col"):
        target_name = f"第{int(data['index']) + 1}{'行' if target == 'row' else '列'}"
        detail = (
            f"在{unit}中，数字 {digit} 的所有可能位置 {_names(cells, n)} 都在同一{('行' if target == 'row' else '列')}。\n"
            f"因此 {target_name} 上、{unit}之外的格子都不能是 {digit}。"
        )
    else:
        detail = (
            f"在{unit}中，数字 {digit} 的所有可能位置 {_names(cells, n)} 都落在同一个区域内。\n"
            f"因此该区域内、{unit}之外的格子都不能是 {digit}。"
        )
    visual = _unit_visual(data.get("unit_cells", []), n, focus=cells)
    if data.get("region_cells"):
        visual["groups"].append({"cells": data["region_cells"], "kind": "unit"})
    return detail, visual


def _explain_subset(events, data, n):
    cells = data["cells"]
    digits = data["digits"]
    detail = (
        f"{data['unit']}中，{_names(cells, n)} 的候选全部落在 {{{_values(digits)}}} 这 {len(digits)} 个数里，"
        f"{len(cells)} 个格子恰好占用这 {len(digits)} 个数字。\n"
        f"因此同一单元的其他格子不能是 {_values(digits)}。"
    )
    visual = _unit_visual(data.get("unit_cells", []), n, focus=cells)
    visual["groups"].append({"cells": cells, "kind": "pair"})
    return detail, visual


def _explain_hidden_subset(events, data, n):
    cells = data["cells"]
    digits = data["digits"]
    detail = (
        f"{data['unit']}中，数字 {_values(digits)} 只可能出现在 {_names(cells, n)} 这几格。\n"
        f"这些格子被这组数字占满，因此只能填 {_values(digits)}。"
    )
    visual = _unit_visual(data.get("unit_cells", []), n, focus=cells)
    visual["groups"].append({"cells": cells, "kind": "pair"})
    return detail, visual


def _explain_x_wing(events, data, n):
    digit = data["digit"]
    cells = data["cells"]
    detail = (
        f"数字 {digit} 在{'第' + '、第'.join(str(r + 1) for r in data['rows']) + '行' if data['orientation'] == 'row' else '第' + '、第'.join(str(c + 1) for c in data['cols']) + '列'}中"
        f"都只出现在{'第' + '、第'.join(str(c + 1) for c in data['cols']) + '列' if data['orientation'] == 'row' else '第' + '、第'.join(str(r + 1) for r in data['rows']) + '行'}，"
        f"四个端点 {_names(cells, n)} 构成 X-Wing。\n"
        f"这两条线中必有一条覆盖数字 {digit}，因此交叉线上的其他格子不能再是 {digit}。"
    )
    visual = _unit_visual([], n, focus=cells)
    visual["groups"].append({"cells": cells, "kind": "xwing"})
    visual["links"] = [
        _link([cells[0], cells[1]], n, "#38bdf8", "dashed"),
        _link([cells[2], cells[3]], n, "#38bdf8", "dashed"),
    ]
    return detail, visual


def _explain_parity(events, data, n):
    cells = data.get("cells", [])
    odd = data.get("kind", "odd") == "odd"
    name = "奇数" if odd else "偶数"
    detail = (
        f"{name}约束：{_names(cells, n)} 必须填{name}。\n"
        f"排除与之矛盾的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "pair"})
    return detail, visual


def _explain_clone(events, data, n):
    cells = data.get("cells", [])
    detail = (
        f"克隆：{_names(cells, n)} 必须填同一个数字。\n"
        f"取所有格子的候选交集，排除不一致的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "pair"})
    return detail, visual


def _explain_sandwich(events, data, n):
    cells = data.get("cells", [])
    total = data.get("sum")
    detail = (
        f"三明治：{_names(cells, n)} 中，1 与 9 之间的所有数字之和为 {total}。\n"
        f"枚举 1 和 9 的所有位置，保留能凑出该和的组合，排除不可能的位置与候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["chips"].append({"cell": cells[0], "text": str(total), "kind": "sum"})
    return detail, visual


def _explain_skyscraper(events, data, n):
    cells = data.get("cells", [])
    clue = data.get("clue")
    side = "左" if data.get("direction", "left") == "left" else "右"
    detail = (
        f"摩天楼：从{side}侧看 {_names(cells, n)}，应看到 {clue} 栋。\n"
        f"数字代表楼高，只有比前面都高的楼才可见；据此排除不可能的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["chips"].append({"cell": cells[0], "text": f"见{clue}", "kind": "sum"})
    return detail, visual


def _explain_region_sum(events, data, n):
    cells = data.get("cells", [])
    segs = data.get("segments") or []
    detail = (
        f"区域和线：{_names(cells, n)} 被区域边界切成 {len(segs)} 段，每段数字和必须相等。\n"
        f"逐段枚举可达和并取交集，排除无法参与该和的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#38bdf8", "line"))
    return detail, visual


def _explain_coloring(events, data, n):
    digit = data.get("digit")
    mode = data.get("mode")
    links = data.get("links") or []
    colors = data.get("colors") or {}
    if mode == "wrap":
        tone = "A" if data.get("color") == 0 else "B"
        cells = data.get("cells") or []
        detail = (
            f"染色法（数字 {digit}）：把所有强链（同一单元里该数字只剩两个位置）连起来，"
            f"交替染成 A / B 两色。\n"
            f"同色格 {_names(cells, n)} 互相看见——它们不可能同时为 {digit}，"
            f"所以 {tone} 色整组都不可能为 {digit}。\n"
            f"排除：\n"
        )
    else:
        detail = (
            f"染色法（数字 {digit}）：强链把候选分成 A / B 两色，必有一色为真。\n"
            f"{_names(data.get('cells') or [], n)} 同时看见 A 色和 B 色格："
            f"无论哪一色为真，它都不能是 {digit}。\n"
            f"排除：\n"
        )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    for a, b in links:
        tone = colors.get(str(a), 0)
        visual["links"].append(_link([a, b], n, "#ef4444" if tone == 0 else "#3b82f6", "dashed"))
    for cell, tone in colors.items():
        visual["chips"].append({
            "cell": int(cell), "text": "A" if tone == 0 else "B", "kind": "color",
        })
    return detail, visual


def _explain_medusa(events, data, n):
    mode = data.get("mode")
    links = data.get("links") or []
    colors = data.get("colors") or {}
    if mode == "wrap":
        tone = "A" if data.get("color") == 0 else "B"
        detail = (
            f"3D Medusa：把候选（格+数字）用强链连起来，交替染成 A / B。\n"
            f"{tone} 色内部出现了互相冲突的候选（同一格两个数字，或同一单元两个同数字），"
            f"说明整组 {tone} 色不可能成立。\n排除该色全部候选：\n"
        )
    elif mode == "trap":
        detail = (
            "3D Medusa：某个候选同时看见 A 色和 B 色候选。\n"
            "两色必有一真，因此无论哪色成立，它都不能成立：\n"
        )
    else:
        detail = (
            "3D Medusa：同一格里同时出现 A 色和 B 色候选，说明这两者必有一真。\n"
            "因此该格其余候选都可以排除：\n"
        )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    for c1, d1, c2, d2 in links:
        if c1 == c2:
            continue
        tone = colors.get(f"{c1}:{d1}", 0)
        visual["links"].append(_link([c1, c2], n, "#ef4444" if tone == 0 else "#3b82f6", "dashed"))
    seen = set()
    for key, tone in colors.items():
        cell = int(key.split(":")[0])
        if cell in seen:
            continue
        seen.add(cell)
        visual["chips"].append({"cell": cell, "text": "A" if tone == 0 else "B", "kind": "color"})
    return detail, visual


def _explain_custom(events, data, n):
    scope = data.get("scope", [])
    cite = data.get("cite") or "未命名自定义规则"
    names = [cell_name(c, n) for c in scope]
    try:
        node = predicate_mod.parse(data["predicate"])
        text = predicate_mod.format_node(node, names)
    except Exception:  # noqa: BLE001 - display only
        text = "（谓词解析失败）"
    prefix = "【推测规则】" if data.get("hypothesis") else ""
    detail = (
        f"{prefix}自定义规则：{cite}\n"
        f"作用域：{_names(scope, n)}\n"
        f"约束：{text}\n"
        f"按当前候选逐组枚举，排除没有任何满足赋值的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    if data.get("hypothesis"):
        detail += "\n注意：这条规则由模型推测，未经形式化证明；可关闭推测规则后重算。"
    visual = _basic_visual(events, n)
    if scope:
        visual["groups"].append({"cells": scope, "kind": "pair"})
        visual["links"].append(_link(scope, n, "#f472b6", "dashed"))
    return detail, visual


def _explain_xy_wing(events, data, n):
    pivot, (w1, w2) = data["pivot"], data["wings"]
    a, b, c = data["digits"]
    detail = (
        f"XY-Wing：枢纽 {cell_name(pivot, n)} 的候选是 {{{a},{b}}}；"
        f"两翼 {cell_name(w1, n)} 为 {{{a},{c}}}、{cell_name(w2, n)} 为 {{{b},{c}}}。\n"
        f"枢纽无论取 {a} 还是 {b}，数字 {c} 都必然落在其中一翼；\n"
        f"因此同时看见两翼的格子不能是 {c}：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [pivot, w1, w2], "kind": "pair"})
    visual["links"] = [
        _link([pivot, w1], n, "#38bdf8", "dashed"),
        _link([pivot, w2], n, "#38bdf8", "dashed"),
    ]
    return detail, visual


def _explain_w_wing(events, data, n):
    x, y = data["cells"]
    p, q = data["link"]
    digit, other = data["digits"]
    detail = (
        f"W-Wing：{cell_name(x, n)} 与 {cell_name(y, n)} 的候选都是 {{{digit},{other}}}。\n"
        f"数字 {digit} 在某个单元里只有 {cell_name(p, n)}、{cell_name(q, n)} 两个位置（强链）。\n"
        f"若 {cell_name(x, n)}={digit}，则 {cell_name(p, n)}≠{digit}，强制 {cell_name(q, n)}={digit}，"
        f"于是 {cell_name(y, n)}={other}；反之亦然。\n"
        f"两种情况下 {other} 都落在这两格之一，因此它们的共同影响格不能是 {other}：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [x, y, p, q], "kind": "pair"})
    visual["links"] = [_link([x, p], n, "#f59e0b", "dashed"), _link([y, q], n, "#f59e0b", "dashed")]
    return detail, visual


def _explain_forcing_chain(events, data, n):
    cell, value = data["cell"], data["value"]
    trace = data.get("trace") or []
    detail = (
        f"反证（高级技巧，不属于纯直接推理）：假设 {cell_name(cell, n)} = {value}。\n"
        f"沿着已确定的约束传播，得到以下连锁反应：\n"
    )
    if trace:
        parts = []
        for item in trace:
            if item["kind"] == "place":
                parts.append(f"{cell_name(item['cell'], n)}={item['value']}")
            else:
                parts.append(f"{cell_name(item['cell'], n)}≠{item['value']}")
        detail += " → ".join(parts) + "\n"
    detail += f"传播最终出现矛盾（某格候选被清空），所以假设不成立：{cell_name(cell, n)} ≠ {value}。\n"
    detail += "注意：这一步是反证，不是直接推理；如只想看纯逻辑链，请关闭「反证」开关。"
    visual = _basic_visual(events, n)
    visual["focus"] = [cell]
    return detail, visual


def _explain_thermo(events, data, n):
    cells = data["cells"]
    detail = (
        f"温度计 {_names(cells, n)} 上的数字必须严格递增。\n"
        f"按当前候选做前后向可行性检查，以下候选无法出现在任何递增序列中，故排除：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#f97316", "thermo"))
    return detail, visual


def _explain_cage(events, data, n):
    cells = data["cells"]
    total = data["sum"]
    combos = data.get("combos") or []
    detail = f"笼 {total}（{len(cells)} 格，数字互不重复）：{_names(cells, n)}。\n"
    if combos:
        shown = ["{" + _values(list(c)) + "}" for c in combos[:8]]
        more = "…" if len(combos) > 8 else ""
        detail += f"当前可行的数字组合共 {len(combos)} 组：{'、'.join(shown)}{more}。\n"
    detail += "按这些组合逐格检查，以下候选不可能出现，故排除：\n"
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "cage"})
    visual["chips"].append({"cell": cells[0], "text": str(total), "kind": "sum"})
    return detail, visual


def _explain_arrow(events, data, n):
    circle = data["circle"]
    arm = data["arm"]
    detail = (
        f"箭头规则：圆圈中的数字等于箭身上所有数字之和。\n"
        f"圆圈 {cell_name(circle, n)}，箭身 {_names(arm, n)}。\n"
        f"穷举箭身可能的和、并与圆圈候选取交集后，排除不可能的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [circle] + arm, "kind": "arrow"})
    visual["links"].append(_link([circle] + arm, n, "#eab308", "arrow"))
    return detail, visual


def _explain_kropki(events, data, n):
    a, b = data["a"], data["b"]
    if data.get("variant") == "black":
        rule = "黑点：两格数字成 1:2 比例（一个是另一个的两倍）"
    else:
        rule = "白点：两格数字相差 1（连续）"
    detail = (
        f"{rule}。涉及 {cell_name(a, n)} 与 {cell_name(b, n)}。\n"
        f"逐值检查配对可能性后，排除找不到任何搭配的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [a, b], "kind": "pair"})
    visual["links"].append(_link([a, b], n, "#a855f7", "dot", dashed=True))
    return detail, visual


def _explain_xv(events, data, n):
    a, b, total = data["a"], data["b"], data["sum"]
    detail = (
        f"XV 规则：{cell_name(a, n)} 与 {cell_name(b, n)} 的和为 {total}。\n"
        f"逐值检查配对可能性后，排除不可能的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [a, b], "kind": "pair"})
    visual["chips"].append({"cell": a, "text": str(total), "kind": "sum"})
    return detail, visual


def _explain_quadruple(events, data, n):
    cells = data["cells"]
    digits = data["digits"]
    detail = (
        f"圆圈周围的四格 {_names(cells, n)} 中，必须出现数字 {_values(digits)}。\n"
        f"按覆盖关系逐格检查，排除会让某个数字无处安放的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "quad"})
    visual["chips"].append({"cell": cells[0], "text": "".join(map(str, digits)), "kind": "sum"})
    return detail, visual


def _explain_innie(events, data, n):
    detail = (
        f"{data['unit']}的数字总和为 45。其中被完整笼覆盖的部分合计 {data['sum']}，"
        f"只剩 {cell_name(data['cell'], n)} 不属于这些笼。\n"
        f"45 − {data['sum']} = {data['value']}，所以 {cell_name(data['cell'], n)} = {data['value']}。"
    )
    visual = _unit_visual(data.get("unit_cells", []), n, focus=[data["cell"]])
    visual["chips"].append({"cell": data["cell"], "text": str(data["value"]), "kind": "value"})
    return detail, visual


def _explain_outie(events, data, n):
    a, b = data["cells"]
    detail = (
        f"{data['unit']}的数字总和为 45。被完整笼覆盖的部分合计 {data['covered']}，"
        f"剩余 {cell_name(a, n)} 与 {cell_name(b, n)} 两格。\n"
        f"这两格之和为 45 − {data['covered']} = {data['sum']}，据此排除无法配对的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _unit_visual(data.get("unit_cells", []), n, focus=[a, b])
    visual["chips"].append({"cell": a, "text": f"和={data['sum']}", "kind": "sum"})
    return detail, visual


def _explain_palindrome(events, data, n):
    cells = data["cells"]
    detail = (
        f"回文线 {_names(cells, n)} 关于中心对称，对称位置的数字相同。\n"
        f"取对称格的候选交集后，排除不一致的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#94a3b8", "palindrome"))
    return detail, visual


def _explain_renban(events, data, n):
    cells = data["cells"]
    detail = (
        f"Renban：{_names(cells, n)} 这 {len(cells)} 格必须是一组连续数字（顺序任意，互不重复）。\n"
        f"逐一检查可能的连续窗口，排除不属于任何可行窗口的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#c084fc", "renban"))
    return detail, visual


def _explain_whisper(events, data, n, kind="german_whisper"):
    cells = data["cells"]
    diff = data.get("diff", 5)
    detail = (
        f"{'德式' if diff >= 5 else '荷式'} Whisper：{_names(cells, n)} 相邻两格的数字差至少为 {diff}。\n"
        f"逐对检查相邻格，排除找不到合法邻居的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#22c55e", "whisper"))
    return detail, visual


def _explain_german_whisper(events, data, n):
    return _explain_whisper(events, data, n, "german_whisper")


def _explain_dutch_whisper(events, data, n):
    return _explain_whisper(events, data, n, "dutch_whisper")


def _explain_between(events, data, n):
    cells = data["cells"]
    detail = (
        f"之间线 {_names(cells, n)}：中间格子的数字必须严格介于两端数字之间。\n"
        f"检查两端所有可能取值后，排除不可能处于中间的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#a3a3a3", "between"))
    return detail, visual


def _explain_consecutive(events, data, n):
    cells = data["cells"]
    detail = (
        f"连续线：{_names(cells, n)} 上相邻两格相差 1。\n"
        f"逐对检查相邻格，排除不可能的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["links"].append(_link(cells, n, "#fb923c", "consecutive"))
    return detail, visual


def _explain_little_killer(events, data, n):
    cells = data["cells"]
    total = data["sum"]
    detail = (
        f"小杀手：{_names(cells, n)} 这条斜线上的数字之和为 {total}。\n"
        f"穷举可达的和，排除无法参与的任何候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "line"})
    visual["chips"].append({"cell": cells[0], "text": str(total), "kind": "sum"})
    return detail, visual


def _explain_anti_knight(events, data, n):
    a, b = data["a"], data["b"]
    detail = (
        f"反骑士：马步位置的两格不能相同。{cell_name(a, n)} 与 {cell_name(b, n)} 互为马步。\n"
        f"排除重复的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [a, b], "kind": "pair"})
    visual["links"].append(_link([a, b], n, "#f43f5e", "knight", dashed=True))
    return detail, visual


def _explain_anti_king(events, data, n):
    a, b = data["a"], data["b"]
    detail = (
        f"反国王：相邻（含斜向）两格不能相同。{cell_name(a, n)} 与 {cell_name(b, n)} 相邻。\n"
        f"排除重复的候选：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": [a, b], "kind": "pair"})
    return detail, visual
