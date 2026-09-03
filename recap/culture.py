"""Culture-specific recap register: curses ONLY on the first and last sentence.

AZ is first-class: old-football-uncle energy, unique swear combos used once
each at the hook and the comment-bait. EN / ES / RU use the local pub / barra /
двор register — not a literal translation of the Azerbaijani lines.

Body copy and on-screen stats stay clean. Numbers still come from the audit.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import i18n
from .audit import result_context
from .data import MatchBundle, clean_text
from .locales import LOCALE_MODULES

_AZ_VOWELS = set("aeıioöuüəiAEIİOÖUÜƏİ")
_ARTICLES = {"fc", "cf", "afc", "the", "de", "cd", "sc", "ac"}

# Spoken bookends. Hook = first sentence of the recap. Bait = last sentence.
BOOKEND_HOOK_VIZ = frozenset({"hook_claim"})
BOOKEND_BAIT_VIZ = frozenset({"close"})

# Gemini / ElevenLabs v3: short spoken lines, optional audio tags, no markdown.
AUDIO_TAG_RE = re.compile(
    r"\[(excited|whispers|sarcastic|angry|laughs|sighs|calm|mischievously|curious|happily)\]",
    re.I,
)

# --- profanity detectors (bookend lock) ------------------------------------
# These are the owner's adult farm register. They are not a kids default.

_AZ_CURSE = re.compile(
    r"(g[öo]t(?:ün[eə]?|ünü|ü)?|a[gğ]ac\s*sox|peys[əe]r|sik(?:ir|irdi|ini)|"
    r"yal[ıi]y|gijd[ıi]llax|amc[ıi][gğ]|qanc[ıi]q)",
    re.IGNORECASE,
)
_EN_CURSE = re.compile(
    r"\b(fuck(?:ing|ed|er)?|shit(?:ty)?|piss(?:ed)?|cock|twat|cunt|"
    r"wanker|arsehole|asshole|dickhead|bollocks|motherfuck(?:er|ing)?)\b",
    re.IGNORECASE,
)
_ES_CURSE = re.compile(
    r"\b(joder|jodid[oa]|jodi[oó]|polla|coño|puta|cabron(?:es|a)?|cabrón|"
    r"cojones|hostia|gilipollas|mierda)\b",
    re.IGNORECASE,
)
_RU_CURSE = re.compile(
    r"(хуй|хуя|пизд|бля(?:ть|д)?|ебан|ёб|сука|хуев)",
    re.IGNORECASE,
)

_CURSE_BY_LANG = {
    "az": _AZ_CURSE,
    "en": _EN_CURSE,
    "es": _ES_CURSE,
    "ru": _RU_CURSE,
}

# Kids-facing switch. Off on this farm unless --kids / RECIPIENT_KIDS=1.
KIDS_ENV = "RECIPIENT_KIDS"


def kids_mode(flag: bool | None = None) -> bool:
    if flag is True:
        return True
    import os
    return str(os.environ.get(KIDS_ENV, "")).strip().lower() in {"1", "true", "yes"}


def curse_regex(language: str) -> re.Pattern[str]:
    try:
        lang = i18n.normalize_language(language)
    except ValueError:
        lang = "en"
    return _CURSE_BY_LANG.get(lang, _EN_CURSE)


def contains_curse(text: str, language: str | None = None) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    if language:
        if curse_regex(language).search(raw):
            return True
    return any(pattern.search(raw) for pattern in _CURSE_BY_LANG.values())


def strip_audio_tags(text: str) -> str:
    return AUDIO_TAG_RE.sub("", str(text or "")).strip()


def first_sentence(text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", raw, maxsplit=1)
    return parts[0].strip()


def last_sentence(text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", raw)
    return (parts[-1] if parts else raw).strip()


def body_sentences(text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", raw)
    if len(parts) <= 2:
        return ""
    return " ".join(parts[1:-1]).strip()


# --- locale pools (offline fallback; never invent match facts) -------------
# Placeholders are only {team} {rival} {home} {away} filled from the bundle.

AZ_HOOKS = (
    "{team} {rival_gen} götünə ağac soxdu",
    "{team} {rival_acc} belə soydu ki, stadion susdu",
    "{team} {rival_gen} kürəyinə mindi",
    "{rival} bu gecə gijdıllax oldu, {team} işini bitirdi",
    "{team} rəqibin nəslini peysər çıxardıb",
    "{rival}ı bu gecə düzgün sikirdilər",
)
AZ_BAITS = (
    "Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?",
    "Aşağı yaz: bu gecənin ən gijdıllaxı kim oldu?",
    "Sən de, kim bu oyunda sikini tapdaqlatdı?",
    "Bəs kim bu matçda ən gijdıllax çıxdı, a kişi?",
)

EN_HOOKS = (
    "{team} sent {rival} home in a bin bag",
    "{team} took {rival} behind the woodshed",
    "{team} ran {rival} off the park",
    "{team} had {rival} on toast",
    "{team} put {rival} through the blender",
    "{team} fucking ran {rival} off the park",
    "{team} pissed all over {rival}",
)
EN_BAITS = (
    "So who bottled it then, you lot?",
    "Right — who was the biggest passenger tonight?",
    "Drop it in the comments: who was bang average?",
    "Go on then, who made a tit of themselves?",
)

ES_HOOKS = (
    "{team} dejó a {rival} para el arrastre",
    "{team} se merendó a {rival}",
    "{team} mandó a {rival} a casa llorando",
    "{team} hizo trizas a {rival}",
    "{team} le dio un palizón a {rival}",
    "{team} jodió a {rival} sin piedad",
    "{team} dejó a {rival} hecho una mierda",
)
ES_BAITS = (
    "¿Y vosotros? ¿Quién fue el más flojo de la noche?",
    "A ver, ¿quién se hizo el ridículo hoy?",
    "Comenten: ¿quién fue el pecho frío del partido?",
    "¿Quién salió con la cola entre las piernas?",
)

RU_HOOKS = (
    "{team} устроил {rival} разнос",
    "{team} укатал {rival} в асфальт",
    "{team} вытер ноги об {rival}",
    "{team} оставил {rival} без штанов",
    "{team} закатал {rival} в бетон",
    "{team} устроил {rival} пиздец",
    "{team} вытер хуй об {rival}",
)
RU_BAITS = (
    "Ну что, кто сегодня самый бесполезный?",
    "Пишите: кто сегодня самый лишний на поле?",
    "Кто сегодня сыграл в одно место? Давайте в комментах.",
    "Ну и кто тут сегодня полный пассажир?",
)

# Spoiler-hide: still adult register, no winner / score leak.
AZ_HOOKS_HIDE = (
    "Bu gecənin əvvəlindən iylənirdi, kişi",
    "Ağzını açmamış oyunun götü görünürdü",
    "Bu matç təmiz olmayacaqdı. Bax.",
)
EN_HOOKS_HIDE = (
    "This one was going to get fucking ugly. Stay.",
    "Ninety minutes of taking the piss starts now",
    "Don't blink. This lot came to scrap.",
)
ES_HOOKS_HIDE = (
    "Esto iba a ser una hostia sí o sí. Quédate.",
    "El partido huele a palo desde el primer minuto",
    "No parpadees. Esto no va a ser limpio.",
)
RU_HOOKS_HIDE = (
    "С первой минуты пахло пиздецом. Смотри.",
    "Это будет грязно. Оставайся.",
    "Девяносто минут без соплей. Дальше.",
)

AZ_HOOKS_DRAW = (
    "Bu oyunda hamı gijdıllax çıxdı",
    "Heç kim oğlan olmadığını sübut etmədi",
    "Doxsan dəqiqə, sıfır kişi",
)
EN_HOOKS_DRAW = (
    "Ninety minutes of fucking nobody showing up",
    "Both lots bottled this shit",
    "A stalemate that deserved a hiding",
)
ES_HOOKS_DRAW = (
    "Noventa minutos de mierda compartida",
    "Nadie se puso los pantalones, joder",
    "Empate de los que duelen",
)
RU_HOOKS_DRAW = (
    "Девяносто минут взаимного пиздеца",
    "Никто не вышел играть, блять",
    "Ничья, за которую стыдно",
)

POOLS = {
    "az": {"hook": AZ_HOOKS, "bait": AZ_BAITS, "hook_hide": AZ_HOOKS_HIDE, "hook_draw": AZ_HOOKS_DRAW},
    "en": {"hook": EN_HOOKS, "bait": EN_BAITS, "hook_hide": EN_HOOKS_HIDE, "hook_draw": EN_HOOKS_DRAW},
    "es": {"hook": ES_HOOKS, "bait": ES_BAITS, "hook_hide": ES_HOOKS_HIDE, "hook_draw": ES_HOOKS_DRAW},
    "ru": {"hook": RU_HOOKS, "bait": RU_BAITS, "hook_hide": RU_HOOKS_HIDE, "hook_draw": RU_HOOKS_DRAW},
}

GEMINI_BOOKEND_RULES = (
    "CURSE BOOKENDS: adult football trash-talk is allowed ONLY in the first "
    "spoken sentence (hook_claim narration / first-second shock) and the last "
    "spoken sentence (close comment_bait). Every analysis scene, every stat "
    "line, every insight, every bridge MUST be clean football analysis — no "
    "swears, no sexual insults, no 'göt/sik/fuck/joder/хуй' in the body."
    "Write in the LOCAL football register of the target language: "
    "az = old Azerbaijani football uncle, creative unique swear combos, pleasant "
    "to the ear, not robotic, not random profanity spam; "
    "en = pub pundit, not a translation of the Azerbaijani curses; "
    "es = barra / tribuna, local Spanish; "
    "ru = двор / пацанский футбольный треп, not a calque of AZ."
    "ElevenLabs v3: short spoken lines. Optional audio tags like [excited] "
    "[whispers] [sarcastic] [mischievously] [curious] SPARINGLY, only on the "
    "first sentence of hook_claim and the last sentence of close. No markdown, "
    "no hashtags, no emoji. Speak numbers naturally ('fifteen shots', 'five-one')."
    "Never invent a match fact, minute, scorer, or coordinate. "
    "AZ smash shape e.g. 'Barcelona Elchenin Götünə Ağac Soxdu'; AZ bait e.g. "
    "'Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?'."
)


def terrace_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    if len(raw) <= 12:
        return raw
    parts = [part for part in re.split(r"\s+", raw) if part.lower() not in _ARTICLES]
    return parts[-1] if parts else raw


def az_genitive(name: str) -> str:
    """Elche → Elchenin."""
    raw = terrace_name(name)
    if not raw:
        return raw
    if raw[-1].lower() in _AZ_VOWELS or raw[-1] in "eE":
        return raw + "nin"
    return raw + "in"


def az_accusative(name: str) -> str:
    raw = terrace_name(name)
    if not raw:
        return raw
    if raw[-1].lower() in _AZ_VOWELS or raw[-1] in "eE":
        return raw + "ni"
    return raw + "i"


def smash_title(text: str, language: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return text
    if language == "az":
        return " ".join((w[:1].upper() + w[1:]) if w else w for w in text.split(" "))
    return text[0].upper() + text[1:] if text else text


def _locale_pools(language: str) -> dict[str, tuple[str, ...]] | None:
    try:
        code = i18n.normalize_language(language)
    except ValueError:
        code = language
    name = LOCALE_MODULES.get(code)
    if not name:
        return None
    try:
        from importlib import import_module
        mod = import_module(name)
    except Exception:
        return None
    hooks = tuple(str(x) for x in (getattr(mod, "CURSE_HOOKS", ()) or ()) if str(x).strip())
    bait = tuple(str(x) for x in (getattr(mod, "CURSE_OUTROS", ()) or ()) if str(x).strip())
    hide = tuple(str(x) for x in (getattr(mod, "CURSE_HOOKS_HIDE", ()) or ()) if str(x).strip())
    draw = tuple(str(x) for x in (getattr(mod, "CURSE_HOOKS_DRAW", ()) or ()) if str(x).strip())
    if not hooks and not bait:
        return None
    return {"hook": hooks, "bait": bait, "hook_hide": hide, "hook_draw": draw}


def pools_for(language: str) -> dict[str, tuple[str, ...]]:
    loc = _locale_pools(language)
    if loc and loc.get("hook"):
        base = dict(POOLS.get(register_for(language), POOLS["en"]))
        base.update({k: v for k, v in loc.items() if v})
        return base
    return dict(POOLS.get(register_for(language), POOLS["en"]))


def register_for(language: str) -> str:
    try:
        lang = i18n.normalize_language(language)
    except ValueError:
        lang = "en"
    return lang if lang in POOLS else "en"


def _fill(template: str, bundle: MatchBundle, audit: dict[str, Any]) -> str:
    ctx = result_context(bundle, audit) if audit else {}
    winner = terrace_name(str(ctx.get("winner") or bundle.home))
    loser = terrace_name(str(ctx.get("loser") or bundle.away))
    try:
        return template.format(
            team=winner,
            rival=loser,
            winner=winner,
            loser=loser,
            rival_gen=az_genitive(loser),
            loser_gen=az_genitive(loser),
            rival_acc=az_accusative(loser),
            loser_acc=az_accusative(loser),
            home=terrace_name(bundle.home),
            away=terrace_name(bundle.away),
            score=getattr(bundle.score, "display", "") or "",
            player="",
        )
    except (KeyError, ValueError, IndexError):
        return template


def _pick(items: tuple[str, ...], bundle: MatchBundle, salt: str) -> str:
    if not items:
        return ""
    key = f"{bundle.home}|{bundle.away}|{getattr(bundle.score, 'display', '')}|{salt}"
    index = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % len(items)
    return items[index]


def offline_hook(
    bundle: MatchBundle,
    audit: dict[str, Any],
    language: str,
    *,
    spoiler: str = "show",
    kids: bool = False,
) -> str:
    pack = pools_for(language)
    lang = register_for(language)
    if kids:
        return ""
    if spoiler == "hide":
        pool = pack.get("hook_hide") or pack["hook"]
    else:
        ctx = result_context(bundle, audit) if audit else {}
        draw = not bool(ctx.get("winner") and ctx.get("loser"))
        pool = (pack.get("hook_draw") or pack["hook"]) if draw else pack["hook"]
    line = _fill(_pick(tuple(pool), bundle, f"hook:{lang}:{spoiler}"), bundle, audit)
    titled = smash_title(line, lang)
    if contains_curse(titled, lang):
        return titled
    # Prefer a detector-visible smash when the hashed pick was milder terrace talk.
    for template in pool:
        candidate = smash_title(_fill(template, bundle, audit), lang)
        if contains_curse(candidate, lang):
            return candidate
    return titled


def offline_bait(
    bundle: MatchBundle,
    audit: dict[str, Any],
    language: str,
    *,
    kids: bool = False,
) -> str:
    if kids:
        return ""
    pack = pools_for(language)
    lang = register_for(language)
    return _fill(_pick(tuple(pack.get("bait") or ()), bundle, f"bait:{lang}"), bundle, audit)


def curse_options(
    bundle: MatchBundle,
    audit: dict[str, Any],
    language: str,
    *,
    kind: str = "hook",
    spoiler: str = "show",
    kids: bool = False,
) -> list[dict[str, str]]:
    """Interactive / studio picker. Empty when kids-mode is on."""
    if kids:
        return []
    pack = pools_for(language)
    lang = register_for(language)
    if kind == "bait":
        templates = pack.get("bait") or ()
    else:
        templates = pack.get("hook_hide") if spoiler == "hide" else pack.get("hook")
    templates = tuple(templates or ())
    out = []
    for index, template in enumerate(templates):
        text = _fill(template, bundle, audit)
        out.append({"kind": f"curse-{kind}", "key": f"{lang}_{kind}_{index}", "text": text, "label": text})
    return out


def gemini_system_addendum(language: str, *, kids: bool = False) -> str:
    lang = register_for(language)
    if kids:
        return (
            "This run is kids-safe. No swearing anywhere. Sharp football analysis only."
        )
    return f"{GEMINI_BOOKEND_RULES} Target language code: {lang}."


def _clean_body_text(text: str, language: str) -> str:
    """Drop cursed sentences from analysis copy; keep numbers and names."""
    raw = str(text or "").strip()
    if not raw or not contains_curse(raw, language):
        return raw
    parts = re.split(r"(?<=[.!?…])\s+", raw)
    kept = [part for part in parts if part and not contains_curse(part, language)]
    return " ".join(kept).strip()


def inspect_bookends(scenes: list[dict[str, Any]], language: str) -> dict[str, Any]:
    """Where curses sit. Used by tests and the script-review gate."""
    lang = register_for(language)
    hits: list[dict[str, Any]] = []
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        for field in ("title", "insight", "narration", "comment_bait", "kicker", "subtitle"):
            value = str(scene.get(field) or "")
            if contains_curse(value, lang):
                hits.append({
                    "id": scene.get("id"),
                    "visualization": viz,
                    "field": field,
                    "bookend": viz in BOOKEND_HOOK_VIZ or viz in BOOKEND_BAIT_VIZ,
                })
    body_hits = [h for h in hits if not h["bookend"]]
    return {
        "language": lang,
        "hits": hits,
        "body_hits": body_hits,
        "clean_body": not body_hits,
    }


def lock_bookends(
    scenes: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
    language: str,
    *,
    spoiler: str = "show",
    kids: bool = False,
    hook_text: str | None = None,
    bait_text: str | None = None,
) -> list[dict[str, Any]]:
    """Force curses onto hook_claim + close only; strip them from the body.

    User / Gemini / offline pool, in that order. Never invents facts: templates
    only substitute team names already on the bundle.
    """
    lang = register_for(language)
    hook = clean_text(hook_text) or ""
    bait = clean_text(bait_text) or ""
    if kids:
        hook = _clean_body_text(hook, lang)
        bait = _clean_body_text(bait, lang)
    else:
        if not hook:
            # Keep a Gemini/user hook if it already has the local register;
            # otherwise plant an offline curse hook.
            current = next((s for s in scenes if s.get("visualization") in BOOKEND_HOOK_VIZ), {})
            current_line = str(current.get("narration") or current.get("title") or "")
            if contains_curse(current_line, lang):
                hook = first_sentence(current_line)
            else:
                hook = offline_hook(bundle, audit, lang, spoiler=spoiler, kids=False)
        if not bait:
            current = next((s for s in scenes if s.get("visualization") in BOOKEND_BAIT_VIZ), {})
            current_line = str(current.get("comment_bait") or current.get("insight") or "")
            last = last_sentence(str(current.get("narration") or ""))
            if contains_curse(current_line, lang):
                bait = current_line
            elif contains_curse(last, lang):
                bait = last
            else:
                bait = offline_bait(bundle, audit, lang, kids=False)

    out: list[dict[str, Any]] = []
    for scene in scenes:
        updated = dict(scene)
        viz = str(updated.get("visualization") or "")
        if viz in BOOKEND_HOOK_VIZ and hook:
            updated["title"] = hook
            updated["narration"] = hook.rstrip(".")
            lines = list(updated.get("lines") or [])
            updated["lines"] = [hook] + ([lines[0]] if lines and lines[0] != hook else [])
            updated["bookend"] = "hook"
        elif viz in BOOKEND_BAIT_VIZ and bait:
            previous = str(updated.get("comment_bait") or "")
            updated["comment_bait"] = bait
            updated["insight"] = bait
            narration = str(updated.get("narration") or "").strip()
            if previous and previous in narration:
                narration = narration.replace(previous, "").strip(" .")
            # Body of the close card (the stats sentence) must stay clean.
            narration = _clean_body_text(narration, lang)
            if bait.lower() not in narration.lower():
                updated["narration"] = (
                    f"{narration.rstrip('. ')}. {bait}".strip() if narration else bait
                )
            else:
                updated["narration"] = narration
            updated["bookend"] = "bait"
        else:
            for field in ("title", "insight", "narration", "kicker", "subtitle", "comment_bait"):
                value = str(updated.get(field) or "")
                if value and contains_curse(value, lang):
                    updated[field] = _clean_body_text(value, lang)
            if isinstance(updated.get("lines"), list):
                updated["lines"] = [
                    _clean_body_text(str(item), lang) for item in updated["lines"]
                ]
        out.append(updated)
    return out


def script_review(scenes: list[dict[str, Any]], language: str) -> dict[str, Any]:
    """Hook / body summary / outro bait for the approval gate."""
    claim = next((s for s in scenes if s.get("visualization") == "hook_claim"), {})
    punch = next((s for s in scenes if s.get("visualization") == "hook_punch"), {})
    close = next((s for s in scenes if s.get("visualization") == "close"), {})
    body = [
        s for s in scenes
        if s.get("visualization") not in {"hook_claim", "hook_punch", "micro_hook", "live_clip", "close"}
        and not str(s.get("visualization") or "").startswith("bridge")
    ]
    hook_line = str(claim.get("narration") or claim.get("title") or "")
    bait_line = str(close.get("comment_bait") or close.get("insight") or last_sentence(str(close.get("narration") or "")))
    body_titles = [str(s.get("title") or s.get("visualization") or "") for s in body]
    body_bits = [str(s.get("narration") or "")[:140] for s in body if s.get("narration")]
    return {
        "language": register_for(language),
        "hook": hook_line,
        "punch": str(punch.get("title") or punch.get("narration") or ""),
        "body_summary": " · ".join(t for t in body_titles if t),
        "body_lines": body_bits,
        "outro_bait": bait_line,
        "bookends": inspect_bookends(scenes, language),
        "scenes": [
            {
                "id": s.get("id"),
                "visualization": s.get("visualization"),
                "title": s.get("title"),
                "narration": s.get("narration"),
                "comment_bait": s.get("comment_bait") or "",
            }
            for s in scenes
        ],
    }
