"""Layered local store: P1 rules, P2 analysis/steps, P3 rendered frames."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from threading import RLock
from pathlib import Path

LAYERS = ("puzzle", "rules", "steps", "frames")
DEFAULT_SETTINGS = {"max_rules": 1000, "max_steps": 1000, "max_frames": 100, "max_mb": 500}


def _root() -> Path:
    return Path(os.environ.get("YSUDOKU_STORE", Path.cwd() / ".cache" / "store"))


def _settings_path() -> Path:
    return _root() / "settings.json"


_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _safe_key(key: str) -> str:
    key = str(key or "")
    if not key or key in (".", "..") or not _KEY_RE.fullmatch(key):
        raise ValueError("invalid cache key")
    return key


def _entry_dir(key: str) -> Path:
    root = _root().resolve()
    candidate = (root / _safe_key(key)).resolve()
    if candidate.parent != root:
        raise ValueError("cache path escapes the store")
    return candidate


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
    return hashlib.sha1(str(target).strip().encode("utf-8")).hexdigest()[:16]


def hash_json(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def load_settings() -> dict:
    defaults = {
        key: max(0, int(os.environ.get(f"YSUDOKU_STORAGE_{key.upper()}", value)))
        for key, value in DEFAULT_SETTINGS.items()
    }
    return {**defaults, **_read_json(_settings_path(), {})}


class CountReductionDisabled(ValueError):
    pass


def save_settings(*, allow_count_reduction=True, **values) -> dict:
    with _META_LOCK:
        settings = load_settings()
        for name in DEFAULT_SETTINGS:
            if name in values:
                value = max(0, int(values[name]))
                if not allow_count_reduction and name != "max_mb" and value < settings[name]:
                    raise CountReductionDisabled()
                settings[name] = value
        _write_json(_settings_path(), settings)
        _prune()
        return settings


def _meta(key: str) -> dict:
    return _read_json(_meta_path(key), {})


_META_LOCK = RLock()
_PINNED = set()


def pin(key):
    with _META_LOCK:
        _PINNED.add(key)


def unpin(key):
    with _META_LOCK:
        _PINNED.discard(key)
        _prune()


def _update_meta(key: str, **values) -> dict:
    with _META_LOCK:
        meta = _meta(key)
        meta.update(values)
        meta["key"] = key
        _write_json(_meta_path(key), meta)
        return meta


def record_open(key, timestamp):
    with _META_LOCK:
        if timestamp > _meta(key).get("opened_at", 0):
            _update_meta(key, opened_at=timestamp)


def save_puzzle(key, raw):
    _write_json(_entry_dir(key) / "puzzle.json", raw)


def load_puzzle(key):
    value = _read_json(_entry_dir(key) / "puzzle.json", None)
    return value if isinstance(value, dict) else None


def save_rules(key: str, spec: dict, meta: dict) -> str:
    digest = hash_json(spec)
    _write_json(_entry_dir(key) / "rules.json", {"hash": digest, "spec": spec,
                                                "includes_underlay_markers": True})
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
    entry = _entry_dir(key)
    frames = (entry / "frames").resolve()
    if frames.parent != entry:
        raise ValueError("frames path escapes the store entry")
    return frames


def frame_path(key: str, step: int | str) -> Path:
    if not re.fullmatch(r"-?\d{1,7}", str(step)):
        raise ValueError("invalid frame index")
    return frames_dir(key) / f"{step}.png"


def has_frames(key: str, digest: str | None = None) -> bool:
    meta = _meta(key)
    if not frames_dir(key).exists():
        return False
    if digest and meta.get("frames_hash") != digest:
        return False
    return any(frames_dir(key).glob("*.png"))


def set_frames_hash(key: str, digest: str, *, proof_hash: str | None = None,
                    renderer: int | None = None) -> None:
    _update_meta(key, frames_hash=digest, frames_proof_hash=proof_hash,
                 frames_renderer=renderer, frames_at=time.time())
    prune()


def delete_layer(key: str, layer: str) -> None:
    if layer not in (*LAYERS, "all"):
        raise ValueError("invalid cache layer")
    if layer == "all":
        delete_entry(key)
    elif layer == "puzzle":
        (_entry_dir(key) / "puzzle.json").unlink(missing_ok=True)
    elif layer == "rules":
        (_entry_dir(key) / "rules.json").unlink(missing_ok=True)
        _update_meta(key, rules_hash=None, notes="")
        delete_layer(key, "steps")
    elif layer == "steps":
        (_entry_dir(key) / "analysis.json").unlink(missing_ok=True)
        _update_meta(key, steps_hash=None)
        shutil.rmtree(frames_dir(key), ignore_errors=True)
        _update_meta(key, frames_hash=None, frames_proof_hash=None, frames_renderer=None)
    elif layer == "frames":
        shutil.rmtree(frames_dir(key), ignore_errors=True)
        _update_meta(key, frames_hash=None, frames_proof_hash=None, frames_renderer=None)


def delete_entry(key: str) -> None:
    shutil.rmtree(_entry_dir(key), ignore_errors=True)


def set_favorite(key: str, favorite: bool) -> None:
    _update_meta(key, favorite=bool(favorite))


def _dir_size(path: Path) -> int:
    def file_size(file):
        try:
            return file.stat().st_size if not file.is_symlink() and file.is_file() else 0
        except FileNotFoundError:
            # A frame or layer may be replaced while a history request is reading it.
            return 0

    if path.is_symlink() or not path.is_dir():
        return file_size(path)
    return sum(file_size(file) for file in path.rglob("*"))


def entry_layers(key: str) -> dict:
    meta = _meta(key)
    rules = _entry_dir(key) / "rules.json"
    analysis = _entry_dir(key) / "analysis.json"
    return {
        "puzzle": (_entry_dir(key) / "puzzle.json").is_file(),
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
        if directory.is_symlink() or not directory.is_dir():
            continue
        key = directory.name
        meta = _meta(key)
        if not meta or "title" not in meta:
            continue
        layers = entry_layers(key)
        out.append({
            "key": key,
            "target": meta.get("target", ""),
            "demo": bool(meta.get("demo")),
            "title": meta.get("title", key),
            "author": meta.get("author", ""),
            "at": meta.get("at", 0),
            "opened_at": meta.get("opened_at", meta.get("at", 0)),
            "favorite": bool(meta.get("favorite")),
            "status": meta.get("status", ""),
            "steps_count": meta.get("steps_count", 0),
            "layers": layers,
            "sizes": {
                "puzzle": _dir_size(directory / "puzzle.json") if layers["puzzle"] else 0,
                "rules": _dir_size(_entry_dir(key) / "rules.json") if layers["rules"] else 0,
                "steps": _dir_size(_entry_dir(key) / "analysis.json") if layers["steps"] else 0,
                "frames": _dir_size(frames_dir(key)) if layers["frames"] else 0,
            },
        })
    out.sort(key=lambda item: item["at"], reverse=True)
    return out


def _storage_total():
    from . import history, rulecache, sudokupad

    cache = rulecache.cache_dir().parent
    raw = sudokupad._cache_file("example").parent
    paths = {_root().resolve(), cache.resolve(), raw.resolve(), history._path().resolve()}
    return sum(_dir_size(path) for path in paths if not any(parent in paths for parent in path.parents))


def storage_info(entries: list[dict] | None = None) -> dict:
    if entries is None:
        entries = list_entries()
    sizes = {layer: sum(item["sizes"][layer] for item in entries) for layer in LAYERS}
    return {
        "location": str(_root().resolve()),
        "settings": load_settings(),
        "counts": {layer: sum(item["layers"][layer] for item in entries) for layer in LAYERS},
        "sizes": sizes,
        "total": _storage_total(),
        "entries": len(entries),
    }


def capacity_error():
    with _META_LOCK:
        _prune()
        limit = load_settings()["max_mb"] * 1024 * 1024
        if limit:
            used = _storage_total()
            if used >= limit:
                return {"used_bytes": used, "limit_bytes": limit}
    return None


def _prunable(entries: list[dict], layer: str) -> list[dict]:
    candidates = [item for item in entries if item["layers"][layer] and item["key"] not in _PINNED]
    candidates.sort(key=lambda item: (item["opened_at"], item["at"], item["key"]))
    return candidates


def prune() -> None:
    with _META_LOCK:
        _prune()


def _prune() -> None:
    settings = load_settings()
    entries = list_entries()

    for layer, limit_name in (("frames", "max_frames"), ("steps", "max_steps"),
                              ("rules", "max_rules")):
        limit = settings.get(limit_name, 0)
        carrying = _prunable(entries, layer)
        while carrying and sum(item["layers"][layer] for item in entries) > limit:
            victim = carrying.pop(0)
            delete_layer(victim["key"], layer)
            if layer in ("rules", "steps") and not any(
                entry_layers(victim["key"])[name] for name in ("rules", "steps", "frames")
            ):
                delete_entry(victim["key"])
            entries = list_entries()
            carrying = _prunable(entries, layer)
