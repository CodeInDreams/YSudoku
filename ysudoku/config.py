"""Typed deployment settings, with fallback to legacy environment variables."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.request import ProxyHandler, build_opener


def env_flag(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be 0 or 1")


def read_config(path) -> dict[str, str | None]:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    schema = json.loads(Path(__file__).with_name("config_schema.json").read_text(encoding="utf-8"))
    with Path(path).open("rb") as config:
        document = tomllib.load(config)
    environment = {}
    for section, values in document.items():
        if section not in schema or not isinstance(values, dict):
            raise ValueError(f"Unknown or invalid configuration table [{section}]")
        for key, value in values.items():
            if key not in schema[section]:
                raise ValueError(f"Unknown configuration key {section}.{key}")
            name, kind = schema[section][key]
            converted = _convert_value(kind, value)
            if converted is False:
                raise ValueError(f"{section}.{key} must be {kind.replace('_', ' ')}")
            environment[name] = converted
    return environment


def _convert_value(kind, value):
    if kind in ("string", "optional_string"):
        if isinstance(value, str) and "\x00" not in value and "\n" not in value:
            return None if not value and kind == "optional_string" else value
    elif kind == "boolean" and type(value) is bool:
        return str(int(value))
    elif kind == "strings" and isinstance(value, list):
        if all(isinstance(item, str) and item and not any(ch.isspace() or ch in ",\x00" for ch in item)
               for item in value):
            return ",".join(value)
    elif kind == "positive_number" and type(value) in (int, float):
        if 0 < value < math.inf:
            return str(value)
    elif type(value) is int:
        if kind == "port" and 1 <= value <= 65535:
            return str(value)
        if kind in ("integer", "auto_integer") and value >= 0:
            return "" if kind == "auto_integer" and value == 0 else str(value)
    return False


def apply_config(values):
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def bind_address(values):
    return (values.get("YSUDOKU_HTTP_HOST", os.environ.get("YSUDOKU_HTTP_HOST", "127.0.0.1")),
            int(values.get("YSUDOKU_HTTP_PORT", os.environ.get("YSUDOKU_HTTP_PORT", "8765"))))


def _wait_http(values):
    host, port = bind_address(values)
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    authority = f"[{host}]" if ":" in host else host
    url = f"http://{authority}:{port}/api/health"
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as response:
                if json.load(response).get("ok") is True:
                    return 0
        except (OSError, ValueError):
            time.sleep(0.35)
    print(f"YSudoku health check failed at {url}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wait for YSudoku HTTP startup")
    parser.add_argument("--wait-http", required=True, metavar="CONFIG")
    args = parser.parse_args()
    raise SystemExit(_wait_http(read_config(args.wait_http)))
