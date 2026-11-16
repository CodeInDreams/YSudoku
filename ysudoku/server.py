"""Local web server (stdlib only)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import history, live
from .pipeline import analyze

STATIC_DIR = Path(__file__).parent / "static"
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


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
        if path == "/api/live/health":
            self._send(200, json.dumps({"ok": live._healthy()}).encode(), "application/json")
            return
        if path == "/api/live/frame":
            try:
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
        if path in ("/", "/index.html"):
            file = STATIC_DIR / "index.html"
        elif path.startswith("/static/"):
            file = STATIC_DIR / path[len("/static/"):]
        else:
            self._send(404, b"not found", "text/plain")
            return
        if not file.exists() or not file.is_file():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, file.read_bytes(), _CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        if urlparse(self.path).path not in (
            "/api/solve", "/api/demo", "/api/live/start", "/api/live/place",
            "/api/history/clear",
        ):
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if urlparse(self.path).path in ("/api/live/start", "/api/live/place"):
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if urlparse(self.path).path == "/api/live/start":
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
        if urlparse(self.path).path == "/api/demo":
            target = str(STATIC_DIR.parent.parent / "fixtures" / "demo-globosite.json")
        if not target:
            self._send(400, b'{"error":"missing url"}', "application/json")
            return
        try:
            analysis = analyze(
                target,
                demo=(urlparse(self.path).path == "/api/demo"),
                use_llm=False if urlparse(self.path).path == "/api/demo" else bool(body.get("llm", True)),
                do_audit=bool(body.get("audit", False)),
                allow_chains=True if urlparse(self.path).path == "/api/demo" else bool(body.get("chains", True)),
                use_global=bool(body.get("global", True)),
                global_time_limit=float(body.get("global_timeout", 60)),
            )
            try:
                history.record(target, analysis,
                               demo=(urlparse(self.path).path == "/api/demo"))
            except Exception:  # noqa: BLE001 - history must never break a solve
                pass
            payload = analysis.to_json()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            payload = {"error": str(exc)}
            self._send(500, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
            return
        self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")


def serve(host: str = "127.0.0.1", port: int = 8765):
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    httpd = serve(host, port)
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
