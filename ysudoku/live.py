"""Read-only SudokuPad mirror: a long-lived Playwright process plus HTTP proxy."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


class LiveError(RuntimeError):
    pass


class LiveGone(LiveError):
    """The browser was recycled while idle; the caller must restart."""


PORT = int(os.environ.get("YSUDOKU_LIVE_PORT", "8791"))
_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "tools" / "live_sudokupad.mjs"
_proc: subprocess.Popen | None = None


def _env() -> dict:
    env = os.environ.copy()
    if not env.get("NODE_PATH"):
        for candidate in (_ROOT / "tools" / "node_modules", Path("/tmp/pw/node_modules")):
            if candidate.exists():
                env["NODE_PATH"] = str(candidate)
                break
    if not env.get("PLAYWRIGHT_BROWSERS_PATH") and Path("/tmp/pw-browsers").exists():
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/tmp/pw-browsers"
    return env


def _request(path: str, payload: dict | None = None, timeout: float = 120.0) -> bytes:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 410:
            raise LiveGone(body) from exc
        raise LiveError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:  # noqa: BLE001
        raise LiveError(str(exc)) from exc


def _healthy() -> bool:
    try:
        _request("/health", timeout=1.5)
        return True
    except LiveError:
        return False


def ensure() -> None:
    global _proc
    if _healthy():
        return
    if _proc is not None and _proc.poll() is None:
        # process exists but the port is not ready yet
        for _ in range(60):
            if _healthy():
                return
            time.sleep(0.25)
    if not _SCRIPT.exists():
        raise LiveError("缺少 tools/live_sudokupad.mjs")
    try:
        _proc = subprocess.Popen(
            ["node", str(_SCRIPT)],
            cwd=str(_ROOT),
            env=_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise LiveError("找不到 node；需要 Node.js + Playwright 才能启用 SudokuPad 镜像") from exc
    for _ in range(80):
        if _healthy():
            return
        if _proc.poll() is not None:
            raise LiveError("SudokuPad 镜像进程启动失败（检查 Playwright/Chromium）")
        time.sleep(0.25)
    raise LiveError("SudokuPad 镜像启动超时")


def start(url: str) -> dict:
    ensure()
    return json.loads(_request("/start", {"url": url}, timeout=120))


def place(digits: list[list[int]], reset: bool, corners: list | None = None,
          pen: list | None = None) -> dict:
    ensure()
    return json.loads(_request("/place", {
        "digits": digits, "reset": reset, "corners": corners or [], "pen": pen or [],
    }, timeout=120))


def frame() -> bytes:
    ensure()
    return _request("/frame", timeout=30)
