"""Detect and localize operator-written hook and bait copy.

The operator writes one source line.  Each language package receives either:

* the exact line when it is the detected source language;
* a Gemini culture translation when available; or
* a deterministic, target-locale terrace line when offline.

The offline fallback intentionally prefers fluent local copy over a broken
word-for-word translation.  It never invents match facts or coordinates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import culture, i18n
from .data import MatchBundle

_ARABIC = re.compile(r"[\u0600-\u06ff]")
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_HIRAGANA_KATAKANA = re.compile(r"[\u3040-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")
_UKRAINIAN = re.compile(r"[іїєґ]", re.I)

_WORDS: dict[str, set[str]] = {
    "az": {
        "oyun", "qapandi", "qapandı", "donushe", "dönüşə", "bax", "kim",
        "sizcə", "idi", "ən", "bu", "rəqib", "götünə", "soxdu", "peysər",
        "gijdıllax", "sikirdilər", "uddu", "etdilər",
    },
    "tr": {"oyun", "kapandı", "dönüşe", "bak", "kim", "sizce", "rakip", "maç", "kazandı"},
    "en": {"the", "was", "who", "match", "game", "minute", "watch", "won", "motm"},
    "es": {"el", "la", "los", "las", "quién", "partido", "minuto", "ganó", "mira", "fue"},
    "pt-BR": {"o", "a", "quem", "jogo", "minuto", "ganhou", "olha", "foi"},
    "fr": {"le", "la", "qui", "match", "minute", "gagné", "regarde", "était"},
    "de": {"der", "die", "das", "wer", "spiel", "minute", "gewann", "war"},
    "it": {"il", "la", "chi", "partita", "minuto", "vinto", "guarda", "era"},
    "pl": {"kto", "mecz", "minuta", "wygrał", "był", "zobacz"},
    "nl": {"wie", "wedstrijd", "minuut", "won", "was", "kijk"},
}

_COMMON: dict[str, dict[str, str]] = {
    "90-minute": {
        "az": "90 DƏQİQƏ", "en": "90 MINUTES", "es": "90 MINUTOS",
        "ru": "90 МИНУТ", "tr": "90 DAKİKA", "pt-BR": "90 MINUTOS",
        "fr": "90 MINUTES", "de": "90 MINUTEN", "it": "90 MINUTI",
    },
    "game-over": {
        "az": "OYUN QAPANDI", "en": "GAME OVER", "es": "SE ACABÓ EL PARTIDO",
        "ru": "ИГРА ОКОНЧЕНА", "tr": "OYUN BİTTİ", "pt-BR": "FIM DE JOGO",
        "fr": "MATCH TERMINÉ", "de": "SPIEL VORBEI", "it": "PARTITA FINITA",
    },
    "watch-turn": {
        "az": "DÖNÜŞƏ BAX", "en": "WATCH THE TURN", "es": "MIRA EL GIRO",
        "ru": "СМОТРИ ПОВОРОТ", "tr": "DÖNÜŞE BAK", "pt-BR": "OLHA A VIRADA",
        "fr": "REGARDE LE TOURNANT", "de": "SCHAU AUF DIE WENDE",
        "it": "GUARDA LA SVOLTA",
    },
}


@dataclass(frozen=True)
class Detection:
    code: str
    confidence: float


def detect_language(text: str) -> tuple[str, float]:
    """Return ``(language_code, confidence)`` for short operator copy."""
    raw = str(text or "").strip()
    if not raw:
        return "en", 0.0
    if _ARABIC.search(raw):
        return "ar", 0.99
    if _HIRAGANA_KATAKANA.search(raw):
        return "ja", 0.99
    if _HANGUL.search(raw):
        return "ko", 0.99
    if _DEVANAGARI.search(raw):
        return "hi", 0.99
    if _CYRILLIC.search(raw):
        return ("uk", 0.96) if _UKRAINIAN.search(raw) else ("ru", 0.94)
    lowered = raw.casefold()
    if any(ch in lowered for ch in "əğı"):
        return "az", 0.99
    tokens = set(re.findall(r"[^\W\d_]+", lowered, flags=re.UNICODE))
    scores = {code: len(tokens & words) for code, words in _WORDS.items()}
    # q is highly characteristic in these short AZ football lines; Turkish
    # uses k where AZ uses q (qapandı / rəqib).
    if "q" in lowered or tokens & {"donushe", "qapandi", "bax"}:
        scores["az"] = scores.get("az", 0) + 2
    winner = max(scores, key=scores.get)
    score = scores[winner]
    if score:
        return winner, min(0.96, 0.58 + score * 0.13)
    return "en", 0.35


def _intent(text: str) -> str | None:
    raw = re.sub(r"[^a-z0-9əğıöüşç]+", " ", str(text or "").casefold()).strip()
    if re.search(r"\b90\b", raw) and any(x in raw for x in ("minute", "minut", "dəqiqə", "dakika")):
        return "90-minute"
    if any(x in raw for x in ("oyun qap", "game over", "se acabo", "se acabó", "игра оконч")):
        return "game-over"
    if any(x in raw for x in ("donushe bax", "dönüşə bax", "watch the turn", "mira el giro")):
        return "watch-turn"
    return None


def _digits(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,:-]\d+)*", str(text or ""))


def _protected_terms(text: str, bundle: MatchBundle, audit: dict[str, Any]) -> list[str]:
    candidates = [bundle.home, bundle.away]
    cast = audit.get("cast") if isinstance(audit, dict) else {}
    for row in (cast or {}).get("stars") or []:
        if isinstance(row, dict):
            candidates.extend([str(row.get("name") or ""), str(row.get("poster_name") or "")])
    raw = str(text or "")
    found: list[str] = []
    for candidate in candidates:
        for part in [candidate, *candidate.split()]:
            part = part.strip()
            if len(part) >= 3 and re.search(rf"\b{re.escape(part)}\b", raw, re.I):
                match = re.search(rf"\b{re.escape(part)}\b", raw, re.I)
                if match:
                    found.append(match.group(0))
    known_words = set().union(*_WORDS.values())
    for token in re.findall(r"\b[A-ZƏĞİÖŞÜÇ][A-Za-zƏĞİÖŞÜÇəğıöşüç'-]{2,}\b", raw):
        if token.casefold() not in known_words:
            found.append(token)
    return list(dict.fromkeys(found))


def _valid_translation(source: str, translated: str, protected: list[str]) -> bool:
    if not translated or translated.strip() == source.strip():
        return False
    if _digits(source) != _digits(translated):
        return False
    folded = translated.casefold()
    return all(term.casefold() in folded for term in protected)


def translate_line(
    text: str,
    target_language: str,
    *,
    kind: str,
    bundle: MatchBundle,
    audit: dict[str, Any],
    gemini: Any | None = None,
) -> dict[str, Any]:
    """Translate one operator line and report the method used."""
    source = str(text or "").strip()
    target = i18n.normalize_language(target_language)
    source_lang, confidence = detect_language(source)
    if not source:
        return {"text": "", "source_language": source_lang, "confidence": confidence, "method": "empty"}
    if source_lang == target:
        return {
            "text": source, "source_language": source_lang,
            "confidence": confidence, "method": "operator_exact",
        }
    protected = _protected_terms(source, bundle, audit)
    translator = getattr(gemini, "translate_operator_line", None)
    if callable(translator) and bool(getattr(gemini, "enabled", False)):
        translated = translator(
            source, source_lang, target, kind=kind, protected=protected,
        )
        if _valid_translation(source, str(translated or ""), protected):
            return {
                "text": str(translated).strip(), "source_language": source_lang,
                "confidence": confidence, "method": "gemini",
            }
    intent = _intent(source)
    if intent and target in _COMMON[intent]:
        translated = _COMMON[intent][target]
        return {
            "text": translated, "source_language": source_lang,
            "confidence": confidence, "method": "offline_intent",
        }
    if kind == "bait":
        translated = culture.offline_bait(bundle, audit, target)
    else:
        translated = culture.offline_hook(bundle, audit, target)
    # Preserve a named player/team in a generic target-locale bait.
    if kind == "bait" and protected and all(x.casefold() not in translated.casefold() for x in protected):
        translated = f"{protected[0]} — {translated}"
    # Preserve numbers even when the fluent fallback chooses a different shape.
    missing_digits = [digit for digit in _digits(source) if digit not in _digits(translated)]
    if missing_digits:
        translated = f"{' '.join(missing_digits)} — {translated}"
    return {
        "text": translated, "source_language": source_lang,
        "confidence": confidence, "method": "fallback_pool",
    }


def localize_operator_copy(
    hook_texts: list[str] | None,
    bait_text: str | None,
    target_language: str,
    *,
    bundle: MatchBundle,
    audit: dict[str, Any],
    gemini: Any | None = None,
) -> dict[str, Any]:
    hooks: list[str] = []
    hook_meta: list[dict[str, Any]] = []
    for text in hook_texts or []:
        result = translate_line(
            text, target_language, kind="hook", bundle=bundle, audit=audit, gemini=gemini,
        )
        hooks.append(result["text"])
        hook_meta.append({k: v for k, v in result.items() if k != "text"})
    bait_result = translate_line(
        bait_text or "", target_language, kind="bait",
        bundle=bundle, audit=audit, gemini=gemini,
    )
    return {
        "hook_texts": hooks,
        "bait_text": bait_result["text"],
        "hooks": hook_meta,
        "bait": {k: v for k, v in bait_result.items() if k != "text"},
        "target_language": i18n.normalize_language(target_language),
    }
