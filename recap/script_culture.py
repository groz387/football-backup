"""Culture-specific recap scripts: curse bookends, clean body, ElevenLabs v3 tags.

Canonical bookend lock lives in ``recap.culture``. This module is the
director / pipeline / studio facade:

* ``gemini_rules`` / ``gemini_brief`` — Gemini payloads (director unpacks rules)
* ``apply_bookends`` — lock curses onto first + last sentence only
* ``build_voiceover_text`` — tagged ElevenLabs v3 string the studio can synthesise
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from recap import culture
from recap.audit import result_context
from recap.data import MatchBundle
from recap.locales.bookends import bookends_for, locales as locale_codes

# Re-export the lock the pipeline already calls.
apply_bookends = culture.lock_bookends

# ElevenLabs v3 audio tags — first / last sentence only, plus a short
# climax/punch beat. Body copy stays clean.
_OPEN_TAGS = {
    "az": "[mischievously]",
    "en": "[mischievously]",
    "es": "[mischievously]",
    "ru": "[whispers]",
    "tr": "[mischievously]",
    "ar": "[mischievously]",
    "pt-BR": "[mischievously]",
    "pt-PT": "[mischievously]",
    "fr": "[sarcastic]",
    "de": "[sarcastic]",
    "it": "[mischievously]",
    "nl": "[sarcastic]",
    "uk": "[whispers]",
    "pl": "[sarcastic]",
    "hi": "[excited]",
    "ja": "[excited]",
    "ko": "[excited]",
}
_CLOSE_TAGS = {
    "az": "[curious]",
    "en": "[curious]",
    "es": "[curious]",
    "ru": "[sighs]",
    "tr": "[curious]",
    "ar": "[curious]",
    "pt-BR": "[curious]",
    "pt-PT": "[curious]",
    "fr": "[sighs]",
    "de": "[sighs]",
    "it": "[curious]",
    "nl": "[sighs]",
    "uk": "[sighs]",
    "pl": "[curious]",
    "hi": "[sighs]",
    "ja": "[sighs]",
    "ko": "[sighs]",
}
_CLIMAX_TAGS = {
    "az": "[excited]",
    "en": "[excited]",
    "es": "[excited]",
    "ru": "[shouts]",
}


def _lang(language: str) -> str:
    try:
        from recap import i18n
        return i18n.normalize_language(language)
    except Exception:
        raw = (language or "en").strip()
        return raw or "en"


def gemini_rules(language: str, *, kids: bool | None = None) -> tuple[str, ...]:
    """Rule strings the director unpacks into the Gemini ``rules`` list."""
    loc = _lang(language)
    if culture.kids_mode(kids):
        return (
            "Kids-safe run: no swearing anywhere. Sharp football analysis only.",
            "Do not wrap lines in adult-register audio tags.",
        )
    return (
        "CURSE BOOKENDS ONLY: adult football trash-talk is allowed in the FIRST "
        "spoken sentence (hook_claim narration) and the LAST spoken sentence "
        "(close comment_bait). Nowhere else.",
        "Body scenes, insights, analysis titles, bridges: clean football analysis. "
        "No sexual insults. No göt / sik / fuck / joder / хуй in the body.",
        "az = old Azerbaijani football uncle. Creative unique swear combos, "
        "pleasant to the ear, not robotic spam. Smash shape e.g. "
        "'Barcelona Elchenin Götünə Ağac Soxdu'. Outro e.g. "
        "'Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?'.",
        "en / es / ru = local pub / barra / двор trash-talk. NEVER a literal "
        "translation of the Azerbaijani curses (no stick-up-the-ass calques, "
        "no göt / ağac sox).",
        "ElevenLabs v3 audio tags ([mischievously], [curious], [excited], "
        "[whispers], [sarcastic]) belong on the hook's first sentence and the "
        "bait's last sentence only. Short spoken lines. No markdown, hashtags, "
        "or emoji. Speak numbers naturally.",
        culture.gemini_system_addendum(loc, kids=False),
        f"Target language code: {loc}.",
    )


def gemini_brief(
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    language: str = "en",
    spoiler: str = "show",
    kids: bool | None = None,
) -> dict[str, Any]:
    """JSON culture payload for Gemini: register, examples, v3 tag rules."""
    loc = _lang(language)
    kids_on = culture.kids_mode(kids)
    ctx = result_context(bundle, audit) if audit else {}
    return {
        "locale": loc,
        "kids": kids_on,
        "spoiler": spoiler or "show",
        "register": culture.register_for(loc),
        "system_addendum": culture.gemini_system_addendum(loc, kids=kids_on),
        "rules": list(gemini_rules(loc, kids=kids_on)),
        "example_hook": culture.offline_hook(
            bundle, audit, loc, spoiler=spoiler or "show", kids=kids_on,
        ),
        "example_bait": culture.offline_bait(bundle, audit, loc, kids=kids_on),
        "winner": ctx.get("winner") or "",
        "loser": ctx.get("loser") or "",
        "elevenlabs_v3": True,
        "audio_tags_bookends_only": True,
        "curse_bookends_only": not kids_on,
        "voice": "Liam Callahan - Witty Media Person",
        "model": "eleven_v3",
        "style": "robust",
    }


def _tag(tag: str, sentence: str) -> str:
    sentence = (sentence or "").strip()
    if not sentence:
        return ""
    if culture.AUDIO_TAG_RE.search(sentence):
        return sentence
    return f"{tag} {sentence}".strip()


def _scene_line(scene: dict[str, Any], language: str) -> str:
    loc = _lang(language)
    viz = str(scene.get("visualization") or "")
    bookend = str(scene.get("bookend") or "")
    narration = str(scene.get("narration") or "").strip()
    if not narration:
        bait = str(scene.get("comment_bait") or "").strip()
        if bait and (viz in culture.BOOKEND_BAIT_VIZ or bookend == "bait"):
            return _tag(_CLOSE_TAGS.get(loc, "[curious]"), bait)
        return ""
    if viz in culture.BOOKEND_HOOK_VIZ or bookend == "hook":
        first = culture.first_sentence(narration)
        rest = narration[len(first) :].strip() if first and narration.startswith(first) else ""
        tagged = _tag(_OPEN_TAGS.get(loc, "[mischievously]"), first)
        return f"{tagged} {rest}".strip() if rest else tagged
    if viz in culture.BOOKEND_BAIT_VIZ or bookend == "bait":
        last = culture.last_sentence(narration)
        body = narration[: max(0, len(narration) - len(last))].rstrip()
        tagged = _tag(_CLOSE_TAGS.get(loc, "[curious]"), last)
        return f"{body} {tagged}".strip() if body and body != last else tagged
    if viz in {"hook_punch"}:
        first = culture.first_sentence(narration)
        rest = narration[len(first) :].strip() if first and narration.startswith(first) else ""
        tagged = _tag(_CLIMAX_TAGS.get(loc, "[excited]"), first)
        return f"{tagged} {rest}".strip() if rest else tagged
    return narration


def build_voiceover_text(
    scenes: Iterable[dict[str, Any]],
    language: str = "en",
) -> str:
    """Join scenes into one ElevenLabs v3 string (tags on bookends + punch)."""
    loc = _lang(language)
    lines = [_scene_line(scene, loc) for scene in scenes]
    return "\n\n".join(line for line in lines if line)


def write_voiceover_files(
    scenes: Iterable[dict[str, Any]],
    dest_dir: Path,
    language: str,
) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    loc = _lang(language)
    text = build_voiceover_text(scenes, loc)
    path = dest_dir / f"voiceover.{loc}.txt"
    path.write_text(text + "\n", encoding="utf-8")
    meta = dest_dir / f"voiceover.{loc}.meta.json"
    meta.write_text(
        json.dumps(
            {
                "language": loc,
                "voice": "Liam Callahan - Witty Media Person",
                "model_id": "eleven_v3",
                "style": "robust",
                "bookends": culture.inspect_bookends(list(scenes), loc),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def curse_pools(locale: str, *, kids: bool = False) -> dict[str, tuple[str, ...]]:
    return bookends_for(_lang(locale), kids=kids)


def supported_locales() -> tuple[str, ...]:
    return locale_codes()
