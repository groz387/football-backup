"""Parse model JSON that may include fences, leading prose, or a second object."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_END = re.compile(r"\s*```\s*$")


def strip_fences(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = _FENCE.sub("", text)
        text = _FENCE_END.sub("", text)
    return text.strip()


def loads_model_json(raw: str) -> dict[str, Any]:
    """Load the first complete JSON value from a model response.

    Gemini sometimes returns a valid object and then another object or
    commentary. ``json.loads`` of first-brace-to-last-brace then fails with
    ``Extra data``. ``raw_decode`` keeps the first value and ignores the rest.
    A top-level array is wrapped as ``{"scenes": [...]}``.
    """
    text = strip_fences(raw)
    if not text:
        raise json.JSONDecodeError("empty model JSON", raw or "", 0)

    start = -1
    for index, char in enumerate(text):
        if char in "{[":
            start = index
            break
    if start < 0:
        raise json.JSONDecodeError("no JSON value in model response", text, 0)

    decoder = json.JSONDecoder()
    obj, end = decoder.raw_decode(text[start:])
    if isinstance(obj, list):
        return {"scenes": obj}
    if not isinstance(obj, dict):
        raise ValueError(f"model JSON was {type(obj).__name__}, not an object")

    rest = text[start + end :].strip()
    if "scenes" not in obj and rest[:1] in "{[":
        try:
            extra, _ = decoder.raw_decode(rest)
        except json.JSONDecodeError:
            extra = None
        if isinstance(extra, dict) and extra.get("scenes"):
            return extra
        if isinstance(extra, list):
            return {"scenes": extra}
    return obj


def extract_json(raw: str) -> str:
    """Back-compat helper: return the first complete JSON text blob."""
    text = strip_fences(raw)
    start = min((i for i, ch in enumerate(text) if ch in "{["), default=-1)
    if start < 0:
        return text
    decoder = json.JSONDecoder()
    try:
        _, end = decoder.raw_decode(text[start:])
        return text[start : start + end]
    except json.JSONDecodeError:
        close = max(text.rfind("}"), text.rfind("]"))
        if close > start:
            return text[start : close + 1]
        return text
