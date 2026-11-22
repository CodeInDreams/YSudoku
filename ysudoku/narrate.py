"""Turn engine events into Chinese explanations and animation scripts."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import predicate as predicate_mod
from .state import Event, bits, cell_name

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
    "x_chain": "X-Chain（单数字链）",
    "als": "ALS-XZ",
    "forcing_chain": "反证（试探）",
    "contradiction": "反证",
    "custom": "自定义规则（L2）",
    "sum_link": "共享格组和数",
    "ir_support": "通用约束支持",
    "pattern_support": "组合占位",
    "rule_choice": "规则选择与分配",
    "full_rank": "Full Rank",
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
    "exact_digits": "固定数字组合",
    "palindrome": "回文线",
    "renban": "Renban",
    "german_whisper": "德式 Whisper",
    "dutch_whisper": "荷式 Whisper",
    "between": "之间线",
    "consecutive": "连续线",
    "little_killer": "小杀手",
    "non_consecutive": "正交相邻格不能填连续数",
    "anti_knight": "反骑士",
    "anti_king": "反国王",
    "unit_peer": "同区排除",
    "chaos_pattern": "圈域模式",
    "class_cover": "2×2 类排除",
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
    "forcing_chain": 4, "contradiction": 4, "custom": 2, "coloring": 3, "parity": 1, "odd": 1, "even": 1,
    "clone": 1, "sandwich": 2, "skyscraper": 2, "region_sum": 2,
    "chaos_pattern": 2, "class_cover": 2, "pattern_support": 2,
    "rule_choice": 2, "full_rank": 2,
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
    candidates: list[dict] = field(default_factory=list)
    audit: str = "unchecked"
    branch: bool = False
    revert: bool = False

    def to_dict(self, n: int) -> dict:
        return {
            "index": self.index,
            "technique": self.technique,
            "tier": self.tier,
            "title": self.title,
            "detail": self.detail,
            "visual": self.visual,
            "pre_dom": self.pre_dom,
            "candidates": self.candidates,
            "audit": self.audit,
            "branch": self.branch,
            "revert": self.revert,
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
        try:
            return handler(events, data, n)
        except Exception:  # noqa: BLE001 - a narration bug must not kill a solve
            return _explain_generic(events, primary, n)
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
    return ("【推测规则】" if data.get("hypothesis") else "") + detail, visual


def _explain_locked(events, data, n):
    reasons = {(ev.value, ev.reason.data["target_unit"]): ev.reason.data
               for ev in events if ev.reason.kind == "locked"}
    detail = []
    visual = _unit_visual(data["unit_cells"], n, focus=sorted(_group_elims(events)))
    hosts = set()
    regions = {tuple(data["unit_cells"])}
    for (digit, target), reason in reasons.items():
        cells = reason["cells"]
        hosts.update(cells)
        target_cells = tuple(reason["target_cells"])
        if target_cells not in regions:
            visual["groups"].append({"cells": list(target_cells), "kind": "unit"})
            regions.add(target_cells)
        prefix = "【推测规则】" if reason.get("hypothesis") else ""
        detail.append(f"{prefix}在{reason['unit']}中，数字 {digit} 只可能出现在 {_names(cells, n)}，"
                      f"这些格都在{target}。因此{target}内、{reason['unit']}之外的格子排除 {digit}。")
    visual["premise"] = sorted(hosts)
    return "\n".join([*detail, *_effect_lines(events, n)]), visual


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
    return ("【推测规则】" if data.get("hypothesis") else "") + detail, visual


def _explain_hidden_subset(events, data, n):
    cells = data["cells"]
    digits = data["digits"]
    detail = (
        f"{data['unit']}中，数字 {_values(digits)} 只可能出现在 {_names(cells, n)} 这几格。\n"
        f"这些格子被这组数字占满，因此只能填 {_values(digits)}。"
    )
    visual = _unit_visual(data.get("unit_cells", []), n, focus=cells)
    visual["groups"].append({"cells": cells, "kind": "pair"})
    if data.get("unit_kind") in ("line", "distinct"):
        detail = f"{data['unit']}有 {n} 格且数字互异，所以每个数字都必须出现一次。\n" + detail
    return ("【推测规则】" if data.get("hypothesis") else "") + detail, visual


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


def _explain_class_cover(events, data, n):
    cells = data.get("cells", [])
    classes = data.get("classes", [])
    forced = data.get("forced_cell")
    forced_class = data.get("forced_class")
    if forced is None:
        groups = _group_elims(events)
        if len(groups) == 1:
            forced = next(iter(groups))
    if forced is None:
        return _explain_generic(events, events[0], n)
    others = [c for c in cells if c != forced]
    class_text = "；".join("{" + _values(cls) + "}" for cls in classes)
    lines = [
        f"2×2 区域：{'、'.join(cell_name(c, n) for c in cells)}。",
        f"这个区域必须包含三类数字：{class_text}。",
    ]
    if forced_class:
        lines.append(
            f"除 {cell_name(forced, n)} 外的 "
            f"{'、'.join(cell_name(c, n) for c in others)} 的候选都不在 "
            f"{{{_values(forced_class)}}} 这一类中，"
            f"所以必须由 {cell_name(forced, n)} 承担这一类：{{{_values(forced_class)}}}。"
        )
        lines.append("因此排除该格其余候选。")
    else:
        lines.append(f"因此 {cell_name(forced, n)} 只能取这一类候选。")
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": cells, "kind": "class_cover"})
    visual["focus"] = [forced]
    return "\n".join(lines), visual


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


def _explain_sum_link(events, data, n):
    lines = list(data["premises"])
    shared = _names(data["shared"], n)
    lines.append(f"两条线索都算了 {shared}。减去相同的部分，剩下 {data['equation']}。")
    domains = dict(data["domains"])
    terms = data["terms"]
    total = data["total"]
    if data["pairs"]:
        # Read from the cell with fewer possibilities, like a player would.
        source = min(range(2), key=lambda i: len(domains[terms[i][0]]))
        dest = 1 - source
        a, x = terms[source]
        b, y = terms[dest]
        an, bn = cell_name(a, n), cell_name(b, n)
        if x == -y and abs(y) == 1:
            offset = total * y
            if offset:
                word = "大" if offset > 0 else "小"
                lines.append(f"也就是说，{bn} 比 {an} {word} {abs(offset)}。")
        options = "、".join(map(str, domains[a]))
        lines.append(f"从 {an} 看，它只能填 {options}。")
        partners = {pair[source]: pair[dest] for pair in data["pairs"]}
        for value in domains[a]:
            if value in partners:
                lines.append(f"若 {an} 填 {value}，按上式，{bn} 就要填 {partners[value]}。")
            else:
                lines.append(f"若 {an} 填 {value}，{bn} 的候选中没有一个能满足上式。")
    else:
        for cell, removed in _group_elims(events).items():
            other = {0}
            coeff = dict(terms)[cell]
            for c, k in terms:
                if c != cell:
                    other = {s + k * v for s in other for v in domains[c]}
            needed = sorted({total - coeff * v for v in removed})
            if len(terms) > 1:
                expr = " ".join(f"{k:+d}×{cell_name(c, n)}" for c, k in terms if c != cell)
                available = (_values(sorted(other)) if len(other) <= 8
                             else f"{min(other)} 到 {max(other)} 之间的 {len(other)} 个数")
                lines.append(f"若 {cell_name(cell, n)} 填 {_values(removed)}，{expr} 就要取 "
                             f"{_values(needed)}。用这些格的当前候选只能得到 {available}，两边没有相同的数。")
    for cell, removed in _group_elims(events).items():
        kept = [v for v in domains[cell] if v not in removed]
        lines.append(f"所以 {cell_name(cell, n)} 只剩 {_values(kept)}。")
    visual = _basic_visual(events, n)
    visual["premise"] = list(data["shared"])
    return "\n".join(lines), visual


def _explain_ir_support(events, data, n):
    rules = data.get("relations") or []
    details = "；".join(rules) if rules else "相关关系的联合约束"
    effects = _effect_lines(events, n)
    detail = (
        f"检查以下关系的所有局部可行赋值：{details}。\n"
        f"没有任何满足这些关系的赋值支持被排除的候选：\n"
        + ("\n".join(effects) if effects else "（无候选变化）")
    )
    return detail, _basic_visual(events, n)


def _explain_pattern_support(events, data, n):
    visual = _basic_visual(events, n)
    if data["unit_cells"]:
        visual["groups"].append({"cells": data["unit_cells"], "kind": "unit"})
    for scope in data["scopes"]:
        visual["groups"].append({"cells": scope, "kind": "pair"})
    if "digits" in data:
        hosts = data["hosts"]
        visual["premise"] = hosts
        detail = (f"按「{data['rules'][0]}」，所有合法组合都让 {_names(hosts, n)} "
                  f"占用 {_values(list(bits(data['digits'])))}。"
                  f"{data['unit']}的其他格不能再用这些数字。")
    else:
        detail = "比较" + "和".join(
            f"{_names(scope, n)} 的「{rule}」"
            for scope, rule in zip(data["scopes"], data["rules"])
        ) + "。"
        if data["shared"]:
            detail += f"两条规则在 {_names(data['shared'], n)} 的取值必须一致。"
        if data["unit"]:
            def occupancy(masks):
                samples = ["{" + _values(list(bits(mask))) + "}" for mask in masks[:4]]
                return " / ".join(samples) + (f" 等 {len(masks)} 种" if len(masks) > 4 else "")

            left, right = data["hosts"]
            visual["premise"] = sorted(set(left + right + data["shared"]))
            left_masks, right_masks = data["occupancy"]
            detail += (f"在{data['unit']}，{_names(left, n)} 占用 {occupancy(left_masks)}，"
                       f"{_names(right, n)} 占用 {occupancy(right_masks)}，两边不能占用同一个数字。")
        else:
            visual["premise"] = data["shared"]
        detail += "被排除的候选只出现在无法配对的组合里。"
    prefix = "【推测规则】" if data["hypothesis"] else ""
    return prefix + detail + "\n" + "；".join(_effect_lines(events, n)), visual


def _explain_rule_choice(events, data, n):
    visual = _basic_visual(events, n)
    lines = []
    if data["quotas"] is not None:
        counts = "、".join(f"{name}恰好 {count} 次" for name, count in data["quotas"].items())
        lines.append(f"这些区域各用一条规则。{counts}。")
    for region in data["regions"]:
        label = region["label"]
        visual["groups"].append({"cells": region["cells"], "kind": "pair"})
        for name, why in region["rejected"].items():
            lines.append(f"{label}排除 {name}。{why}。")
        for name, witness in region["witnesses"].items():
            groups = "、".join(data["regions"][index]["label"] for index in witness["regions"])
            lines.append(f"{label}若使用 {name}，{groups} 只能分到 {witness['slots']} 次规则名额，"
                         f"少于这 {len(witness['regions'])} 个区域所需的次数。")
        remaining = "、".join(region["remaining"])
        lines.append(f"{label}只能使用 {remaining}。")
    labels = [region["label"] for region in data["regions"]]

    def assignment(names):
        return "、".join(f"{label}用 {name}" for label, name in zip(labels, names))

    for failure in data.get("failures", [])[:4]:
        lines.append(f"若{assignment(failure['rules'])}，则{failure['reason']}。")
    for branch in data.get("assignments", [])[:4]:
        facts = branch["facts"]
        if not facts:
            continue
        premises = []
        for p in branch["premises"]:
            if p["kind"] == "rank_head":
                premises.append(f"排名 {p['rank']} 的首位是 {p['head']}")
            elif len(p["lengths"]) == 1:
                length = p["lengths"][0]
                if 0 < n - length <= 3:
                    premises.append(f"整组和 {p['sum'] + p['complement']} 减去前缀和 "
                                    f"{p['sum']}，尾部和为 {p['complement']}")
                else:
                    premises.append(f"前 {length} 格之和为 {p['sum']}")
        fixed = "、".join(f"{cell_name(cell, n)}={value}" for cell, value in facts[:4])
        if len(facts) > 4:
            fixed += f" 等 {len(facts)} 格"
        detail = "，".join(premises)
        lines.append(f"{assignment(branch['rules'])}时，{detail + '，所以 ' if detail else ''}{fixed}。")
    for lock in data.get("occupancy", []):
        hosts = lock["hosts"]
        digit = lock["digit"]
        lines.append(f"所有剩余分配都让{lock['unit']}的 {digit} 落在 {_names(hosts, n)}，"
                     f"所以该单元其他格可以排除 {digit}。")
        visual["groups"].append({"cells": lock["unit_cells"], "kind": "unit"})
        visual["premise"] = sorted(set(visual.get("premise", [])) | set(hosts))
    lines.append("排除所有剩余规则都无法支持的候选。")
    return "\n".join([*lines, *_effect_lines(events, n)]), visual


def _explain_x_sums(events, data, n):
    lines = [f"按提示方向读取，首格数字决定前缀长度，前缀和为 {data['sum']}。"]
    if "complement" in data:
        lines.append(f"整组数字互异且包含 1–{n}，"
                     f"因此尾部和为 {data['sum'] + data['complement']} − {data['sum']} = {data['complement']}。")
    return "\n".join([*lines, *_effect_lines(events, n)]), _unit_visual(
        data["cells"], n, focus=sorted(_group_elims(events)))


def _explain_full_rank(events, data, n):
    rank, head = data["rank"], data["head"]
    lines = [f"每个数字都在首位出现 4 次。排名 {rank} 的读数首位是 {head}。"]
    if data["lower"] or data["upper"]:
        lines.append("只与首位相同的其他三个读数比较。")
    if data["lower"]:
        lines.append("这个读数必须大于 " + "".join(map(str, data["lower"])) + "。")
    if data["upper"]:
        lines.append("这个读数不能大于 " + "".join(map(str, data["upper"])) + "。")
    visual = _unit_visual(data["cells"], n, focus=sorted(_group_elims(events)))
    return "\n".join([*lines, *_effect_lines(events, n)]), visual


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
    component = int(data.get("component", 0))
    palette = data.get("palette") or [["#ef4444", "#3b82f6"]]
    labels = data.get("labels") or ["A", "B"]
    pair = palette[component % len(palette)]
    label_a = labels[(2 * component) % len(labels)]
    label_b = labels[(2 * component + 1) % len(labels)]
    if mode == "wrap":
        tone = label_a if data.get("color") == 0 else label_b
        cells = data.get("cells") or []
        detail = (
            f"染色法（数字 {digit}）：把所有强链（同一单元里该数字只剩两个位置）连起来，"
            f"交替染成 {label_a} / {label_b} 两色（不同连通块用不同色对）。\n"
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
        visual["links"].append(_link([a, b], n, pair[tone], "dashed"))
    for cell, tone in colors.items():
        visual["chips"].append({
            "cell": int(cell),
            "text": label_a if tone == 0 else label_b,
            "kind": "color",
            "color": pair[tone],
        })
    return detail, visual


def _explain_medusa(events, data, n):
    mode = data.get("mode")
    links = data.get("links") or []
    colors = data.get("colors") or {}
    component = int(data.get("component", 0))
    palette = data.get("palette") or [["#ef4444", "#3b82f6"]]
    labels = data.get("labels") or ["A", "B"]
    pair = palette[component % len(palette)]
    label_a = labels[(2 * component) % len(labels)]
    label_b = labels[(2 * component + 1) % len(labels)]
    if mode == "wrap":
        tone = label_a if data.get("color") == 0 else label_b
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
        visual["links"].append(_link([c1, c2], n, pair[tone], "dashed"))
    seen = set()
    for key, tone in colors.items():
        cell = int(key.split(":")[0])
        if cell in seen:
            continue
        seen.add(cell)
        visual["chips"].append({
            "cell": cell,
            "text": label_a if tone == 0 else label_b,
            "kind": "color",
            "color": pair[tone],
        })
    return detail, visual


def _explain_x_chain(events, data, n):
    digit = data.get("digit")
    path = data.get("cells") or []
    a, b = data.get("ends") or (path[0], path[-1])
    detail = (
        f"X-Chain（数字 {digit}）：沿强链/弱链交替走 "
        f"{' → '.join(cell_name(c, n) for c in path)}。\n"
        f"链的两端 {cell_name(a, n)}、{cell_name(b, n)} 必有一格为 {digit}，"
        f"所以同时看见两端的 {cell_name(data['target'], n)} 不能是 {digit}。\n"
        f"排除：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": path, "kind": "line"})
    visual["links"].append(_link(path, n, "#f59e0b", "line"))
    return detail, visual


def _explain_als(events, data, n):
    a1 = data.get("als1") or []
    a2 = data.get("als2") or []
    x = data.get("x")
    z = data.get("z")
    detail = (
        f"ALS-XZ：两个「几乎锁定集」\n"
        f"  A = {_names(a1, n)}，B = {_names(a2, n)}\n"
        f"共同候选里，{x} 是受限共同候选（A、B 中所有 {x} 都互相看见，不能同时在两边成立），"
        f"{z} 是普通共同候选。\n"
        f"若 A 不含 {z}，则 A 的其余候选被迫成立，进而推出 B 的 {z} 成立；"
        f"所以 {z} 必然落在 A 或 B 中。\n"
        f"因此同时看见 A、B 里所有 {z} 的格子不能是 {z}：\n"
    )
    detail += "；".join(_effect_lines(events, n)) or "（无）"
    visual = _basic_visual(events, n)
    visual["groups"].append({"cells": a1, "kind": "pair"})
    visual["groups"].append({"cells": a2, "kind": "pair"})
    visual["chips"].append({"cell": a1[0], "text": f"X={x}", "kind": "sum"})
    visual["chips"].append({"cell": a2[0], "text": f"Z={z}", "kind": "value"})
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


def _explain_contradiction(events, data, n):
    cell, value = data["cell"], data["value"]
    forced = data.get("forced")
    prefix = "反证推翻" if data.get("phase") == "end" else "反证"
    cause = data.get("cause") or "沿规则继续推导后无解"
    detail = (
        f"{prefix}：假设 {cell_name(cell, n)} = {value}。\n"
        f"在假设下继续按规则推导，最终出现矛盾：{cause}。\n"
    )
    if forced is not None:
        detail += f"因此 {cell_name(cell, n)} 不可能是 {value}，只能是 {forced}。\n"
    else:
        detail += f"因此 {cell_name(cell, n)} ≠ {value}，删除该候选。\n"
    detail += "注意：这一步通过反证排除候选，不是直接推理。"
    visual = _basic_visual(events, n)
    visual["focus"] = []
    visual["groups"].append({"cells": [cell], "kind": "assumption"})
    visual["assumption"] = {
        "cells": [cell],
        "label": f"{prefix}：假设 {cell_name(cell, n)}={value}",
    }
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


def _explain_non_consecutive(events, data, n):
    detail = (f"{_names([data['a'], data['b']], n)} 共边，两数既不能相同，也不能相差 1。"
              "\n以下候选在另一格没有可配的数字：" + "；".join(_effect_lines(events, n)))
    return detail, _basic_visual(events, n)


def _explain_cage(events, data, n):
    cells = data["cells"]
    total = data["sum"]
    combos = data.get("combos") or []
    detail = f"笼 {total}（{len(cells)} 格，数字互不重复）：{_names(cells, n)}。\n"
    for a, b in data.get("consecutive_pairs", []):
        detail += f"这两格共边，不能同时填相差 1 的 {a} 和 {b}。\n"
    if combos:
        detail += f"当前可行的数字组合共 {len(combos)} 组：\n"
        for combo in combos[:8]:
            detail += f"  {{{_values(list(combo))}}}\n"
        if len(combos) > 8:
            detail += "  …\n"
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


def _explain_exact_digits(events, data, n):
    detail = f"{_names(data['cells'], n)} 必须恰好填入 {_values(data['digits'])}。"
    return "\n".join([detail, *_effect_lines(events, n)]), _basic_visual(events, n)


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
    cells = data.get("cells") or ([data["a"], data["b"]] if "a" in data else [])
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
    cells = data.get("cells") or ([data["a"], data["b"]] if "a" in data else [])
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
