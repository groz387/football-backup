"""Contextual whole-story translation for recap scripts.

Translation is one request per language, with every scene plus the audited
match context. This preserves the relationship between each spoken line and
its statistic. Groq is the hosted translator; Gemini remains an optional
fallback. Hosted APIs still have quotas and rate limits.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from . import i18n
from .data import MatchBundle

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Llama 3.3 70B was retired on Groq (Aug 2026). GPT-OSS 120B is the production
# replacement and has usable developer-tier throughput. Qwen 3.8/3.6 are
# stronger at AZ/ES/RU but sit on a tight preview quota on this account.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MODEL_CANDIDATES = (
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
)
FIELDS = ("kicker", "title", "subtitle", "insight", "narration", "comment_bait")
_AZ_WORDS = {"oyun", "qapandi", "qapandı", "bax", "sizcə", "götünə", "gijdıllax", "sikirdilər"}
_ES_WORDS = {"partido", "quién", "ganó", "mira", "gol", "tiros"}
_GROQ_PROVIDERS = {"auto", "groq", "deepseek"}


@dataclass
class TranslationResult:
    scenes: list[dict[str, Any]]
    provider: str
    ok: bool
    warnings: list[str]


def detect_language(text: str) -> tuple[str, float]:
    """Short-copy detector for exact operator hook/bait preservation."""
    raw = str(text or "").strip()
    lower = raw.casefold()
    if re.search(r"[\u0400-\u04ff]", raw):
        return "ru", 0.98
    if any(ch in lower for ch in "əğı") or set(re.findall(r"[^\W\d_]+", lower)) & _AZ_WORDS:
        return "az", 0.94
    if set(re.findall(r"[^\W\d_]+", lower)) & _ES_WORDS or any(ch in lower for ch in "ñ¿¡"):
        return "es", 0.88
    return "en", 0.60


def _digits(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,:%+\-/]\d+)*", str(value or ""))


def _protected_names(bundle: MatchBundle, audit: dict[str, Any]) -> list[str]:
    names = [bundle.home, bundle.away]
    for row in audit.get("goal_timeline") or []:
        names.extend([str(row.get("scorer") or ""), str(row.get("assist") or "")])
    return [name for name in dict.fromkeys(names) if len(name.strip()) >= 2]


def match_context(bundle: MatchBundle, audit: dict[str, Any]) -> dict[str, Any]:
    """Only audited context is sent to translators."""
    return {
        "home": bundle.home,
        "away": bundle.away,
        "score": audit.get("match", {}).get("score_display"),
        "competition": bundle.competition_line(),
        "facts": audit.get("facts") or [],
        "team_stats": audit.get("team_stats") or {},
        "goal_timeline": audit.get("goal_timeline") or [],
        "definitions": audit.get("definitions") or {},
        "blocked_claims": audit.get("data_health", {}).get("blocked_claims") or [],
    }


def translation_payload(
    scenes: list[dict[str, Any]],
    target: str,
    bundle: MatchBundle,
    audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task": (
            f"Translate this COMPLETE football recap into {i18n.language_name(target)} "
            f"(`{target}`) as one coherent script."
        ),
        "match_context": match_context(bundle, audit),
        "protected_names": _protected_names(bundle, audit),
        "rules": [
            "Translate every scene in context; do not translate isolated phrases independently.",
            "Each analysis narration must remain directly about that scene's audited statistic.",
            "Preserve every digit, scoreline, minute and percentage exactly.",
            "Preserve team and player names exactly.",
            "Do not add facts, causal claims, xG, possession, coordinates or conclusions.",
            "Keep analysis narration compact: normally 14–20 spoken words, one evidence-rich sentence.",
            "Keep the hook sharp and the closing question natural in the target culture.",
            "No English leftovers except proper names and established football abbreviations.",
            "Return exactly one object for every input scene id, in the same order.",
            "Return JSON only.",
        ],
        "scenes": [
            {
                "id": scene["id"],
                "visualization": scene.get("visualization"),
                **{field: scene.get(field, "") for field in FIELDS},
                "lines": list(scene.get("lines") or []),
            }
            for scene in scenes
        ],
        "response_schema": {
            "scenes": [
                {
                    "id": "same id",
                    **{field: "translated string" for field in FIELDS},
                    "lines": ["translated hook line"],
                }
            ]
        },
    }


def _parse_json_content(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("translator JSON was not an object")
    return parsed


def _model_error(status: int, body: str) -> bool:
    if status not in {400, 404}:
        return False
    lower = (body or "").lower()
    return any(
        token in lower
        for token in ("model", "decommission", "not found", "does not exist", "unknown")
    )


class GroqTranslator:
    """OpenAI-compatible Groq chat client for one whole-script translation."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("GROQ_API_KEY") or "").strip()
        self.model = (
            model or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL
        ).strip() or DEFAULT_GROQ_MODEL
        self.enabled = bool(self.api_key)
        self.last_error = ""
        self.last_model = ""

    def _models(self) -> list[str]:
        ordered: list[str] = []
        for name in (self.model, *GROQ_MODEL_CANDIDATES):
            token = str(name or "").strip()
            if token and token not in ordered:
                ordered.append(token)
        return ordered

    def translate(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        errors: list[str] = []
        for model in self._models():
            parsed = self._translate_with(model, payload)
            if parsed is not None:
                self.last_model = model
                self.last_error = ""
                return parsed
            errors.append(f"{model}: {self.last_error or 'failed'}")
        self.last_error = " | ".join(errors)
        return None

    def _translate_with(self, model: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.25,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a native football editor. Return strict JSON. "
                                "Never invent a number or match fact."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
                timeout=120,
            )
            if not response.ok:
                snippet = (response.text or "")[:240]
                self.last_error = f"HTTP {response.status_code} {snippet}"
                if _model_error(response.status_code, snippet):
                    return None
                return None
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_json_content(content)
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


# Old settings/tests used this name. Groq is the live client.
DeepSeekTranslator = GroqTranslator


def _merge_and_validate(
    source: list[dict[str, Any]],
    translated: dict[str, Any],
    bundle: MatchBundle,
    audit: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = translated.get("scenes") if isinstance(translated, dict) else None
    if not isinstance(rows, list):
        return source, ["translator returned no scenes"]
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    protected = _protected_names(bundle, audit)
    warnings: list[str] = []
    out: list[dict[str, Any]] = []
    for scene in source:
        scene_id = str(scene.get("id"))
        row = by_id.get(scene_id)
        if not row:
            warnings.append(f"{scene_id}: missing from translation")
            out.append(dict(scene))
            continue
        updated = dict(scene)
        for field in FIELDS:
            before = str(scene.get(field) or "")
            after = str(row.get(field) or "").strip()
            if not before:
                updated[field] = ""
                continue
            if not after:
                warnings.append(f"{scene_id}.{field}: empty translation")
                continue
            if _digits(before) != _digits(after):
                warnings.append(f"{scene_id}.{field}: digit lock failed")
                continue
            required_names = [name for name in protected if name.casefold() in before.casefold()]
            if any(name.casefold() not in after.casefold() for name in required_names):
                warnings.append(f"{scene_id}.{field}: name lock failed")
                continue
            updated[field] = after
        if isinstance(scene.get("lines"), list) and isinstance(row.get("lines"), list):
            updated["lines"] = [str(value).strip() for value in row["lines"] if str(value).strip()]
        out.append(updated)
    return out, warnings


def translate_story(
    scenes: list[dict[str, Any]],
    target_language: str,
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    provider: str = "auto",
    gemini: Any | None = None,
    groq: GroqTranslator | None = None,
    deepseek: GroqTranslator | None = None,
    force: bool = False,
) -> TranslationResult:
    target = i18n.normalize_language(target_language)
    if target == "en" and not force:
        return TranslationResult([dict(scene) for scene in scenes], "source", True, [])
    payload = translation_payload(scenes, target, bundle, audit)
    choice = str(provider or "auto").strip().lower()
    if choice == "deepseek":
        choice = "groq"
    parsed: dict[str, Any] | None = None
    used = ""
    client = groq or deepseek or GroqTranslator()
    if choice in _GROQ_PROVIDERS and client.enabled:
        parsed = client.translate(payload)
        used = "groq"
    if not parsed and choice in {"auto", "gemini"} and gemini is not None and getattr(gemini, "enabled", False):
        fn = getattr(gemini, "translate_contextual_script", None)
        if callable(fn):
            parsed = fn(payload)
            used = "gemini"
    if parsed:
        merged, warnings = _merge_and_validate(scenes, parsed, bundle, audit)
        return TranslationResult(merged, used, not warnings, warnings)
    # Conservative fallback translates catalog/template lines only. It is
    # explicitly marked partial so Studio can require human approval.
    offline = i18n.localize_scenes_offline(scenes, target)
    extra = []
    if choice in _GROQ_PROVIDERS and getattr(client, "last_error", ""):
        extra.append(f"Groq: {client.last_error}")
    return TranslationResult(
        offline,
        "offline_partial",
        False,
        extra + [
            "No contextual translation API was available. Known templates were localized, "
            "but free-form narration requires review."
        ],
    )
