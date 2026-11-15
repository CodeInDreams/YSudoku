"""Loading puzzles from SudokuPad links."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .decode import decode_payload

API_URL = "https://sudokupad.app/api/puzzle/{id}"
LEGACY_URL = "https://sudokupad.svencodes.com/ctclegacy/{id}"
CACHE_DIR = Path(os.environ.get("SUDOKU_EXPLAIN_CACHE", Path.cwd() / ".cache"))
CACHE_VERSION = 2
UA = "sudoku-explain/0.1 (+https://logic-masters.de)"


class LoadError(RuntimeError):
    pass


def _http_get(url: str, timeout: float = 25.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _extract_target(target: str) -> tuple[str, str]:
    """Return (kind, value) where kind is id | payload | file | json."""
    target = target.strip()
    if not target:
        raise LoadError("链接为空")

    if target.startswith("{"):
        return "json", target
    if re.match(r"^(scl|ctc|scf)", target):
        return "payload", target
    if re.match(r"^(fpuz|fpuzzles)", target):
        raise LoadError("暂不支持 f-puzzles 格式（P2 计划）")

    if target.startswith("http://") or target.startswith("https://"):
        parsed = urlparse(target)
        query = parse_qs(parsed.query)
        for key in ("puzzle", "id"):
            if key in query and query[key]:
                return "id", query[key][0]
        path = parsed.path.strip("/")
        if not path:
            raise LoadError("这个链接里没有题目 id")
        if path.startswith("scl") or "/scl" in path:
            return "payload", path[path.index("scl"):]
        return "id", path

    if Path(target).exists():
        return "file", target

    if "/" in target or " " in target:
        raise LoadError(f"无法识别的输入：{target}")
    return "id", target


def _payload_from_raw(raw: str) -> dict:
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    if re.match(r"^(scl|ctc)", raw):
        return decode_payload(raw)
    raise LoadError("响应不是 SudokuPad 数据包")


def load(target: str, use_cache: bool = True) -> dict:
    kind, value = _extract_target(target)
    if kind == "json":
        return json.loads(value)
    if kind == "payload":
        return decode_payload(value)
    if kind == "file":
        text = Path(value).read_text(encoding="utf-8")
        return _payload_from_raw(text)

    puzzle_id = value
    cache_file = CACHE_DIR / f"v{CACHE_VERSION}" / (re.sub(r"[^A-Za-z0-9_.-]", "_", puzzle_id) + ".json")
    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    errors = []
    for url in (API_URL.format(id=urllib.parse.quote(puzzle_id, safe="")),
                LEGACY_URL.format(id=urllib.parse.quote(puzzle_id, safe=""))):
        try:
            data = _payload_from_raw(_http_get(url))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            continue
        if use_cache:
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
            except OSError:
                pass
        return data
    raise LoadError("从 SudokuPad 读取题目失败：\n" + "\n".join(errors))
