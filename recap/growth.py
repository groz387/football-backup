"""Growth / SEO posting pack for one recap render.

Every render can emit titles, descriptions, hashtags, chapters, thumbnail
specs, alt text, pinned-comment bait and filename suggestions — in the
render language **and English** — written next to the mp4.

Schema version: ``recap.growth.v1``

Numbers and names come only from the match export + ``data_audit`` + the
hook engine. This module reads ``hooks.build_hook``; it does not change
hook kinds, copy, or visuals.

Write path (default): ``<match-dir>/growth/`` and, when rendering,
``<video-output>/<match>/growth/`` (next to ``match_video.mp4``).

    python -m recap.growth --match-dir output/1953861_Scotland_vs_Morocco --language es
    recap.growth.write_growth_pack(match_dir, language="es", package_dir=out_dir)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import audit as audit_mod
from . import hooks, i18n, thumbnails
from .audit import result_context
from .data import MatchBundle, load_match, write_json

SCHEMA = "recap.growth.v1"

PLATFORMS = ("tiktok", "reels", "shorts", "youtube", "instagram_feed")
TITLE_KINDS = ("curiosity", "spoiler_slam", "player_seo", "derby_language", "question")

TITLE_LIMIT = {
    "tiktok": 90,
    "reels": 90,
    "shorts": 100,
    "youtube": 70,
    "instagram_feed": 85,
    "youtube_long": 100,
}

BIG_POOLS: dict[str, tuple[str, ...]] = {
    "tiktok": (
        "football", "soccer", "fyp", "highlights", "sports",
        "matchday", "recap", "foryou", "worldcup", "viral",
    ),
    "reels": (
        "football", "soccer", "reels", "highlights", "sports",
        "matchday", "instafootball", "recap", "goals", "worldcup",
    ),
    "shorts": (
        "football", "soccer", "shorts", "ytshorts", "highlights",
        "sports", "tactics", "recap", "goals", "worldcup",
    ),
    "youtube": (
        "FootballHighlights", "Soccer", "MatchRecap", "TacticalAnalysis",
        "Sports", "Goals", "WorldCup", "WhoScored", "FootballTactics", "Shorts",
    ),
    "instagram_feed": (
        "football", "soccer", "matchday", "highlights", "thebeautifulgame",
        "sports", "tactics", "recap", "worldcup", "goals",
    ),
    "youtube_long": (
        "FootballHighlights", "FullMatchRecap", "TacticalAnalysis",
        "Soccer", "WorldCup", "MatchReview", "SportsDocumentary", "WhoScored",
    ),
}

# Local names used only when we actually know the club/country. Fallback = English.
TEAM_LOCAL: dict[str, dict[str, str]] = {
    "scotland": {"es": "Escocia", "az": "Şotlandiya", "ru": "Шотландия"},
    "morocco": {"es": "Marruecos", "az": "Mərakeş", "ru": "Марокко"},
    "mexico": {"es": "México", "az": "Meksika", "ru": "Мексика"},
    "south korea": {"es": "Corea del Sur", "az": "Cənubi Koreya", "ru": "Южная Корея"},
    "barcelona": {"es": "Barça", "az": "Barselona", "ru": "Барселона"},
    "rayo vallecano": {"es": "Rayo Vallecano", "az": "Rayo Valyekano", "ru": "Райо Вальекано"},
    "real madrid": {"es": "Real Madrid", "az": "Real Madrid", "ru": "Реал Мадрид"},
    "espanyol": {"es": "Espanyol", "az": "Espanyol", "ru": "Эспаньол"},
    "celtic": {"es": "Celtic", "az": "Seltik", "ru": "Селтик"},
    "rangers": {"es": "Rangers", "az": "Reyncers", "ru": "Рейнджерс"},
}

LEAGUE_LOCAL: dict[str, dict[str, str]] = {
    "fifa world cup": {
        "en": "World Cup", "es": "Mundial", "az": "Dünya Kuboku", "ru": "ЧМ",
    },
    "premier league": {
        "en": "Premier League", "es": "Premier League", "az": "Premer Liqa", "ru": "АПЛ",
    },
    "laliga": {
        "en": "LaLiga", "es": "LaLiga", "az": "LaLiqa", "ru": "Ла Лига",
    },
    "la liga": {
        "en": "LaLiga", "es": "LaLiga", "az": "LaLiqa", "ru": "Ла Лига",
    },
}

DERBIES: dict[frozenset[str], dict[str, str]] = {
    frozenset({"barcelona", "real madrid"}): {
        "en": "El Clasico", "es": "El Clásico", "az": "El Klasiko", "ru": "Эль Класико",
    },
    frozenset({"barcelona", "espanyol"}): {
        "en": "Derbi Barceloni", "es": "Derbi barcelonés", "az": "Barselona derbisi", "ru": "Дерби Барселоны",
    },
    frozenset({"celtic", "rangers"}): {
        "en": "Old Firm", "es": "Old Firm", "az": "Old Firm", "ru": "Олд Фирм",
    },
    frozenset({"liverpool", "everton"}): {
        "en": "Merseyside derby", "es": "Derbi de Merseyside", "az": "Merseyside derbisi", "ru": "Мерсисайдское дерби",
    },
    frozenset({"manchester united", "manchester city"}): {
        "en": "Manchester derby", "es": "Derbi de Mánchester", "az": "Mançester derbisi", "ru": "Манчестерское дерби",
    },
    frozenset({"arsenal", "tottenham"}): {
        "en": "North London derby", "es": "Derbi del Norte de Londres", "az": "Şimali London derbisi", "ru": "Северолондонское дерби",
    },
    frozenset({"inter", "ac milan"}): {
        "en": "Derby della Madonnina", "es": "Derbi de Milán", "az": "Milan derbisi", "ru": "Миланское дерби",
    },
}

_SCORELINE = re.compile(r"\b\d+\s*[-–:/]\s*\d+\b")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")
_NON_TAG = re.compile(r"[^A-Za-z0-9À-ÿА-Яа-яЁёƏəĞğİıÖöŞşÜüÇç]")

DISCLAIMERS = {
    "en": "Numbers are from the WhoScored/Opta event export. Pass share is not possession. We do not invent xG.",
    "es": "Las cifras salen del export de eventos WhoScored/Opta. La cuota de pases no es posesión. No inventamos xG.",
    "az": "Rəqəmlər WhoScored/Opta hadisə exportundandır. Pas payı posessiya deyil. xG uydurmuruq.",
    "ru": "Цифры — из WhoScored/Opta-экспорта. Доля передач — не владение. xG мы не выдумываем.",
}

FOLLOW_CTA = {
    "en": "Follow for the next audited recap — same data, no invented numbers.",
    "es": "Síguenos para el próximo recap auditado: mismos datos, cero cifras inventadas.",
    "az": "Növbəti yoxlanılmış recap üçün izlə: eyni data, uydurma rəqəm yoxdur.",
    "ru": "Подписывайтесь на следующий проверенный recap — те же данные, никаких выдуманных цифр.",
}

CHAPTER_LABELS = {
    "hook_claim": {"en": "The open", "es": "La apertura", "az": "Açılış", "ru": "Открытие"},
    "hook_punch": {"en": "The punch", "es": "El golpe", "az": "Zərbə", "ru": "Удар"},
    "live_clip": {"en": "The clip", "es": "El clip", "az": "Klip", "ru": "Клип"},
    "micro_hook": {"en": "Cut", "es": "Corte", "az": "Kəsim", "ru": "Нарезка"},
    "shot_map": {"en": "Shot map", "es": "Mapa de tiros", "az": "Zərbə xəritəsi", "ru": "Карта ударов"},
    "goal_chain": {"en": "Goal chain", "es": "Cadena del gol", "az": "Qol zənciri", "ru": "Голевая цепь"},
    "goal_timeline": {"en": "Goals", "es": "Goles", "az": "Qollar", "ru": "Голы"},
    "zone_control": {"en": "Territory", "es": "Territorio", "az": "Ərazi", "ru": "Территория"},
    "touch_heatmap": {"en": "Heatmap", "es": "Mapa de calor", "az": "İstilik xəritəsi", "ru": "Теплокарта"},
    "momentum": {"en": "Momentum", "es": "Momentum", "az": "Temp", "ru": "Моментум"},
    "field_tilt_wave": {"en": "Field tilt", "es": "Inclinación", "az": "Sahə meyli", "ru": "Наклон поля"},
    "stat_slam": {"en": "The numbers", "es": "Los números", "az": "Rəqəmlər", "ru": "Цифры"},
    "match_radar": {"en": "Radar", "es": "Radar", "az": "Radar", "ru": "Радар"},
    "keeper_frame": {"en": "The keeper", "es": "El portero", "az": "Qapıçı", "ru": "Вратарь"},
    "close": {"en": "Final score", "es": "Marcador final", "az": "Yekun hesab", "ru": "Итоговый счёт"},
    "player_spike": {"en": "The leader", "es": "El líder", "az": "Lider", "ru": "Лидер"},
    "pass_network": {"en": "Pass network", "es": "Red de pases", "az": "Pas şəbəkəsi", "ru": "Сеть передач"},
    "chance_funnel": {"en": "Chances", "es": "Ocasiones", "az": "Şanslar", "ru": "Моменты"},
    "conversion_gauges": {"en": "Conversion", "es": "Conversión", "az": "Realizasiya", "ru": "Реализация"},
    "time_zones": {"en": "By half", "es": "Por partes", "az": "Hissələr", "ru": "По таймам"},
    "standard_stats": {"en": "Box score", "es": "Estadísticas", "az": "Statistika", "ru": "Статистика"},
    "sterile_domination": {"en": "The ball", "es": "El balón", "az": "Top", "ru": "Мяч"},
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def localize_team(name: str, lang: str) -> str:
    if lang == "en":
        return name
    return TEAM_LOCAL.get(_key(name), {}).get(lang) or name


def localize_league(name: str, lang: str) -> str:
    table = LEAGUE_LOCAL.get(_key(name)) or {}
    if lang == "en":
        return table.get("en") or name
    return table.get(lang) or table.get("en") or name


def derby_name(home: str, away: str, lang: str) -> str | None:
    pair = frozenset({_key(home), _key(away)})
    row = DERBIES.get(pair)
    if not row:
        return None
    return row.get(lang) or row.get("en")


def slug(value: str) -> str:
    text = re.sub(r"[^\w]+", "-", (value or "").strip(), flags=re.ASCII)
    return text.strip("-").lower() or "match"


def hashtag_token(value: str) -> str:
    token = _NON_TAG.sub("", value or "")
    if not token:
        return ""
    if token[0].isdigit():
        token = "n" + token
    return "#" + token


def surname(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return parts[-1] if parts else name


def _pick(seq: list[str] | tuple[str, ...], seed: str, salt: str) -> str:
    if not seq:
        return ""
    return seq[hooks.pick_index(f"{seed}:{salt}", len(seq))]


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut or text[:limit]


def competition_line(ctx: FactContext, lang: str) -> str:
    """League + stage without repeating 'World Cup World Cup Grp. C'."""
    league = ctx.loc_league(lang)
    stage = (ctx.stage or "").strip()
    if not stage:
        return league
    if league and league.lower() in stage.lower():
        return stage
    if stage.lower() in league.lower():
        return league
    return f"{league} {stage}".strip()


def _ordinal(minute: int, lang: str) -> str:
    if lang == "es":
        return f"min {minute}"
    if lang == "az":
        return f"{minute}-ci dəq"
    if lang == "ru":
        return f"{minute}-я мин"
    if 10 <= minute % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(minute % 10, "th")
    return f"{minute}{suffix}"


def _minute_stamp(minute: int, lang: str) -> str:
    if lang == "es":
        return f"min {minute}"
    return f"{minute}'"


def _fmt_ts(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _collect_allowed_numbers(bundle: MatchBundle, audit: dict[str, Any], hook: dict[str, Any]) -> set[str]:
    values: list[Any] = [
        bundle.score.home, bundle.score.away, bundle.last_minute,
    ]
    kickoff = bundle.kickoff or ""
    if len(kickoff) >= 4 and kickoff[:4].isdigit():
        values.append(int(kickoff[:4]))
    for team_stats in (audit.get("team_stats") or {}).values():
        if isinstance(team_stats, dict):
            values.extend(team_stats.values())
    for goal in audit.get("goal_timeline") or []:
        values.extend([goal.get("minute"), goal.get("passes"), goal.get("duration_seconds"),
                       goal.get("pass_distance_m"), goal.get("second")])
    leaders = audit.get("player_leaders") or {}
    for item in leaders.values():
        if isinstance(item, dict):
            values.append(item.get("count"))
    values.extend(hook.get("numbers") or [])
    values.append(hook.get("hero_number"))
    values.append(len(audit.get("goal_timeline") or []))
    return hooks.allowed_number_tokens(hooks.collect_numbers(*values))


# ---------------------------------------------------------------------------
# fact context (audit + hook, no invention)
# ---------------------------------------------------------------------------

@dataclass
class FactContext:
    bundle: MatchBundle
    audit: dict[str, Any]
    hook: dict[str, Any]
    home: str
    away: str
    score: str
    score_home: int
    score_away: int
    winner: str
    loser: str
    is_draw: bool
    league: str
    stage: str
    kickoff: str
    year: str
    venue: str
    hook_kind: str
    hook_lines: list[str]
    hook_punch: str
    hero_number: Any
    hero_label: str
    scorers: list[dict[str, Any]]
    spike: dict[str, Any] | None
    shots_home: int
    shots_away: int
    blocked_claims: list[str]
    allowed_numbers: set[str]
    seed: str
    last_minute: int
    score_banned: list[str] = field(default_factory=list)

    @property
    def primary_scorer(self) -> dict[str, Any] | None:
        return self.scorers[0] if self.scorers else None

    @property
    def named_player(self) -> str:
        scorer = self.primary_scorer
        if scorer and scorer.get("name"):
            return str(scorer["name"])
        if self.spike and self.spike.get("player"):
            return str(self.spike["player"])
        return ""

    def loc_home(self, lang: str) -> str:
        return localize_team(self.home, lang)

    def loc_away(self, lang: str) -> str:
        return localize_team(self.away, lang)

    def loc_league(self, lang: str) -> str:
        return localize_league(self.league, lang)

    def fixture(self, lang: str) -> str:
        return f"{self.loc_home(lang)} vs {self.loc_away(lang)}"

    def derby(self, lang: str) -> str | None:
        return derby_name(self.home, self.away, lang)


def load_facts(
    bundle: MatchBundle,
    audit: dict[str, Any],
    hook: dict[str, Any] | None = None,
) -> FactContext:
    hook = hook or hooks.build_hook(bundle, audit)
    context = result_context(bundle, audit)
    timeline = audit.get("goal_timeline") or []
    scorers = []
    for goal in timeline:
        name = (goal.get("scorer") or "").strip()
        if not name or name.lower() == "unknown":
            continue
        scorers.append({
            "name": name,
            "surname": surname(name),
            "minute": int(goal.get("minute") or 0),
            "team": goal.get("team") or "",
            "own_goal": bool(goal.get("own_goal")),
            "penalty": bool(goal.get("penalty")),
            "passes": int(goal.get("passes") or 0),
        })
    leaders = audit.get("player_leaders") or {}
    spike = leaders.get("spike") if isinstance(leaders.get("spike"), dict) else None
    stats = audit.get("team_stats") or {}
    home_stats = stats.get(bundle.home) or {}
    away_stats = stats.get(bundle.away) or {}
    kickoff = bundle.kickoff or ""
    return FactContext(
        bundle=bundle,
        audit=audit,
        hook=hook,
        home=bundle.home,
        away=bundle.away,
        score=f"{bundle.score.home}-{bundle.score.away}",
        score_home=bundle.score.home,
        score_away=bundle.score.away,
        winner=context["winner"] or "",
        loser=context["loser"] or "",
        is_draw=bool(context["is_draw"]),
        league=bundle.league or "",
        stage=bundle.stage or "",
        kickoff=kickoff,
        year=kickoff[:4] if len(kickoff) >= 4 else "",
        venue=bundle.venue or "",
        hook_kind=str(hook.get("kind") or ""),
        hook_lines=[str(line) for line in (hook.get("lines") or []) if line],
        hook_punch=str(hook.get("punch") or ""),
        hero_number=hook.get("hero_number"),
        hero_label=str(hook.get("hero_label") or ""),
        scorers=scorers,
        spike=spike,
        shots_home=int(home_stats.get("shots") or 0),
        shots_away=int(away_stats.get("shots") or 0),
        blocked_claims=list((audit.get("data_health") or {}).get("blocked_claims") or []),
        allowed_numbers=_collect_allowed_numbers(bundle, audit, hook),
        seed=hooks.match_seed(bundle),
        last_minute=bundle.last_minute,
        score_banned=hooks.score_variants(bundle),
    )


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------

def _curiosity_templates(ctx: FactContext, lang: str) -> list[str]:
    fixture = ctx.fixture(lang)
    league = ctx.loc_league(lang)
    hero = ctx.hero_number
    kind = ctx.hook_kind
    if lang == "es":
        rows = [
            f"{fixture}: el dato que no cuadra",
            f"Recap {league} — {fixture} (sin spoiler)",
            f"{fixture}: mira esto antes del marcador",
        ]
        if hero is not None and kind == "chain_shock":
            rows.append(f"{fixture}: una jugada de {hero} pases")
        elif hero is not None:
            rows.append(f"{fixture}: el número {hero}")
        return rows
    if lang == "az":
        rows = [
            f"{fixture}: oturmayan rəqəm",
            f"{league} recap — {fixture} (spoylersiz)",
            f"{fixture}: hesabdan əvvəl bu kadr",
        ]
        if hero is not None and kind == "chain_shock":
            rows.append(f"{fixture}: {hero} paslıq hücum")
        elif hero is not None:
            rows.append(f"{fixture}: {hero} rəqəmi")
        return rows
    if lang == "ru":
        rows = [
            f"{fixture}: цифра, которая не сходится",
            f"Recap {league} — {fixture} (без спойлера)",
            f"{fixture}: сначала это, потом счёт",
        ]
        if hero is not None and kind == "chain_shock":
            rows.append(f"{fixture}: атака из {hero} передач")
        elif hero is not None:
            rows.append(f"{fixture}: число {hero}")
        return rows
    rows = [
        f"{fixture}: the number that doesn't fit",
        f"{league} recap — {fixture} (no spoilers)",
        f"Watch {fixture} before you look at the score",
    ]
    if hero is not None and kind == "chain_shock":
        rows.append(f"{fixture}: a {hero}-pass move you need to see")
    elif hero is not None:
        rows.append(f"{fixture}: start with {hero}")
    return rows


def _spoiler_templates(ctx: FactContext, lang: str) -> list[str]:
    scorer = ctx.primary_scorer
    minute = _minute_stamp(int(scorer["minute"]), lang) if scorer else ""
    who = scorer["surname"] if scorer else ""
    fixture = f"{ctx.loc_home(lang)} {ctx.score} {ctx.loc_away(lang)}"
    league = ctx.loc_league(lang)
    if lang == "es":
        rows = [f"{fixture} | {league}"]
        if who:
            rows.append(f"{fixture} | {who} {minute}")
        if ctx.winner:
            rows.append(f"{localize_team(ctx.winner, lang)} gana {ctx.score} | {league}")
        return rows
    if lang == "az":
        rows = [f"{fixture} | {league}"]
        if who:
            rows.append(f"{fixture} | {who} {minute}")
        if ctx.winner:
            rows.append(f"{localize_team(ctx.winner, lang)} {ctx.score} qalib | {league}")
        return rows
    if lang == "ru":
        rows = [f"{fixture} | {league}"]
        if who:
            rows.append(f"{fixture} | {who} {minute}")
        if ctx.winner:
            rows.append(f"{localize_team(ctx.winner, lang)} побеждает {ctx.score} | {league}")
        return rows
    rows = [f"{fixture} | {league} recap"]
    if who:
        rows.append(f"{fixture} | {who} {minute}")
    if ctx.winner:
        rows.append(f"{ctx.winner} win {ctx.score} | {league} {ctx.year}".strip())
    return rows


def _player_seo_templates(ctx: FactContext, lang: str) -> list[str]:
    player = ctx.named_player
    opponent = ctx.away if (ctx.primary_scorer or {}).get("team") == ctx.home else ctx.home
    if ctx.primary_scorer:
        opponent = ctx.away if ctx.primary_scorer["team"] == ctx.home else ctx.home
        opponent_l = localize_team(opponent, lang)
        league = ctx.loc_league(lang)
        minute = _minute_stamp(int(ctx.primary_scorer["minute"]), lang)
        if lang == "es":
            return [
                f"{player} vs {opponent_l} | gol {minute} | {league} {ctx.year}".strip(),
                f"Gol de {surname(player)} a {opponent_l} | {league}",
            ]
        if lang == "az":
            return [
                f"{player} vs {opponent_l} | {minute} qolu | {league} {ctx.year}".strip(),
                f"{surname(player)} qolu — {opponent_l} | {league}",
            ]
        if lang == "ru":
            return [
                f"{player} vs {opponent_l} | гол {minute} | {league} {ctx.year}".strip(),
                f"Гол {surname(player)} в ворота {opponent_l} | {league}",
            ]
        return [
            f"{player} vs {opponent_l} | {minute} goal | {league} {ctx.year}".strip(),
            f"{surname(player)} goal vs {opponent_l} | {league} recap",
        ]
    if ctx.spike and player:
        n = int(ctx.spike.get("count") or 0)
        action = str(ctx.spike.get("action") or "actions")
        team = localize_team(str(ctx.spike.get("team") or ""), lang)
        league = ctx.loc_league(lang)
        if lang == "es":
            return [f"{player} ({team}) — {n} {action} | {league}"]
        if lang == "az":
            return [f"{player} ({team}) — {n} {action} | {league}"]
        if lang == "ru":
            return [f"{player} ({team}) — {n} {action} | {league}"]
        return [f"{player} ({team}) {n} {action} | {league} recap"]
    return [f"{ctx.fixture(lang)} | {ctx.loc_league(lang)} {ctx.year}".strip()]


def _derby_templates(ctx: FactContext, lang: str) -> list[str]:
    derby = ctx.derby(lang)
    fixture = ctx.fixture(lang)
    league = ctx.loc_league(lang)
    comp = competition_line(ctx, lang)
    if derby:
        if lang == "es":
            return [f"{derby} | {fixture}", f"{derby} — recap {league}"]
        if lang == "az":
            return [f"{derby} | {fixture}", f"{derby} — {league} recap"]
        if lang == "ru":
            return [f"{derby} | {fixture}", f"{derby} — обзор {league}"]
        return [f"{derby} | {fixture} recap", f"{derby} — {league} {ctx.year}".strip()]
    if lang == "es":
        return [
            f"{fixture} | {comp}",
            f"Recap en español: {fixture} ({league})",
        ]
    if lang == "az":
        return [
            f"{fixture} | {comp}",
            f"Azərbaycanca recap: {fixture} ({league})",
        ]
    if lang == "ru":
        return [
            f"{fixture} | {comp}",
            f"Обзор на русском: {fixture} ({league})",
        ]
    return [
        f"{ctx.home} vs {ctx.away} | {comp}",
        f"{league} {ctx.year}: {ctx.home} vs {ctx.away}".strip(),
    ]


def _question_templates(ctx: FactContext, lang: str) -> list[str]:
    fixture = ctx.fixture(lang)
    hero = ctx.hero_number
    kind = ctx.hook_kind
    if lang == "es":
        rows = [f"¿Quién mandó de verdad en {fixture}?"]
        if hero is not None and kind == "chain_shock":
            rows.append(f"¿Qué fue la jugada de {hero} pases en {fixture}?")
        elif hero is not None:
            rows.append(f"¿Dónde entra el {hero} en {fixture}?")
        return rows
    if lang == "az":
        rows = [f"{fixture} oyununu kim idarə etdi?"]
        if hero is not None and kind == "chain_shock":
            rows.append(f"{fixture} matçındakı {hero} paslıq hücum nə idi?")
        elif hero is not None:
            rows.append(f"{fixture} üçün {hero} rəqəmi nə deməkdir?")
        return rows
    if lang == "ru":
        rows = [f"Кто реально контролировал {fixture}?"]
        if hero is not None and kind == "chain_shock":
            rows.append(f"Что это была за атака из {hero} передач в {fixture}?")
        elif hero is not None:
            rows.append(f"Откуда цифра {hero} в {fixture}?")
        return rows
    rows = [f"Who actually ran {fixture}?"]
    if hero is not None and kind == "chain_shock":
        rows.append(f"What was the {hero}-pass move in {fixture}?")
    elif hero is not None:
        rows.append(f"Where does {hero} fit in {fixture}?")
    return rows


def _is_curiosity_safe(text: str, ctx: FactContext) -> bool:
    raw = text or ""
    if _SCORELINE.search(raw):
        return False
    lower = raw.lower()
    for banned in ctx.score_banned:
        if banned and banned.lower() in lower:
            return False
    spoilers = (" still lost", " they lost", " win ", " wins ", " defeated", " gana ", " qalib", " побежд")
    return not any(token in lower for token in spoilers)


def build_titles(ctx: FactContext, lang: str, platform: str) -> dict[str, str]:
    limit = TITLE_LIMIT.get(platform, 90)
    builders = {
        "curiosity": _curiosity_templates,
        "spoiler_slam": _spoiler_templates,
        "player_seo": _player_seo_templates,
        "derby_language": _derby_templates,
        "question": _question_templates,
    }
    titles: dict[str, str] = {}
    for kind, builder in builders.items():
        options = builder(ctx, lang)
        if kind == "curiosity":
            options = [row for row in options if _is_curiosity_safe(row, ctx)] or [
                ctx.fixture(lang) + (" recap" if lang == "en" else "")
            ]
        chosen = _pick(options, ctx.seed, f"title:{lang}:{platform}:{kind}")
        titles[kind] = _trim(chosen, limit)
    return titles


# ---------------------------------------------------------------------------
# descriptions, hashtags, comments, chapters
# ---------------------------------------------------------------------------

def _hook_line(ctx: FactContext) -> str:
    return (ctx.hook_lines[0] if ctx.hook_lines else ctx.hook_punch).strip()


def _keyword_line(ctx: FactContext, lang: str) -> str:
    bits = [
        ctx.loc_home(lang), ctx.loc_away(lang), ctx.loc_league(lang),
        ctx.stage, ctx.year, ctx.named_player, ctx.venue, "recap", "highlights",
    ]
    if lang == "es":
        bits += ["resumen", "análisis"]
    elif lang == "az":
        bits += ["icmal", "analiz"]
    elif lang == "ru":
        bits += ["обзор", "анализ"]
    seen: set[str] = set()
    out = []
    for bit in bits:
        text = (bit or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return ", ".join(out)


def _fact_sentence(ctx: FactContext, lang: str) -> str:
    """One grounded sentence. No xG. No fake MOTM."""
    scorer = ctx.primary_scorer
    if lang == "es":
        if scorer:
            return (
                f"{scorer['name']} marcó al {_ordinal(int(scorer['minute']), lang)} "
                f"({ctx.loc_home(lang)} {ctx.score} {ctx.loc_away(lang)}). "
                f"Tiros {ctx.shots_home}-{ctx.shots_away}."
            )
        return f"{ctx.fixture(lang)} terminó {ctx.score}. Tiros {ctx.shots_home}-{ctx.shots_away}."
    if lang == "az":
        if scorer:
            return (
                f"{scorer['name']} {_ordinal(int(scorer['minute']), lang)} qol vurdu "
                f"({ctx.loc_home(lang)} {ctx.score} {ctx.loc_away(lang)}). "
                f"Zərbələr {ctx.shots_home}-{ctx.shots_away}."
            )
        return f"{ctx.fixture(lang)} {ctx.score} bitdi. Zərbələr {ctx.shots_home}-{ctx.shots_away}."
    if lang == "ru":
        if scorer:
            return (
                f"{scorer['name']} забил на {_ordinal(int(scorer['minute']), lang)} "
                f"({ctx.loc_home(lang)} {ctx.score} {ctx.loc_away(lang)}). "
                f"Удары {ctx.shots_home}-{ctx.shots_away}."
            )
        return f"{ctx.fixture(lang)} — {ctx.score}. Удары {ctx.shots_home}-{ctx.shots_away}."
    if scorer:
        extra = ""
        if scorer.get("passes"):
            extra = f" Build-up: {scorer['passes']} passes."
        return (
            f"{scorer['name']} scored in the {_ordinal(int(scorer['minute']), 'en')} minute "
            f"({ctx.home} {ctx.score} {ctx.away}). "
            f"Shots {ctx.shots_home}-{ctx.shots_away}.{extra}"
        )
    return f"{ctx.home} {ctx.score} {ctx.away}. Shots {ctx.shots_home}-{ctx.shots_away}."


def build_description(ctx: FactContext, lang: str, platform: str, *, chapters: list[dict[str, Any]] | None = None) -> str:
    hook = _hook_line(ctx)
    facts = _fact_sentence(ctx, lang)
    keywords = _keyword_line(ctx, lang)
    disclaimer = DISCLAIMERS.get(lang) or DISCLAIMERS["en"]
    cta = FOLLOW_CTA.get(lang) or FOLLOW_CTA["en"]
    if platform in {"tiktok", "reels", "shorts"}:
        body = f"{hook}\n\n{facts}\n\n{disclaimer}\n{cta}"
    else:
        header = f"{ctx.fixture(lang)} | {ctx.score} | {competition_line(ctx, lang)} | {ctx.kickoff} | {ctx.venue}".strip(" |")
        body = (
            f"{hook}\n\n{header}\n\n{facts}\n\nKeywords: {keywords}\n\n{disclaimer}\n{cta}"
        )
        if platform in {"youtube", "youtube_long"} and chapters:
            lines = "\n".join(f"{row['t']} {row['title']}" for row in chapters)
            label = {"en": "Chapters", "es": "Capítulos", "az": "Fəsillər", "ru": "Таймкоды"}.get(lang, "Chapters")
            body += f"\n\n{label}:\n{lines}"
    return body.strip() + "\n"


def build_hashtags(ctx: FactContext, lang: str, platform: str) -> dict[str, list[str]]:
    pool = list(BIG_POOLS.get(platform) or BIG_POOLS["tiktok"])
    seed = f"{ctx.seed}:{platform}:{lang}"
    start = hooks.pick_index(seed, max(1, len(pool) - 4))
    big = [hashtag_token(tag) for tag in (pool[start:start + 5] or pool[:5])]
    if len(big) < 5:
        extra = [hashtag_token(tag) for tag in pool if hashtag_token(tag) not in big]
        big.extend(extra)
    big = [tag for tag in big if tag][:5]

    niche_bits = [
        ctx.loc_home(lang), ctx.loc_away(lang), ctx.loc_league(lang),
        ctx.stage, ctx.named_player, surname(ctx.named_player) if ctx.named_player else "",
        ctx.venue, f"{ctx.loc_league(lang)}{ctx.year}" if ctx.year else ctx.year,
        (ctx.spike or {}).get("player") or "",
        derby_name(ctx.home, ctx.away, "en") or "",
    ]
    if lang == "es":
        niche_bits += ["resumenfutbol", "analisisoptado"]
    elif lang == "az":
        niche_bits += ["futbolrecap", "DunyaKuboku"] if "world cup" in _key(ctx.league) else ["futbolrecap"]
    elif lang == "ru":
        niche_bits += ["обзорматча", "тактика"]
    niche: list[str] = []
    seen = {tag.lower() for tag in big}
    for bit in niche_bits:
        tag = hashtag_token(str(bit))
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        niche.append(tag)
        if len(niche) >= 8:
            break
    # Pad with real competition fragments only — never junk or invented clubs.
    pads = [ctx.home, ctx.away, ctx.league, "recap"]
    for bit in pads:
        if len(niche) >= 8:
            break
        tag = hashtag_token(str(bit))
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            niche.append(tag)
    return {"big": big[:5], "niche": niche[:8]}


def build_pinned_comments(ctx: FactContext, lang: str, platform: str) -> list[str]:
    fixture = ctx.fixture(lang)
    hero = ctx.hero_number
    scorer = ctx.primary_scorer
    spike = ctx.spike or {}
    questions: list[str] = []
    if lang == "es":
        questions.append(f"¿Quién controló de verdad {fixture}?")
        if hero is not None:
            questions.append(f"El {hero} del open — ¿te convenció?")
        if scorer:
            questions.append(f"{scorer['surname']} al {_ordinal(int(scorer['minute']), lang)}: ¿el momento del partido?")
        if spike.get("player"):
            questions.append(f"{spike['player']} lideró {spike.get('action')} ({spike.get('count')}). ¿Lo viste?")
    elif lang == "az":
        questions.append(f"{fixture} oyununu kim idarə etdi?")
        if hero is not None:
            questions.append(f"Açılışdakı {hero} — razısan?")
        if scorer:
            questions.append(f"{scorer['surname']} {_ordinal(int(scorer['minute']), lang)}: matçın anı?")
        if spike.get("player"):
            questions.append(f"{spike['player']} {spike.get('action')} üzrə {spike.get('count')}. Gördün?")
    elif lang == "ru":
        questions.append(f"Кто реально контролировал {fixture}?")
        if hero is not None:
            questions.append(f"Цифра {hero} в открытии — согласны?")
        if scorer:
            questions.append(f"{scorer['surname']} на {_ordinal(int(scorer['minute']), lang)}: момент матча?")
        if spike.get("player"):
            questions.append(f"{spike['player']} лидировал по {spike.get('action')} ({spike.get('count')}). Заметили?")
    else:
        questions.append(f"Who actually ran {fixture}?")
        if hero is not None:
            questions.append(f"That opening {hero} — did it land?")
        if scorer:
            questions.append(
                f"{scorer['surname']} in the {_ordinal(int(scorer['minute']), 'en')} minute: the moment of the match?"
            )
        if spike.get("player"):
            questions.append(
                f"{spike['player']} led {spike.get('action')} ({spike.get('count')}). Did you clock it?"
            )
    # Platform-flavoured closer, still grounded.
    if platform in {"tiktok", "reels", "shorts"}:
        questions.append(
            {"en": "Replay or overreact — which one are you?",
             "es": "¿Lo ves otra vez o exageramos?",
             "az": "Təkrar, yoxsa həddən artıq reaksiya?",
             "ru": "Пересмотр или перегон?"}.get(lang, "Replay or overreact?")
        )
    else:
        questions.append(
            {"en": "Drop the minute you rewound.",
             "es": "¿En qué minuto diste atrás?",
             "az": "Hansı dəqiqəyə qayıtdın?",
             "ru": "На какой минуте перемотали?"}.get(lang, "Drop the minute you rewound.")
        )
    # Stable unique pick of 3.
    if len(questions) <= 3:
        return questions
    start = hooks.pick_index(f"{ctx.seed}:pin:{lang}:{platform}", len(questions) - 2)
    return questions[start:start + 3]


def build_chapters(
    scene_list: list[dict[str, Any]] | None,
    duration: float | None,
    lang: str,
) -> list[dict[str, Any]]:
    if not duration or duration < 8:
        return []
    chapters: list[dict[str, Any]] = []
    if scene_list:
        for scene in scene_list:
            viz = str(scene.get("visualization") or scene.get("id") or "")
            if viz in {"micro_hook"}:
                continue
            start = float(scene.get("visible_start") or scene.get("start") or 0)
            if start >= duration:
                continue
            label_row = CHAPTER_LABELS.get(viz) or {}
            title = label_row.get(lang) or label_row.get("en") or viz.replace("_", " ")
            stamp = _fmt_ts(start)
            if chapters and chapters[-1]["t"] == stamp:
                continue
            chapters.append({"t": stamp, "seconds": round(start, 2), "title": title, "id": viz})
    if not chapters:
        labels = {
            "en": [("The open", 0.0), ("Proof", min(8.0, duration * 0.25)), ("Final score", max(0.0, duration - 4))],
            "es": [("Apertura", 0.0), ("Prueba", min(8.0, duration * 0.25)), ("Marcador", max(0.0, duration - 4))],
            "az": [("Açılış", 0.0), ("Sübut", min(8.0, duration * 0.25)), ("Hesab", max(0.0, duration - 4))],
            "ru": [("Открытие", 0.0), ("Доказательство", min(8.0, duration * 0.25)), ("Счёт", max(0.0, duration - 4))],
        }[lang if lang in {"en", "es", "az", "ru"} else "en"]
        chapters = [{"t": _fmt_ts(sec), "seconds": round(sec, 2), "title": title} for title, sec in labels]
    if not chapters or chapters[0]["seconds"] != 0:
        first_title = CHAPTER_LABELS["hook_claim"].get(lang) or "The open"
        chapters = [{"t": "0:00", "seconds": 0.0, "title": first_title, "id": "open"}] + [
            row for row in chapters if row.get("seconds", 1) > 0
        ]
    return chapters


def build_filenames(ctx: FactContext, lang: str, platform: str) -> list[str]:
    home, away = slug(ctx.home), slug(ctx.away)
    league = slug(ctx.loc_league("en") or ctx.league)
    player = slug(surname(ctx.named_player)) if ctx.named_player else "recap"
    year = ctx.year or "match"
    return [
        f"{home}-vs-{away}-{year}-recap-{lang}.mp4",
        f"{home}_{away}_{ctx.score}_{player}.mp4",
        f"{year}-{league}-{home}-vs-{away}-{platform}.mp4",
    ]


def thumbnail_words(ctx: FactContext, lang: str, variant: str) -> str:
    scorer = ctx.primary_scorer
    if variant == "slam":
        parts: list[str] = []
        if scorer:
            parts += [scorer["surname"].upper(), f"{int(scorer['minute'])}'", "GOAL"]
        elif ctx.winner:
            parts += [hooks.hook_team_name(ctx.winner), ctx.score, "FINAL"]
        else:
            parts += [hooks.hook_team_name(ctx.home), ctx.score, hooks.hook_team_name(ctx.away)]
        if ctx.year:
            parts.append(ctx.year)
        return thumbnails.clip_words(" ".join(parts), 3, 5)
    parts = []
    if ctx.hero_number is not None:
        label = (ctx.hero_label or "NO").split()[0]
        parts += [str(ctx.hero_number), label.upper()]
        if ctx.hook_kind == "chain_shock":
            parts += ["KNIFE"] if lang == "en" else {
                "es": ["PASES"], "az": ["PAS"], "ru": ["ПАС"],
            }.get(lang, ["MOVE"])
        else:
            parts += ["LOOK"] if lang == "en" else {
                "es": ["MIRA"], "az": ["BAX"], "ru": ["СМОТРИ"],
            }.get(lang, ["LOOK"])
    else:
        parts += [hooks.hook_team_name(ctx.home), "VS", hooks.hook_team_name(ctx.away)]
    return thumbnails.clip_words(" ".join(parts), 3, 5)


def alt_text(ctx: FactContext, lang: str, overlay: str) -> str:
    if lang == "es":
        return (
            f"Miniatura del recap {ctx.fixture(lang)} ({ctx.loc_league(lang)} {ctx.year}). "
            f"Texto: {overlay}. Datos WhoScored/Opta."
        )
    if lang == "az":
        return (
            f"{ctx.fixture(lang)} recap thumbnail ({ctx.loc_league(lang)} {ctx.year}). "
            f"Yazı: {overlay}. WhoScored/Opta datası."
        )
    if lang == "ru":
        return (
            f"Превью recap {ctx.fixture(lang)} ({ctx.loc_league(lang)} {ctx.year}). "
            f"Текст: {overlay}. Данные WhoScored/Opta."
        )
    return (
        f"Thumbnail for {ctx.home} vs {ctx.away} {ctx.league} {ctx.year} recap. "
        f"Overlay: {overlay}. Event data from WhoScored/Opta."
    )


# ---------------------------------------------------------------------------
# pack assembly + IO
# ---------------------------------------------------------------------------

def _platform_pack(
    ctx: FactContext,
    lang: str,
    platform: str,
    *,
    chapters: list[dict[str, Any]] | None,
    thumbs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    titles = build_titles(ctx, lang, platform)
    tags = build_hashtags(ctx, lang, platform)
    shape = thumbnails.SHAPE_FOR_PLATFORM.get(platform, "vertical")
    variant = "curiosity" if platform in {"tiktok", "reels"} else "slam"
    thumb = thumbs.get(f"{variant}_{shape}") or thumbs.get(f"slam_{shape}") or {}
    return {
        "titles": titles,
        "description": build_description(ctx, lang, platform, chapters=chapters if platform in {"youtube", "youtube_long"} else None),
        "hashtags": tags,
        "pinned_comments": build_pinned_comments(ctx, lang, platform),
        "thumbnail": thumb,
        "alt": thumb.get("alt") or alt_text(ctx, lang, thumb.get("text") or thumbnail_words(ctx, lang, variant)),
        "filenames": build_filenames(ctx, lang, platform),
    }


def _posting_txt(lang: str, language_name: str, ctx: FactContext, platforms: dict[str, Any], youtube_long: dict[str, Any]) -> str:
    lines = [
        f"GROWTH PACK — {ctx.home} vs {ctx.away} — {ctx.score}",
        f"Language: {language_name} ({lang})",
        f"Hook kind: {ctx.hook_kind}  (read from hooks.build_hook, not rewritten)",
        f"Competition: {competition_line(ctx, 'en')}  |  {ctx.kickoff}  |  {ctx.venue}",
        f"Blocked claims: {', '.join(ctx.blocked_claims) or 'none'}",
        "",
        DISCLAIMERS.get(lang) or DISCLAIMERS["en"],
        "",
    ]
    for platform, pack in platforms.items():
        lines += [f"{'=' * 72}", f"PLATFORM: {platform}", "=" * 72, ""]
        lines.append("Titles:")
        for kind in TITLE_KINDS:
            lines.append(f"  [{kind}] {pack['titles'][kind]}")
        lines += ["", "Description:", pack["description"].rstrip(), ""]
        tags = pack["hashtags"]
        lines.append("Hashtags — big (5):  " + " ".join(tags["big"]))
        lines.append("Hashtags — niche (8): " + " ".join(tags["niche"]))
        lines.append("")
        lines.append("Pinned comment bait:")
        for index, comment in enumerate(pack["pinned_comments"], 1):
            lines.append(f"  {index}. {comment}")
        thumb = pack.get("thumbnail") or {}
        lines += [
            "",
            f"Thumbnail overlay ({thumb.get('words', '?')} words, huge): {thumb.get('text', '')}",
            f"Thumbnail file: {thumb.get('path', '')}",
            f"Alt: {pack.get('alt', '')}",
            "Filenames:",
        ]
        for name in pack["filenames"]:
            lines.append(f"  - {name}")
        lines.append("")
    if youtube_long:
        lines += ["=" * 72, "YOUTUBE LONG (chapters)", "=" * 72, ""]
        if youtube_long.get("chapters"):
            for row in youtube_long["chapters"]:
                lines.append(f"  {row['t']}  {row['title']}")
        else:
            lines.append(f"  skipped: {youtube_long.get('skipped') or 'duration unknown'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _match_payload(ctx: FactContext) -> dict[str, Any]:
    return {
        "dir": str(ctx.bundle.match_dir),
        "home": ctx.home,
        "away": ctx.away,
        "score": ctx.score,
        "score_display": ctx.bundle.score.display,
        "league": ctx.league,
        "stage": ctx.stage,
        "kickoff": ctx.kickoff,
        "venue": ctx.venue,
        "winner": ctx.winner,
        "loser": ctx.loser,
        "scorers": ctx.scorers,
        "player_leaders": {
            "spike": {k: v for k, v in (ctx.spike or {}).items() if k != "points"},
        },
        "shots": {"home": ctx.shots_home, "away": ctx.shots_away},
        "blocked_claims": ctx.blocked_claims,
        "hook": {
            "kind": ctx.hook_kind,
            "lines": ctx.hook_lines,
            "punch": ctx.hook_punch,
            "hero_number": ctx.hero_number,
            "hero_label": ctx.hero_label,
            "numbers": ctx.hook.get("numbers"),
        },
    }


def build_language_pack(
    ctx: FactContext,
    lang: str,
    *,
    dest: Path,
    duration: float | None,
    scene_list: list[dict[str, Any]] | None,
    still: Path | None,
) -> dict[str, Any]:
    slam = thumbnail_words(ctx, lang, "slam")
    curiosity = thumbnail_words(ctx, lang, "curiosity")
    thumbs = thumbnails.write_thumbnails(
        dest / "thumbs",
        language=lang,
        slam_text=slam,
        curiosity_text=curiosity,
        home=ctx.home,
        away=ctx.away,
        kicker=f"{ctx.home} vs {ctx.away}",
        alt_slam=alt_text(ctx, lang, slam),
        alt_curiosity=alt_text(ctx, lang, curiosity),
        still=still,
    )
    chapters = build_chapters(scene_list, duration, lang)
    platforms = {
        platform: _platform_pack(ctx, lang, platform, chapters=chapters, thumbs=thumbs)
        for platform in PLATFORMS
    }
    youtube_long = {
        "titles": build_titles(ctx, lang, "youtube_long"),
        "description": build_description(ctx, lang, "youtube_long", chapters=chapters),
        "hashtags": build_hashtags(ctx, lang, "youtube_long"),
        "pinned_comments": build_pinned_comments(ctx, lang, "youtube_long"),
        "chapters": chapters,
        "duration_seconds": duration,
        "skipped": None if chapters else "duration unknown",
        "thumbnail": thumbs.get("slam_youtube") or {},
        "filenames": build_filenames(ctx, lang, "youtube_long"),
    }
    (dest / lang).mkdir(parents=True, exist_ok=True)
    posting = _posting_txt(lang, i18n.language_name(lang), ctx, platforms, youtube_long)
    posting_path = dest / lang / "posting.txt"
    posting_path.write_text(posting, encoding="utf-8")
    return {
        "language": lang,
        "language_name": i18n.language_name(lang),
        "platforms": platforms,
        "youtube_long": youtube_long,
        "thumbnails": thumbs,
        "posting_txt": str(posting_path),
    }


def _copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def write_growth_pack(
    match_dir: str | Path,
    *,
    language: str = "en",
    package_dir: str | Path | None = None,
    dest_dir: str | Path | None = None,
    audit: dict[str, Any] | None = None,
    bundle: MatchBundle | None = None,
    scene_list: list[dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
    mp4_path: str | Path | None = None,
    hook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build bilingual posting artefacts. Always includes English.

    Returns the pack dict that was written to ``pack.json``.
    """
    match_dir = Path(match_dir)
    bundle = bundle or load_match(match_dir)
    audit = audit or audit_mod.build_audit(bundle)
    language = i18n.normalize_language(language)

    if scene_list is None and package_dir:
        plan_path = Path(package_dir) / "video_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            scene_list = plan.get("scenes") or []
            if duration_seconds is None:
                duration_seconds = (plan.get("generation") or {}).get("total_seconds")

    if duration_seconds is None and mp4_path:
        from . import video as video_mod
        duration_seconds = video_mod.probe_duration(Path(mp4_path))
    if duration_seconds is None and package_dir:
        from . import video as video_mod
        mp4 = Path(package_dir) / "match_video.mp4"
        if mp4.exists():
            duration_seconds = video_mod.probe_duration(mp4)

    still = thumbnails.find_hook_still(match_dir, package_dir)

    previous = i18n.get_language()
    languages = [language]
    if language != "en":
        languages.append("en")

    dests: list[Path] = []
    if dest_dir:
        dests.append(Path(dest_dir))
    else:
        dests.append(match_dir / "growth")
        if package_dir and Path(package_dir).resolve() != match_dir.resolve():
            dests.append(Path(package_dir) / "growth")

    primary = dests[0]
    if primary.exists():
        shutil.rmtree(primary)
    primary.mkdir(parents=True, exist_ok=True)

    packs: dict[str, Any] = {}
    try:
        for lang in languages:
            i18n.set_language(lang)
            hook_for_lang = hook if (hook and lang == language) else hooks.build_hook(bundle, audit)
            ctx = load_facts(bundle, audit, hook_for_lang)
            packs[lang] = build_language_pack(
                ctx, lang, dest=primary, duration=duration_seconds,
                scene_list=scene_list, still=still,
            )
        # Snapshot facts from the render-language context for the JSON header.
        i18n.set_language(language)
        header_hook = hook or hooks.build_hook(bundle, audit)
        ctx = load_facts(bundle, audit, header_hook)
    finally:
        i18n.set_language(previous)

    payload = {
        "schema": SCHEMA,
        "match": _match_payload(ctx),
        "languages": languages,
        "duration_seconds": duration_seconds,
        "mp4": str(mp4_path) if mp4_path else None,
        "hook_still": str(still) if still else None,
        "packs": packs,
        "written": [str(path) for path in dests],
    }
    write_json(primary / "pack.json", payload)
    index = [
        f"GROWTH PACK  {ctx.home} vs {ctx.away}  {ctx.score}",
        f"schema {SCHEMA}",
        f"languages: {', '.join(languages)}",
        f"json: {primary / 'pack.json'}",
        "",
        "Open {lang}/posting.txt for copy-paste titles, descriptions, hashtags,",
        "pinned comments, thumbnail overlay, alt text and filenames.",
        "",
    ]
    (primary / "INDEX.txt").write_text("\n".join(index), encoding="utf-8")

    for extra in dests[1:]:
        _copy_tree(primary, extra)
        # Rewrite posting paths in the copied JSON so they point at the copy.
        copied = json.loads((extra / "pack.json").read_text(encoding="utf-8"))
        copied_text = json.dumps(copied, ensure_ascii=False).replace(str(primary), str(extra))
        (extra / "pack.json").write_text(json.dumps(json.loads(copied_text), indent=2, ensure_ascii=False), encoding="utf-8")

    return payload


def parse_growth_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Standalone CLI with dest names that will not collide with video_pipeline flags."""
    parser = argparse.ArgumentParser(
        prog="python -m recap.growth",
        description="Write a bilingual growth/SEO posting pack for one match export.",
    )
    parser.add_argument("--match-dir", dest="growth_match_dir", required=True,
                        help="Scrape export directory (output/<match>/)")
    parser.add_argument("--language", dest="growth_language", default="en",
                        help="Render language; English is always added")
    parser.add_argument("--package-dir", dest="growth_package_dir", default="",
                        help="video_output/<match>/ — used for plan, mp4 duration, hook stills")
    parser.add_argument("--growth-dir", dest="growth_pack_dir", default="",
                        help="Override output directory (default: <match-dir>/growth)")
    parser.add_argument("--duration", dest="growth_duration_seconds", type=float, default=None,
                        help="Known recap duration in seconds (enables YouTube chapters)")
    parser.add_argument("--mp4", dest="growth_mp4_path", default="",
                        help="Path to the rendered mp4 (probed for duration when --duration omitted)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_growth_args(argv)
    pack = write_growth_pack(
        args.growth_match_dir,
        language=args.growth_language,
        package_dir=args.growth_package_dir or None,
        dest_dir=args.growth_pack_dir or None,
        duration_seconds=args.growth_duration_seconds,
        mp4_path=args.growth_mp4_path or None,
    )
    for path in pack.get("written") or []:
        print(f"  growth: {path}")
    return pack


if __name__ == "__main__":
    main()
