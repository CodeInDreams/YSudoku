"""End-to-end pipeline: link -> puzzle -> rules -> reasoning path."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import llm, rulecache
from .model import Puzzle, parse_puzzle
from .rules import compile_spec, heuristic_spec, build_inventory
from .chaos import check_chaos_solution, solve_chaos
from .solve import Solver, SolveResult, audit_steps, check_solution, compare_with_solution
from .state import cell_name
from .narrate import Step


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

    def to_json(self) -> dict:
        n = self.puzzle.size
        return {
            "puzzle": {
                "id": self.puzzle.puzzle_id,
                "title": self.puzzle.title,
                "author": self.puzzle.author,
                "size": n,
                "rules": self.puzzle.rules_text,
                "givens": [self.puzzle.givens.get(c, 0) for c in range(n * n)],
                "regions": self.puzzle.regions,
                "has_solution": bool(self.puzzle.solution),
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
            "constraints": [c.to_dict() for c in self.rules.constraints],
            "clue_types": self.clue_types,
            "rule_sheet": (
                f"/api/rulesheet/{Path(self.puzzle.rule_sheet).name}"
                if self.puzzle.rule_sheet else ""
            ),
            "steps": [step.to_dict(n) for step in self.result.steps],
            "status": self.status,
            "message": self.message,
            "final": self.result.values,
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
            "这一步只缩小“区域划分模式”的范围，还不能确定任何一格属于哪个区域；\n"
            "要删候选或定区域，需要对“同区/不同区”做假设并传播矛盾。"
        )
        steps.append(Step(
            index=index, technique="chaos_pattern", tier=2,
            title=title, detail=detail, events=[],
            visual={"focus": cells, "groups": [{"cells": cells, "label": f"圈{index + 1}"}]},
            pre_dom=list(state.dom), pre_vals=list(state.vals),
            audit="unknown",
        ))
        index += 1
    return steps


def _try_global(puzzle, rules, solver, source, warnings, time_limit, target, demo):
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
    return Analysis(
        puzzle=puzzle,
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
    use_global: bool = True,
    global_time_limit: float = 60.0,
    notes: str = "",
    on_rules=None,
    on_step=None,
) -> Analysis:
    from .sudokupad import load

    data = load(target)
    puzzle = parse_puzzle(data, puzzle_id=_puzzle_id(target))
    inventory = build_inventory(puzzle)

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
    fingerprint = rulecache.fingerprint(puzzle, inventory)
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
                spec, source, validated = _llm_spec(puzzle, inventory, config, warnings)
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
                                    global_time_limit, target, demo)
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
            message="盘外提示未被规则映射（可能是 Full Rank / X-Sums 的未知类型配对，或尚未实现的盘外线索）",
        )
    if clue_ids - mapped_clues:
        warnings.append(f"{len(clue_ids - mapped_clues)} 个盘外提示未被规则使用")
    rules_low = (puzzle.rules_text or "").lower()
    chaos = any(key in rules_low for key in (
        "chaos construction", "chaos sudoku", "regions are hidden",
        "hidden regions", "regions must be determined",
    ))
    if chaos:
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
                message="检测到作者自定义的区域语义（区域计数/视野/边界），首个混沌版本暂不支持",
            )
        pattern_steps = _chaos_pattern_steps(puzzle, rules, solver.state)
        chaos_result = solve_chaos(puzzle, rules.constraints, time_limit=chaos_time_limit)
        if chaos_result.status == "solved":
            errors = check_chaos_solution(puzzle, rules.constraints, chaos_result.values, chaos_result.regions)
            return Analysis(
                puzzle=puzzle, spec=spec, rules=rules,
                result=SolveResult("solved", pattern_steps, chaos_result.values),
                initial=solver.initial, source=source,
                warnings=warnings + [chaos_result.message, "混沌构造由搜索求解，不是逐步人类推理"],
                status="solved-search",
                message=chaos_result.message,
                chaos_regions=chaos_result.regions,
                solution_check="；".join(errors[:3]) if errors else "混沌解自检通过",
            )
        return Analysis(
            puzzle=puzzle, spec=spec, rules=rules,
            result=SolveResult("stuck", pattern_steps, solver.state.vals),
            initial=solver.initial, source=source,
            warnings=warnings + [chaos_result.message],
            status="stuck",
            message=f"混沌搜索未完成：{chaos_result.message}",
        )

    result = solver.run(max_steps=max_steps)

    if result.status == "stuck" and puzzle.clues and use_global:
        attempted = _try_global(puzzle, rules, solver, source, warnings,
                                global_time_limit, target, demo)
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
                result2 = solver2.run(max_steps=max_steps)
                if (result2.status == "solved"
                        or len(result2.steps) > len(result.steps)):
                    rules, result, solver, spec = new_rules, result2, solver2, new_spec
                    source = "llm-repair"
                    try:
                        rulecache.save(puzzle, inventory, fingerprint, spec,
                                       model=config.model, shared=save_rules)
                    except OSError:
                        pass

    if result.status == "stuck":
        import time as _time
        deadline = _time.time() + 25.0
        while result.status == "stuck" and _time.time() < deadline:
            step = solver.contradiction_step(deadline)
            if step is None:
                break
            result = solver.run(max_steps=max_steps)
        if result.status == "stuck":
            warnings.append("反证尝试未能在预算内找到可排除的候选")

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

    return Analysis(
        puzzle=puzzle,
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
    try:
        new_spec = llm.repair_rules(config, puzzle.rules_text, inventory_json, spec, diagnostics)
    except llm.LLMError as exc:
        warnings.append(f"LLM 规则修复失败：{exc}")
        return None
    new_rules = compile_spec(puzzle, inventory, new_spec, source="llm-repair")
    if puzzle.solution:
        errors = check_solution(puzzle, new_rules, puzzle.solution)
        if errors:
            warnings.append("LLM 修复后的规则仍与官方答案冲突：" + "；".join(errors[:3]))
            return None
    return new_spec, new_rules


def _rule_image(puzzle, inventory, warnings: list[str]):
    try:
        from .rulesheet import legend_text, render
        payload = [[e.id, e.kind, e.cells, e.attrs or {}] for e in inventory]
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        path = Path(".cache") / "rulesheets" / f"{puzzle.puzzle_id or 'puzzle'}-{digest}.png"
        legend = render(puzzle, inventory, path)
        uri = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
        return uri, legend_text(puzzle, inventory, legend), path
    except Exception as exc:  # noqa: BLE001 - the sheet is an optional aid
        warnings.append(f"规则图生成失败，改用纯文本：{exc}")
        return None, None, None


def _llm_spec(puzzle, inventory, config, warnings: list[str]):
    inventory_json = [element.to_json(puzzle.size) for element in inventory]
    image_uri, legend, sheet_path = _rule_image(puzzle, inventory, warnings)
    if sheet_path is not None:
        puzzle.rule_sheet = str(sheet_path)
    feedback: list[dict] = []
    spec: dict = {"rules": [], "globals": []}
    rules = None
    validated = False
    for attempt in range(2):
        try:
            spec = llm.compile_rules(
                config, puzzle.rules_text, inventory_json, puzzle.size,
                previous=feedback, image_uri=image_uri, legend=legend,
            )
        except llm.LLMError as exc:
            if image_uri and "image" in str(exc).lower():
                warnings.append("模型不支持视觉输入，退回文本规则表")
                spec = llm.compile_rules(
                    config, puzzle.rules_text, inventory_json, puzzle.size,
                    previous=feedback,
                )
            else:
                raise
        rules = compile_spec(puzzle, inventory, spec, source="llm")
        if not puzzle.solution:
            return spec, "llm", True
        errors = check_solution(puzzle, rules, puzzle.solution)
        if not errors:
            return spec, "llm", True
        if attempt == 0:
            warnings.append("LLM 规则与内置答案冲突，正在自动修正：" + "；".join(errors[:4]))
            feedback = [
                {"role": "assistant", "content": json.dumps(spec, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        "The official solution violates these constraints: "
                        + "; ".join(errors[:10])
                        + ". Fix the rule spec (wrong element mapping, wrong variant, "
                        "missing/extra rules) and reply with JSON only."
                    ),
                },
            ]
    warnings.append("LLM 规则仍未通过内置答案校验")
    return spec, "llm", validated
