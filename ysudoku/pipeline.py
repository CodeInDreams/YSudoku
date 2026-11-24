"""End-to-end pipeline: link -> puzzle -> rules -> reasoning path."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import llm, rulecache
from .model import Puzzle, parse_puzzle
from .rules import (CompiledRules, build_inventory, compile_spec, heuristic_spec, paired_outside_choices,
                    with_paired_outside_choices)
from .chaos import check_chaos_solution, solve_chaos
from .solve import Solver, SolveResult, audit_steps, check_solution, compare_with_solution
from .state import Contradiction, cell_name
from .refutation_path import finish_regions, finish_with_refutations
from .narrate import Step


# Invalidate cached results when the solver's proof strategy changes.
ANALYSIS_VERSION = 36


def _requires_liar_cell_values(rules_text: str) -> bool:
    """Identify a declared cell modifier that needs a separate value domain."""
    return bool(
        re.search(r"\bliar\s+cells?\b", rules_text, re.IGNORECASE)
        and re.search(
            r"\b(?:real|effective)\s+values?\s+(?:(?:is|are)\s+different\s+from|differs?\s+from)"
            r"\s+(?:(?:its|their|the)\s+)?(?:written\s+)?digits?\b",
            rules_text, re.IGNORECASE,
        )
    )


@dataclass
class Analysis:
    puzzle: Puzzle
    spec: dict
    rules: object
    result: object
    initial: list[int]
    source: str = "heuristic"
    warnings: list[str] = field(default_factory=list)
    solution_check: str = ""
    audit: dict = field(default_factory=dict)
    status: str = "solved"
    message: str = ""
    chaos_regions: list = field(default_factory=list)
    clue_types: list = field(default_factory=list)
    demo: bool = False
    provenance: str = ""
    source_url: str = ""
    conflicts: list = field(default_factory=list)
    lang: str = "zh"
    effective_values: list[int] = field(default_factory=list)
    shades: list[int] = field(default_factory=list)

    def to_json(self, *, lang: str | None = None) -> dict:
        n = self.puzzle.size
        content_lang = "en" if (lang or self.lang) == "en" else "zh"
        return {
            "algo_version": ANALYSIS_VERSION,
            "lang": content_lang,
            "content_lang": content_lang,
            "puzzle": {
                "id": self.puzzle.puzzle_id,
                "title": self.puzzle.title,
                "author": self.puzzle.author,
                "size": n,
                "canvas_size": max(
                    [len((self.puzzle.raw or {}).get("cells") or [])]
                    + [len(row) for row in ((self.puzzle.raw or {}).get("cells") or [])]
                ) or n,
                "rules": self.puzzle.rules_text,
                "givens": [self.puzzle.givens.get(c, 0) for c in range(n * n)],
                "regions": self.puzzle.regions,
                "has_solution": bool(self.puzzle.solution),
                "outside": self.puzzle.has_outside_clues,
                "clues": [
                    {"side": c.side, "index": c.index, "value": c.value}
                    for c in self.puzzle.clues
                ],
            },
            "rules": {
                "source": self.source,
                "resolved": self.rules.describe(),
                "warnings": self.warnings,
                "spec": self.spec,
            },
            "initial": self.initial,
            "chaos_regions": self.chaos_regions,
            "demo": self.demo,
            "provenance": self.provenance,
            "source_url": self.source_url,
            "conflicts": self.conflicts,
            "constraints": [c.to_dict() for c in self.rules.constraints],
            "clue_types": self.clue_types,
            "rule_sheet": (
                f"/api/rulesheet/{Path(self.puzzle.rule_sheet).name}"
                if self.puzzle.rule_sheet else ""
            ),
            "steps": [step.to_dict(n, content_lang) for step in self.result.steps],
            "status": self.status,
            "message": self.message,
            "final": self.result.values,
            "effective_values": self.effective_values,
            "shades": self.shades,
            "solution_check": self.solution_check,
            "audit": self.audit,
        }


def _stirling2(n: int, k: int) -> int:
    if k <= 0 or k > n:
        return 0
    if k == 1 or k == n:
        return 1
    return k * _stirling2(n - 1, k) + _stirling2(n - 1, k - 1)


def _chaos_pattern_steps(puzzle, rules, state) -> list:
    """Truthful observation steps: constrain patterns, not individual cells."""
    quads = {
        frozenset(con.cells()): con
        for con in rules.constraints if con.kind == "quadruple"
    }
    steps = []
    index = 0
    for con in rules.constraints:
        if con.kind != "region_count":
            continue
        cells = con.cells()
        quad = quads.get(frozenset(cells))
        digits = "、".join(str(d) for d in quad.digits) if quad else ""
        patterns = sum(_stirling2(len(cells), k) for k in con.counts)
        counts = " 或 ".join(str(c) for c in con.counts)
        title = f"圈域模式：{len(cells)} 格跨 {counts} 个区域"
        detail = (
            f"这个圆周围的 {len(cells)} 格必须包含数字 {digits or '（未标注）'}；\n"
            f"区域计数要求它们跨 {counts} 个区域，因此区域划分只剩 {patterns} 类模式。\n"
            "结合其他线索、区域大小与连通性，可以继续判断哪些格必须同区或不同区。"
        )
        if con.repeat_witness:
            digit, copies = con.repeat_witness
            original = " 或 ".join(map(str, con.clue_counts))
            conclusion = (f"所以这 {len(cells)} 格两两不同区。"
                          if con.counts == [len(cells)] else
                          f"所以可行的区域数只剩 {counts}。" if con.counts else
                          "因此圈中的数字与区域数提示矛盾。")
            title = f"约束简化：{conclusion.rstrip('。')}"
            detail = (f"圈的区域提示原本允许 {original} 个区域。圈内有 {copies} 个 {digit}，"
                      f"而每个区域只能出现一次 {digit}，所以至少需要 {copies} 个区域。"
                      + conclusion)
        steps.append(Step(
            index=index, technique="chaos_pattern", tier=2,
            title=title, detail=detail, events=[],
            visual={"focus": cells, "groups": [{"cells": cells, "label": f"圈{index + 1}"}]},
            pre_dom=list(state.dom), pre_vals=list(state.vals),
            audit="unknown",
            narration={"cells": cells, "counts": con.counts},
        ))
        index += 1
    return steps


def _try_global(puzzle, rules, solver, source, warnings, time_limit, target, demo, lang="zh"):
    from . import global_clues
    if not global_clues.available():
        warnings.append("检测到盘外全局线索；安装可选依赖 ortools 后可启用 CP-SAT 全局求解")
        return None
    try:
        result = global_clues.solve(puzzle, time_limit=time_limit)
    except Exception as exc:  # noqa: BLE001 - optional solver
        warnings.append(f"全局线索求解失败：{exc}")
        return None
    if not result or result.get("status") != "solved":
        status = result.get("status") if result else "no result"
        warnings.append(f"全局线索求解未完成（{status}）")
        return None
    grid = result["grid"]
    values = [v for row in grid for v in row]
    types = result.get("types") or []
    errors = check_solution(puzzle, rules, values)
    errors += global_clues.verify(puzzle, values, types)
    if errors:
        warnings.append("全局解校验失败：" + "；".join(errors[:3]))
        return None
    diff = compare_with_solution(puzzle, values)
    clean = [
        w for w in warnings
        if "Full Rank 约束暂未实现" not in w
        and "未被任何规则使用" not in w
        and "暂不自动映射" not in w
    ]
    rank_count = types.count("R")
    text_low = (puzzle.rules_text or "").lower()
    conflicts = []
    if ("x-sum" in text_low or "x sum" in text_low) and (puzzle.raw or {}).get("arrows"):
        conflicts = [{
            "id": "xsum",
            "question": "这题的盘外 X-Sums 采用哪种识别？",
            "options": [
                {"id": "compiler", "label": "编译器箭头识别（推荐）"},
                {"id": "llm", "label": "LLM 规则识别"},
            ],
        }]
    return Analysis(
        puzzle=puzzle,
        conflicts=conflicts,
        lang=(lang or "zh").lower()[:2],
        spec={"rules": [], "globals": [], "notes": "cp-sat"},
        rules=rules,
        result=SolveResult("solved", [], values),
        initial=solver.initial,
        source=source,
        warnings=clean + [
            f"CP-SAT 全局求解：{rank_count} 条 Full Rank / {len(types) - rank_count} 条 X-Sums",
        ],
        status="solved-global",
        message="全局盘外线索由 CP-SAT 求解（Full Rank / X-Sums / 类型配对）",
        clue_types=types,
        solution_check=diff or "全局线索自检通过",
        demo=demo,
        provenance=(
            f"真实题示例：{puzzle.title} — {puzzle.author}"
            if demo and puzzle.source_url
            else "内置生成示例（程序生成，非已发表题目）"
            if demo
            else str(target)
        ),
        source_url=puzzle.source_url or (str(target) if str(target).startswith("http") else ""),
    )


def _puzzle_id(target: str) -> str:
    target = target.strip()
    if target.startswith("http"):
        from urllib.parse import urlparse
        return urlparse(target).path.strip("/").split("/")[-1]
    return ""


def analyze(
    target: str,
    use_llm: bool = True,
    spec_override: dict | None = None,
    do_audit: bool = False,
    max_steps: int = 4000,
    llm_config: "llm.LLMConfig | None" = None,
    use_cache: bool = True,
    save_rules: bool = False,
    allow_chains: bool = False,
    chaos_time_limit: float = 8.0,
    demo: bool = False,
    use_global: bool = False,
    rule_prompt: str = "",
    rule_mode: str = "auto",
    lang: str = "zh",
    global_time_limit: float = 60.0,
    notes: str = "",
    on_rules=None,
    on_step=None,
    on_puzzle=None,
    load_puzzle=None,
) -> Analysis:
    from .sudokupad import load

    data = (load_puzzle or load)(target)
    puzzle = parse_puzzle(data, puzzle_id=_puzzle_id(target))
    if target.startswith("https://sudokupad.app/"):
        puzzle.source_url = target
    elif not puzzle.source_url and target.isalnum():
        puzzle.source_url = "https://sudokupad.app/" + target
    if on_puzzle:
        puzzle.rule_sheet = on_puzzle(puzzle) or ""
    inventory = build_inventory(puzzle)
    from .shaded_inversions import recognizes_shaded_inversions, solve_shaded
    if puzzle.clues and not notes.strip() and recognizes_shaded_inversions(puzzle.rules_text):
        spec = {"rules": [], "globals": [], "model": "shaded_inversions"}
        rules = CompiledRules([], source="heuristic")
        english = lang == "en"
        rules.resolved = [
            {"kind": "two_connected_shades", "label": "Two connected colours, no monochrome 2×2"
             if english else "双色正交连通，禁止单色 2×2", "count": 1, "elements": []},
            {"kind": "shaded_inversions", "label": "Shaded inversions"
             if english else "深色逆序对", "count": len(puzzle.clues),
             "elements": [f"clue:{i}" for i in range(len(puzzle.clues))]},
        ]
        if on_rules is not None:
            try:
                on_rules(rules.describe())
            except Exception:
                pass
        solver = Solver(puzzle, rules, allow_chains=allow_chains, on_step=on_step)
        result, shades = solve_shaded(solver, max_steps)
        check = ""
        if result.status == "solved" and puzzle.solution:
            check = compare_with_solution(puzzle, result.values) or "与题面内置答案一致"
        return Analysis(puzzle=puzzle, spec=spec, rules=rules, source=rules.source,
                        result=result, initial=solver.initial, status=result.status,
                        message=result.message, solution_check=check, source_url=puzzle.source_url,
                        lang=lang, shades=shades)
    if _requires_liar_cell_values(puzzle.rules_text or ""):
        from .dual_values import liar_value_spec, solve_dual
        spec = liar_value_spec(puzzle, inventory) if not notes.strip() else None
        if spec is not None:
            rules = compile_spec(puzzle, inventory, spec)
            if len(rules.constraints) == len(spec["rules"]):
                rules.resolved = [r for r in rules.resolved if r["kind"] != "_ignored"]
                rules.resolved.insert(0, {"kind": "liar_values",
                                         "label": "说谎格（填写数字与实际值）" if not lang.startswith("en")
                                         else "Liar cells (written digits and effective values)",
                                         "count": puzzle.size, "elements": []})
                if on_rules is not None:
                    try:
                        on_rules(rules.describe())
                    except Exception:
                        pass
                result, initial, effective = solve_dual(
                    puzzle, rules.constraints, max_steps, allow_chains=allow_chains, on_step=on_step,
                )
                check = ""
                if result.status == "solved" and puzzle.solution:
                    check = compare_with_solution(puzzle, result.values) or "与题面内置答案一致"
                return Analysis(
                    puzzle=puzzle, spec=spec, rules=rules, source="heuristic",
                    result=result, initial=initial, status=result.status, message=result.message,
                    source_url=puzzle.source_url, lang=lang, solution_check=check,
                    effective_values=effective,
                )
        message = (
            "Liar cells require separate domains for written digits and effective values. "
            "This rule is not supported yet."
            if lang == "en" else
            "说谎格要求把盘面数字和实际值分别推理，当前求解器暂不支持这类规则。"
        )
        rules = CompiledRules([])
        solver = Solver(puzzle, rules)
        if on_rules is not None:
            try:
                on_rules([])
            except Exception:
                pass
        return Analysis(
            puzzle=puzzle, spec={"rules": [], "globals": []}, rules=rules, source="heuristic",
            result=SolveResult("unsupported", [], []), initial=solver.initial,
            status="unsupported", message=message, warnings=[message],
            source_url=puzzle.source_url, lang=lang,
        )

    warnings: list[str] = []
    source = "heuristic"
    original_rules = puzzle.rules_text or ""
    notes = (notes or "").strip()
    if notes:
        puzzle.rules_text = (
            original_rules
            + "\n\n=== USER SUPPLEMENT (treat as authoritative rule text) ===\n"
            + notes
        )
    text_low = (puzzle.rules_text or "").lower()
    paired_choices = paired_outside_choices(puzzle, inventory)
    arrow_xsum = (("x-sum" in text_low or "x sum" in text_low or "xsum" in text_low)
                  and bool((puzzle.raw or {}).get("arrows")))
    if arrow_xsum and rule_mode != "llm":
        spec_override = None
        use_llm = False
    if paired_choices and not notes and rule_mode != "llm":
        use_llm = False
    fingerprint = rulecache.fingerprint(puzzle, inventory, rule_prompt)
    cached = None
    if spec_override is None and use_llm and use_cache:
        cached = rulecache.load(puzzle, inventory, fingerprint)

    if not puzzle.regions:
        warnings.append("题目没有区域定义，按标准宫处理（混沌构造暂不支持）")

    if spec_override is not None:
        spec = spec_override
        source = "manual"
    elif cached is not None:
        spec = cached["spec"]
        source = "cache"
        warnings.append(f"规则来自缓存：{cached.get('_path', '')}")
    elif use_llm and puzzle.rules_text:
        config = llm_config or llm.LLMConfig.from_env()
        if config is None:
            warnings.append("未配置 LLM（SUDOKU_LLM_API_KEY），使用本地启发式规则识别")
            spec = heuristic_spec(puzzle, inventory)
        else:
            try:
                spec, source, validated = _llm_spec(puzzle, inventory, config, warnings, rule_prompt)
                if validated:
                    try:
                        rulecache.save(
                            puzzle, inventory, fingerprint, spec,
                            model=config.model, shared=save_rules,
                        )
                    except OSError as exc:
                        warnings.append(f"规则缓存写入失败：{exc}")
            except llm.LLMError as exc:
                warnings.append(f"LLM 规则编译失败，改用启发式：{exc}")
                spec = heuristic_spec(puzzle, inventory)
    else:
        spec = heuristic_spec(puzzle, inventory)

    spec = with_paired_outside_choices(spec, paired_choices)
    puzzle.rules_text = original_rules
    rules = compile_spec(puzzle, inventory, spec, source=source)
    warnings.extend(spec.get("warnings", []))
    warnings.extend(rules.warnings)
    if on_rules is not None:
        try:
            on_rules(rules.describe())
        except Exception:
            pass

    solver = Solver(puzzle, rules, allow_chains=allow_chains, on_step=on_step,
                           solution=puzzle.solution)

    clue_ids = {f"clue:{i}" for i in range(len(puzzle.clues))}
    used_ids = {
        eid for rule in rules.resolved
        if rule.get("kind") != "_ignored"
        for eid in rule.get("elements", [])
    }
    mapped_clues = clue_ids & used_ids
    if clue_ids and not mapped_clues:
        if use_global:
            attempted = _try_global(puzzle, rules, solver, source, warnings,
                                    global_time_limit, target, demo, lang=lang)
            if attempted is not None:
                return attempted
        return Analysis(
            puzzle=puzzle, spec=spec, rules=rules,
            result=SolveResult("unsupported", [], []),
            initial=solver.initial, source=source,
            warnings=warnings + [
                f"检测到 {len(clue_ids)} 个盘外提示，但当前规则没有使用任何一条",
            ],
            status="unsupported",
            source_url=puzzle.source_url or (str(target) if str(target).startswith("http") else ""),
            message="盘外提示未被规则映射（可能是 Full Rank / X-Sums 的未知类型配对，或尚未实现的盘外线索）",
        )
    if clue_ids - mapped_clues:
        warnings.append(f"{len(clue_ids - mapped_clues)} 个盘外提示未被规则使用")
    rules_low = (puzzle.rules_text or "").lower()
    if puzzle.is_chaos:
        exotic = any(word in rules_low for word in (
            "trisection", "unbalanced", "region count", "region-count",
            "how many cells of its own region", "block vision",
            "region borders", "consecutive cells immediately following",
        ))
        has_region_rules = any(c.kind == "region_count" for c in rules.constraints)
        if exotic and not has_region_rules:
            return Analysis(
                puzzle=puzzle, spec=spec, rules=rules, result=SolveResult("unsupported", [], []),
                initial=solver.initial, source=source,
                warnings=warnings + ["检测到作者自定义的区域计数规则，首个混沌版本暂不支持"],
                status="unsupported",
                source_url=puzzle.source_url or (str(target) if str(target).startswith("http") else ""),
                message="检测到作者自定义的区域语义（区域计数/视野/边界），首个混沌版本暂不支持",
            )
        pattern_steps = _chaos_pattern_steps(puzzle, rules, solver.state)
        if solver.invalid or any(c.kind == "region_count" and not c.counts for c in rules.constraints):
            return Analysis(puzzle=puzzle, spec=spec, rules=rules, source=source,
                            initial=solver.initial, status="invalid", warnings=warnings,
                            result=SolveResult("invalid", pattern_steps, solver.state.vals),
                            message=solver.invalid or "圈内重复数字与区域数提示矛盾")
        try:
            solver.steps = pattern_steps
            solver, fragments = finish_regions(
                solver, rules, lambda state: _chaos_pattern_steps(puzzle, rules, state),
            )
            pattern_steps = solver.steps
        except Contradiction as exc:
            return Analysis(puzzle=puzzle, spec=spec, rules=rules, source=source,
                            initial=solver.initial, status="invalid", warnings=warnings,
                            result=SolveResult("invalid", pattern_steps, solver.state.vals),
                            source_url=puzzle.source_url, message=str(exc))
        groups = list(fragments.groups.values())
        if solver.state.solved and all(len(group) == puzzle.size for group in groups):
            regions = [sorted(group) for group in groups]
            if not check_chaos_solution(puzzle, rules.constraints, solver.state.vals, regions):
                return Analysis(puzzle=puzzle, spec=spec, rules=rules, source=source,
                                initial=solver.initial, status="solved", warnings=warnings,
                                result=SolveResult("solved", pattern_steps, solver.state.vals),
                                source_url=puzzle.source_url, chaos_regions=regions,
                                solution_check="区域和数字均通过校验")
        chaos_result = solve_chaos(puzzle, rules.constraints, time_limit=chaos_time_limit,
                                  fragments=fragments, domains=solver.state.dom)
        if chaos_result.status == "solved":
            errors = check_chaos_solution(puzzle, rules.constraints, chaos_result.values, chaos_result.regions)
            return Analysis(
                puzzle=puzzle, spec=spec, rules=rules,
                result=SolveResult("solved", pattern_steps, chaos_result.values),
                initial=solver.initial, source=source,
                warnings=warnings + [chaos_result.message, "混沌构造由搜索求解，不是逐步人类推理"],
                status="solved-search",
                message=chaos_result.message,
                chaos_regions=chaos_result.regions, source_url=puzzle.source_url,
                solution_check="；".join(errors[:3]) if errors else "混沌解自检通过",
            )
        return Analysis(
            puzzle=puzzle, spec=spec, rules=rules,
            result=SolveResult("stuck", pattern_steps, solver.state.vals),
            initial=solver.initial, source=source,
            warnings=warnings + [chaos_result.message],
            status="stuck",
            source_url=puzzle.source_url, message=f"混沌搜索未完成：{chaos_result.message}",
        )

    result = solver.run(max_steps=max_steps, candidate_maps=not allow_chains)

    if result.status == "stuck" and puzzle.clues and use_global:
        attempted = _try_global(puzzle, rules, solver, source, warnings,
                                global_time_limit, target, demo, lang=lang)
        if attempted is not None:
            return attempted

    # If the trusted rules stall, ask the LLM to re-read the rule text and fix
    # the spec (never shown the solution, only the diagnostics).
    if (result.status == "stuck" and use_llm and source in ("llm", "cache")
            and puzzle.rules_text):
        config = llm_config or llm.LLMConfig.from_env()
        if config is not None:
            diagnostics = {
                "steps": len(result.steps),
                "message": result.message,
                "tried": sorted({step.technique for step in result.steps}),
                "unused_elements": [w for w in warnings if "未被任何规则使用" in w][:10],
                "warnings": [w for w in warnings if "未被任何规则使用" not in w][-6:],
            }
            repaired = _llm_repair(puzzle, inventory, config, spec, diagnostics, warnings)
            if repaired is not None:
                new_spec, new_rules = repaired
                solver2 = Solver(puzzle, new_rules, allow_chains=allow_chains,
                                 solution=puzzle.solution,
                                 on_step=on_step)
                result2 = solver2.run(max_steps=max_steps, candidate_maps=not allow_chains)
                if (result2.status == "solved"
                        or len(result2.steps) > len(result.steps)):
                    rules, result, solver, spec = new_rules, result2, solver2, new_spec
                    source = "llm-repair"
                    try:
                        rulecache.save(puzzle, inventory, fingerprint, spec,
                                       model=config.model, shared=save_rules)
                    except OSError:
                        pass

    if result.status == "stuck" and allow_chains:
        solver, result = finish_with_refutations(solver, result, max_steps, warnings)

    for constraint in rules.constraints:
        support = getattr(constraint, "last_result", None)
        if support is not None and support.unresolved:
            warnings.append(
                f"通用局部支持有 {len(support.unresolved)} 个候选未能完整检查"
            )
            break

    status = result.status
    message = result.message
    solution_check = ""

    if status in ("solved", "solved-search"):
        errors = check_solution(puzzle, rules, result.values)
        if errors:
            status = "invalid-rules"
            message = "；".join(errors[:5])
        else:
            diff = compare_with_solution(puzzle, result.values)
            if diff:
                solution_check = diff
            else:
                solution_check = "与题面内置答案一致" if puzzle.solution else "无内置答案可比对"

    audit: dict = {}
    if do_audit and result.steps:
        audit = audit_steps(puzzle, rules, result.steps)

    text_low = (puzzle.rules_text or "").lower()
    conflicts = []
    if ("x-sum" in text_low or "x sum" in text_low) and (puzzle.raw or {}).get("arrows"):
        conflicts = [{
            "id": "xsum",
            "question": "这题的盘外 X-Sums 采用哪种识别？",
            "options": [
                {"id": "compiler", "label": "编译器箭头识别（推荐）"},
                {"id": "llm", "label": "LLM 规则识别"},
            ],
        }]
    return Analysis(
        puzzle=puzzle,
        conflicts=conflicts,
        lang=(lang or "zh").lower()[:2],
        demo=demo,
        provenance=(
            f"真实题示例：{puzzle.title} — {puzzle.author}"
            if demo and puzzle.source_url
            else "内置生成示例（程序生成，非已发表题目）"
            if demo
            else target
        ),
        source_url=puzzle.source_url or (target if str(target).startswith("http") else ""),
        spec=spec,
        rules=rules,
        result=result,
        initial=solver.initial,
        source=source,
        warnings=warnings,
        solution_check=solution_check,
        audit=audit,
        status=status,
        message=message,
    )


def _llm_repair(puzzle, inventory, config, spec, diagnostics, warnings):
    inventory_json = [element.to_json(puzzle.size) for element in inventory]
    raw = puzzle.raw or {}
    if raw.get("arrows"):
        from .arrow_geometry import geometry_payload
        inventory_json.append({
            "id": "_arrow_geometry", "kind": "arrow_geometry",
            "geometry": geometry_payload(puzzle, raw.get("arrows") or [],
                                          raw.get("underlays") or []),
        })
    try:
        new_spec = llm.repair_rules(config, puzzle.rules_text, inventory_json, spec, diagnostics,
                                    image_uri=_rule_image(puzzle))
    except llm.LLMError as exc:
        warnings.append(f"LLM 规则修复失败：{exc}")
        return None
    new_spec = with_paired_outside_choices(new_spec, paired_outside_choices(puzzle, inventory))
    new_rules = compile_spec(puzzle, inventory, new_spec, source="llm-repair")
    if new_rules.errors:
        warnings.append("LLM 修复后的规则无法编译：" + "；".join(new_rules.errors[:3]))
        return None
    if puzzle.solution:
        errors = check_solution(puzzle, new_rules, puzzle.solution)
        if errors:
            warnings.append("LLM 修复后的规则仍与官方答案冲突：" + "；".join(errors[:3]))
            return None
    return new_spec, new_rules


def rulesheet_dir():
    return rulecache.cache_dir().parent / "rulesheets"


def save_rulesheet(png):
    from .live import FRAME_RENDERER_VERSION
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or not png.endswith(b"IEND\xaeB`\x82"):
        raise ValueError("初始帧 PNG 不完整")
    path = rulesheet_dir() / f"r{FRAME_RENDERER_VERSION}-{hashlib.sha256(png).hexdigest()}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return str(path)


def initial_screenshot(url, size, frame=None, *, crop=False):
    from urllib.parse import urlsplit
    from . import live
    if urlsplit(url).hostname != "sudokupad.app" or urlsplit(url).scheme != "https":
        raise llm.LLMError("缺少可用于截取初始盘面的 SudokuPad 链接")
    try:
        png = frame.read_bytes() if frame is not None and frame.is_file() else live.initial_frame(url, size, crop=crop)
        return save_rulesheet(png)
    except (OSError, ValueError, live.LiveError) as exc:
        raise llm.LLMError(f"无法取得 SudokuPad 初始盘面截图：{exc}") from exc


def _rule_image(puzzle):
    if not puzzle.rule_sheet:
        puzzle.rule_sheet = initial_screenshot(puzzle.source_url, puzzle.size)
    png = Path(puzzle.rule_sheet).read_bytes()
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _apply_arrow_geometry(puzzle, spec, warnings):
    items = spec.get("arrows")
    if not items:
        return
    from .arrow_geometry import validate_all
    try:
        rules = validate_all(items, puzzle.size)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"LLM 箭头几何无效，已忽略：{exc}")
        return
    for index, rule in enumerate(rules):
        spec.setdefault("rules", []).append({
            "kind": "x_sums",
            "elements": [f"clue:{min(index, max(0, len(puzzle.clues) - 1))}"],
            "sum": rule["total"],
            "cells": rule["cells"],
            "side": "arrow",
        })


def _llm_spec(puzzle, inventory, config, warnings: list[str], rule_prompt=""):
    inventory_json = [element.to_json(puzzle.size) for element in inventory]
    raw = puzzle.raw or {}
    if raw.get("arrows"):
        from .arrow_geometry import geometry_payload
        inventory_json.append({
            "id": "_arrow_geometry", "kind": "arrow_geometry",
            "geometry": geometry_payload(puzzle, raw.get("arrows") or [],
                                          raw.get("underlays") or []),
        })
    image_uri = _rule_image(puzzle)
    feedback: list[dict] = []
    spec: dict = {"rules": [], "globals": []}
    rules = None
    validated = False
    for attempt in range(2):
        spec = llm.compile_rules(
            config, puzzle.rules_text, inventory_json, puzzle.size,
            previous=feedback, image_uri=image_uri, hint=rule_prompt,
        )
        _apply_arrow_geometry(puzzle, spec, warnings)
        spec = with_paired_outside_choices(spec, paired_outside_choices(puzzle, inventory))
        rules = compile_spec(puzzle, inventory, spec, source="llm")
        errors = rules.errors
        if not errors and puzzle.solution:
            errors = check_solution(puzzle, rules, puzzle.solution)
        if not errors:
            return spec, "llm", True
        if attempt == 0:
            warnings.append("LLM 规则校验失败，正在自动修正：" + "；".join(errors[:4]))
            feedback = [
                {"role": "assistant", "content": json.dumps(spec, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        "Rule validation found these errors: "
                        + "; ".join(errors[:10])
                        + ". Fix the rule spec (wrong element mapping, wrong variant, "
                        "missing/extra rules) and reply with JSON only."
                    ),
                },
            ]
    if rules.errors:
        raise llm.LLMError("；".join(rules.errors[:3]))
    warnings.append("LLM 规则仍未通过内置答案校验")
    return spec, "llm", validated
