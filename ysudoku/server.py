"""Local web server (stdlib only)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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
        if urlparse(self.path).path not in ("/api/solve", "/api/demo"):
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        target = (body.get("url") or "").strip()
        if urlparse(self.path).path == "/api/demo":
            target = str(STATIC_DIR.parent.parent / "fixtures" / "demo-killer.json")
        if not target:
            self._send(400, b'{"error":"missing url"}', "application/json")
            return
        try:
            analysis = analyze(
                target,
                use_llm=bool(body.get("llm", True)),
                do_audit=bool(body.get("audit", False)),
                allow_chains=bool(body.get("chains", False)),
            )
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
