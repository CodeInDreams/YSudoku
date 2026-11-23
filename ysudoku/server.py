"""Local web server (stdlib only)."""

from __future__ import annotations

import hmac
import json
import os
import re
import math
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, history, live, llm, store, sudokupad
from .service_limits import Limits, PROMPT_LIMIT, Rejected, Work
from .pipeline import ANALYSIS_VERSION, analyze, initial_screenshot, rulesheet_dir, save_rulesheet
from .llm import LLMError
from .model import parse_puzzle

STATIC_DIR = Path(__file__).parent / "static"
DIST_DIR = Path(__file__).parent.parent / "web" / "dist"
_BUILDING: set[str] = set()
_BUILDING_LOCK = threading.Lock()


def _content_language(body):
    return "en" if str(body.get("lang") or "").lower().startswith("en") else "zh"


def _clean_frames(meta):
    version = meta.get("frames_renderer")
    return isinstance(version, int) and version >= live.MIN_CLEAN_FRAME_VERSION


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
                     on_rules=None, on_step=None, on_preview=None, on_preview_start=None, on_title=None,
                     opened_at=None, work=None):
    if work is None and urlparse(target).hostname in ("logic-masters.de", "www.logic-masters.de"):
        try:
            data = sudokupad.load(target)
            canonical = (data.get("metadata") or {}).get("source_url")
            if canonical:
                target = _web_target(canonical)
        except Exception:
            pass
    key = store.key_for(target)
    lang = _content_language(body)
    def opened():
        if opened_at is not None:
            store.record_open(key, opened_at)

    def preview(url, size, existing="", outside=True):
        path = rulesheet_dir() / Path(existing).name
        try:
            if not path.name.startswith(f"r{live.FRAME_RENDERER_VERSION}-") or not path.is_file():
                frame = store.frame_path(key, -1) if _clean_frames(store._meta(key)) else None
                path = Path(initial_screenshot(url, size, frame, crop=not outside))
        except (OSError, LLMError):
            on_preview("")
            return ""
        on_preview(f"/api/rulesheet/{path.name}")
        return str(path)

    rules = None if force_rules else store.load_rules(key)
    cached = None if force_rules or force_steps else store.load_analysis(key)
    old_version = bool(cached and cached.get("algo_version") != ANALYSIS_VERSION)
    saved_language = "en" if cached and cached.get("content_lang") == "en" else "zh"
    different_language = bool(cached and saved_language != lang)
    if not (old_version or different_language) and rules and not rules.get("includes_underlay_markers"):
        try:
            raw = store.load_puzzle(key) or sudokupad.load_cached(target)
        except sudokupad.LoadError:
            raw = None
        if raw and any(marker.layer == "underlay" for marker in parse_puzzle(raw).markers):
            rules = None
    meta = store._meta(key)
    if on_title and meta.get("title"):
        on_title(meta["title"])
    notes = str(body["notes"] if "notes" in body else meta.get("notes", "") or "").strip()
    if work:
        prompt = body.get("rule_prompt", "")
        notes = notes[:max(0, PROMPT_LIMIT - len(prompt))]
    if cached:
        if old_version or different_language or (rules and meta.get("rules_hash") == rules.get("hash")):
            opened()
            if not Path(cached.get("rule_sheet") or "").name.startswith(f"r{live.FRAME_RENDERER_VERSION}-"):
                cached["rule_sheet"] = ""
            if on_preview and not on_preview_start:
                preview(cached.get("source_url", ""), cached["puzzle"]["size"],
                        cached.get("rule_sheet", ""),
                        bool(cached.get("puzzle", {}).get("outside", True)))
            elif not cached.get("rule_sheet") and _clean_frames(meta):
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
                "key": key,
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

    def load_source(url):
        raw = store.load_puzzle(key)
        if raw is None:
            raw = sudokupad.load_cached(url) or sudokupad.load(url, use_cache=False)
            store.save_puzzle(key, raw)
        return raw

    if work:
        work.acquire(solve=True)
        if body.get("llm", True) and not rules and llm.available() and work.limits.exhausted():
            work.llm_fallback = True
    if not demo and not meta.get("title"):
        store._update_meta(key, title=target[:160], author="", target=target,
                           at=time.time(), status="running", steps_count=0)
    opened()
    if on_preview_start:
        on_preview_start()
    analysis = analyze(
        target,
        demo=demo,
        use_llm=bool(body.get("llm", True)) and not rules and not (work and work.llm_fallback),
        spec_override=rules["spec"] if rules and not force_rules else None,
        use_cache=not force_rules,
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
        load_puzzle=load_source if work else None,
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
        "key": key,
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


def _start_job(target: str, body: dict, demo: bool, limits=None, ip=None, *, synchronous=False):
    work = Work(limits, ip, store.key_for(target), "Demo" if demo else target[:160]) if limits else None
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
        now = time.time()
        completed = [key for key, value in _JOBS.items() if value["status"] != "running"]
        for key in completed[:-200]:
            del _JOBS[key]
        for key in completed[-200:]:
            if now - _JOBS[key].get("finished", now) > 600:
                del _JOBS[key]

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

    def on_title(title):
        if work:
            work.title = str(title)[:160]
        _job_update(job_id, title=title)

    def run():
        render = None
        token = llm.web_request.set(work.llm_request) if work else None
        try:
            key, payload = _stored_analysis(
                target, body, demo=demo, on_rules=on_rules, on_step=on_step,
                force_rules=bool(body.get("refresh_rules")),
                force_steps=bool(body.get("refresh_steps")),
                on_preview=None if synchronous else on_preview,
                on_preview_start=None if synchronous else lambda: _job_update(job_id, phase="preview"),
                on_title=on_title, opened_at=job["started"], work=work,
            )
            if work:
                if work.llm_fallback:
                    payload["llm_quota_exceeded"] = True
                try:
                    render = _prepare_render(key, payload, work)
                except Rejected as exc:
                    if not payload.get("cached") or exc.payload["code"] != "storage_limit_exceeded":
                        raise
                    payload["render_blocked"] = exc.payload
                payload["quota"] = limits.usage(ip)
            _job_update(
                job_id, phase="done", status="done", key=key, payload=payload, finished=time.time(),
                rules=payload.get("rules", {}).get("resolved", []),
                steps=payload.get("steps", []),
            )
        except Rejected as exc:
            _job_update(job_id, phase="failed", status="failed", rejection=exc, error=exc.payload["error"], finished=time.time())
        except Exception as exc:  # noqa: BLE001
            _job_update(job_id, phase="failed", status="failed", error=str(exc), finished=time.time())
        finally:
            if token is not None:
                llm.web_request.reset(token)
            if work:
                work.log()
                if render is None:
                    work.release()
        if render is not None:
            if synchronous:
                threading.Thread(target=render, daemon=True).start()
            else:
                render()

    if synchronous:
        run()
        return job
    threading.Thread(target=run, daemon=True).start()
    return job_id


def _web_target(value, render=False):
    """Only accept puzzle identifiers and approved HTTPS origins from HTTP clients."""
    if not isinstance(value, str):
        raise Rejected(400, "invalid_puzzle")
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) and not render:
        return "https://sudokupad.app/" + value
    if len(value) > 131072 or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value):
        raise Rejected(400, "invalid_puzzle")
    try:
        url = urlparse(value)
        if url.scheme == "https" and not url.username and not url.password and url.port in (None, 443):
            if url.hostname == "sudokupad.app" and re.fullmatch(r"/[A-Za-z0-9_.~=+%$!(),;-]+/?", url.path):
                return "https://sudokupad.app/" + url.path.strip("/")
            if (not render and url.hostname in ("logic-masters.de", "www.logic-masters.de")
                    and url.path in ("/Raetselportal/Raetsel/zeigen.php", "/Raetselportal/Raetsel/zeigen.php/")
                    and re.fullmatch(r"[A-Za-z0-9]+", parse_qs(url.query).get("id", [""])[0])):
                return f"https://{url.hostname}/Raetselportal/Raetsel/zeigen.php?id=" + parse_qs(url.query)["id"][0]
    except ValueError:
        pass
    raise Rejected(400, "invalid_puzzle")


def _prepare_render(key, payload, work):
    steps = payload.get("steps") or []
    try:
        url = _web_target(payload.get("source_url"), render=True)
    except Rejected:
        return None
    meta = store._meta(key)
    proof = store.hash_json(steps)
    directory = store.frames_dir(key)
    with _BUILDING_LOCK:
        if key in _BUILDING:
            payload["frames"] = {"session": key, "building": True}
            return None
        if (_clean_frames(meta) and meta.get("frames_proof_hash") == proof
                and not (directory / "error.json").exists()
                and all(store.frame_path(key, index).is_file() for index in range(-1, len(steps)))):
            payload["frames"] = {"session": key, "complete": True}
            return None
        if work.started is None:
            work.acquire(solve=False)
        store.delete_layer(key, "frames")
        _BUILDING.add(key)
        payload["frames"] = {"session": key, "building": True}

    def render():
        try:
            puzzle = payload["puzzle"]
            analysis = {"steps": steps, "puzzle": {"size": puzzle["size"]}}
            live.build(url, [], analysis=analysis, directory=str(directory), session=key,
                       size=puzzle["size"], crop=not puzzle.get("outside", True), wait=True)
            store.set_frames_hash(key, proof, proof_hash=proof, renderer=live.FRAME_RENDERER_VERSION)
        except Exception as exc:  # noqa: BLE001
            print(f"frame build failed: {exc}", flush=True)
            if not (directory / "error.json").is_file():
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "error.json").write_text(json.dumps({"message": str(exc)}), encoding="utf-8")
        finally:
            with _BUILDING_LOCK:
                _BUILDING.discard(key)
            work.release()

    return render


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
    server_version = "YSudoku"
    last_analysis = None

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _ip(self):
        ip = self.server.limits.client_ip(self.client_address[0], self.headers)
        if self.server.limits.banned(ip):
            raise Rejected(403, "ip_banned")
        return ip

    def _permissions(self):
        protected = bool(os.environ.get("YSUDOKU_ADMIN_TOKEN"))
        admin = self._admin()
        return {
            "can_update_settings": self.server.limits.allow_settings and (not protected or admin),
            "can_delete": self.server.limits.allow_delete and (not protected or admin),
            "can_favorite": not protected or admin,
        }

    def _admin(self):
        token = os.environ.get("YSUDOKU_ADMIN_TOKEN", "")
        return bool(token and hmac.compare_digest(
            self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()
        ))

    def log_message(self, fmt, *args):  # quiet
        return

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def _send(self, status: int, payload: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            ip = self._ip()
            self._get(ip)
        except Rejected as exc:
            self._json(exc.status, exc.payload)
        except ValueError:
            self._json(400, {"error": "invalid request"})

    def _get(self, ip):
        path = urlparse(self.path).path
        if path == "/api/quota":
            self._json(200, self.server.limits.usage(ip))
            return
        if path == "/api/store":
            entries = store.list_entries()
            info = store.storage_info(entries)
            info.pop("location", None)
            payload = {"info": info, "entries": entries, **self._permissions()}
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
            if job.get("rejection"):
                exc = job["rejection"]
                raise exc
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
            complete = not building and -1 in numbers and frames == total
            error = None
            error_file = store.frames_dir(session) / "error.json"
            if error_file.exists():
                try:
                    error = json.loads(error_file.read_text(encoding="utf-8"))
                except Exception:
                    error = {"message": "frame build failed"}
            self._send(200, json.dumps({
                "frames": frames,
                "complete": complete, "total": total, "error": error, "building": building,
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
                    rect = None
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
                self._send(404, b"frame not ready", "text/plain")
            except live.LiveError as exc:
                self._send(503, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                           "application/json")
            return
        if path.startswith("/api/rulesheet/"):
            name = Path(path.split("/")[-1]).name
            file = _safe_static(rulesheet_dir(), name)
            if file and file.is_file() and file.suffix == ".png":
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
                "version": __version__,
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
            if file and file.is_dir():
                file = _safe_static(DIST_DIR, path.lstrip("/") + "/index.html")
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
        try:
            self._post(self._ip())
        except Rejected as exc:
            self._json(exc.status, exc.payload)
        except (ValueError, TypeError):
            self._json(400, {"error": "invalid request"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    def _post(self, ip):
        path = urlparse(self.path)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise Rejected(403, "cross_site_write")
        if path.path == "/api/job/preview-ready":
            job_id = parse_qs(path.query).get("id", [""])[0]
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job:
                    job["preview_ready"].set()
            self._json(200, {})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= 262144:
            raise Rejected(413, "request_too_large")
        if length and self.headers.get_content_type() != "application/json":
            raise Rejected(415, "json_required")
        body = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(body, dict):
            raise Rejected(400, "invalid_request")
        if path.path in ("/api/store/settings", "/api/store/favorite", "/api/store/delete", "/api/history/clear"):
            permission = {
                "/api/store/settings": "can_update_settings",
                "/api/store/favorite": "can_favorite",
                "/api/store/delete": "can_delete",
                "/api/history/clear": "can_delete",
            }[path.path]
            if not self._permissions()[permission]:
                raise Rejected(403, "write_disabled")
            key = str(body.get("key") or "")
            title = store._meta(key).get("title", key) if key else ""
            if path.path == "/api/store/settings":
                values = {key: body[key] for key in store.DEFAULT_SETTINGS if key in body}
                try:
                    result = store.save_settings(allow_count_reduction=self._permissions()["can_delete"], **values)
                except store.CountReductionDisabled:
                    raise Rejected(403, "count_reduction_disabled") from None
            elif path.path == "/api/history/clear":
                history.clear()
                result = {"ok": True}
            else:
                with self.server.limits.lock:
                    if key in self.server.limits.active:
                        raise Rejected(409, "puzzle_busy")
                    if path.path == "/api/store/delete":
                        store.delete_layer(key, str(body.get("layer") or ""))
                    else:
                        store.set_favorite(key, bool(body.get("favorite")))
                result = {"ok": True}
            Work(self.server.limits, ip, key, title).log()
            self._json(200, result)
            return
        if path.path == "/api/live/build":
            key = body.get("key", "")
            analysis = store.load_analysis(key)
            if not analysis:
                raise Rejected(404, "puzzle_not_cached")
            work = Work(self.server.limits, ip, key, analysis["puzzle"]["title"])
            try:
                render = _prepare_render(key, analysis, work)
                if render:
                    threading.Thread(target=render, daemon=True).start()
            except Exception:
                work.release()
                raise
            finally:
                work.log()
            self._json(200, analysis.get("frames") or {})
            return
        if path.path not in ("/api/solve", "/api/solve/start", "/api/demo", "/api/store/refresh_rules"):
            self._json(404, {"error": "not found"})
            return
        prompts = [body.get(field, "") for field in ("notes", "rule_prompt")]
        if any(not isinstance(value, str) for value in prompts) or sum(map(len, prompts)) > PROMPT_LIMIT:
            raise Rejected(400, "prompt_too_long", limit=PROMPT_LIMIT)
        demo = path.path == "/api/demo" or (path.path != "/api/solve" and bool(body.get("demo")))
        if demo:
            target = str(STATIC_DIR.parent.parent / "fixtures" / "demo-globosite.json")
        else:
            target = _web_target(body.get("url") if path.path != "/api/store/refresh_rules" else body.get("target"))
        if path.path == "/api/store/refresh_rules":
            body["refresh_rules"] = True
        else:
            body["refresh_rules"] = body.get("rule_mode") in ("llm", "heuristic")
        if path.path == "/api/solve/start" or body.get("stream"):
            self._json(200, {"id": _start_job(target, body, demo, self.server.limits, ip)})
        else:
            job = _start_job(target, body, demo, self.server.limits, ip, synchronous=True)
            if job.get("rejection"):
                raise job["rejection"]
            self._json(200 if job["payload"] is not None else 500, job["payload"] or {"error": job["error"]})


class PublicServer(ThreadingHTTPServer):
    def __init__(self, address):
        self.limits = Limits(store._root())
        self._instance_lock = None
        if os.name == "posix":
            import fcntl

            file = (store._root() / "service.lock").open("a")
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                file.close()
                raise RuntimeError("The YSudoku data store already has a running web service") from None
            self._instance_lock = file
        try:
            super().__init__(address, Handler)
        except BaseException:
            self.server_close()
            raise

    def service_actions(self):
        self.limits.refresh_bans()

    def server_close(self):
        if hasattr(self, "socket"):
            super().server_close()
        if self._instance_lock is not None:
            self._instance_lock.close()
            self._instance_lock = None


def serve(host: str = "127.0.0.1", port: int = 8765):
    return PublicServer((host, port))


def _warm_live() -> None:
    try:
        live.ensure()
    except Exception:
        pass


def _run_as_configured_user():
    user = os.environ.get("YSUDOKU_RUN_USER")
    if not user:
        return
    import pwd
    account = pwd.getpwnam(user)
    if account.pw_uid != os.geteuid() or account.pw_gid != os.getegid():
        if os.geteuid() != 0:
            raise PermissionError("Start as YSUDOKU_RUN_USER or use a privileged service manager to switch accounts")
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    os.environ.update(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name)


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    _run_as_configured_user()
    if data_dir := os.environ.get("YSUDOKU_DATA_DIR"):
        data = Path(data_dir).resolve()
        os.environ.setdefault("YSUDOKU_STORE", str(data / "store"))
        os.environ.setdefault("YSUDOKU_CACHE", str(data))
        os.environ.setdefault("SUDOKU_EXPLAIN_CACHE", str(data))
        os.environ.setdefault("YSUDOKU_HISTORY", str(data / "history.json"))
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
        live.stop()
