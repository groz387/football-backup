"""Contextual whole-story translation for recap scripts.

Translation is one request per language, with every scene plus the audited
match context. This preserves the relationship between each spoken line and
its statistic. DeepSeek is optional; it is not described as unlimited because
all hosted APIs have quotas/rate limits.
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

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
FIELDS = ("kicker", "title", "subtitle", "insight", "narration", "comment_bait")


@dataclass
class TranslationResult:
    scenes: list[dict[str, Any]]
    provider: str
    ok: bool
    warnings: list[str]


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


class DeepSeekTranslator:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("DEEPSEEK_API_KEY") or "").strip()
        self.model = (model or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()
        self.enabled = bool(self.api_key)
        self.last_error = ""

    def translate(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            response = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
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
                self.last_error = f"HTTP {response.status_code}"
                return None
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


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
    deepseek: DeepSeekTranslator | None = None,
) -> TranslationResult:
    target = i18n.normalize_language(target_language)
    if target == "en":
        return TranslationResult([dict(scene) for scene in scenes], "source", True, [])
    payload = translation_payload(scenes, target, bundle, audit)
    choice = str(provider or "auto").strip().lower()
    parsed: dict[str, Any] | None = None
    used = ""
    ds = deepseek or DeepSeekTranslator()
    if choice in {"auto", "deepseek"} and ds.enabled:
        parsed = ds.translate(payload)
        used = "deepseek"
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
    return TranslationResult(
        offline,
        "offline_partial",
        False,
        [
            "No contextual translation API was available. Known templates were localized, "
            "but free-form narration requires review."
        ],
    )
