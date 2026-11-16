"""Local history of analysed puzzles (no cloud, no LLM)."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_MAX = 200


def _path() -> Path:
    return Path(os.environ.get("YSUDOKU_HISTORY", Path.cwd() / ".cache" / "history.json"))


def load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(entries: list[dict]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def record(target: str, analysis, demo: bool = False) -> None:
    entry = {
        "target": "" if demo else target,
        "demo": demo,
        "title": analysis.puzzle.title,
        "author": analysis.puzzle.author,
        "id": analysis.puzzle.puzzle_id,
        "status": analysis.status,
        "steps": len(analysis.result.steps),
        "source": analysis.source,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    key = (entry["demo"], entry["target"], entry["id"])
    with _LOCK:
        entries = load()
        entries = [e for e in entries
                   if (e.get("demo"), e.get("target"), e.get("id")) != key]
        entries.insert(0, entry)
        _save(entries[:_MAX])


def clear() -> None:
    with _LOCK:
        _save([])
