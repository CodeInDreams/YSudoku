"""Minimal OpenAI-compatible client used to compile rule text into JSON."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

SYSTEM_PROMPT = """You are a precise rule compiler for variant sudoku puzzles.
You receive (1) the official rules text and (2) an inventory of every element
drawn on the board, each with a stable id.  Translate the rules into the JSON
spec below.  Reference elements only by id.  Never invent a constraint that the
rules text does not state, and never skip a constraint that it does state.

Schema:
{
  "rules": [
    {"kind": "cage" | "thermo" | "arrow" | "kropki" | "xv" | "quadruple" |
             "palindrome" | "renban" | "german_whisper" | "dutch_whisper" |
             "between" | "consecutive" | "little_killer",
     "elements": ["<element id>", ...],
     "variant": "black" | "white",     // kropki only
     "sum": 15,                        // xv / little_killer only
     "note": "why this rule applies"}
  ],
  "globals": [
    {"kind": "anti_knight" | "anti_king" | "diagonal", "direction": "main" | "anti" | "both"}
  ],
  "ignored": [{"element": "<element id>", "why": "decoration / already covered"}],
  "notes": "short summary of your interpretation"
}

Rules:
- The rules text is authoritative. Colours, thicknesses and sizes are hints only.
- A line that the text calls a "German Whisper" is german_whisper even if it is
  not green; "Renban" is renban; "Palindrome" is palindrome, etc.
- Dots: "white dot" = consecutive = variant "white"; "black dot" = ratio 1:2 =
  variant "black".  If the text inverts this, follow the text.
- Quadruple circles: digits written in the circle must appear in the four cells
  around it.  A "?" is unknown and must be skipped.
- A cage with a number is killer.  A cage without a number is only a region
  outline: skip it.
- "Arrow" means the digit in the circle equals the sum of the digits on the arm.
- Put every non-cosmetic element you did not use into "ignored" with a reason.
- Output valid JSON only, no markdown fences, no commentary.
"""


@dataclass
class LLMConfig:
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-chat"
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "LLMConfig | None":
        key = (
            os.environ.get("SUDOKU_LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if not key:
            return None
        return cls(
            base_url=os.environ.get("SUDOKU_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            api_key=key,
            model=os.environ.get("SUDOKU_LLM_MODEL", "deepseek-chat"),
            timeout=float(os.environ.get("SUDOKU_LLM_TIMEOUT", "60")),
        )


class LLMError(RuntimeError):
    pass


def available(config: "LLMConfig | None" = None) -> bool:
    """True when an OpenAI-compatible endpoint is configured."""
    return (config or LLMConfig.from_env()) is not None


def _post(config: LLMConfig, payload: dict) -> dict:
    url = config.base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:  # noqa: BLE001 - network errors are surfaced to the user
        raise LLMError(str(exc)) from exc


def chat(config: LLMConfig, messages: list[dict], temperature: float = 0.0) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    data = _post(config, payload)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"unexpected response: {data}") from exc


def parse_json_reply(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("reply did not contain JSON")
    return json.loads(text[start:end + 1])


def compile_rules(
    config: LLMConfig,
    rules_text: str,
    inventory: list[dict],
    size: int,
    previous: list[dict] | None = None,
) -> dict:
    """Ask the model for a rule spec.  ``previous`` replays repair feedback."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Grid size: {size}x{size}\n\n"
                f"=== OFFICIAL RULES ===\n{rules_text}\n\n"
                "=== DRAWN ELEMENTS ===\n"
                + json.dumps(inventory, ensure_ascii=False)
            ),
        },
    ]
    if previous:
        messages.extend(previous)
    last_error = ""
    for attempt in range(3):
        reply = chat(config, messages)
        try:
            spec = parse_json_reply(reply)
        except Exception as exc:  # noqa: BLE001
            last_error = f"invalid JSON: {exc}"
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"Your reply was not valid JSON ({exc}). Reply again with JSON only."})
            continue
        try:
            return spec
        except Exception as exc:  # pragma: no cover - defensive
            last_error = str(exc)
        time.sleep(0.3)
    raise LLMError(f"failed to compile rules: {last_error}")
