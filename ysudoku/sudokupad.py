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


_SUDOKU_LINK = re.compile(r"https://sudokupad\.app/[A-Za-z0-9_=-]+")


def extract_sudokupad_link(html: str) -> str | None:
    match = _SUDOKU_LINK.search(html)
    return match.group(0) if match else None


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
        if "logic-masters.de" in parsed.netloc:
            return "lm", target
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
    if kind == "lm":
        html = _http_get(value)
        sudoku_url = extract_sudokupad_link(html)
        if not sudoku_url:
            raise LoadError("这个 Logic Masters 页面没有 SudokuPad 链接（可能只有 Penpa+）")
        data = load(sudoku_url, use_cache=use_cache)
        meta = data.setdefault("metadata", {})
        meta["lm_url"] = value
        meta["source_url"] = sudoku_url
        return data
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
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
            except OSError:
                pass
        return data
    raise LoadError("从 SudokuPad 读取题目失败：\n" + "\n".join(errors))
