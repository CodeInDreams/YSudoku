"""Local web server (stdlib only)."""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import history, live, store, sudokupad
from .pipeline import ANALYSIS_VERSION, analyze, initial_screenshot, save_rulesheet
from .llm import LLMError
from .model import parse_puzzle

STATIC_DIR = Path(__file__).parent / "static"
DIST_DIR = Path(__file__).parent.parent / "web" / "dist"
PEN_COLOURS = {"confirmed": 1, "candidate": 5, "excluded": 4}
_BUILDING: dict[str, str] = {}
_BUILDING_LOCK = threading.Lock()


def _content_language(body):
    return "en" if str(body.get("lang") or "").lower().startswith("en") else "zh"


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


def _hide_legacy_refutation_controls(payload):
    hint = "；可开启「反证」(--allow-chains) 尝试高级试探"
    if isinstance(payload.get("message"), str):
        payload["message"] = payload["message"].removesuffix(hint)
    footer = "\n注意：这一步是反证，不是直接推理；如只想看纯逻辑链，请关闭「反证」开关。"
    for step in payload.get("steps", []):
        if step.get("technique") == "forcing_chain" and isinstance(step.get("detail"), str):
            step["detail"] = step["detail"].removesuffix(footer)


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
    lang = _content_language(body)
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
            if not outside or not existing or not path.is_file():
                path = Path(initial_screenshot(url, size, store.frame_path(key, -1), crop=not outside))
        except (OSError, LLMError):
            on_preview("")
            return ""
        on_preview(f"/api/rulesheet/{path.name}")
        return str(path)

    if force_rules:
        for layer in ("rules", "steps", "frames"):
            store.delete_layer(key, layer)
    rules = store.load_rules(key)
    cached = None if force_rules or force_steps else store.load_analysis(key)
    old_version = bool(cached and cached.get("algo_version") != ANALYSIS_VERSION)
    saved_language = "en" if cached and cached.get("content_lang") == "en" else "zh"
    different_language = bool(cached and saved_language != lang)
    if not (old_version or different_language) and rules and not rules.get("includes_underlay_markers"):
        try:
            raw = sudokupad.load_cached(target)
        except sudokupad.LoadError:
            raw = None
        if raw and any(marker.layer == "underlay" for marker in parse_puzzle(raw).markers):
            rules = None
    meta = store._meta(key)
    if on_title and meta.get("title"):
        on_title(meta["title"])
    notes = str(body["notes"] if "notes" in body else meta.get("notes", "") or "").strip()
    if cached:
        if old_version or different_language or (rules
                and cached.get("status") != "stuck"
                and meta.get("rules_hash") == rules.get("hash")):
            if on_preview and not on_preview_start:
                preview(cached.get("source_url", ""), cached["puzzle"]["size"],
                        cached.get("rule_sheet", ""),
                        bool(cached.get("puzzle", {}).get("outside", True)))
            elif not cached.get("rule_sheet"):
                try:
                    path = save_rulesheet(store.frame_path(key, -1).read_bytes())
                    cached["rule_sheet"] = f"/api/rulesheet/{Path(path).name}"
                except (OSError, ValueError):
                    pass
            cached["notes"] = meta.get("notes", "")
            _hide_legacy_refutation_controls(cached)
            if isinstance(cached.get("rules"), dict):
                cached["rules"]["notes"] = meta.get("notes", "")
            cached["cached"] = True
            cached["content_lang"] = saved_language
            cached["current_algo_version"] = ANALYSIS_VERSION
            if old_version:
                cached["cache_version"] = {
                    "saved": cached.get("algo_version"), "current": ANALYSIS_VERSION,
                    "steps_hash": meta.get("steps_hash"),
                }
            cached["storage"] = {
                "key": key, "location": store.storage_info()["location"],
                "settings": store.load_settings(),
                "steps_hash": meta.get("steps_hash"),
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
                           outside=puzzle.has_outside_clues)
        return None

    if on_preview_start:
        on_preview_start()
    analysis = analyze(
        target,
        demo=demo,
        use_llm=bool(body.get("llm", True)) and (force_rules or not rules),
        spec_override=rules["spec"] if rules and not force_rules else None,
        do_audit=bool(body.get("audit", False)),
        allow_chains=True,
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
    payload = analysis.to_json(lang=lang)
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
    steps_hash = store.save_analysis(key, payload, info)
    payload["storage"] = {
        "key": key, "location": store.storage_info()["location"],
        "settings": store.load_settings(),
        "steps_hash": steps_hash,
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
            data = step.to_dict(n, _content_language(body))
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
                force_steps=bool(body.get("refresh_steps")),
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
            with _BUILDING_LOCK:
                building = session in _BUILDING
            directory = store.frames_dir(session)
            numbers = set()
            if directory.exists():
                for file in directory.glob("*.png"):
                    try:
                        numbers.add(int(file.stem))
                    except ValueError:
                        pass
            frames = sum(0 <= n < total for n in numbers)
            complete = -1 in numbers and frames == total
            error = None
            error_file = store.frames_dir(session) / "error.json"
            if error_file.exists():
                try:
                    error = json.loads(error_file.read_text(encoding="utf-8"))
                except Exception:
                    error = {"message": "frame build failed"}
            self._send(200, json.dumps({
                "frames": frames,
                "complete": complete, "total": total, "error": error,
                "interrupted": not building and not complete and not error,
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
                    proof_hash = store.hash_json(analysis["steps"]) if analysis and "steps" in analysis else None
                    keep_frames_for = body.get("keep_frames_for")
                    canonical = _canonical_frame_actions(steps, analysis)
                    digest = str(body.get("steps_hash") or "")
                    if canonical is not steps:
                        frame_spec = {"renderer": 33, "url": url, "size": size,
                                      "crop": crop, "steps": canonical}
                        content_lang = (analysis or {}).get("content_lang", "zh")
                        if content_lang != "zh":
                            frame_spec["lang"] = content_lang
                        digest = store.hash_json(frame_spec)
                    steps = canonical
                    if key:
                        if keep_frames_for and (keep_frames_for != proof_hash
                                                or len(steps) != len(analysis["steps"])):
                            self._send(409, json.dumps({
                                "error": "解题步骤缓存已更新，请重新打开谜题。"
                            }, ensure_ascii=False).encode(), "application/json")
                            return
                        directory = store.frames_dir(key)

                        def _build():
                            try:
                                live.build(url, steps, directory=str(directory), session=key,
                                           size=size, crop=crop, wait=True)
                                if digest:
                                    store.set_frames_hash(key, digest, proof_hash=proof_hash)
                            except Exception as exc:  # noqa: BLE001
                                print(f"frame build failed: {exc}", flush=True)
                                if not (directory / "error.json").is_file():
                                    directory.mkdir(parents=True, exist_ok=True)
                                    (directory / "error.json").write_text(
                                        json.dumps({"message": str(exc)}), encoding="utf-8")
                            finally:
                                with _BUILDING_LOCK:
                                    _BUILDING.pop(key, None)

                        with _BUILDING_LOCK:
                            result = {"ok": True, "session": key, "building": True}
                            if key in _BUILDING:
                                if _BUILDING[key] != digest:
                                    self._send(409, json.dumps({
                                        "error": "正在生成这道题的另一组截图，请稍后重试。"
                                    }, ensure_ascii=False).encode(), "application/json")
                                    return
                            else:
                                meta = store._meta(key)
                                retained = (proof_hash and keep_frames_for == proof_hash
                                            and meta.get("frames_proof_hash") == proof_hash)
                                matching = store.has_frames(key, digest) if digest else False
                                if ((matching or retained)
                                        and not (directory / "error.json").exists()
                                        and all(store.frame_path(key, step).is_file()
                                                for step in range(-1, len(steps)))):
                                    if matching and proof_hash and meta.get("frames_proof_hash") != proof_hash:
                                        store.set_frames_hash(key, digest, proof_hash=proof_hash)
                                    result = {"ok": True, "session": key, "cached": True, "complete": True}
                                else:
                                    store.delete_layer(key, "frames")
                                    _BUILDING[key] = digest
                                    threading.Thread(target=_build, daemon=True).start()
                    else:
                        result = live.build(url, steps, size=size, crop=crop)
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
                force_steps=bool(body.get("refresh_steps")),
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
