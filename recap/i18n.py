"""UI and script localization for match-recap videos.

English is the source of truth. ``t()`` falls back to English for any missing
key. Locale packs live in ``recap.locales``; fonts/RTL live in ``locale_meta``.

Scores are always ``2-1`` (Western digits, ASCII hyphen), in every language.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from . import locale_meta
from .locales import LOCALE_MODULES, LocalePack, all_packs, available_codes, load_pack
from .locales._extras import CHROME_SENTENCES, CHROME_TO_KEY, OFFLINE_PATTERNS

SUPPORTED = tuple(LOCALE_MODULES)

ALIASES: dict[str, str] = {}
LANGUAGE_NAMES: dict[str, str] = {}
_PACKS: dict[str, LocalePack] = {}

_current = "en"
_RESHAPER = None
_BIDI = None
_RTL_ENGINE: str | None = None

_STATIC_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "az": "az", "aze": "az", "azerbaijani": "az", "azeri": "az",
    "es": "es", "spa": "es", "spanish": "es", "español": "es", "espanol": "es",
    "tr": "tr", "tur": "tr", "turkish": "tr", "türkçe": "tr", "turkce": "tr",
    "pt": "pt-BR", "ptbr": "pt-BR", "pt-br": "pt-BR", "pt_br": "pt-BR",
    "brazilian": "pt-BR", "por": "pt-BR",
    "ptpt": "pt-PT", "pt-pt": "pt-PT", "pt_pt": "pt-PT",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "français": "fr", "francais": "fr",
    "de": "de", "ger": "de", "deu": "de", "german": "de", "deutsch": "de",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "ar": "ar", "ara": "ar", "arabic": "ar",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "uk": "uk", "ukr": "uk", "ua": "uk", "ukrainian": "uk",
    "pl": "pl", "pol": "pl", "polish": "pl",
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl", "nederlands": "nl",
    "ja": "ja", "jpn": "ja", "jp": "ja", "japanese": "ja",
    "ko": "ko", "kor": "ko", "kr": "ko", "korean": "ko",
    "hi": "hi", "hin": "hi", "hindi": "hi",
}


def _boot() -> None:
    global ALIASES, LANGUAGE_NAMES, _PACKS
    if _PACKS:
        return
    names = {code: meta.name for code, meta in locale_meta.META.items()}
    aliases = dict(_STATIC_ALIASES)
    for code in SUPPORTED:
        aliases[code.lower()] = code
        aliases[code] = code
    try:
        loaded = all_packs()
    except Exception:
        loaded = {}
    for code, pack in loaded.items():
        names[code] = pack.name
        for alias in pack.aliases:
            aliases[str(alias).strip().lower()] = code
    _PACKS.update(loaded)
    ALIASES = aliases
    LANGUAGE_NAMES = names


def _ensure() -> None:
    if not ALIASES:
        _boot()
    if not _PACKS:
        _boot()


def normalize_language(value: str | None) -> str:
    _ensure()
    raw = (value or "en").strip()
    if not raw:
        return "en"
    key = raw.lower().replace("_", "-")
    code = ALIASES.get(key) or ALIASES.get(raw.lower())
    if code is None:
        raise ValueError(
            f"Unsupported language {value!r}. Choose one of: {', '.join(SUPPORTED)}"
        )
    return code


def parse_languages(value: str | None) -> list[str]:
    """Parse ``az,tr,ar`` / ``az tr ar`` into canonical codes, de-duplicated."""
    if not value or not str(value).strip():
        return []
    parts = re.split(r"[,\s;]+", str(value).strip())
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        code = normalize_language(part)
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def set_language(code: str) -> str:
    global _current
    _current = normalize_language(code)
    from . import theme
    theme.apply_language_fonts(_current)
    return _current


def get_language() -> str:
    return _current


def language_name(code: str | None = None) -> str:
    _ensure()
    return LANGUAGE_NAMES.get(code or _current, "English")


def pack(code: str | None = None) -> LocalePack:
    _ensure()
    want = code or _current
    if want not in _PACKS:
        try:
            _PACKS[want] = load_pack(want)
        except Exception:
            return _PACKS["en"]
    return _PACKS.get(want) or _PACKS["en"]


def is_rtl(code: str | None = None) -> bool:
    return locale_meta.is_rtl(code or _current)


def meta(code: str | None = None):
    return locale_meta.for_language(code or _current)


def t(key: str, *, lang: str | None = None, **kwargs: Any) -> str:
    """Look up *key*. Missing translations fall back to English, then the key."""
    _ensure()
    code = lang or _current
    if code not in _PACKS:
        try:
            code = normalize_language(code)
        except ValueError:
            code = "en"
    catalog = pack(code).ui
    template = catalog.get(key)
    if template is None:
        template = pack("en").ui.get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return template
    return template


def stat_label(key: str, *, lang: str | None = None) -> str:
    _ensure()
    code = lang or _current
    if code not in _PACKS:
        try:
            code = normalize_language(code)
        except ValueError:
            code = "en"
    labels = pack(code).stat_labels
    return (
        labels.get(key)
        or pack("en").stat_labels.get(key)
        or key.replace("_", " ").capitalize()
    )


def format_score(home: Any, away: Any) -> str:
    """Universal scoreline: ``2-1``. Never locale digits, never a dash variant."""
    return f"{int(home)}-{int(away)}"


def format_number(value: Any, *, lang: str | None = None, decimals: int | None = None) -> str:
    """Locale grouping/decimal. Scores must go through ``format_score`` instead."""
    info = meta(lang)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals is None:
        decimals = 0 if float(number).is_integer() else 2
    if decimals == 0:
        raw = f"{int(round(number))}"
    else:
        raw = f"{number:.{decimals}f}"
    if "." in raw:
        whole, frac = raw.split(".", 1)
    else:
        whole, frac = raw, ""
    if len(whole.lstrip("-")) > 3 and info.group:
        sign = ""
        if whole.startswith("-"):
            sign, whole = "-", whole[1:]
        grouped = []
        while whole:
            grouped.append(whole[-3:])
            whole = whole[:-3]
        whole = sign + info.group.join(reversed(grouped))
    if frac:
        return f"{whole}{info.decimal}{frac}"
    return whole


def format_percent(value: Any, *, lang: str | None = None) -> str:
    return f"{format_number(value, lang=lang, decimals=0)}%"


def format_date(value: str | None, *, lang: str | None = None) -> str:
    """Format a YYYY-MM-DD (or longer ISO) kickoff stamp."""
    raw = (value or "").strip()
    if not raw:
        return ""
    stamp = raw[:10]
    try:
        dt = datetime.strptime(stamp, "%Y-%m-%d")
    except ValueError:
        return raw
    info = meta(lang)
    y, m, d = dt.year, dt.month, dt.day
    if info.date_order == "mdy":
        return f"{m:02d}/{d:02d}/{y}"
    if info.date_order == "ymd":
        return f"{y}/{m:02d}/{d:02d}"
    return f"{d:02d}.{m:02d}.{y}"


def ordinal(n: int, *, lang: str | None = None) -> str:
    """Minute ordinals. English 81st; most football languages just say the number."""
    code = lang or _current
    number = int(n)
    if code == "en":
        if 10 <= number % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
        return f"{number}{suffix}"
    if code in {"fr"}:
        return "1er" if number == 1 else f"{number}e"
    if code in {"es", "pt-BR", "pt-PT", "it"}:
        return f"{number}º"
    if code in {"de", "tr", "az", "pl", "nl", "ru", "uk"}:
        return f"{number}."
    return str(number)


def score_qualifier(after_extra_time: bool = False, after_shootout: bool = False,
                    *, lang: str | None = None) -> str:
    if after_shootout:
        return t("on_penalties", lang=lang)
    if after_extra_time:
        return t("after_extra_time", lang=lang)
    return ""


_PERIOD_KEYS = {
    "First half": "period_first_half",
    "Second half": "period_second_half",
    "Extra time": "period_extra_time",
    "Extra time 1": "period_extra_time_1",
    "Extra time 2": "period_extra_time_2",
    "HT": "boundary_ht",
    "FT": "boundary_ft",
    "ET": "boundary_et",
}


def period_label(english: str, *, lang: str | None = None) -> str:
    key = _PERIOD_KEYS.get(english)
    if key:
        return t(key, lang=lang)
    return english


def outcome_label(outcome: str, *, lang: str | None = None) -> str:
    return t(f"outcome_{outcome}", lang=lang)


def _load_rtl_engine() -> str:
    global _RESHAPER, _BIDI, _RTL_ENGINE
    if _RTL_ENGINE is not None:
        return _RTL_ENGINE
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        _RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
            "delete_harakat": True,
            "support_ligatures": True,
        })
        _BIDI = get_display
        _RTL_ENGINE = "reshaper+bidi"
    except Exception:
        _RTL_ENGINE = "fallback-ltr"
    return _RTL_ENGINE


def rtl_engine() -> str:
    return _load_rtl_engine()


_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")


def shape_text(text: str, *, lang: str | None = None) -> str:
    """Reshape Arabic for matplotlib's LTR canvas. No-op for other scripts."""
    if not text or not _ARABIC_RE.search(text):
        return text
    engine = _load_rtl_engine()
    if engine != "reshaper+bidi" or _RESHAPER is None or _BIDI is None:
        return text
    try:
        return _BIDI(_RESHAPER.reshape(text))
    except Exception:
        return text


def prepare_display(text: str, *, upper: bool = False, lang: str | None = None) -> str:
    """Case + RTL shaping for on-screen chrome."""
    raw = str(text or "")
    if not raw:
        return ""
    info = meta(lang)
    if upper and info.uppercase_chrome:
        raw = raw.upper()
    return shape_text(raw, lang=lang or _current)


def headline_anchor(x: float, ha: str, *, lang: str | None = None) -> tuple[float, str]:
    """Mirror left/right figure anchors when the active language is RTL."""
    if not is_rtl(lang):
        return x, ha
    if ha == "left":
        return 1.0 - x, "right"
    if ha == "right":
        return 1.0 - x, "left"
    return x, ha


def social_copy(
    home: str,
    away: str,
    score: str,
    league: str = "",
    *,
    lang: str | None = None,
) -> dict[str, Any]:
    """Captions, CTAs, comment bait and end cards for one language."""
    kwargs = {"home": home, "away": away, "score": score, "league": league or home}
    return {
        "language": lang or _current,
        "language_name": language_name(lang),
        "rtl": is_rtl(lang),
        "captions": {
            "hook": t("caption_hook", lang=lang, **kwargs),
            "result": t("caption_result", lang=lang, **kwargs),
            "cta": t("caption_cta", lang=lang),
        },
        "ctas": [
            t("cta_follow", lang=lang),
            t("cta_like", lang=lang),
            t("cta_share", lang=lang),
            t("cta_save", lang=lang),
            t("cta_watch_full", lang=lang),
        ],
        "comment_bait": [
            t("comment_bait_motm", lang=lang),
            t("comment_bait_robbery", lang=lang),
            t("comment_bait_score", lang=lang),
            t("comment_bait_keeper", lang=lang),
            t("comment_bait_xg", lang=lang),
        ],
        "endcard": {
            "title": t("endcard_title", lang=lang),
            "follow": t("endcard_follow", lang=lang),
            "watch": t("endcard_watch", lang=lang),
            "score": t("endcard_score", lang=lang, **kwargs),
        },
    }


def offline_line(text: str, *, lang: str | None = None) -> str:
    """Translate a known English chrome/template line; leave unknowns alone."""
    code = lang or _current
    if code == "en" or not text:
        return text
    _ensure()
    table = pack(code).offline_lines
    if text in table and table[text]:
        return table[text]
    upper = text.upper()
    for source, target in table.items():
        if source.upper() == upper and target:
            return target
    key = CHROME_TO_KEY.get(upper) or CHROME_TO_KEY.get(text)
    if key:
        return t(key, lang=code)
    key = CHROME_SENTENCES.get(text)
    if key:
        return t(key, lang=code)
    for pattern, key, groups in OFFLINE_PATTERNS:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        kwargs = {name: match.group(index) for name, index in groups.items() if index}
        try:
            return t(key, lang=code, **kwargs)
        except Exception:
            return text
    return text


_ENGLISH_LEFTOVER = re.compile(
    r"\b(against|above the line|pass share|every attempt|touch volume|"
    r"average positions|what it produced|on.target|eighteen zones|"
    r"strongest links|the keeper|match result|match recap|full time|"
    r"the baseline|every goal|shot map|where on-target|follow for|"
    r"drop your motm)\b",
    re.IGNORECASE,
)


def looks_english(text: str) -> bool:
    if not text:
        return False
    if is_rtl() and _ARABIC_RE.search(text):
        return False
    return bool(_ENGLISH_LEFTOVER.search(text))


def scrub_english_leftovers(scenes: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    code = normalize_language(language)
    if code == "en":
        return scenes
    out = []
    for scene in scenes:
        updated = dict(scene)
        hook = bool(updated.get("hook"))
        for field in ("kicker", "title", "subtitle", "insight", "narration", "hook_stat"):
            value = str(updated.get(field) or "")
            if not value:
                continue
            translated = offline_line(value, lang=code)
            if translated != value:
                updated[field] = translated
                continue
            if looks_english(value) and not hook:
                updated[field] = "" if field in ("subtitle", "kicker", "hook_stat") else value
        if isinstance(updated.get("lines"), list):
            updated["lines"] = [offline_line(str(item), lang=code) for item in updated["lines"]]
        out.append(updated)
    return out


def localize_scenes_offline(scenes: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    code = normalize_language(language)
    if code == "en":
        return scenes
    out = []
    for scene in scenes:
        updated = dict(scene)
        for field in ("kicker", "title", "subtitle", "insight", "narration", "hook_stat"):
            value = str(updated.get(field) or "")
            if not value:
                continue
            updated[field] = offline_line(value, lang=code)
        if isinstance(updated.get("lines"), list):
            updated["lines"] = [offline_line(str(item), lang=code) for item in updated["lines"]]
        if updated.get("kicker") in ("AFTER EXTRA TIME", "ON PENALTIES", "FULL TIME"):
            mapping = {
                "AFTER EXTRA TIME": t("after_extra_time", lang=code),
                "ON PENALTIES": t("on_penalties", lang=code),
                "FULL TIME": t("full_time", lang=code),
            }
            updated["kicker"] = mapping[scene.get("kicker", "FULL TIME")]
        out.append(updated)
    return out


def localize_scenes(
    scenes: list[dict[str, Any]],
    language: str,
    gemini: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    code = normalize_language(language)
    if code == "en":
        return scenes, "en"
    if gemini is not None and getattr(gemini, "enabled", False):
        translated = gemini.translate_script(scenes, code)
        if translated:
            from .director import apply_script

            return scrub_english_leftovers(apply_script(scenes, translated), code), "gemini"
    return scrub_english_leftovers(localize_scenes_offline(scenes, code), code), "offline"


def missing_keys(code: str) -> dict[str, list[str]]:
    _ensure()
    en = pack("en")
    other = pack(normalize_language(code))
    ui = sorted(set(en.ui) - other.ui_key_set())
    stat = sorted(set(en.stat_labels) - other.stat_key_set())
    return {"ui": ui, "stat": stat}


def coverage_report() -> dict[str, Any]:
    _ensure()
    rows = []
    en_ui = len(pack("en").ui)
    en_stat = len(pack("en").stat_labels)
    for code in available_codes():
        miss = missing_keys(code) if code != "en" else {"ui": [], "stat": []}
        p = pack(code)
        rows.append({
            "code": code,
            "name": p.name,
            "native_name": p.native_name,
            "rtl": is_rtl(code),
            "ui_keys": len(p.ui),
            "stat_keys": len(p.stat_labels),
            "en_ui": en_ui,
            "en_stat": en_stat,
            "missing_ui": miss["ui"],
            "missing_stat": miss["stat"],
            "explicit_fallbacks": sorted(p.explicit_fallbacks),
            "complete": not miss["ui"] and not miss["stat"],
        })
    return {"languages": rows, "supported": list(SUPPORTED)}
