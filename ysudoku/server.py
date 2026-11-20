"""Local web server (stdlib only)."""

from __future__ import annotations

import json
import threading

_BUILDING: set[str] = set()
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import math
import threading
import time
import uuid

from . import history, live, store, sudokupad
from .pipeline import analyze, initial_screenshot
from .llm import LLMError

STATIC_DIR = Path(__file__).parent / "static"
DIST_DIR = Path(__file__).parent.parent / "web" / "dist"
PEN_COLOURS = {"confirmed": 1, "candidate": 5, "excluded": 4}


def _canonical_frame_actions(steps, analysis):
    """Use the saved proof to make boundary rendering independent of client version."""
    if not analysis or len(analysis.get("steps", ())) != len(steps):
        return steps
    visuals = [step.get("visual", {}) for step in analysis["steps"]]
    if not any("region_edges" in visual for visual in visuals):
        return steps

    frames = []
    previous = {}
    for actions, proof_step, visual in zip(steps, analysis["steps"], visuals):
        frame = [action for action in actions if action.get("op") != "pen"]
        if not proof_step.get("branch"):
            current = {}
            for edge in visual.get("region_edges", ()):
                status = edge.get("status") or ("confirmed" if edge.get("fixed") else "candidate")
                current[tuple(sorted(edge["cells"]))] = PEN_COLOURS[status]
            for cells, index in previous.items():
                if cells not in current:
                    frame.append({"op": "pen", "cells": list(cells), "index": index, "enabled": False})
            for cells, index in current.items():
                if previous.get(cells) != index:
                    frame.append({"op": "pen", "cells": list(cells), "index": index, "enabled": True})
            previous = current
        frames.append(frame)
    return frames


def _stored_analysis(target: str, body: dict, demo: bool = False,
                     force_rules: bool = False, force_steps: bool = False,
                     on_rules=None, on_step=None, on_preview=None, on_preview_start=None, on_title=None, opened_at=None):
    if "logic-masters.de" in target:
        try:
            data = sudokupad.load(target)
            canonical = (data.get("metadata") or {}).get("source_url")
            if canonical:
                target = canonical
        except Exception:
            pass
    key = store.key_for(target)
    lang = str(body.get("lang") or "zh").lower()[:2]
    if not demo:
        meta = store._meta(key)
        if not meta.get("title"):
            store._update_meta(key, title=target, author="", target=target,
                               at=time.time(), opened_at=time.time(),
                               status="running", steps_count=0)
    if opened_at is not None:
        store.record_open(key, opened_at)

    def preview(url, size, existing="", outside=True):
        path = Path(".cache/rulesheets") / Path(existing).name
        try:
            if not outside:
                png = live.initial_frame(url, size, crop=True)
                path = Path(".cache/rulesheets") / (store.hash_json({"url": url, "crop": True}) + ".png")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png)
            elif not existing or not path.is_file():
                path = Path(initial_screenshot(url, size, store.frame_path(key, -1)))
        except (OSError, LLMError):
            on_preview("")
            return ""
        on_preview(f"/api/rulesheet/{path.name}")
        return str(path)

    if force_rules:
        for layer in ("rules", "steps", "frames"):
            store.delete_layer(key, layer)
    elif force_steps:
        for layer in ("steps", "frames"):
            store.delete_layer(key, layer)

    rules = store.load_rules(key)
    meta = store._meta(key)
    if on_title and meta.get("title"):
        on_title(meta["title"])
    notes = str(body["notes"] if "notes" in body else meta.get("notes", "") or "").strip()
    if not force_rules and not force_steps and rules:
        cached = store.load_analysis(key)
        from .pipeline import ANALYSIS_VERSION
        if (cached and cached.get("lang", "zh") == lang
                and cached.get("algo_version") == ANALYSIS_VERSION
                and meta.get("rules_hash") == rules.get("hash")):
            if on_preview and not on_preview_start:
                preview(cached.get("source_url", ""), cached["puzzle"]["size"],
                        cached.get("rule_sheet", ""),
                        bool(cached.get("puzzle", {}).get("outside", True)))
            cached["notes"] = meta.get("notes", "")
            if isinstance(cached.get("rules"), dict):
                cached["rules"]["notes"] = meta.get("notes", "")
            cached["cached"] = True
            cached["storage"] = {
                "key": key, "location": store.storage_info()["location"],
                "settings": store.load_settings(),
            }
            if on_rules is not None and not on_preview_start:
                try:
                    on_rules(cached.get("rules", {}).get("resolved", []))
                except Exception:
                    pass
            if on_step is not None and not on_preview_start:
                for index, step in enumerate(cached.get("steps", [])):
                    try:
                        on_step(index, step)
                    except Exception:
                        pass
            return key, cached

    def on_puzzle(puzzle):
        if on_title:
            on_title(puzzle.title)
        if on_preview:
            return preview(puzzle.source_url, puzzle.size,
                           outside=bool(puzzle.clues or puzzle.arrows))
        return None

    if on_preview_start:
        on_preview_start()
    analysis = analyze(
        target,
        demo=demo,
        use_llm=bool(body.get("llm", True)) and (force_rules or not rules),
        spec_override=rules["spec"] if rules and not force_rules else None,
        do_audit=bool(body.get("audit", False)),
        allow_chains=True if demo else bool(body.get("chains", True)),
        use_global=False,
        global_time_limit=float(body.get("global_timeout", 60)),
        notes=notes,
        rule_prompt=str(body.get("rule_prompt") or ""),
        rule_mode=str(body.get("rule_mode") or "auto"),
        lang=lang,
        on_rules=on_rules,
        on_step=on_step,
        on_puzzle=on_puzzle if on_preview or on_title else None,
    )
    payload = analysis.to_json()
    payload["notes"] = notes
    if isinstance(payload.get("rules"), dict):
        payload["rules"]["notes"] = notes
    info = {
        "target": "" if demo else target,
        "demo": demo,
        "title": analysis.puzzle.title,
        "author": analysis.puzzle.author,
        "at": time.time(),
        "status": analysis.status,
        "steps_count": len(analysis.result.steps),
        "notes": notes,
    }
    if analysis.spec:
        store.save_rules(key, analysis.spec, info)
    store.save_analysis(key, payload, info)
    payload["storage"] = {
        "key": key, "location": store.storage_info()["location"],
        "settings": store.load_settings(),
    }
    return key, payload


_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _job_update(job_id: str, **values) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(values)


def _start_job(target: str, body: dict, demo: bool) -> str:
    job_id = uuid.uuid4().hex[:12]
    preview_ready = threading.Event()
    job = {
        "preview_ready": preview_ready,
        "id": job_id, "phase": "opening", "status": "running",
        "rules": [], "steps": [], "error": None, "payload": None,
        "key": None, "started": time.time(),
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        while len(_JOBS) > 20:
            _JOBS.pop(next(iter(_JOBS)))

    def on_preview(url):
        if url:
            _job_update(job_id, preview=url)
            if body.get("wait_for_preview"):
                preview_ready.wait(timeout=3)
        _job_update(job_id, phase="rules")

    def on_rules(rules):
        _job_update(job_id, phase="solving", rules=list(rules or []))

    def on_step(first, second=None):
        if second is not None:
            index, data = first, second
        else:
            step = first
            n = max(1, int(math.isqrt(len(step.pre_dom) or 1)))
            data = step.to_dict(n)
            with _JOBS_LOCK:
                index = len(_JOBS[job_id]["steps"])
        data = dict(data)
        data["index"] = index
        with _JOBS_LOCK:
            _JOBS[job_id]["steps"].append(data)

    def run():
        try:
            key, payload = _stored_analysis(
                target, body, demo=demo, on_rules=on_rules, on_step=on_step,
                on_preview=on_preview,
                on_preview_start=lambda: _job_update(job_id, phase="preview"),
                on_title=lambda title: _job_update(job_id, title=title),
                opened_at=job["started"],
            )
            _job_update(
                job_id, phase="done", status="done", key=key, payload=payload,
                rules=payload.get("rules", {}).get("resolved", []),
                steps=payload.get("steps", []),
            )
        except Exception as exc:  # noqa: BLE001
            _job_update(job_id, phase="failed", status="failed", error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return job_id


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".map": "application/json",
    ".ico": "image/x-icon",
}


def _safe_static(base, relative: str):
    base = Path(base).resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


class Handler(BaseHTTPRequestHandler):
    server_version = "YSudoku/0.1"
    last_analysis = None

    def log_message(self, fmt, *args):  # quiet
        return

    def _send(self, status: int, payload: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/store":
            entries = store.list_entries()
            payload = {"info": store.storage_info(entries), "entries": entries}
            self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json")
            return
        if path == "/api/job":
            query = parse_qs(urlparse(self.path).query)
            job_id = (query.get("id") or [""])[0]
            with _JOBS_LOCK:
                job = dict(_JOBS.get(job_id) or {})
            if not job:
                self._send(404, b'{"error":"job not found"}', "application/json")
                return
            payload = {
                "id": job["id"], "phase": job["phase"], "status": job["status"],
                "rules": job.get("rules", []), "steps": job.get("steps", []),
                "error": job.get("error"), "key": job.get("key"), "title": job.get("title"),
                "count": len(job.get("steps", [])), "preview": job.get("preview", ""),
            }
            if job.get("payload") is not None:
                payload["payload"] = job["payload"]
            self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json")
            return
        if path == "/api/live/progress":
            query = parse_qs(urlparse(self.path).query)
            session = (query.get("session") or [""])[0]
            total = int((query.get("total") or ["0"])[0] or 0)
            directory = store.frames_dir(session)
            numbers = []
            if directory.exists():
                for file in directory.glob("*.png"):
                    try:
                        numbers.append(int(file.stem))
                    except ValueError:
                        pass
            complete = bool(total) and (total - 1) in numbers
            error = None
            error_file = store.frames_dir(session) / "error.json"
            if error_file.exists():
                try:
                    error = json.loads(error_file.read_text(encoding="utf-8"))
                except Exception:
                    error = {"message": "frame build failed"}
            self._send(200, json.dumps({
                "frames": len([n for n in numbers if n >= 0]),
                "complete": complete, "total": total, "error": error,
            }).encode(), "application/json")
            return
        if path == "/api/live/health":
            self._send(200, json.dumps({"ok": live._healthy()}).encode(), "application/json")
            return
        if path == "/api/live/grid":
            try:
                query = parse_qs(urlparse(self.path).query)
                session = (query.get("session") or [None])[0]
                if session:
                    try:
                        rect = json.loads((store.frames_dir(session) / "grid.json").read_text())
                    except (FileNotFoundError, json.JSONDecodeError):
                        rect = None
                else:
                    rect = live.grid()
                self._send(200, json.dumps(rect).encode(), "application/json")
            except Exception as exc:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        if path == "/api/live/frame":
            try:
                query = parse_qs(urlparse(self.path).query)
                session = query.get("session", [None])[0]
                step = query.get("step", [None])[0]
                if session and step is not None:
                    frame = store.frame_path(session, step)
                    if frame.exists():
                        self._send(200, frame.read_bytes(), "image/png")
                    else:
                        self._send(404, b'{"error":"frame not ready"}', "application/json")
                    return
                self._send(200, live.frame(), "image/png")
            except live.LiveError as exc:
                self._send(503, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                           "application/json")
            return
        if path.startswith("/api/rulesheet/"):
            name = Path(path.split("/")[-1]).name
            file = Path(".cache") / "rulesheets" / name
            if file.exists() and file.suffix == ".png":
                self._send(200, file.read_bytes(), "image/png")
            else:
                self._send(404, b"not found", "text/plain")
            return
        if path == "/api/history":
            self._send(200, json.dumps(history.load(), ensure_ascii=False).encode("utf-8"),
                       "application/json")
            return
        if path == "/api/health":
            from . import llm, rulecache
            config = llm.LLMConfig.from_env()
            payload = {
                "ok": True,
                "llm_available": config is not None,
                "llm_model": config.model if config else None,
                "rules_cache": rulecache.summary(),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
            return
        if path in ("/", "/index.html") and (DIST_DIR / "index.html").exists():
            file = DIST_DIR / "index.html"
        elif path.startswith("/assets/") and DIST_DIR.exists():
            file = _safe_static(DIST_DIR, path.lstrip("/"))
        elif path in ("/favicon.svg", "/favicon.ico"):
            file = _safe_static(DIST_DIR, path.lstrip("/"))
        elif path.startswith("/mockups/") and DIST_DIR.exists():
            file = _safe_static(DIST_DIR, path.lstrip("/"))
            if file.is_dir():
                file = file / "index.html"
        elif path in ("/", "/index.html"):
            file = STATIC_DIR / "index.html"
        elif path.startswith("/static/"):
            file = _safe_static(STATIC_DIR, path[len("/static/"):])
        else:
            self._send(404, b"not found", "text/plain")
            return
        if file is None or not file.exists() or not file.is_file():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, file.read_bytes(), _CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        path = urlparse(self.path)
        if path.path == "/api/job/preview-ready":
            job_id = parse_qs(path.query).get("id", [""])[0]
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job:
                    job["preview_ready"].set()
            self._send(200, b'{}', "application/json")
            return
        if path.path not in (
            "/api/solve", "/api/solve/start", "/api/demo", "/api/live/start", "/api/live/place",
            "/api/live/build", "/api/history/clear",
            "/api/store/settings", "/api/store/delete", "/api/store/favorite",
            "/api/store/refresh_rules",
        ):
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if urlparse(self.path).path.startswith("/api/store/"):
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                path = urlparse(self.path).path
                if path == "/api/store/settings":
                    result = store.save_settings(**body)
                elif path == "/api/store/delete":
                    store.delete_layer(str(body.get("key") or ""), str(body.get("layer") or ""))
                    result = {"ok": True}
                elif path == "/api/store/favorite":
                    store.set_favorite(str(body.get("key") or ""), bool(body.get("favorite")))
                    result = {"ok": True}
                elif path == "/api/store/refresh_rules":
                    target = str(body.get("target") or "")
                    demo = bool(body.get("demo"))
                    if demo and not target:
                        target = str(STATIC_DIR.parent.parent / "fixtures" / "demo-globosite.json")
                    key, payload = _stored_analysis(
                        target, body, demo=demo, force_rules=True,
                    )
                    result = payload
                else:
                    result = {"error": "unknown store action"}
                self._send(200, json.dumps(result, ensure_ascii=False).encode(), "application/json")
            except Exception as exc:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                           "application/json")
            return
        if urlparse(self.path).path in ("/api/live/start", "/api/live/place", "/api/live/build"):
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if urlparse(self.path).path == "/api/live/build":
                    key = str(body.get("key") or "")
                    steps = body.get("steps") or []
                    url = str(body.get("url") or "")
                    size = int(body.get("size") or 0)
                    crop = bool(body.get("crop"))
                    analysis = store.load_analysis(key) if key else None
                    canonical = _canonical_frame_actions(steps, analysis)
                    digest = str(body.get("steps_hash") or "")
                    if canonical is not steps:
                        digest = store.hash_json({"renderer": 32, "url": url, "size": size, "steps": canonical})
                    steps = canonical
                    if key and digest and store.has_frames(key, digest):
                        last = len(steps) - 1
                        complete = store.frame_path(key, -1).is_file() and store.frame_path(key, last).is_file()
                        result = {"ok": True, "session": key, "cached": True, "complete": complete}
                    else:
                        directory = str(store.frames_dir(key)) if key else None
                        if key and key in _BUILDING:
                            result = {"ok": True, "session": key, "building": True}
                        elif key:
                            store.delete_layer(key, "frames")
                            _BUILDING.add(key)
                            def _build():
                                try:
                                    live.build(url, steps, directory=directory, session=key, size=size, crop=crop)
                                    if digest:
                                        store.set_frames_hash(key, digest)
                                except Exception as exc:  # noqa: BLE001
                                    print(f"frame build failed: {exc}", flush=True)
                                finally:
                                    _BUILDING.discard(key)
                            threading.Thread(target=_build, daemon=True).start()
                            result = {"ok": True, "session": key, "building": True}
                        else:
                            result = live.build(url, steps, directory=directory, session=None, size=size, crop=crop)
                            if digest:
                                store.set_frames_hash(key, digest)
                elif urlparse(self.path).path == "/api/live/start":
                    result = live.start(str(body.get("url") or ""))
                else:
                    result = live.place(body.get("digits") or body.get("places") or [],
                                        bool(body.get("reset")),
                                        body.get("corners") or [],
                                        body.get("pen") or [])
                self._send(200, json.dumps(result).encode(), "application/json")
            except live.LiveGone as exc:
                self._send(410, json.dumps({"error": str(exc), "restart": True},
                                           ensure_ascii=False).encode(), "application/json")
            except Exception as exc:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                           "application/json")
            return
        if urlparse(self.path).path == "/api/history/clear":
            history.clear()
            self._send(200, b'{"ok":true}', "application/json")
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        target = (body.get("url") or "").strip()
        demo = urlparse(self.path).path == "/api/demo"
        if urlparse(self.path).path == "/api/solve/start":
            demo = bool(body.get("demo"))
            if demo:
                target = str(STATIC_DIR.parent.parent / "fixtures" / "demo-globosite.json")
            if not target:
                self._send(400, b'{"error":"missing url"}', "application/json")
                return
            job_id = _start_job(target, body, demo)
            self._send(200, json.dumps({"id": job_id}).encode(), "application/json")
            return
        if urlparse(self.path).path == "/api/demo":
            target = str(STATIC_DIR.parent.parent / "fixtures" / "demo-globosite.json")
        if not target:
            self._send(400, b'{"error":"missing url"}', "application/json")
            return
        try:
            key, payload = _stored_analysis(
                target, body,
                demo=(urlparse(self.path).path == "/api/demo"),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            payload = {"error": str(exc)}
            self._send(500, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
            return
        self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")


def serve(host: str = "127.0.0.1", port: int = 8765):
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def _warm_live() -> None:
    try:
        live.ensure()
    except Exception:
        pass


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    httpd = serve(host, port)
    threading.Thread(target=_warm_live, daemon=True).start()
    url = f"http://{host}:{port}/"
    print(f"YSudoku 正在运行：{url}")
    if open_browser:
        try:
            import webbrowser
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
