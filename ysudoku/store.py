"""Layered local store: P1 rules, P2 analysis/steps, P3 rendered frames."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

LAYERS = ("rules", "steps", "frames")


def _root() -> Path:
    return Path(os.environ.get("YSUDOKU_STORE", Path.cwd() / ".cache" / "store"))


def _settings_path() -> Path:
    return _root() / "settings.json"


def _entry_dir(key: str) -> Path:
    return _root() / key


def _meta_path(key: str) -> Path:
    return _entry_dir(key) / "meta.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def key_for(target: str) -> str:
    return hashlib.sha1(str(target).strip().lower().encode("utf-8")).hexdigest()[:16]


def hash_json(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def load_settings() -> dict:
    defaults = {"max_rules": 100, "max_steps": 100, "max_frames": 10, "max_mb": 500}
    defaults.update(_read_json(_settings_path(), {}))
    return defaults


def save_settings(**values) -> dict:
    settings = load_settings()
    for name in ("max_rules", "max_steps", "max_frames", "max_mb"):
        if name in values:
            settings[name] = max(0, int(values[name]))
    _write_json(_settings_path(), settings)
    prune()
    return settings


def _meta(key: str) -> dict:
    return _read_json(_meta_path(key), {})


def _update_meta(key: str, **values) -> dict:
    meta = _meta(key)
    meta.update(values)
    meta["key"] = key
    _write_json(_meta_path(key), meta)
    return meta


def save_rules(key: str, spec: dict, meta: dict) -> str:
    digest = hash_json(spec)
    _write_json(_entry_dir(key) / "rules.json", {"hash": digest, "spec": spec})
    _update_meta(key, rules_hash=digest, **meta)
    prune()
    return digest


def load_rules(key: str) -> dict | None:
    value = _read_json(_entry_dir(key) / "rules.json", None)
    return value if isinstance(value, dict) and value.get("spec") else None


def save_analysis(key: str, payload: dict, meta: dict) -> str:
    digest = hash_json(payload.get("steps", []))
    _write_json(_entry_dir(key) / "analysis.json", payload)
    _update_meta(key, steps_hash=digest, **meta)
    prune()
    return digest


def load_analysis(key: str) -> dict | None:
    value = _read_json(_entry_dir(key) / "analysis.json", None)
    return value if isinstance(value, dict) else None


def steps_hash(key: str) -> str | None:
    return _meta(key).get("steps_hash")


def frames_dir(key: str) -> Path:
    return _entry_dir(key) / "frames"


def frame_path(key: str, step: int | str) -> Path:
    return frames_dir(key) / f"{step}.png"


def has_frames(key: str, digest: str | None = None) -> bool:
    meta = _meta(key)
    if not frames_dir(key).exists():
        return False
    if digest and meta.get("frames_hash") != digest:
        return False
    return any(frames_dir(key).glob("*.png"))


def set_frames_hash(key: str, digest: str) -> None:
    _update_meta(key, frames_hash=digest, frames_at=time.time())
    prune()


def delete_layer(key: str, layer: str) -> None:
    if layer == "rules":
        ( _entry_dir(key) / "rules.json").unlink(missing_ok=True)
        _update_meta(key, rules_hash=None)
    elif layer == "steps":
        (_entry_dir(key) / "analysis.json").unlink(missing_ok=True)
        _update_meta(key, steps_hash=None)
        shutil.rmtree(frames_dir(key), ignore_errors=True)
        _update_meta(key, frames_hash=None)
    elif layer == "frames":
        shutil.rmtree(frames_dir(key), ignore_errors=True)
        _update_meta(key, frames_hash=None)


def delete_entry(key: str) -> None:
    shutil.rmtree(_entry_dir(key), ignore_errors=True)


def set_favorite(key: str, favorite: bool) -> None:
    _update_meta(key, favorite=bool(favorite))


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def entry_layers(key: str) -> dict:
    meta = _meta(key)
    rules = _entry_dir(key) / "rules.json"
    analysis = _entry_dir(key) / "analysis.json"
    return {
        "rules": rules.exists(),
        "steps": analysis.exists(),
        "frames": has_frames(key),
        "rules_hash": meta.get("rules_hash"),
        "steps_hash": meta.get("steps_hash"),
        "frames_hash": meta.get("frames_hash"),
    }


def list_entries() -> list[dict]:
    root = _root()
    if not root.exists():
        return []
    out = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        key = directory.name
        meta = _meta(key)
        if not meta:
            continue
        layers = entry_layers(key)
        out.append({
            "key": key,
            "target": meta.get("target", ""),
            "demo": bool(meta.get("demo")),
            "title": meta.get("title", key),
            "author": meta.get("author", ""),
            "at": meta.get("at", 0),
            "favorite": bool(meta.get("favorite")),
            "status": meta.get("status", ""),
            "steps_count": meta.get("steps_count", 0),
            "layers": layers,
            "sizes": {
                "rules": _dir_size(_entry_dir(key) / "rules.json") if layers["rules"] else 0,
                "steps": _dir_size(_entry_dir(key) / "analysis.json") if layers["steps"] else 0,
                "frames": _dir_size(frames_dir(key)) if layers["frames"] else 0,
            },
        })
    out.sort(key=lambda item: item["at"], reverse=True)
    return out


def storage_info() -> dict:
    entries = list_entries()
    sizes = {layer: sum(item["sizes"][layer] for item in entries) for layer in ("rules", "steps", "frames")}
    return {
        "location": str(_root().resolve()),
        "settings": load_settings(),
        "counts": {layer: sum(1 for item in entries if item["layers"][layer]) for layer in ("rules", "steps", "frames")},
        "sizes": sizes,
        "total": sum(sizes.values()),
        "entries": len(entries),
    }


def _prunable(entries: list[dict], layer: str) -> list[dict]:
    candidates = [item for item in entries if item["layers"][layer]]
    candidates.sort(key=lambda item: (item["favorite"], item["at"]))
    return candidates


def prune() -> None:
    settings = load_settings()
    entries = list_entries()

    for layer, limit_name in (("frames", "max_frames"), ("steps", "max_steps")):
        limit = settings.get(limit_name, 0)
        carrying = _prunable(entries, layer)
        while len(carrying) > limit:
            victim = carrying.pop(0)
            delete_layer(victim["key"], layer)
            entries = list_entries()
            carrying = _prunable(entries, layer)

    max_bytes = settings.get("max_mb", 0) * 1024 * 1024
    if max_bytes > 0:
        entries = list_entries()

        def total() -> int:
            return sum(sum(item["sizes"].values()) for item in entries)

        while total() > max_bytes:
            victim = None
            for layer in ("frames", "steps"):
                pool = _prunable(entries, layer)
                if pool:
                    victim = (pool[0], layer)
                    break
            if victim is None:
                break
            delete_layer(victim[0]["key"], victim[1])
            entries = list_entries()
