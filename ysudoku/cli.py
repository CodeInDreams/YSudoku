"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from .pipeline import analyze


def _print_text(analysis) -> None:
    p = analysis.puzzle
    print(f"\n{p.title}  —  {p.author}   [{p.size}×{p.size}]")
    print("=" * 64)
    for rule in analysis.rules.describe():
        if rule.get("kind") == "_ignored":
            continue
        print(f"  规则  {rule.get('label', rule['kind']):<22} ×{rule.get('count', 1)}")
    if analysis.warnings:
        print("  提示：")
        for warning in analysis.warnings[:6]:
            print(f"    - {warning}")
    print("-" * 64)
    for step in analysis.result.steps:
        mark = {"ok": "✓", "bad": "✗", "unknown": "?"}.get(step.audit, " ")
        print(f"\n[{step.index + 1:>3}] {mark} {step.title}  (T{step.tier})")
        for line in step.detail.splitlines():
            print("      " + line)
    print("\n" + "=" * 64)
    print(f"状态：{analysis.status}  步数：{len(analysis.result.steps)}  {analysis.message}")
    if analysis.solution_check:
        print(f"校验：{analysis.solution_check}")
    if analysis.audit:
        print(f"审计：{analysis.audit}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ysudoku",
        description="把 SudokuPad 变形数独拆成可解释的推理步骤",
    )
    parser.add_argument("target", nargs="?", help="SudokuPad 链接 / id / 本地 JSON")
    parser.add_argument("--web", action="store_true", help="启动本地 Web 界面")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-llm", action="store_true", help="不使用 LLM，走本地启发式")
    parser.add_argument("--audit", action="store_true", help="用穷举反证校验每一步")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--no-cache", action="store_true", help="跳过规则缓存")
    parser.add_argument("--save-rules", action="store_true", help="把编译出的规则写入 rules/ 共享目录")
    parser.add_argument("--allow-chains", action="store_true", help="允许反证（试探）作为最后手段，步骤会标注 T4")
    args = parser.parse_args(argv)

    if args.web or not args.target:
        from .server import run
        run(args.host, args.port)
        return 0

    analysis = analyze(
        args.target,
        use_llm=not args.no_llm,
        do_audit=args.audit,
        use_cache=not args.no_cache,
        save_rules=args.save_rules,
        allow_chains=args.allow_chains,
    )
    if args.json:
        print(json.dumps(analysis.to_json(), ensure_ascii=False, indent=1))
    else:
        _print_text(analysis)
    return 0


if __name__ == "__main__":
    sys.exit(main())
