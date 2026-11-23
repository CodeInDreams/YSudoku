"""Admission and durable daily accounting for the public web service."""
from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
from datetime import datetime
from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock
import time
from zoneinfo import ZoneInfo

from . import store
from .llm import LLMError
from .config import env_flag


PROMPT_LIMIT = 1000


class Rejected(Exception):
    def __init__(self, status, code, **details):
        self.status = status
        self.payload = {"error": code, "code": code, **details}


class LLMBudgetExceeded(LLMError):
    pass


def _number(name):
    value = int(os.environ.get("YSUDOKU_" + name, "0"))
    if value < 0:
        raise ValueError("YSUDOKU_" + name + " must be nonnegative")
    return value


def _networks(text):
    return tuple(ip_network(value, strict=False) for value in re.split(r"[,\s]+", text) if value)


def _address(value):
    result = ip_address(value.strip())
    if getattr(result, "scope_id", None):
        raise ValueError("IP scope is unsupported")
    return getattr(result, "ipv4_mapped", None) or result


def _log(**fields):
    print(json.dumps({"time": datetime.now().astimezone().isoformat(), **fields},
                     ensure_ascii=False), flush=True)


class Limits:
    def __init__(self, root):
        self.concurrent = _number("MAX_CONCURRENT")
        self.per_ip = _number("DAILY_SOLVES_PER_IP")
        self.allow_settings = env_flag("YSUDOKU_ALLOW_STORAGE_SETTINGS", True)
        self.allow_delete = env_flag("YSUDOKU_ALLOW_DELETE", True)
        self.input_limit = _number("DAILY_LLM_INPUT_TOKENS")
        self.output_limit = _number("DAILY_LLM_OUTPUT_TOKENS")
        self.zone = ZoneInfo(os.environ.get("YSUDOKU_QUOTA_TIMEZONE", "Asia/Shanghai"))
        self.proxies = _networks(os.environ.get("YSUDOKU_TRUSTED_PROXIES", ""))
        self.ip_header = os.environ.get("YSUDOKU_PROXY_IP_HEADER", "CF-Connecting-IP")
        if self.ip_header.lower() not in ("cf-connecting-ip", "x-real-ip"):
            raise ValueError("YSUDOKU_PROXY_IP_HEADER must be CF-Connecting-IP or X-Real-IP")
        self.inline_bans = _networks(os.environ.get("YSUDOKU_BANNED_IPS", ""))
        self.ban_file = os.environ.get("YSUDOKU_BAN_FILE", "")
        self.bans = self.inline_bans
        self.bans_checked = -float("inf")
        self.lock = Lock()
        self.llm_lock = Lock()
        self.active = {}
        self.database = Path(root) / "usage.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quota (
                    day TEXT, subject TEXT, count INTEGER, PRIMARY KEY (day, subject)
                );
            """)
        self._reload_bans()

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self.database, timeout=15)) as db, db:
            yield db

    @staticmethod
    def _used(db, day, subject):
        row = db.execute("SELECT count FROM quota WHERE day=? AND subject=?", (day, subject)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _add(db, day, subject, count):
        db.execute("""INSERT INTO quota VALUES(?,?,?)
                      ON CONFLICT (day,subject) DO UPDATE SET count=count+excluded.count""",
                   (day, subject, count))

    def day(self):
        return datetime.now(self.zone).date().isoformat()

    def _reload_bans(self):
        if not self.ban_file or time.monotonic() - self.bans_checked < 300:
            return
        self.bans_checked = time.monotonic()
        try:
            lines = Path(self.ban_file).read_text(encoding="utf-8").splitlines()
            self.bans = self.inline_bans + _networks(" ".join(line.split("#", 1)[0] for line in lines))
        except (OSError, ValueError):
            _log(event="ban_reload_failed")

    def client_ip(self, peer, headers):
        address = _address(peer)
        if any(address in network for network in self.proxies):
            forwarded = headers.get_all(self.ip_header, [])
            if len(forwarded) == 1:
                try:
                    address = _address(forwarded[0])
                except ValueError:
                    pass
        return str(address)

    def refresh_bans(self):
        if not self.ban_file or time.monotonic() - self.bans_checked < 300:
            return
        with self.lock:
            self._reload_bans()

    def banned(self, ip):
        self.refresh_bans()
        address = _address(ip)
        return any(address in network for network in self.bans)

    def usage(self, ip):
        day = self.day()
        with self._db() as db:
            used = self._used(db, day, ip) if self.per_ip else 0
        return {"limit": self.per_ip, "remaining": max(0, self.per_ip - used),
                "day": day, "timezone": str(self.zone)}

    def acquire(self, work, *, solve):
        with self.lock:
            full = self.concurrent and len(self.active) >= self.concurrent
            same = self.active.get(work.key)
            if full or same:
                now = time.monotonic()
                raise Rejected(429, "server_busy" if full else "puzzle_busy", limit=self.concurrent, jobs=[
                    {"title": item.title, "seconds": int(now - item.started)}
                    for item in (self.active.values() if full else (same,))
                ])
            if capacity := store.capacity_error():
                raise Rejected(507, "storage_limit_exceeded", **capacity)
            if solve and self.per_ip:
                day = self.day()
                with self._db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    used = self._used(db, day, work.ip)
                    if used >= self.per_ip:
                        raise Rejected(429, "daily_solves_exceeded", quota={
                            "limit": self.per_ip, "remaining": 0, "day": day, "timezone": str(self.zone),
                        })
                    self._add(db, day, work.ip, 1)
            work.started = time.monotonic()
            store.pin(work.key)
            self.active[work.key] = work

    def exhausted(self):
        with self._db() as db:
            return self._exhausted(db, self.day())

    def _exhausted(self, db, day):
        return ((self.input_limit and self._used(db, day, "llm-input") >= self.input_limit)
                or (self.output_limit and self._used(db, day, "llm-output") >= self.output_limit))

    def llm_request(self, work, send):
        # Under a configured budget, only one provider request can cross the threshold.
        with self.llm_lock if self.input_limit or self.output_limit else nullcontext():
            day = self.day()
            with self._db() as db:
                if self._exhausted(db, day):
                    work.llm_fallback = True
                    raise LLMBudgetExceeded("daily LLM token allowance exhausted")
                remaining = (self.output_limit - self._used(db, day, "llm-output")
                             if self.output_limit else None)
            data = None
            try:
                data = send(remaining)
                return data
            finally:
                usage = data.get("usage") if isinstance(data, dict) else None
                if not isinstance(usage, dict):
                    usage = {}
                tokens = [usage.get(key) for key in ("prompt_tokens", "completion_tokens")]
                tokens = [value if type(value) is int and value >= 0 else None for value in tokens]
                with self._db() as db:
                    for subject, value, limit in zip(
                        ("llm-input", "llm-output"), tokens, (self.input_limit, self.output_limit)
                    ):
                        # A response without usage cannot be safely budgeted.
                        self._add(db, day, subject, value if value is not None else limit)
                _log(event="llm", puzzle=work.title, input_tokens=tokens[0], output_tokens=tokens[1])


class Work:
    def __init__(self, limits, ip, key, title):
        self.limits, self.ip, self.key, self.title = limits, ip, key, title
        self.started = None
        self.received = datetime.now().astimezone().isoformat()
        self.llm_fallback = False

    def acquire(self, *, solve):
        self.limits.acquire(self, solve=solve)

    def release(self):
        with self.limits.lock:
            if self.limits.active.get(self.key) is self:
                del self.limits.active[self.key]
                store.unpin(self.key)

    def llm_request(self, send):
        return self.limits.llm_request(self, send)

    def log(self):
        _log(event="write", time=self.received, ip=self.ip, puzzle=self.title)
