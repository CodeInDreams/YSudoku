"""Cache of compiled rule specs.

Two layers:

* ``rules/<key>.json``   – shared, committed specs (curated / contributed)
* ``.cache/rules/<key>.json`` – local, written automatically after an LLM compile

A spec is only reused when the fingerprint of (rules text + element inventory)
still matches, so editing a puzzle or changing the decoder invalidates it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

VERSION = 1

def cache_dir() -> Path:
    root = Path(os.environ.get("YSUDOKU_CACHE", Path.cwd() / ".cache"))
    return root / "rules"


def shared_dir() -> Path:
    return Path(os.environ.get("YSUDOKU_RULES", Path.cwd() / "rules"))


def fingerprint(puzzle, inventory, rule_prompt="") -> str:
    payload = json.dumps(
        {
            "size": puzzle.size,
            "rules": puzzle.rules_text,
            "elements": [element.to_json(puzzle.size) for element in inventory],
            **({"hint": rule_prompt} if rule_prompt else {}),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def key_for(puzzle) -> str:
    raw = puzzle.puzzle_id or ""
    raw = re.sub(r"[^A-Za-z0-9_.-]", "_", raw)[:80]
    return raw or "h_" + fingerprint(puzzle, [])[:16]


def _path(puzzle, base: Path) -> Path:
    return base / (key_for(puzzle) + ".json")


def load(puzzle, inventory, fp: str) -> dict | None:
    for base in (shared_dir(), cache_dir()):
        path = _path(puzzle, base)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("version") != VERSION or data.get("fingerprint") != fp:
            continue
        if isinstance(data.get("spec"), dict):
            data["_path"] = str(path)
            return data
    return None


def save(puzzle, inventory, fp: str, spec: dict, *, model: str = "", shared: bool = False) -> Path:
    base = shared_dir() if shared else cache_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = _path(puzzle, base)
    payload = {
        "version": VERSION,
        "id": puzzle.puzzle_id,
        "title": puzzle.title,
        "fingerprint": fp,
        "model": model,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "spec": spec,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def summary() -> dict:
    def count(base: Path) -> int:
        try:
            return len(list(base.glob("*.json")))
        except OSError:
            return 0

    return {"shared": count(shared_dir()), "cached": count(cache_dir())}
