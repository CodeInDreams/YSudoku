"""End-to-end pipeline: link -> puzzle -> rules -> reasoning path."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import llm, rulecache
from .model import Puzzle, parse_puzzle
from .rules import compile_spec, heuristic_spec, build_inventory
from .solve import Solver, audit_steps, check_solution, compare_with_solution
from .state import cell_name


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
            },
            "rules": {
                "source": self.source,
                "resolved": self.rules.describe(),
                "warnings": self.warnings,
                "spec": self.spec,
            },
            "initial": self.initial,
            "steps": [step.to_dict(n) for step in self.result.steps],
            "status": self.status,
            "message": self.message,
            "final": self.result.values,
            "solution_check": self.solution_check,
            "audit": self.audit,
        }


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
) -> Analysis:
    from .sudokupad import load

    data = load(target)
    puzzle = parse_puzzle(data, puzzle_id=_puzzle_id(target))
    inventory = build_inventory(puzzle)

    warnings: list[str] = []
    source = "heuristic"
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

    rules = compile_spec(puzzle, inventory, spec, source=source)
    warnings.extend(rules.warnings)

    solver = Solver(puzzle, rules, allow_chains=allow_chains)
    chaos = "chaos construction" in (puzzle.rules_text or "").lower()
    if chaos:
        return Analysis(
            puzzle=puzzle, spec=spec, rules=rules, result=type("R", (), {
                "steps": [], "values": solver.state.vals, "message": "",
            })(),
            initial=solver.initial, source=source,
            warnings=warnings + ["检测到 Chaos Construction（区域待定），P1 暂不支持，计划 P3 实现"],
            status="unsupported",
            message="混沌构造需要把区域也当作变量求解，属于 P3 范围",
        )

    result = solver.run(max_steps=max_steps)

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
                solver2 = Solver(puzzle, new_rules, allow_chains=allow_chains)
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

    status = result.status
    message = result.message
    solution_check = ""

    if status == "solved":
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


def _llm_spec(puzzle, inventory, config, warnings: list[str]):
    inventory_json = [element.to_json(puzzle.size) for element in inventory]
    feedback: list[dict] = []
    spec: dict = {"rules": [], "globals": []}
    rules = None
    validated = False
    for attempt in range(2):
        spec = llm.compile_rules(
            config, puzzle.rules_text, inventory_json, puzzle.size, previous=feedback
        )
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
