"""SudokuPad payload decoding.

SudokuPad stores puzzles as a custom LZW-compressed, base64-ish string
(prefix ``scl``) that expands to a "zipped" JSON dialect (short keys,
unquoted keys, single quotes).  This module ports the two decoders used by
the official web app so that the tool has no external dependencies.
"""

from __future__ import annotations

import json
import re

# 65-character alphabet used by SudokuPad ('\\' replaced the usual '=').
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/\\"
_REV = {ch: i for i, ch in enumerate(_ALPHABET)}

# Property abbreviations produced by PuzzleZipper.
_PROP_REV = {
    "c": "color",
    "ca": "cages",
    "ct": "center",
    "c1": "borderColor",
    "c2": "backgroundColor",
    "ce": "cells",
    "cs": "cellSize",
    "a": "arrows",
    "o": "overlays",
    "u": "underlays",
    "w": "width",
    "h": "height",
    "v": "value",
    "vd": "videos",
    "l": "lines",
    "r": "rounded",
    "re": "regions",
    "fs": "fontSize",
    "th": "thickness",
    "hl": "headLength",
    "wp": "wayPoints",
    "t": "title",
    "te": "text",
    "d": "duration",
    "d2": "d",
}


def lzw_decompress(data: str) -> str:
    """Decompress the base64-like LZW stream used by ``scl`` payloads."""
    if not data:
        return ""

    state = {"val": _REV.get(data[0], 0), "position": 32, "index": 0}

    def read_bits(n: int) -> int:
        bits, power = 0, 1
        for _ in range(n):
            in_range = state["val"] & state["position"]
            state["position"] >>= 1
            if state["position"] == 0:
                state["position"] = 32
                state["index"] += 1
                ch = data[state["index"]] if state["index"] < len(data) else "\0"
                state["val"] = _REV.get(ch, 0)
            bits |= (1 if in_range else 0) * power
            power <<= 1
        return bits

    prefix = read_bits(2)
    if prefix == 2:
        return ""
    char = chr(read_bits(8 if prefix == 0 else 16))

    dictionary: list[str] = ["\0", "\1", "\2", char]
    enlarge_in = 4
    num_bits = 3
    word = char
    out = [char]

    while True:
        if state["index"] >= len(data) - 1:
            return "".join(out)
        code = read_bits(num_bits)
        if code == 0:
            dictionary.append(chr(read_bits(8)))
            code = len(dictionary) - 1
            enlarge_in -= 1
        elif code == 1:
            dictionary.append(chr(read_bits(16)))
            code = len(dictionary) - 1
            enlarge_in -= 1
        elif code == 2:
            return "".join(out)

        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

        if code < len(dictionary):
            entry = dictionary[code]
        elif code == len(dictionary):
            entry = word + word[0]
        else:
            raise ValueError(f"corrupt LZW stream (code {code})")

        out.append(entry)
        dictionary.append(word + entry[0])
        enlarge_in -= 1
        word = entry
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1


def _restore_quotes(text: str) -> str:
    if '"' in text:
        return text
    return text.replace("\\'", "\x00").replace("'", '"').replace("\x00", "'")


def unzip_payload(payload: str) -> dict:
    """Expand the "zipped" JSON dialect into a normal dict."""
    text = _restore_quotes(payload)

    parts = re.split(r'("(?:[^"\\]|\\.)*")', text)
    strings = [part for i, part in enumerate(parts) if i % 2]
    text = "".join(
        part if i % 2 == 0 else f'"__{{S{i // 2}}}__"' for i, part in enumerate(parts)
    )
    text = re.sub(r"([\,\{\[])([a-zA-Z0-9]+)\:", r'\1"\2":', text)
    text = re.sub(r"([\,\{\[])(?=[,\}\]])", r"\1_", text)
    text = re.sub(r"\{_\}", "{}", text)
    text = re.sub(r"([\,\{\[])_", r"\1{}", text)
    text = re.sub(r"(:)f([,\}\]])", r"\1false\2", text)
    text = re.sub(r"(:)t([,\}\]])", r"\1true\2", text)
    text = re.sub(r"(:)#0([,\}\]])", r'\1"#000000"\2', text)
    text = re.sub(r"(:)#F([,\}\]])", r'\1"#FFFFFF"\2', text)
    text = re.sub(r"(:)([0-9a-fA-F]{6})([,\}\]])", r'\1"#\2"\3', text)
    text = re.sub(r'"__\{S(\d+)\}__"', lambda m: strings[int(m.group(1))], text)

    return _restore_names(json.loads(text))


def _restore_names(obj):
    if isinstance(obj, list):
        # Do NOT drop empty objects: SudokuPad uses {} as a placeholder for an
        # empty cell, so removing them would shift every later column.
        return [_restore_names(v) for v in obj]
    if isinstance(obj, dict):
        return {_PROP_REV.get(k, k): _restore_names(v) for k, v in obj.items()}
    if isinstance(obj, str) and re.fullmatch(r"[0-9a-fA-F]{6}", obj):
        return "#" + obj
    return obj


def decode_payload(raw: str) -> dict:
    """Decode a raw ``scl...`` payload into a dict."""
    raw = raw.strip()
    for prefix in ("scl", "ctc"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return unzip_payload(lzw_decompress(raw))
