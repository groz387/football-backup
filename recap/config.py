"""Farm config: languages, ElevenLabs, env. Never logs secret values."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Premade "Liam" is TX3LPaxmHKxFdv7VOQHJ. The library voice
# "Liam Callahan - Witty Media Person" is resolved by name search at runtime
# and cached in ELEVENLABS_VOICE_ID when found.
DEFAULT_VOICE_NAME = "Liam Callahan - Witty Media Person"
FALLBACK_VOICE_ID = "TX3LPaxmHKxFdv7VOQHJ"
DEFAULT_MODEL = "eleven_v3"
MODEL_CANDIDATES = ("eleven_v3", "eleven_multilingual_v2", "eleven_turbo_v2_5")
ELEVEN_STYLES = ("robust", "normal")

FARM_LANGUAGES = ("az", "en", "es", "ru", "tr")
DEFAULT_STUDIO_LANGUAGES = ("az", "en", "es")


def _csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw).replace(";", ",").split(","):
        token = part.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or default).strip()


@dataclass
class ElevenSlot:
    """One API key and the optional proxy that rides with it."""

    api_key: str
    proxy: str | None = None
    index: int = 0

    def redacted(self) -> str:
        key = self.api_key
        if len(key) < 8:
            return "****"
        return f"{key[:4]}…{key[-3:]}#{self.index}"


@dataclass
class ElevenConfig:
    slots: list[ElevenSlot] = field(default_factory=list)
    voice_id: str = ""
    voice_name: str = DEFAULT_VOICE_NAME
    model: str = DEFAULT_MODEL
    style: str = "robust"

    @property
    def enabled(self) -> bool:
        return bool(self.slots)

    def slot_count(self) -> int:
        return len(self.slots)


def eleven_style(value: str | None) -> str:
    raw = (value or "robust").strip().lower()
    aliases = {"robust": "robust", "stable": "robust", "normal": "normal", "natural": "normal"}
    if raw not in aliases:
        raise ValueError(f"Unknown ElevenLabs style {value!r}. Use robust or normal.")
    return aliases[raw]


def style_voice_settings(style: str) -> dict[str, Any]:
    """Map robust|normal onto v3 stability.

    Eleven v3 documents Creative / Natural / Robust as the stability slider.
    Robust ≈ high stability (less tag-reactive, consistent). Normal ≈ Natural.
    """
    kind = eleven_style(style)
    if kind == "robust":
        return {
            "stability": 0.85,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        }
    return {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.15,
        "use_speaker_boost": True,
    }


def load_eleven_config() -> ElevenConfig:
    keys = _csv(_env("ELEVENLABS_API_KEYS"))
    single = _env("ELEVENLABS_API_KEY")
    if single and single not in keys:
        keys.insert(0, single)
    proxies = _csv(_env("ELEVENLABS_PROXIES"))
    slots: list[ElevenSlot] = []
    for index, key in enumerate(keys):
        proxy = proxies[index] if index < len(proxies) else None
        slots.append(ElevenSlot(api_key=key, proxy=proxy, index=index))
    style = "robust"
    try:
        style = eleven_style(_env("ELEVENLABS_STYLE", "robust"))
    except ValueError:
        style = "robust"
    return ElevenConfig(
        slots=slots,
        voice_id=_env("ELEVENLABS_VOICE_ID"),
        voice_name=_env("ELEVENLABS_VOICE_NAME", DEFAULT_VOICE_NAME) or DEFAULT_VOICE_NAME,
        model=_env("ELEVENLABS_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        style=style,
    )


def public_env() -> dict[str, Any]:
    """Safe snapshot for studio / --print-plan. No secret material."""
    eleven = load_eleven_config()
    return {
        "gemini": bool(_env("GEMINI_API_KEY")),
        "groq": bool(_env("GROQ_API_KEY")),
        "groq_model": _env("GROQ_MODEL", "openai/gpt-oss-120b") or "openai/gpt-oss-120b",
        "elevenlabs": eleven.enabled,
        "elevenlabs_slots": eleven.slot_count(),
        "elevenlabs_voice_id": eleven.voice_id or None,
        "elevenlabs_voice_name": eleven.voice_name,
        "elevenlabs_model": eleven.model,
        "elevenlabs_style": eleven.style,
        "elevenlabs_model_notes": (
            "Preferred model_id is eleven_v3. The client lists GET /v1/models and "
            "falls back through eleven_multilingual_v2 if v3 is not on the account."
        ),
    }
