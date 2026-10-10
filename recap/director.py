"""Choosing what to show and writing what to say.

Gemini is optional throughout. Every function here has a deterministic path
that produces a complete, match-specific script from the audit alone, and the
Gemini path can only ever override *wording* — never numbers, never which
metric a label is attached to.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .audit import best_goal_chain, credible_goal_chains, dominant_team, result_context
from .data import MatchBundle, clean_text
from .jsonutil import loads_model_json
from . import hooks, i18n

# Script and translation stay on this list. gemini-3.6/3.7/3.8 are excluded:
# they answer 403, 429, or 500 often enough that walking them dominates runtime.
# Gemini 3 Flash has no stable id; the API name is gemini-3-flash-preview.
GEMINI_MODELS = (
    "gemma-4-31b-it",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
)
DEFAULT_MODEL = GEMINI_MODELS[0]
DEFAULT_SCRIPT_MODEL = GEMINI_MODELS[0]
_GEMINI_ALLOW = frozenset(GEMINI_MODELS)

SYSTEM_PROMPT = (
    "You write short-form football voiceover for vertical recap cards. "
    "Return exactly one JSON object. No markdown fences, no second object, "
    "no commentary before or after the JSON. "
    "Specific names and minutes. Titles are claims, not labels. "
    "No hashtags, no emoji, no 'in this video'. Never invent a number. "
    "The score stays off every card except close. "
    "Vary sentence openings. Do not start every line with a team name. "
    "Do not tease the next card unless it earns it. Do not use the word 'but' "
    "more than once across the whole script."
)

SCRIPT_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "scenes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "kicker": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "subtitle": {"type": "STRING"},
                    "insight": {"type": "STRING"},
                    "narration": {"type": "STRING"},
                },
                "required": ["id", "title", "narration"],
            },
        }
    },
    "required": ["scenes"],
}

_JSON_FAIL = (
    "jsondecodeerror",
    "extra data",
    "expecting value",
    "unterminated",
    "invalid control",
    "not an object",
    "empty model json",
    "no json value",
)
_SCHEMA_FAIL = ("response_schema", "invalid schema", "unknown field", "response schema")


def allowed_gemini_model(name: str | None) -> str | None:
    token = str(name or "").strip()
    return token if token in _GEMINI_ALLOW else None


def _resolve_gemini_model(
    explicit: str | None,
    from_env: str | None,
    default: str,
    label: str,
) -> str:
    """CLI wins, then an allowlisted env value. Retired ids are ignored."""
    for raw in (explicit, from_env):
        token = str(raw or "").strip()
        if not token:
            continue
        allowed = allowed_gemini_model(token)
        if allowed:
            return allowed
        print(f"  [gemini] ignoring {label}={token}; not in the script model list")
    return default


def gemini_model_chain(*preferred: str | None) -> list[str]:
    """Preferred allowlisted ids first, then the rest. Unknown ids are dropped."""
    ordered: list[str] = []
    for name in preferred:
        token = allowed_gemini_model(name)
        if token and token not in ordered:
            ordered.append(token)
    for name in GEMINI_MODELS:
        if name not in ordered:
            ordered.append(name)
    return ordered


def gemini_failure_action(message: str, *, can_strip_schema: bool) -> str:
    """What to do after one generate_content failure.

    ``switch`` abandons the model immediately (403, 429, 500, 503, missing model).
    ``strip_schema`` retries the same model once without response_schema.
    ``retry_json`` retries the same model once when the body was not JSON.
    ``stop`` moves on without a backoff sleep.
    """
    lowered = (message or "").lower()
    if can_strip_schema and any(token in lowered for token in _SCHEMA_FAIL):
        return "strip_schema"
    if any(token in lowered for token in _JSON_FAIL):
        return "retry_json"
    upper = message.upper()
    if any(token in lowered for token in (
        "not found",
        "not supported",
        "unknown model",
        "permission_denied",
        "permission denied",
        "forbidden",
        "exceeded your current quota",
        "quota exceeded",
        "resource_exhausted",
        "resource exhausted",
        "unavailable",
    )) or any(code in upper for code in ("403", "404", "429", "500", "503")) or "INTERNAL" in upper:
        return "switch"
    return "stop"


SCRIPT_FEW_SHOTS = [
    {
        "good": "Saka had the last word in the 81st. The first hour was all City.",
        "why": "A surname, a minute, a claim.",
    },
    {
        "good": "Villa put 15 shots on the tape. The box was a graveyard.",
        "why": "A real count and an interpretation of the picture.",
    },
    {
        "bad": "They came out swinging. But look at the shot map.",
        "why": "No number, no name, formulaic 'but' tease.",
    },
]


# ---------------------------------------------------------------------------
# stat catalogue
# ---------------------------------------------------------------------------
# The label is bound to the key here and cannot be overridden downstream. This
# is what stops a pass-share proxy from being presented as "possession".

STAT_CATALOG: dict[str, dict[str, Any]] = {
    "goals": {"label": "Goals", "kind": "count"},
    "shots": {"label": "Shots", "kind": "count"},
    "shots_on_target": {"label": "On target", "kind": "count"},
    "shots_blocked": {"label": "Blocked", "kind": "count"},
    "big_chances": {"label": "Big chances", "kind": "count"},
    "pass_share_pct": {"label": "Pass share", "kind": "percent"},
    "possession_pct": {"label": "Possession", "kind": "percent"},
    "pass_accuracy_pct": {"label": "Pass accuracy", "kind": "percent"},
    "touch_share_pct": {"label": "Touch share", "kind": "percent"},
    "final_third_passes": {"label": "Final-third passes", "kind": "count"},
    "box_entry_passes": {"label": "Passes into the box", "kind": "count"},
    "penalty_box_touches": {"label": "Box touches", "kind": "count"},
    "key_passes": {"label": "Chances created", "kind": "count"},
    "corners": {"label": "Corners", "kind": "count"},
    "fouls": {"label": "Fouls", "kind": "count"},
    "saves": {"label": "Keeper saves", "kind": "count"},
    "blocks": {"label": "Blocks", "kind": "count"},
    "tackles_won": {"label": "Tackles won", "kind": "count"},
    "interceptions": {"label": "Interceptions", "kind": "count"},
    "dribbles_won": {"label": "Dribbles won", "kind": "count"},
    "dispossessed": {"label": "Dispossessed", "kind": "count"},
    "xg": {"label": "xG", "kind": "decimal"},
    "xgot": {"label": "xGOT", "kind": "decimal"},
    "offsides": {"label": "Offsides", "kind": "count"},
}

# Weight applied when picking the most interesting rows for a stat card.
STAT_INTEREST = {
    "goals": 1.40,
    "shots_on_target": 0.70,
    "big_chances": 0.60,
    "shots": 0.50,
    "penalty_box_touches": 0.40,
    "pass_share_pct": 0.30,
    "possession_pct": 0.35,
    "final_third_passes": 0.25,
    "saves": 0.25,
    "dribbles_won": 0.32,
    "xg": 0.80,
    "xgot": 0.55,
    "corners": 0.10,
}


def stat_label(key: str) -> str:
    return i18n.stat_label(key)


def format_stat(key: str, value: Any) -> str:
    kind = STAT_CATALOG.get(key, {}).get("kind", "count")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind == "percent":
        return f"{number:.0f}%"
    if kind == "decimal":
        return f"{number:.2f}"
    return f"{number:.0f}"


def pick_stat_rows(bundle: MatchBundle, audit: dict[str, Any], limit: int = 5,
                   skip: tuple[str, ...] = ("goals",)) -> list[str]:
    """Rank stat keys by how much they separate the two teams for this match."""
    stats = audit["team_stats"]
    home = stats.get(bundle.home, {})
    away = stats.get(bundle.away, {})

    ranked: list[tuple[float, str]] = []
    health = audit.get("data_health") or {}
    source_supported = set(audit.get("source_supported_stats") or [])
    for key in STAT_CATALOG:
        if key in skip:
            continue
        if key == "xg" and not health.get("has_vendor_xg"):
            continue
        if key == "xgot" and not health.get("has_vendor_xgot"):
            continue
        if source_supported and key not in source_supported and key != "goals":
            continue
        if key not in home or key not in away:
            continue
        home_value = float(home.get(key) or 0)
        away_value = float(away.get(key) or 0)
        if home_value == 0 and away_value == 0:
            continue
        denominator = max(abs(home_value), abs(away_value), 1.0)
        separation = abs(home_value - away_value) / denominator
        ranked.append((separation + STAT_INTEREST.get(key, 0.0), key))

    ranked.sort(reverse=True)
    chosen = [key for _, key in ranked[:limit]]
    return chosen or ["shots"]


# ---------------------------------------------------------------------------
# copy hygiene
# ---------------------------------------------------------------------------

# Claims we cannot support from an event export, checked against public copy.
_FORBIDDEN = [
    (r"\bx\s?g(ot)?\b", "expected-goals language, which this export has no data for"),
    (r"\bpossession\b", "'possession' — the export only supports pass share"),
    (r"\breceipts?\b", "internal jargon"),
    (r"\baudit\b", "internal jargon"),
    (r"\bexpected goals?\b", "expected-goals language"),
]

_SOFTEN = [
    (r"\bpossession share\b", "pass share"),
    (r"\bpossession\b", "pass share"),
    (r"\breceipts\b", "numbers"),
    (r"\breceipt\b", "number"),
]


def sanitize(value: Any, fallback: str = "") -> str:
    text = clean_text(value, fallback)
    for pattern, replacement in _SOFTEN:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def copy_problems(scenes: list[dict[str, Any]], audit: dict[str, Any]) -> list[str]:
    """Public-facing strings that make a claim the data cannot back."""
    health = audit.get("data_health", {})
    allow_xg = bool(health.get("has_vendor_xg"))
    allow_poss = bool(health.get("has_vendor_possession"))
    problems: list[str] = []
    for scene in scenes:
        for field in ("kicker", "title", "subtitle", "insight", "narration"):
            text = clean_text(scene.get(field))
            if not text:
                continue
            for pattern, reason in _FORBIDDEN:
                if allow_xg and "expected" in reason:
                    continue
                if allow_poss and "possession" in reason:
                    continue
                if re.search(pattern, text, flags=re.IGNORECASE):
                    problems.append(f"{scene.get('id', '?')}.{field} uses {reason}: {text[:70]!r}")
            if scene.get("hook") and _SCORELINE.search(text):
                problems.append(
                    f"{scene.get('id', '?')}.{field} spoils the score in the hook: {text[:70]!r}"
                )
    return problems


# ---------------------------------------------------------------------------
# visualization candidates
# ---------------------------------------------------------------------------

SHAPE_FAMILY = {
    "shot_map": "pitch",
    "goalmouth": "pitch",
    "keeper_frame": "pitch",
    "goal_chain": "hero",
    "pass_network": "territory",
    "zone_control": "territory",
    "touch_heatmap": "territory",
    "time_zones": "territory",
    "momentum": "time",
    "goal_timeline": "time",
    "field_tilt_wave": "time",
    "xg_race": "time",
    "sterile_domination": "comparison",
    "chance_funnel": "funnel",
    "match_radar": "radar",
    "stat_slam": "slam",
    "conversion_gauges": "gauges",
    "player_spike": "poster",
    "standard_stats": "bars",
    "box_score": "bars",
    "shot_clock_spiral": "spiral",
    "press_trap": "trap",
    "pass_lanes": "lanes",
    "bench_impact": "bench",
    "duel_tower": "tower",
    "aerial_war": "aerial",
    "halftime_split": "split",
    "touch_skyline": "skyline",
    "shot_skyline": "towers",
    "shot_trajectories": "trajectory",
    "player_podium": "podium",
    "lineup_board": "lineup",
    "shot_dna": "waffle",
    "pass_sonar": "sonar",
    "defensive_block": "block",
}

ANGLE_VIZ = {
    "upset": ["stat_slam", "shot_skyline", "touch_skyline", "duel_tower", "player_podium"],
    "robbery": ["conversion_gauges", "xg_race", "shot_trajectories", "player_podium", "keeper_frame"],
    "siege": ["press_trap", "touch_skyline", "defensive_block", "momentum", "pass_lanes"],
    "blowout": ["goal_timeline", "shot_skyline", "player_podium", "lineup_board", "pass_lanes"],
    "comeback": ["momentum", "halftime_split", "bench_impact", "shot_trajectories", "player_podium"],
    "stalemate": ["shot_trajectories", "chance_funnel", "defensive_block", "pass_sonar", "duel_tower"],
    "two_halves": ["halftime_split", "field_tilt_wave", "time_zones", "shot_skyline", "pass_sonar"],
    "keeper": ["keeper_frame", "shot_trajectories", "player_podium", "conversion_gauges", "xg_race"],
}

# These are the scenes where the viewer reads a physical picture first:
# height, territory, path, formation or shape carries the claim.  They are
# intentionally not just an alternate chart skin.  A short-form deck should
# make room for them whenever the audited event feed supports it.
VISUAL_FIRST_IDS = frozenset({
    "touch_skyline",
    "shot_skyline",
    "shot_trajectories",
    "player_podium",
    "lineup_board",
    "shot_dna",
    "pass_sonar",
    "defensive_block",
})


def pack_shape_families(ids: list[str]) -> list[str]:
    return [SHAPE_FAMILY.get(vid, "other") for vid in ids]


def unique_shape_pack(ids: list[str]) -> bool:
    families = pack_shape_families(ids)
    return len(families) == len(set(families))


def colliding_shape_ids(ids: list[str]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for vid in ids:
        shape = SHAPE_FAMILY.get(vid, "other")
        if shape in seen:
            collisions.append((seen[shape], vid))
        else:
            seen[shape] = vid
    return collisions


def pick_angle(bundle: MatchBundle, audit: dict[str, Any]) -> str:
    hook = hooks.build_hook(bundle, audit)
    kind = hook["kind"]
    mapping = {
        "volume_upset": "upset",
        "sterile_upset": "upset",
        "waste": "upset",
        "xg_robbery": "robbery",
        "keeper_wall": "keeper",
        "blowout": "blowout",
        "comeback": "comeback",
        "stoppage": "comeback",
        "late_turn": "two_halves",
        "press_pin": "siege",
        "chain_shock": "blowout",
        "stalemate": "stalemate",
        "level": "stalemate",
        "red_or_card": "two_halves",
        "own_goal": "upset",
        "penalty": "keeper",
        "one_moment": "upset",
    }
    return mapping.get(kind, "upset")


def visualization_candidates(bundle: MatchBundle, audit: dict[str, Any]) -> list[dict[str, Any]]:
    stats = audit["team_stats"]
    home = stats.get(bundle.home, {})
    away = stats.get(bundle.away, {})
    health = audit["data_health"]
    timeline = audit["goal_timeline"]
    chains = credible_goal_chains(audit)
    momentum = audit["momentum"]
    tilt = audit["field_tilt"]
    score = bundle.score

    total_shots = home.get("shots", 0) + away.get("shots", 0)
    shot_gap = abs(home.get("shots", 0) - away.get("shots", 0))
    on_target_gap = abs(home.get("shots_on_target", 0) - away.get("shots_on_target", 0))
    control_key = "possession_pct" if health.get("has_vendor_possession") else "pass_share_pct"
    pass_gap = abs(home.get(control_key, 50) - away.get(control_key, 50))
    max_saves = max(home.get("saves", 0), away.get("saves", 0))
    max_swing = max((abs(row["swing"]) for row in momentum), default=0.0)
    max_tilt = max((max(row["home_tilt_pct"], row["away_tilt_pct"]) for row in tilt), default=50.0)
    best_chain_passes = max((int(c.get("passes") or 0) for c in chains), default=0)
    on_target_total = home.get("shots_on_target", 0) + away.get("shots_on_target", 0)

    candidates = [
        {
            "id": "goal_timeline",
            "title": "Goal Timeline",
            "available": len(timeline) >= 2,
            "score": 62 + min(14, score.total_goals * 3) + (6 if score.margin <= 1 else 0) - (12 if score.total_goals <= 2 else 0),
            "reason": "Every goal in order with the running scoreline.",
            "best_for": "Matches where the scoreline itself is the story.",
            "avoid_when": "One-goal games, where a single tactical pattern says more.",
        },
        {
            "id": "shot_map",
            "title": "Shot Map",
            "available": total_shots >= 6 and bool(health.get("has_precise_coordinates")),
            "score": 70 + min(16, total_shots * 0.6) + min(10, shot_gap + on_target_gap),
            "reason": "Where both teams shot from and what happened to each attempt.",
            "best_for": "Volume mismatches, wasteful finishing, or a goal glut.",
            "avoid_when": "Too few shots to fill the pitch.",
        },
        {
            "id": "momentum",
            "title": "Momentum Swing",
            "available": len(momentum) >= 6
            and int(health.get("pass_rows") or 0) >= 40,
            "score": 68 + min(20, max_swing * 0.4),
            "reason": "Attacking pressure per five minutes, so the turning point is visible.",
            "best_for": "Comebacks, late sieges, and games that changed character.",
            "avoid_when": "The curve is flat and no swing actually happened.",
        },
        {
            "id": "zone_control",
            "title": "Territory Map",
            "available": len(audit["zone_control"]) >= 12,
            "score": 58 + min(18, max(0.0, max_tilt - 50) * 0.4),
            "reason": "Touch volume across eighteen zones shows who owned which areas.",
            "best_for": "Territorial stories where one side was pinned back.",
            "avoid_when": "Territory was even and the scoreline was not.",
        },
        {
            "id": "goal_chain",
            "title": "Goal Build-up",
            "available": bool(chains),
            "score": max(0, 52 + min(24, best_chain_passes * 2) - (16 if score.total_goals >= 4 else 0)),
            "reason": "One verified possession traced pass by pass to the finish.",
            "best_for": "A single constructed goal worth slowing down for.",
            "avoid_when": "High-scoring games, where one chain cannot carry the story.",
        },
        {
            "id": "goalmouth",
            "title": "Goalmouth Placement",
            "available": health["has_goal_mouth_coordinates"] and on_target_total >= 4,
            "score": 50 + min(20, max_saves * 2.5) + min(10, on_target_total),
            "reason": "Where every on-target shot crossed the goal line, and who stopped it.",
            "best_for": "Goalkeeping performances and finishing quality.",
            "avoid_when": "Few shots reached the frame.",
        },
        {
            "id": "pass_network",
            "title": "Pass Network",
            "available": max(home.get("pass_attempts", 0), away.get("pass_attempts", 0)) >= 150,
            "score": 44 + pass_gap,
            "reason": "Average positions and the strongest passing links.",
            "best_for": "Build-up identity and control stories.",
            "avoid_when": "Goals and shots explain the result more directly.",
        },
        {
            "id": "sterile_domination",
            "title": "Control vs Threat",
            "available": max(home.get(control_key, 0), away.get(control_key, 0)) >= 56
            and total_shots >= 4,
            "score": 48 + pass_gap,
            "reason": "Tests whether the team with the ball turned it into shots.",
            "best_for": "One-sided pass share that did not become chances.",
            "avoid_when": "The pass-share edge is small.",
        },
        {
            "id": "stat_slam",
            "title": "The Number",
            "available": shot_gap >= 3 or pass_gap >= 8 or on_target_gap >= 2,
            "score": 78 + min(12, shot_gap + on_target_gap),
            "reason": "One hero number that is the match.",
            "best_for": "Volume mismatches and upsets.",
            "avoid_when": "Every count is even.",
        },
        {
            "id": "match_radar",
            "title": "Match Radar",
            "available": total_shots >= 4 and (
                len(audit.get("source_supported_stats") or []) >= 4
                or int(health.get("event_rows") or 0) >= 50
            ),
            "score": 66 + min(10, pass_gap * 0.2),
            "reason": "Six axes, two overlays — the shape of the night.",
            "best_for": "A one-look profile of both teams.",
            "avoid_when": "Too few comparable stats.",
        },
        {
            "id": "touch_heatmap",
            "title": "Touch Territory",
            "available": bool((audit.get("touch_heatmap") or {}).get("home"))
            and bool(health.get("has_precise_coordinates")),
            "score": 64 + min(16, max(0.0, max_tilt - 50) * 0.35),
            "reason": "Crisp dominance cells from every real touch; no blur or invented interpolation.",
            "best_for": "Pins, sieges, territorial stories.",
            "avoid_when": "Even territory.",
        },
        {
            "id": "field_tilt_wave",
            "title": "Field Tilt",
            "available": len(tilt) >= 4 and max_tilt >= 58,
            "score": 72 + min(18, max(0.0, max_tilt - 50) * 0.5),
            "reason": "Final-third pass share as a full-bleed wave.",
            "best_for": "Tale of two halves, a side pinned in.",
            "avoid_when": "Tilt is flat.",
        },
        {
            "id": "conversion_gauges",
            "title": "Chances vs Goals",
            "available": total_shots >= 6,
            "score": 70 + min(12, abs(int(home.get("big_chances") or 0) - int(away.get("big_chances") or 0))),
            "reason": "Rings of chance quality against what actually went in.",
            "best_for": "Wasteful finishing or a clinical smash-and-grab.",
            "avoid_when": "Conversion matches the chances.",
        },
        {
            "id": "chance_funnel",
            "title": "Chance Funnel",
            "available": max(home.get(control_key, 0), away.get(control_key, 0)) >= 54
            and total_shots >= 6,
            "score": 60 + pass_gap,
            "reason": "Control to third to box to shot to goal, narrowing as it dies.",
            "best_for": "Sterile domination.",
            "avoid_when": "The funnel does not drop.",
        },
        {
            "id": "keeper_frame",
            "title": "The Frame",
            "available": bool(health.get("has_goal_mouth_coordinates")) and on_target_total >= 4,
            "score": 58 + min(18, max_saves * 2.2),
            "reason": "Every on-target shot on a real goal mouth.",
            "best_for": "Brick-wall keepers.",
            "avoid_when": "Few shots reached the frame.",
        },
        {
            "id": "xg_race",
            "title": "xG Race",
            "available": bool(health.get("has_vendor_xg")) and any(s.get("xg") for s in (audit.get("shots") or [])),
            "score": 80 if health.get("has_vendor_xg") else 0,
            "reason": "Cumulative xG against the goals that counted.",
            "best_for": "A robbery relative to chance quality.",
            "avoid_when": "No vendor xG.",
        },
        {
            "id": "time_zones",
            "title": "Three Slices",
            "available": len(audit.get("time_zones") or []) >= 3
            and any(slice_.get("home_touches") or slice_.get("away_touches") for slice_ in audit.get("time_zones") or []),
            "score": 57 + min(12, max(0.0, max_tilt - 50) * 0.25),
            "reason": "Territory in 0-30 / 30-60 / 60-90.",
            "best_for": "Games that changed character.",
            "avoid_when": "One territorial story all night.",
        },
        {
            "id": "player_spike",
            "title": "The Spike",
            "available": bool((audit.get("player_leaders") or {}).get("spike")),
            "score": 55 + min(14, int(((audit.get("player_leaders") or {}).get("spike") or {}).get("count") or 0)),
            "reason": "One surname and the actions that made them the spike.",
            "best_for": "A human face on the numbers.",
            "avoid_when": "No player clearly led an action.",
        },
        {
            "id": "shot_clock_spiral",
            "title": "Shot Clock",
            "available": total_shots >= 4 and len(audit.get("shots") or []) >= 4,
            "score": 74 + min(12, shot_gap + on_target_gap),
            "reason": "Every shot on a match clock, numbered in order.",
            "best_for": "Volume stories and games with a shooting gallery.",
            "avoid_when": "Too few shots to fill the spiral.",
        },
        {
            "id": "press_trap",
            "title": "The Trap",
            "available": bool((audit.get("press_trap") or {}).get("audited")),
            "score": 76 if (audit.get("press_trap") or {}).get("audited") else 0,
            "reason": "Audited PPDA as closing jaws. Never a guessed 50.0.",
            "best_for": "A side that really pressed.",
            "avoid_when": "Fewer than five press actions high up the pitch.",
        },
        {
            "id": "pass_lanes",
            "title": "Pass Lanes",
            "available": (
                max(home.get("pass_attempts", 0), away.get("pass_attempts", 0)) >= 80
                and int(health.get("pass_rows") or 0) >= 80
            ),
            "score": 58 + pass_gap * 0.4,
            "reason": "Only the thickest passing lanes, revealed in sequence.",
            "best_for": "Build-up identity without a full hairball network.",
            "avoid_when": "Pass volume is too thin for strong edges.",
        },
        {
            "id": "bench_impact",
            "title": "The Bench",
            "available": len((audit.get("bench_impact") or {}).get("subs") or []) >= 2,
            "score": 54 + min(12, len((audit.get("bench_impact") or {}).get("subs") or [])),
            "reason": "Who came on, and the shots that followed.",
            "best_for": "Games that turned after the changes.",
            "avoid_when": "No substitutions on the tape.",
        },
        {
            "id": "duel_tower",
            "title": "Duel Tower",
            "available": int((audit.get("duels") or {}).get("total") or 0) >= 8,
            "score": 61 + min(14, abs(
                int(((audit.get("duels") or {}).get("home") or {}).get("total") or 0)
                - int(((audit.get("duels") or {}).get("away") or {}).get("total") or 0)
            )),
            "reason": "Tackles, aerials and take-ons stacked as towers.",
            "best_for": "Physical mismatches.",
            "avoid_when": "Duels were even and scarce.",
        },
        {
            "id": "aerial_war",
            "title": "Aerial War",
            "available": int((audit.get("aerials") or {}).get("total") or 0) >= 6,
            "score": 59 + min(16, abs(
                int((audit.get("aerials") or {}).get("home_won") or 0)
                - int((audit.get("aerials") or {}).get("away_won") or 0)
            )),
            "reason": "Headers won as rising chevrons.",
            "best_for": "A side that owned the air.",
            "avoid_when": "Too few aerials.",
        },
        {
            "id": "halftime_split",
            "title": "Two Halves",
            "available": bool((audit.get("halftime_split") or {}).get("ready"))
            and int(health.get("event_rows") or 0) >= 50,
            "score": 63 + min(12, abs(
                int(((audit.get("halftime_split") or {}).get("first") or {}).get("home_shots") or 0)
                + int(((audit.get("halftime_split") or {}).get("first") or {}).get("away_shots") or 0)
                - int(((audit.get("halftime_split") or {}).get("second") or {}).get("home_shots") or 0)
                - int(((audit.get("halftime_split") or {}).get("second") or {}).get("away_shots") or 0)
            )),
            "reason": "First half against the second, stamped.",
            "best_for": "Games that changed character at the break.",
            "avoid_when": "Both halves look the same.",
        },
    ]
    candidates.extend(_picture_candidates(bundle, audit, total_shots=total_shots, shot_gap=shot_gap,
                                          on_target_total=on_target_total, max_tilt=max_tilt))
    for candidate in candidates:
        candidate["shape"] = SHAPE_FAMILY.get(candidate["id"], "other")
        candidate["score"] = round(float(candidate["score"]), 1)
    return candidates


def _trajectory_shots(audit: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        shot for shot in audit.get("shots") or []
        if shot.get("outcome") != "blocked"
        and shot.get("goal_mouth_y") is not None and shot.get("goal_mouth_z") is not None
    ]


def _picture_candidates(bundle: MatchBundle, audit: dict[str, Any], *, total_shots: int, shot_gap: int,
                        on_target_total: int, max_tilt: float) -> list[dict[str, Any]]:
    """3D scenes and infographics. Each one is only offered when its audit block is complete."""
    health = audit.get("data_health") or {}
    precise = bool(health.get("has_precise_coordinates"))
    ratings = audit.get("player_ratings") or {}
    top = ratings.get("top") or []
    sonar = audit.get("pass_sonar") or {}
    shape = audit.get("defensive_shape") or {}
    forward_gap = abs(float((sonar.get("home") or {}).get("forward_pct") or 0)
                      - float((sonar.get("away") or {}).get("forward_pct") or 0))
    line_gap = abs(float((shape.get("home") or {}).get("line_height_m") or 0)
                   - float((shape.get("away") or {}).get("line_height_m") or 0))
    best_rating = float(top[0]["rating"]) if top else 0.0
    return [
        {
            "id": "touch_skyline",
            "title": "Territory Skyline (3D)",
            "available": bool((audit.get("touch_heatmap") or {}).get("home")) and precise,
            "score": 67 + min(14, max(0.0, max_tilt - 50) * 0.4),
            "reason": "Every touch bin as a 3D column: height is volume, colour is who owned it.",
            "best_for": "Territorial stories where one side lived in the other's half.",
            "avoid_when": "Coordinates are reconstructed rather than real.",
        },
        {
            "id": "shot_skyline",
            "title": "Shot Skyline (3D)",
            "available": total_shots >= 8 and precise,
            "score": 73 + min(10, shot_gap),
            "reason": "Every shot as a tower where it was struck; taller means it tested the keeper.",
            "best_for": "Shooting galleries and volume mismatches.",
            "avoid_when": "Too few shots to build a skyline.",
        },
        {
            "id": "shot_trajectories",
            "title": "Into the Frame (3D)",
            "available": bool(health.get("has_goal_mouth_coordinates")) and len(_trajectory_shots(audit)) >= 6,
            "score": 71 + min(12, on_target_total),
            "reason": "Every shot from boot to where it crossed the goal line, folded onto one goal.",
            "best_for": "Finishing stories: wasteful, clinical or a keeper under fire.",
            "avoid_when": "Few shots reached the goal line.",
        },
        {
            "id": "player_podium",
            "title": "Top Rated Podium (3D)",
            "available": bool(ratings.get("available")) and len(top) >= 3,
            "score": 64 + min(14, max(0.0, best_rating - 7.0) * 8),
            "reason": "The three best WhoScored ratings on a podium, with each rating curve.",
            "best_for": "A standout individual night.",
            "avoid_when": "The export has no player ratings.",
        },
        {
            "id": "lineup_board",
            "title": "Lineup Board",
            "available": bool((audit.get("lineups") or {}).get("available")),
            "score": 59 + min(10, max(0.0, best_rating - 7.0) * 5),
            "reason": "Both starting shapes on one pitch, every shirt ringed by its rating.",
            "best_for": "Shape-versus-shape stories and who carried each XI.",
            "avoid_when": "No formation slots in the export.",
        },
        {
            "id": "shot_dna",
            "title": "Shot DNA",
            "available": bool((audit.get("shot_profile") or {}).get("available")) and total_shots >= 8,
            "score": 61 + min(10, total_shots / 3),
            "reason": "One tile per shot by outcome, then how each side's shots arrived and what struck them.",
            "best_for": "Set-piece reliance, counter-attacking threat, wasteful volume.",
            "avoid_when": "Too few shots for a unit chart.",
        },
        {
            "id": "pass_sonar",
            "title": "Pass Sonar",
            "available": bool(sonar.get("available")),
            "score": 58 + min(14, forward_gap * 0.8),
            "reason": "Which way each side passed, how often, and how often it arrived.",
            "best_for": "Direct versus patient styles.",
            "avoid_when": "Both sides passed the same way.",
        },
        {
            "id": "defensive_block",
            "title": "Defensive Block",
            "available": bool(shape.get("available")) and precise,
            "score": 60 + min(14, line_gap * 0.8),
            "reason": "Where each side won the ball back, the shape of its block, and its line height.",
            "best_for": "High press against low block.",
            "avoid_when": "Too few defensive actions.",
        },
    ]


def _diverse_pick(available: dict[str, dict[str, Any]], count: int, preferred: list[str]) -> list[str]:
    """Greedy: preferred order, then score. Never collide on shape if a substitute exists."""
    picked: list[str] = []
    used_shapes: set[str] = set()

    def try_add(vid: str, *, allow_collision: bool = False) -> bool:
        if vid not in available or vid in picked:
            return False
        shape = SHAPE_FAMILY.get(vid, "other")
        if shape in used_shapes and not allow_collision:
            return False
        picked.append(vid)
        used_shapes.add(shape)
        return True

    for vid in preferred:
        if len(picked) >= count:
            return picked
        try_add(vid)

    ranked = sorted(available.values(), key=lambda c: c["score"], reverse=True)
    for candidate in ranked:
        if len(picked) >= count:
            break
        try_add(candidate["id"])
    # Last resort: collide on shape only when the pack cannot be filled otherwise.
    for candidate in ranked:
        if len(picked) >= count:
            break
        try_add(candidate["id"], allow_collision=True)
    return picked[:count]


def select_visualizations(
    bundle: MatchBundle,
    audit: dict[str, Any],
    count: int,
    gemini: "Gemini | None" = None,
    instruction: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (selected, all_candidates). Angle first, then shape-diverse pack."""
    candidates = visualization_candidates(bundle, audit)
    available = {c["id"]: c for c in candidates if c["available"]}
    angle = pick_angle(bundle, audit)
    preferred = [vid for vid in ANGLE_VIZ.get(angle, []) if vid in available]

    chosen_ids: list[str] = []
    if gemini is not None and gemini.enabled:
        chosen_ids = gemini.choose_visualizations(
            bundle, audit, candidates, count, instruction, angle=angle
        )
        chosen_ids = [vid for vid in chosen_ids if vid in available]

    # Reserve the visual centre of the deck before adding a model's chart
    # choices.  Without this, a plausible Gemini selection can fill all four
    # slots with conventional metrics even when the feed supports a 3D pitch,
    # trajectory or lineup scene.  One slot is protected in a two-card deck;
    # two are protected once there is room for a real story arc.
    visual_target = 2 if count >= 3 else 1
    visual_available = {vid: item for vid, item in available.items() if vid in VISUAL_FIRST_IDS}
    visual_ranked = [
        item["id"] for item in sorted(visual_available.values(), key=lambda item: item["score"], reverse=True)
    ]
    visual_seeds = _diverse_pick(
        visual_available,
        min(visual_target, len(visual_available)),
        [vid for vid in chosen_ids + preferred if vid in visual_available] + visual_ranked,
    )
    chosen_ids = _diverse_pick(available, count, visual_seeds + chosen_ids + preferred)

    seen: set[str] = set()
    selected = []
    for vid in chosen_ids:
        if vid in available and vid not in seen:
            seen.add(vid)
            item = dict(available[vid])
            item["angle"] = angle
            selected.append(item)
    return selected[:count], candidates


# ---------------------------------------------------------------------------
# deterministic script
# ---------------------------------------------------------------------------

def _ordinal(minute: int) -> str:
    if 10 <= minute % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(minute % 10, "th")
    return f"{minute}{suffix}"


_SCORELINE = re.compile(r"\b\d+\s*[-–:/]\s*\d+\b")
_ARTICLES = {"fc", "cf", "afc", "the", "de", "cd", "sc", "ac"}
BRIDGE_SECONDS = hooks.BRIDGE_SECONDS
_PACKAGE = set(SHAPE_FAMILY) | {"close", "standard_stats"}

hook_team_name = hooks.hook_team_name
build_hook = hooks.build_hook
build_bridge = hooks.build_bridge



def _hook_stat(bundle: MatchBundle, audit: dict[str, Any]) -> str:
    """One number worth putting on frame one."""
    context = result_context(bundle, audit)
    stats = context["winner_stats"] or audit["team_stats"].get(bundle.home, {})
    on_target = int(stats.get("shots_on_target") or 0)
    big = int(stats.get("big_chances") or 0)
    shots = int(stats.get("shots") or 0)
    if context["margin"] >= 3:
        return i18n.t("hook_stat_margin", n=context["margin"])
    if big >= 3:
        return i18n.t("hook_stat_big_chances", n=big)
    if on_target >= 4:
        return i18n.t("hook_stat_on_target", n=on_target)
    if shots:
        return i18n.t("hook_stat_shots", n=shots)
    return ""


def _headline_copy(bundle: MatchBundle, audit: dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, insight, hook_stat) for the opening card.

    The kicker on this card is the score itself. The title has to land as a
    claim in the first second, not a polite competition label.
    """
    context = result_context(bundle, audit)
    score = bundle.score
    winner = context["winner"]
    stats = audit["team_stats"]
    hook = _hook_stat(bundle, audit)
    timeline = audit.get("goal_timeline") or []
    first = timeline[0] if timeline else None
    first_minute = int(first["minute"]) if first and first.get("minute") is not None else None

    if winner:
        winner_stats = context["winner_stats"]
        if score.after_shootout:
            return i18n.t("hook_shootout", team=winner.upper()), "Level after 120 minutes, settled from the spot.", hook
        if score.after_extra_time:
            return i18n.t("hook_extra_time", team=winner.upper()), "Ninety minutes could not separate them.", hook
        if first_minute is not None and first_minute <= 12 and first.get("team") == winner:
            return (
                i18n.t("hook_needed_minutes", team=winner.upper(), n=first_minute),
                f"{winner} scored in the {_ordinal(first_minute)} minute and never looked back.",
                hook,
            )
        if score.margin >= 3:
            return (
                i18n.t("hook_ran_riot", team=winner.upper()),
                f"{score.margin} goals of daylight by the final whistle.",
                hook,
            )
        if score.total_goals >= 4:
            return (
                i18n.t("hook_goals_take_it", n=score.total_goals, team=winner.upper()),
                "A shootout of a match, decided in open play.",
                hook,
            )
        return (
            i18n.t("hook_found_a_way", team=winner.upper()),
            f"{winner_stats.get('shots_on_target', 0)} shots on target turned into the win.",
            hook,
        )

    if score.total_goals == 0:
        total_shots = sum(team.get("shots", 0) for team in stats.values())
        return i18n.t("hook_nobody_blinked"), f"{total_shots} attempts and not one of them counted.", hook
    return i18n.t("hook_honours_even", score=score.display), "Two teams, two answers, one point each.", hook


def _stats_copy(bundle: MatchBundle, audit: dict[str, Any]) -> tuple[str, str]:
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    edges = [
        home.get(key, 0) > away.get(key, 0)
        for key in ("pass_share_pct", "shots", "shots_on_target", "final_third_passes", "penalty_box_touches")
    ]
    home_edges = sum(edges)
    if home_edges >= 4:
        return f"{bundle.home.upper()} LED ALMOST EVERYTHING", f"{bundle.home} won four of the five baseline counts."
    if home_edges <= 1:
        return f"{bundle.away.upper()} LED ALMOST EVERYTHING", f"{bundle.away} won four of the five baseline counts."
    return "THE NUMBERS SPLIT DOWN THE MIDDLE", "Neither side could claim the baseline counts."


def _visual_copy(bundle: MatchBundle, audit: dict[str, Any], viz_id: str) -> dict[str, str]:
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    timeline = audit["goal_timeline"]

    if viz_id == "goal_timeline":
        first = timeline[0] if timeline else None
        last = timeline[-1] if timeline else None

        def surname(goal: dict[str, Any]) -> str:
            name = str(goal.get("scorer") or "")
            return name.split()[-1] if name else str(goal.get("team") or "")

        if first and last and len(timeline) > 1:
            narration = (
                f"{surname(first)} opened it in the {_ordinal(first['minute'])} minute, "
                f"and {surname(last)} had the last word."
            )
        elif first:
            narration = (
                f"One goal settled it: {surname(first)} in the {_ordinal(first['minute'])} minute."
            )
        else:
            narration = "Not one goal all match."
        return {
            "kicker": i18n.t("kicker_every_goal"),
            "title": (
                i18n.t("title_goals_running", n=len(timeline))
                if timeline else i18n.t("title_goal_timeline")
            ),
            "subtitle": "",
            "insight": (
                i18n.t("insight_last_word", team=last["team"], n=last["minute"])
                if last else i18n.t("insight_every_finish")
            ),
            "narration": narration,
        }

    if viz_id == "shot_map":
        leader = dominant_team(bundle, audit, "shots_on_target") or bundle.home
        return {
            "kicker": i18n.t("kicker_shot_map"),
            "title": i18n.t("title_on_the_map", home=home["shots"], away=away["shots"]),
            "subtitle": i18n.t("sub_shot_map"),
            "insight": i18n.t(
                "insight_shots_split",
                home=home["shots"], away=away["shots"],
                home_on=home["shots_on_target"], away_on=away["shots_on_target"],
            ),
            "narration": (
                f"{bundle.home} {home['shots']} shots to {away['shots']}, "
                f"{home['shots_on_target']} on target against {away['shots_on_target']}."
            ),
        }

    if viz_id == "momentum":
        momentum = audit["momentum"]
        peak = max(momentum, key=lambda row: abs(row["swing"])) if momentum else None
        leader = bundle.home if peak and peak["swing"] > 0 else bundle.away
        return {
            "kicker": i18n.t("kicker_pressure"),
            "title": _momentum_title(audit),
            "subtitle": i18n.t("sub_momentum", home=bundle.home, away=bundle.away),
            "insight": (
                i18n.t("insight_heavy_spell", team=leader, block=peak["minute_block"])
                if peak else i18n.t("insight_pressure_level")
            ),
            "narration": (
                f"The heaviest spell belonged to {leader} in the {peak['minute_block']} window."
                if peak else "Pressure stayed level throughout."
            ),
        }

    if viz_id == "zone_control":
        zones = audit["zone_control"]
        home_touches = sum(z["home_touches"] for z in zones)
        away_touches = sum(z["away_touches"] for z in zones)
        leader = bundle.home if home_touches >= away_touches else bundle.away
        return {
            "kicker": i18n.t("kicker_territory"),
            "title": _zone_title(bundle, audit),
            "subtitle": i18n.t("sub_zone"),
            "insight": i18n.t("insight_owned_grid", team=leader),
            "narration": (
                f"{leader} owned the map, {home_touches} touches against {away_touches}."
            ),
        }

    if viz_id == "goal_chain":
        chain = best_goal_chain(audit)
        if chain:
            return {
                "kicker": i18n.t("kicker_one_goal"),
                "title": i18n.t("title_passes_finish", n=chain["passes"]),
                "subtitle": f"{chain['team']} / {chain['scorer']}",
                "insight": i18n.t(
                    "insight_chain_metres",
                    metres=f"{chain['pass_distance_m']:.0f}",
                    seconds=f"{chain['duration_seconds']:.0f}",
                ),
                "narration": (
                    f"{chain['team']} strung {chain['passes']} passes across "
                    f"{chain['pass_distance_m']:.0f} metres before {chain['scorer']} finished it."
                ),
            }
        return {
            "kicker": i18n.t("kicker_buildup"),
            "title": i18n.t("title_move_before"),
            "subtitle": "",
            "insight": "",
            "narration": "The build-up to the goal, taken straight from the event coordinates.",
        }

    if viz_id == "goalmouth":
        # The busier keeper is the one whose opponent got more shots on target,
        # not simply the one with more saves; save counts are often level.
        if away["shots_on_target"] >= home["shots_on_target"]:
            keeper_side, faced = bundle.home, away["shots_on_target"]
        else:
            keeper_side, faced = bundle.away, home["shots_on_target"]
        keeper_stats = stats[keeper_side]
        return {
            "kicker": i18n.t("kicker_frame"),
            "title": i18n.t("title_had_work", team=keeper_side.upper()),
            "subtitle": i18n.t("sub_goalmouth"),
            "insight": i18n.t("insight_saves_stopped", faced=faced, saves=keeper_stats["saves"]),
            "narration": (
                f"{keeper_side} faced {faced} shots on target and saved {keeper_stats['saves']} of them."
            ),
        }

    if viz_id == "pass_network":
        leader = dominant_team(bundle, audit, "pass_attempts") or bundle.home
        leader_stats = stats[leader]
        return {
            "kicker": i18n.t("kicker_pass_network"),
            "title": i18n.t("title_how_moved", team=leader.upper()),
            "subtitle": i18n.t("sub_pass_network"),
            "insight": i18n.t(
                "insight_pass_acc",
                n=leader_stats["passes_completed"],
                pct=f"{leader_stats['pass_accuracy_pct']:.0f}",
            ),
            "narration": (
                f"{leader} completed {leader_stats['passes_completed']} passes at "
                f"{leader_stats['pass_accuracy_pct']:.0f} percent accuracy."
            ),
        }

    if viz_id == "sterile_domination":
        control_key = "possession_pct" if (audit.get("data_health") or {}).get("has_vendor_possession") else "pass_share_pct"
        leader = dominant_team(bundle, audit, control_key) or bundle.home
        leader_stats = stats[leader]
        threat_key = "shots_on_target" if "shots_on_target" in (audit.get("source_supported_stats") or []) or not audit.get("source_supported_stats") else "shots"
        return {
            "kicker": i18n.t("kicker_control"),
            "title": i18n.t("title_had_the_ball", team=leader.upper()),
            "subtitle": i18n.t("sub_sterile"),
            "insight": i18n.t(
                "insight_control_threat",
                pct=f"{leader_stats.get(control_key, 0):.0f}",
                control=stat_label(control_key).lower(),
                n=leader_stats.get(threat_key, 0),
                threat=stat_label(threat_key).lower(),
            ),
            "narration": (
                f"{leader} held {leader_stats.get(control_key, 0):.0f} percent {stat_label(control_key).lower()} "
                f"but produced only {leader_stats.get(threat_key, 0)} {stat_label(threat_key).lower()}."
            ),
        }

    if viz_id == "stat_slam":
        key = pick_stat_rows(bundle, audit, limit=1)[0]
        leader = dominant_team(bundle, audit, key) or bundle.home
        other = bundle.away if leader == bundle.home else bundle.home
        hero_value = format_stat(key, stats[leader].get(key))
        return {
            "kicker": stat_label(key).upper(),
            "title": i18n.t("title_n_stat", n=hero_value, stat=stat_label(key).upper()),
            "subtitle": i18n.t("sub_slam"),
            "insight": i18n.t(
                "insight_slam",
                team=leader,
                stat=stat_label(key),
                a=format_stat(key, stats[leader].get(key)),
                b=format_stat(key, stats[other].get(key)),
            ),
            "narration": (
                f"{leader} posted {format_stat(key, stats[leader].get(key))} {stat_label(key)} "
                f"against {format_stat(key, stats[other].get(key))}; that was the clearest "
                "statistical gap in the underlying performance."
            ),
            "stat_keys": [key],
            "hero_number": hero_value,
            "hero_label": stat_label(key).upper(),
            "hero_team": leader,
        }

    if viz_id == "match_radar":
        control_key = "possession_pct" if (audit.get("data_health") or {}).get("has_vendor_possession") else "pass_share_pct"
        return {
            "kicker": i18n.t("kicker_profile"),
            "title": i18n.t("title_shape"),
            "subtitle": i18n.t("sub_radar"),
            "insight": i18n.t(
                "insight_radar",
                hs=home["shots"], ashots=away["shots"],
                hc=f"{home.get(control_key, 0):.0f}",
                ac=f"{away.get(control_key, 0):.0f}",
                control=stat_label(control_key).lower(),
            ),
            "narration": (
                f"{bundle.home} led {home['shots']}-{away['shots']} in shots and "
                f"{home.get(control_key, 0):.0f}-{away.get(control_key, 0):.0f} in "
                f"{stat_label(control_key).lower()}; {bundle.away} led {away.get('goals', 0)}-"
                f"{home.get('goals', 0)} in goals."
            ),
        }

    if viz_id == "touch_heatmap":
        zones = audit.get("zone_control") or []
        home_t = sum(int(z.get("home_touches") or 0) for z in zones)
        away_t = sum(int(z.get("away_touches") or 0) for z in zones)
        leader = bundle.home if home_t >= away_t else bundle.away
        return {
            "kicker": i18n.t("kicker_touch"),
            "title": i18n.t("title_n_touches", n=max(home_t, away_t)),
            "subtitle": i18n.t("sub_heatmap"),
            "insight": i18n.t("insight_touches", home=home_t, away=away_t),
            "narration": (
                f"{leader} drove the territory map: {home_t} touches against {away_t}, "
                "with each hex tied to recorded events."
            ),
        }

    if viz_id == "field_tilt_wave":
        tilt = audit.get("field_tilt") or []
        peak = max(tilt, key=lambda row: max(row["home_tilt_pct"], row["away_tilt_pct"])) if tilt else None
        if peak and peak["home_tilt_pct"] >= peak["away_tilt_pct"]:
            leader, pct = bundle.home, peak["home_tilt_pct"]
        elif peak:
            leader, pct = bundle.away, peak["away_tilt_pct"]
        else:
            leader, pct = bundle.home, 50
        return {
            "kicker": i18n.t("kicker_tilt"),
            "title": i18n.t(
                "title_tilt_window",
                n=int(pct),
                window=peak["minute_block"] if peak else i18n.t("match_recap"),
            ),
            "subtitle": i18n.t("sub_tilt"),
            "insight": i18n.t("insight_tilt_owned", team=leader),
            "narration": f"{leader} hit {int(pct)} percent field tilt in the {peak['minute_block'] if peak else 'match'} window.",
        }

    if viz_id == "conversion_gauges":
        source_supported = set(audit.get("source_supported_stats") or [])
        outer_key = (
            "shots_on_target"
            if not source_supported or "shots_on_target" in source_supported
            else "big_chances"
            if "big_chances" in source_supported
            else "shots"
        )
        home_outer = home.get(outer_key, 0)
        away_outer = away.get(outer_key, 0)
        xg_line = (
            f" xG {home.get('xg', 0):.2f} to {away.get('xg', 0):.2f}."
            if (audit.get("data_health") or {}).get("has_vendor_xg")
            else ""
        )
        return {
            "kicker": i18n.t("kicker_conversion"),
            "title": i18n.t("title_n_stat", n=f"{home_outer}-{away_outer}", stat=stat_label(outer_key).upper()),
            "subtitle": i18n.t("sub_gauges"),
            "insight": i18n.t(
                "insight_gauges",
                hs=home.get("shots", 0), ashots=away.get("shots", 0),
                ho=home_outer, ao=away_outer,
                stat=stat_label(outer_key).lower(),
                xg=xg_line,
            ),
            "narration": (
                f"{bundle.home} had {home.get('shots', 0)} shots and {home_outer} "
                f"{stat_label(outer_key).lower()}; {bundle.away} scored "
                f"{away.get('goals', 0)} from {away.get('shots', 0)} attempts."
            ),
        }

    if viz_id == "chance_funnel":
        control_key = "possession_pct" if (audit.get("data_health") or {}).get("has_vendor_possession") else "pass_share_pct"
        leader = dominant_team(bundle, audit, control_key) or bundle.home
        leader_stats = stats[leader]
        return {
            "kicker": i18n.t("kicker_funnel"),
            "title": i18n.t("title_then_drop", n=int(leader_stats.get(control_key, 0))),
            "subtitle": i18n.t("sub_funnel"),
            "insight": i18n.t(
                "insight_funnel",
                pct=f"{leader_stats.get(control_key, 0):.0f}",
                control=stat_label(control_key).lower(),
                shots=leader_stats.get("shots", 0),
                big=leader_stats.get("big_chances", 0),
                goals=leader_stats.get("goals", 0),
            ),
            "narration": (
                f"{leader} held {leader_stats.get(control_key, 0):.0f} percent "
                f"{stat_label(control_key).lower()}, took {leader_stats.get('shots', 0)} shots "
                f"and created {leader_stats.get('big_chances', 0)} big chances, yet scored "
                f"{leader_stats.get('goals', 0)}."
            ),
        }

    if viz_id == "keeper_frame":
        if away["shots_on_target"] >= home["shots_on_target"]:
            keeper_side, faced = bundle.home, away["shots_on_target"]
        else:
            keeper_side, faced = bundle.away, home["shots_on_target"]
        return {
            "kicker": i18n.t("kicker_wall"),
            "title": i18n.t("title_saves_for", n=stats[keeper_side]["saves"], team=keeper_side.upper()),
            "subtitle": i18n.t("sub_keeper_frame"),
            "insight": i18n.t(
                "insight_saves_stopped",
                faced=faced,
                saves=stats[keeper_side]["saves"],
            ),
            "narration": f"{keeper_side} faced {faced} on target and saved {stats[keeper_side]['saves']}.",
        }

    if viz_id == "xg_race":
        return {
            "kicker": i18n.t("kicker_xg_race"),
            "title": i18n.t("title_race_ignored"),
            "subtitle": i18n.t("sub_race"),
            "insight": i18n.t("insight_xg_race", home=home.get("xg", 0), away=away.get("xg", 0)),
            "narration": (
                f"Expected goals ran {home.get('xg', 0)} to {away.get('xg', 0)}. "
                f"The scoreline did not follow the race."
            ),
        }

    if viz_id == "time_zones":
        return {
            "kicker": i18n.t("kicker_three_slices"),
            "title": i18n.t("title_map_changed"),
            "subtitle": i18n.t("sub_zones_time"),
            "insight": i18n.t("insight_three_windows"),
            "narration": "Territory in three slices: the first half hour, the middle, and the close.",
        }

    if viz_id == "player_spike":
        spike = (audit.get("player_leaders") or {}).get("spike") or {}
        surname = spike.get("surname") or spike.get("player") or "A player"
        count = int(spike.get("count") or 0)
        action = spike.get("action") or "actions"
        return {
            "kicker": i18n.t("kicker_spike"),
            "title": i18n.t("title_player_had", name=str(surname).upper(), n=count),
            "subtitle": i18n.t("sub_player"),
            "insight": i18n.t(
                "insight_spike",
                player=spike.get("player") or surname,
                action=i18n.spike_action_label(action),
                n=count,
            ),
            "narration": f"{spike.get('player') or surname} put {count} {action} on the tape, the spike of the night.",
        }

    if viz_id == "shot_clock_spiral":
        total = home.get("shots", 0) + away.get("shots", 0)
        return {
            "kicker": i18n.t("kicker_shot_clock"),
            "title": i18n.t("title_shots_clock", n=total),
            "subtitle": i18n.t("sub_spiral"),
            "insight": i18n.t(
                "insight_shots_order",
                home=home.get("shots", 0),
                away=away.get("shots", 0),
            ),
            "narration": f"{total} shots on the clock. {bundle.home} {home.get('shots', 0)} to {away.get('shots', 0)}.",
        }

    if viz_id == "press_trap":
        trap = audit.get("press_trap") or {}
        leader = trap.get("leader") or bundle.home
        ppda = trap.get("leader_ppda")
        label = f"{ppda:.1f}" if isinstance(ppda, (int, float)) else "—"
        return {
            "kicker": i18n.t("kicker_trap"),
            "title": i18n.t("title_at_ppda", team=str(leader).upper(), n=label),
            "subtitle": i18n.t("sub_trap"),
            "insight": i18n.t("insight_ppda", team=leader, n=label),
            "narration": f"{leader} set the trap at {label} PPDA. That is an audited number.",
        }

    if viz_id == "pass_lanes":
        leader = dominant_team(bundle, audit, "pass_attempts") or bundle.home
        return {
            "kicker": i18n.t("kicker_lanes"),
            "title": i18n.t("title_how_moved_it", team=leader.upper()),
            "subtitle": i18n.t("sub_lanes"),
            "insight": i18n.t("insight_lanes", team=leader),
            "narration": f"{leader} moved it down a few thick lanes. The rest is noise.",
        }

    if viz_id == "bench_impact":
        bench = audit.get("bench_impact") or {}
        n = len(bench.get("subs") or [])
        return {
            "kicker": i18n.t("kicker_bench"),
            "title": i18n.t("title_off_bench", n=n),
            "subtitle": i18n.t("sub_bench"),
            "insight": i18n.t("insight_bench", n=n),
            "narration": f"{n} players came off the bench. The tape shows what happened next.",
        }

    if viz_id == "duel_tower":
        duels = audit.get("duels") or {}
        home_d = int((duels.get("home") or {}).get("total") or 0)
        away_d = int((duels.get("away") or {}).get("total") or 0)
        leader = bundle.home if home_d >= away_d else bundle.away
        return {
            "kicker": i18n.t("kicker_duels"),
            "title": i18n.t("title_duels_for", n=max(home_d, away_d), team=leader.upper()),
            "subtitle": i18n.t("sub_duel"),
            "insight": i18n.t("insight_duels", home=home_d, away=away_d),
            "narration": f"{leader} won the duel tower, {home_d} against {away_d}.",
        }

    if viz_id == "aerial_war":
        aerials = audit.get("aerials") or {}
        home_a = int(aerials.get("home_won") or 0)
        away_a = int(aerials.get("away_won") or 0)
        leader = bundle.home if home_a >= away_a else bundle.away
        return {
            "kicker": i18n.t("kicker_air"),
            "title": i18n.t("title_owned_air", team=leader.upper()),
            "subtitle": i18n.t("sub_aerial"),
            "insight": i18n.t("insight_headers", home=home_a, away=away_a),
            "narration": f"{leader} won the aerial war, {home_a} against {away_a}.",
        }

    if viz_id == "halftime_split":
        split = audit.get("halftime_split") or {}
        first = split.get("first") or {}
        second = split.get("second") or {}
        first_shots = int(first.get("home_shots") or 0) + int(first.get("away_shots") or 0)
        second_shots = int(second.get("home_shots") or 0) + int(second.get("away_shots") or 0)
        return {
            "kicker": i18n.t("kicker_two_halves"),
            "title": i18n.t("title_then", a=first_shots, b=second_shots),
            "subtitle": i18n.t("sub_split"),
            "insight": i18n.t("insight_split", first=first_shots, second=second_shots),
            "narration": f"{first_shots} shots before the break, {second_shots} after. Two different halves.",
        }

    picture = _picture_copy(bundle, audit, viz_id)
    if picture is not None:
        return picture

    if viz_id == "standard_stats":
        return {
            "kicker": i18n.t("the_baseline"),
            "title": i18n.t("title_standard"),
            "subtitle": "",
            "insight": i18n.t("insight_event_feed"),
            "narration": i18n.t("insight_event_feed"),
        }

    return {
        "kicker": i18n.t("kicker_event_data"),
        "title": viz_id.replace("_", " ").upper(),
        "subtitle": "",
        "insight": i18n.t("insight_event_feed"),
        "narration": i18n.t("insight_event_feed"),
    }


def _touch_totals(audit: dict[str, Any]) -> tuple[int, int]:
    heat = audit.get("touch_heatmap") or {}
    return (
        int(sum(sum(row) for row in heat.get("home") or [])),
        int(sum(sum(row) for row in heat.get("away") or [])),
    )


def _trajectory_counts(audit: dict[str, Any]) -> tuple[int, int, int, int]:
    shots = _trajectory_shots(audit)
    goals = sum(1 for shot in shots if shot.get("outcome") == "goal")
    on = sum(1 for shot in shots if shot.get("outcome") in {"goal", "saved"})
    return len(shots), on, len(shots) - on, goals


def _picture_copy(bundle: MatchBundle, audit: dict[str, Any], viz_id: str) -> dict[str, str] | None:
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]

    if viz_id == "touch_skyline":
        home_t, away_t = _touch_totals(audit)
        leader = bundle.home if home_t >= away_t else bundle.away
        return {
            "kicker": i18n.t("kicker_skyline"),
            "title": i18n.t("title_skyline", team=leader.upper()),
            "subtitle": i18n.t("sub_skyline"),
            "insight": i18n.t("insight_skyline", home=home_t, away=away_t),
            "narration": f"{home_t} touches against {away_t}. {leader} built the taller city.",
        }

    if viz_id == "shot_skyline":
        hs, as_ = int(home.get("shots") or 0), int(away.get("shots") or 0)
        leader = bundle.home if hs >= as_ else bundle.away
        return {
            "kicker": i18n.t("kicker_shot_skyline"),
            "title": i18n.t("title_shot_skyline", n=max(hs, as_), team=leader.upper()),
            "subtitle": i18n.t("sub_shot_skyline"),
            "insight": i18n.t("insight_shot_skyline", home=hs, away=as_),
            "narration": f"{hs} shots against {as_}, each one standing where it was struck.",
        }

    if viz_id == "shot_trajectories":
        total, on, off, goals = _trajectory_counts(audit)
        return {
            "kicker": i18n.t("kicker_trajectories"),
            "title": i18n.t("title_trajectories", n=total),
            "subtitle": i18n.t("sub_trajectories"),
            "insight": i18n.t("insight_trajectories", on=on, off=off, goals=goals),
            "narration": f"{total} shots reached the goal line. {on} were on target and {goals} went in.",
        }

    if viz_id == "player_podium":
        top = (audit.get("player_ratings") or {}).get("top") or []
        if len(top) < 3:
            return None
        first, second, third = top[:3]
        return {
            "kicker": i18n.t("kicker_podium"),
            "title": i18n.t("title_podium", name=str(first["surname"]).upper()),
            "subtitle": i18n.t("sub_podium"),
            "insight": i18n.t(
                "insight_podium",
                first=first["surname"], r1=f"{first['rating']:.2f}",
                second=second["surname"], r2=f"{second['rating']:.2f}",
                third=third["surname"], r3=f"{third['rating']:.2f}",
            ),
            "narration": (
                f"{first['player']} topped the ratings at {first['rating']:.2f}, "
                f"ahead of {second['surname']} and {third['surname']}."
            ),
        }

    if viz_id == "lineup_board":
        lineups = audit.get("lineups") or {}
        home_shape = str((lineups.get("home") or {}).get("formation") or "")
        away_shape = str((lineups.get("away") or {}).get("formation") or "")
        best = ((audit.get("player_ratings") or {}).get("top") or [None])[0] or {}
        return {
            "kicker": i18n.t("kicker_lineup"),
            "title": i18n.t("title_lineup", a=home_shape, b=away_shape),
            "subtitle": i18n.t("sub_lineup"),
            "insight": (
                i18n.t("insight_lineup", name=best.get("surname"), rating=f"{best.get('rating', 0):.2f}")
                if best else i18n.t("insight_event_feed")
            ),
            "narration": (
                f"{bundle.home} lined up {home_shape}, {bundle.away} {away_shape}."
                + (f" {best['player']} was the best rated on the pitch." if best else "")
            ),
        }

    if viz_id == "shot_dna":
        profile = audit.get("shot_profile") or {}
        hs, as_ = int((profile.get("home") or {}).get("total") or 0), int((profile.get("away") or {}).get("total") or 0)
        side_key, team = ("home", bundle.home) if hs >= as_ else ("away", bundle.away)
        pct = int(round(float((profile.get(side_key) or {}).get("box_pct") or 0)))
        return {
            "kicker": i18n.t("kicker_shot_dna"),
            "title": i18n.t("title_shot_dna", n=hs + as_),
            "subtitle": i18n.t("sub_shot_dna"),
            "insight": i18n.t("insight_shot_dna", home=hs, away=as_, pct=pct, team=team),
            "narration": f"{hs + as_} shots, taken apart. {pct} percent of {team}'s came from inside the box.",
        }

    if viz_id == "pass_sonar":
        sonar = audit.get("pass_sonar") or {}
        hf = float((sonar.get("home") or {}).get("forward_pct") or 0)
        af = float((sonar.get("away") or {}).get("forward_pct") or 0)
        team, other, pct, pct2 = (
            (bundle.home, bundle.away, hf, af) if hf >= af else (bundle.away, bundle.home, af, hf)
        )
        title = (
            i18n.t("title_sonar_forward", team=team.upper()) if abs(hf - af) >= 3
            else i18n.t("title_sonar_even")
        )
        return {
            "kicker": i18n.t("kicker_sonar"),
            "title": title,
            "subtitle": i18n.t("sub_sonar"),
            "insight": i18n.t("insight_sonar", team=team, pct=f"{pct:.0f}", other=other, pct2=f"{pct2:.0f}"),
            "narration": f"{team} sent {pct:.0f} percent of their passes forward. {other} managed {pct2:.0f}.",
        }

    if viz_id == "defensive_block":
        shape = audit.get("defensive_shape") or {}
        hm = float((shape.get("home") or {}).get("line_height_m") or 0)
        am = float((shape.get("away") or {}).get("line_height_m") or 0)
        team = bundle.home if hm >= am else bundle.away
        title = (
            i18n.t("title_block_high", team=team.upper()) if abs(hm - am) >= 3
            else i18n.t("title_block_even")
        )
        return {
            "kicker": i18n.t("kicker_block"),
            "title": title,
            "subtitle": i18n.t("sub_block"),
            "insight": i18n.t("insight_block", home=bundle.home, hm=f"{hm:.0f}", away=bundle.away, am=f"{am:.0f}"),
            "narration": (
                f"{team} won the ball back higher. Their average line sat {max(hm, am):.0f} metres "
                f"from their own goal, against {min(hm, am):.0f}."
            ),
        }
    return None


def _block_minute(row: dict[str, Any]) -> int:
    """Leading real minute of a bucket label such as ``"66-70"``."""
    digits = re.findall(r"\d+", str(row.get("minute_block", "")))
    return int(digits[0]) if digits else 0


def _momentum_title(audit: dict[str, Any]) -> str:
    momentum = audit.get("momentum") or []
    if not momentum:
        return i18n.t("title_pressure_match")
    peak = max(momentum, key=lambda row: abs(row["swing"]))
    period = str(peak.get("period", ""))
    if period.endswith("PeriodOfExtraTime"):
        return i18n.t("title_et_deadlock")
    minute = _block_minute(peak)
    if minute <= 20:
        return i18n.t("title_minute_tone", n=minute)
    if minute <= 45:
        return i18n.t("title_nth_tone", n=minute)
    if minute <= 70:
        return i18n.t("title_turned_after", n=minute)
    return i18n.t("title_settled_nth", n=minute)


def _zone_title(bundle: MatchBundle, audit: dict[str, Any]) -> str:
    zones = audit.get("zone_control") or []
    if not zones:
        return i18n.t("title_where_played")
    home_touches = sum(z["home_touches"] for z in zones)
    away_touches = sum(z["away_touches"] for z in zones)
    if home_touches > away_touches * 1.15:
        return i18n.t("title_owned_map", team=bundle.home.upper())
    if away_touches > home_touches * 1.15:
        return i18n.t("title_owned_map", team=bundle.away.upper())
    return i18n.t("title_every_zone")


def _closing_copy(bundle: MatchBundle, audit: dict[str, Any]) -> dict[str, str]:
    context = result_context(bundle, audit)
    score = bundle.score
    winner = context["winner"]
    loser = context["loser"]
    hook = build_hook(bundle, audit)
    if winner and loser:
        loser_shots = int(context["loser_stats"].get("shots") or 0)
        source_supported = set(audit.get("source_supported_stats") or [])
        if source_supported:
            winner_shots = int(context["winner_stats"].get("shots") or 0)
            narration = (
                f"{winner} won {score.display}; {loser} led shots "
                f"{loser_shots}-{winner_shots}"
            )
            if "xg" in source_supported:
                narration += (
                    f" and xG {float(context['loser_stats'].get('xg') or 0):.2f}-"
                    f"{float(context['winner_stats'].get('xg') or 0):.2f}."
                )
            else:
                narration += "."
        elif hook["kind"] in {"volume_upset", "waste", "sterile_upset"}:
            narration = (
                f"{loser} had {loser_shots} shots. {winner} take it {score.display}."
            )
        elif hook["kind"] == "blowout":
            narration = f"{winner} win it {score.display}. The map was never a contest."
        elif hook["kind"] in {"comeback", "stoppage", "late_turn"}:
            last = (audit.get("goal_timeline") or [None])[-1]
            minute = int((last or {}).get("minute") or 0)
            narration = f"{winner} win it {score.display}, settled in the {minute}th."
        else:
            narration = (
                f"{winner} win it {score.display}. "
                f"{int(context['winner_stats'].get('shots_on_target') or 0)} on target."
            )
        if source_supported:
            if "xg" in source_supported:
                insight = i18n.t(
                    "insight_close_shots_xg",
                    a=loser_shots, b=winner_shots,
                    xg_a=f"{float(context['loser_stats'].get('xg') or 0):.2f}",
                    xg_b=f"{float(context['winner_stats'].get('xg') or 0):.2f}",
                    score=score.display,
                )
            else:
                insight = i18n.t("insight_close_shots", a=loser_shots, b=winner_shots, score=score.display)
        else:
            insight = i18n.t("insight_close_result", team=winner)
    elif score.total_goals == 0:
        total = sum(int(team.get("shots") or 0) for team in audit["team_stats"].values())
        narration = f"Goalless. {total} shots, and the net never moved."
        insight = i18n.t("insight_close_goalless")
    else:
        narration = f"It finishes {score.display}. A point each."
        insight = i18n.t("insight_close_level")
    return {
        "kicker": i18n.t("full_time") if not score.qualifier else score.qualifier,
        "title": f"{bundle.home.upper()} {score.display} {bundle.away.upper()}",
        "subtitle": "",
        "insight": insight,
        "narration": narration,
    }


def _micro_hook_scene(bundle: MatchBundle, audit: dict[str, Any], viz_id: str, index: int) -> dict[str, Any]:
    bridge = build_bridge(bundle, audit, viz_id)
    line = bridge["line"]
    flash_cycle = ("cream", "team", "black")
    return {
        "id": f"bridge_{viz_id}",
        "visualization": "micro_hook",
        "hook": True,
        "cut": "hard",
        "seconds": bridge["seconds"],
        "opens": viz_id,
        "flash": flash_cycle[index % 3],
        "show_badges": index % 2 == 0,
        "kicker": f"{bundle.home} — {bundle.away}",
        "title": line,
        "subtitle": "",
        "insight": "",
        "lines": [line],
        "narration": line.rstrip("."),
        "visual_language": "stamp",
    }


def attach_handoffs(
    scenes: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep each analysis sentence attached to its own evidence card.

    Micro-hooks already provide transitions. Replacing a statistical sentence
    with a generic tease destroyed the evidence-first format.
    """
    return scenes


def _hook_fields(hook: dict[str, Any]) -> dict[str, Any]:
    return {
        "hook_kind": hook.get("kind"),
        "visual_language": hook.get("visual_language"),
        "hero_number": hook.get("hero_number"),
        "hero_label": hook.get("hero_label"),
        "hero_team": hook.get("team"),
        "split": hook.get("split") or {},
        "fact_pack": {
            "kind": hook.get("kind"),
            "numbers": hook.get("numbers") or [],
            "never_say": hook.get("never_say") or [],
            "qualified": hook.get("qualified") or [],
        },
        "allowed_numbers": hook.get("numbers") or [],
    }


def build_storyboard(
    bundle: MatchBundle,
    audit: dict[str, Any],
    selected: list[dict[str, Any]],
    clip_beats: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The deterministic script. Every string here comes from the audit.

    Open on a contradiction, prove it, then at most two mid-pack slams.
    The score stays on the last card.
    """
    hook = build_hook(bundle, audit)
    matchup = hook["matchup"]
    scenes: list[dict[str, Any]] = []
    beats = list(clip_beats or [])
    pre_beats, mid_beats = beats[:1], beats[1:2]

    def clip_scene(index: int, beat: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"live_clip_{index}",
            "visualization": "live_clip",
            "hook": True,
            "cut": "hard",
            "seconds": min(0.55, float(beat["duration"])),
            "clip_path": beat["path"],
            "clip_offset": float(beat["start"]),
            "kicker": matchup,
            "title": str(beat.get("label") or matchup),
            "subtitle": "",
            "insight": "",
            "narration": "",
            "lines": [],
        }

    for index, beat in enumerate(pre_beats, 1):
        scenes.append(clip_scene(index, beat))

    claim_lines = list(hook["lines"])
    scenes.append(
        {
            "id": "hook_claim",
            "visualization": "hook_claim",
            "hook": True,
            "cut": "hard",
            "seconds": hook["seconds_claim"],
            "kicker": matchup,
            "title": claim_lines[0],
            "subtitle": claim_lines[1] if len(claim_lines) > 1 else "",
            "insight": claim_lines[2] if len(claim_lines) > 2 else "",
            "lines": claim_lines,
            "narration": hook["narration_claim"],
            **_hook_fields(hook),
        }
    )
    for index, beat in enumerate(mid_beats, 1 + len(pre_beats)):
        scenes.append(clip_scene(index, beat))
    scenes.append(
        {
            "id": "hook_punch",
            "visualization": "hook_punch",
            "hook": True,
            "cut": "hard",
            "seconds": hook["seconds_punch"],
            "kicker": matchup,
            "title": hook["punch"],
            "subtitle": "",
            "insight": "",
            "lines": [hook["punch"]],
            "narration": hook["narration_punch"],
            **_hook_fields(hook),
        }
    )

    # Cap micro-hooks at two mid-pack interrupts. Skip the first viz and the close.
    micro_slots = set()
    if len(selected) >= 3:
        micro_slots = {1, 2}
    elif len(selected) == 2:
        micro_slots = {1}

    for index, item in enumerate(selected):
        if index in micro_slots:
            scenes.append(_micro_hook_scene(bundle, audit, item["id"], index))
        copy = _visual_copy(bundle, audit, item["id"])
        fact = scene_fact_pack(bundle, audit, item["id"], copy)
        scenes.append(
            {
                "id": item["id"],
                "visualization": item["id"],
                "cut": "wipe",
                "fact_pack": fact,
                "allowed_numbers": fact.get("numbers") or [],
                **copy,
            }
        )

    closing = _closing_copy(bundle, audit)
    close_fact = scene_fact_pack(bundle, audit, "close", closing)
    scenes.append(
        {
            "id": "close",
            "visualization": "close",
            "cut": "hard",
            "stat_keys": pick_stat_rows(bundle, audit)[:3],
            "fact_pack": close_fact,
            "allowed_numbers": close_fact.get("numbers") or [],
            **closing,
        }
    )
    return attach_handoffs(scenes, bundle, audit)


def scene_fact_pack(bundle: MatchBundle, audit: dict[str, Any], viz_id: str, copy: dict[str, Any]) -> dict[str, Any]:
    """Numbers a scene is allowed to speak, for the Gemini lock."""
    stats = audit.get("team_stats") or {}
    home, away = stats.get(bundle.home, {}), stats.get(bundle.away, {})
    numbers: list[Any] = []
    surnames: list[str] = []

    def add_stat(*keys: str) -> None:
        for key in keys:
            numbers.append(home.get(key))
            numbers.append(away.get(key))

    if viz_id in {"shot_map", "stat_slam", "match_radar", "standard_stats", "box_score"}:
        add_stat("shots", "shots_on_target", "big_chances", "pass_share_pct", "possession_pct", "saves",
                 "penalty_box_touches", "tackles_won", "dribbles_won")
    elif viz_id in {"goalmouth", "keeper_frame"}:
        add_stat("saves", "shots_on_target", "shots")
    elif viz_id in {"sterile_domination", "chance_funnel", "pass_network"}:
        add_stat("pass_share_pct", "possession_pct", "final_third_passes", "box_entry_passes",
                 "penalty_box_touches", "big_chances", "shots", "shots_on_target", "goals")
    elif viz_id in {"zone_control", "touch_heatmap", "time_zones", "field_tilt_wave"}:
        zones = audit.get("zone_control") or []
        numbers.extend([
            sum(int(z.get("home_touches") or 0) for z in zones),
            sum(int(z.get("away_touches") or 0) for z in zones),
        ])
        tilt = audit.get("field_tilt") or []
        if tilt:
            peak = max(tilt, key=lambda row: max(row.get("home_tilt_pct") or 0, row.get("away_tilt_pct") or 0))
            numbers.extend([peak.get("home_tilt_pct"), peak.get("away_tilt_pct")])
    elif viz_id == "goal_timeline":
        for goal in audit.get("goal_timeline") or []:
            numbers.append(goal.get("minute"))
            if goal.get("scorer"):
                surnames.append(str(goal["scorer"]).split()[-1])
        numbers.append(len(audit.get("goal_timeline") or []))
    elif viz_id == "goal_chain":
        chain = best_goal_chain(audit)
        if chain:
            numbers.extend([chain.get("passes"), chain.get("pass_distance_m"), chain.get("duration_seconds"), chain.get("minute")])
            if chain.get("scorer"):
                surnames.append(str(chain["scorer"]).split()[-1])
    elif viz_id == "player_spike":
        spike = (audit.get("player_leaders") or {}).get("spike") or {}
        numbers.append(spike.get("count"))
        numbers.append(spike.get("rest"))
        numbers.append(spike.get("shirt"))
        if spike.get("surname"):
            surnames.append(str(spike["surname"]))
    elif viz_id == "shot_clock_spiral":
        add_stat("shots", "shots_on_target")
        numbers.append(len(audit.get("shots") or []))
    elif viz_id == "press_trap":
        trap = audit.get("press_trap") or {}
        numbers.extend([
            (trap.get("home") or {}).get("ppda"),
            (trap.get("away") or {}).get("ppda"),
            (trap.get("home") or {}).get("press_actions"),
            (trap.get("away") or {}).get("press_actions"),
            trap.get("leader_ppda"),
        ])
    elif viz_id == "pass_lanes":
        add_stat("pass_attempts", "passes_completed", "pass_accuracy_pct")
    elif viz_id == "bench_impact":
        bench = audit.get("bench_impact") or {}
        numbers.append(len(bench.get("subs") or []))
        for sub in bench.get("subs") or []:
            numbers.append(sub.get("minute"))
            numbers.append(sub.get("shots_after"))
            numbers.append(sub.get("shirt"))
    elif viz_id == "duel_tower":
        duels = audit.get("duels") or {}
        numbers.extend([
            (duels.get("home") or {}).get("total"),
            (duels.get("away") or {}).get("total"),
            (duels.get("home") or {}).get("tackles"),
            (duels.get("away") or {}).get("tackles"),
        ])
    elif viz_id == "aerial_war":
        aerials = audit.get("aerials") or {}
        numbers.extend([aerials.get("home_won"), aerials.get("away_won"), aerials.get("total")])
    elif viz_id == "halftime_split":
        split = audit.get("halftime_split") or {}
        first, second = split.get("first") or {}, split.get("second") or {}
        numbers.extend([
            first.get("home_shots"), first.get("away_shots"),
            second.get("home_shots"), second.get("away_shots"),
        ])
    elif viz_id == "xg_race":
        add_stat("xg", "xgot", "goals", "shots")
    elif viz_id == "conversion_gauges":
        add_stat("shots", "shots_on_target", "big_chances", "xg")
    elif viz_id == "momentum":
        peak = max(audit.get("momentum") or [{"swing": 0}], key=lambda row: abs(row.get("swing") or 0))
        numbers.append(_block_minute(peak))
    elif viz_id == "touch_skyline":
        numbers.extend(_touch_totals(audit))
    elif viz_id == "shot_skyline":
        add_stat("shots", "shots_on_target", "goals")
    elif viz_id == "shot_trajectories":
        numbers.extend(_trajectory_counts(audit))
    elif viz_id in {"player_podium", "lineup_board"}:
        for player in ((audit.get("player_ratings") or {}).get("top") or [])[:3]:
            numbers.extend([player.get("rating"), f"{float(player.get('rating') or 0):.2f}", player.get("shirt")])
            surnames.append(str(player.get("surname") or ""))
        lineups = audit.get("lineups") or {}
        for key in ("home", "away"):
            numbers.extend(re.findall(r"\d", str((lineups.get(key) or {}).get("formation") or "")))
    elif viz_id == "shot_dna":
        profile = audit.get("shot_profile") or {}
        for key in ("home", "away"):
            side = profile.get(key) or {}
            numbers.extend([side.get("total"), int(round(float(side.get("box_pct") or 0)))])
            numbers.extend((side.get("situation") or {}).values())
            numbers.extend((side.get("body") or {}).values())
    elif viz_id == "pass_sonar":
        sonar = audit.get("pass_sonar") or {}
        for key in ("home", "away"):
            side = sonar.get(key) or {}
            numbers.extend([f"{float(side.get(field) or 0):.0f}" for field in
                            ("forward_pct", "backward_pct", "avg_length_m", "long_pct")])
            numbers.append(side.get("total"))
    elif viz_id == "defensive_block":
        shape = audit.get("defensive_shape") or {}
        for key in ("home", "away"):
            side = shape.get(key) or {}
            numbers.extend([f"{float(side.get('line_height_m') or 0):.0f}",
                            f"{float(side.get('high_pct') or 0):.0f}", side.get("count")])
    elif viz_id == "close":
        score = bundle.score
        numbers.extend([score.home, score.away])
        add_stat("shots", "shots_on_target", "big_chances", "saves", "pass_share_pct")
        for goal in audit.get("goal_timeline") or []:
            numbers.append(goal.get("minute"))
            if goal.get("scorer"):
                surnames.append(str(goal["scorer"]).split()[-1])

    blob = " ".join(str(copy.get(field) or "") for field in ("title", "insight", "narration", "kicker", "hero_number"))
    numbers.extend(hooks.collect_numbers(blob))
    return {
        "id": viz_id,
        "numbers": hooks.collect_numbers(*numbers),
        "surnames": surnames,
        "never_say": hooks.score_variants(bundle) if viz_id != "close" else [],
        "what_the_picture_shows": copy.get("subtitle") or viz_id.replace("_", " "),
    }


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class Gemini:
    """Thin, retrying wrapper around google-genai.

    Every call degrades to ``None`` rather than raising, unless the caller asked
    for Gemini to be mandatory.
    """

    def __init__(
        self,
        enabled: bool = True,
        required: bool = False,
        model: str | None = None,
        script_model: str | None = None,
    ) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = _resolve_gemini_model(model, os.getenv("GEMINI_MODEL"), DEFAULT_MODEL, "GEMINI_MODEL")
        self.script_model = _resolve_gemini_model(
            script_model, os.getenv("GEMINI_SCRIPT_MODEL"), DEFAULT_SCRIPT_MODEL, "GEMINI_SCRIPT_MODEL",
        )
        self.required = required
        self.enabled = bool(enabled and self.api_key)
        self._client: Any = None
        self.last_error = ""
        self._blocked: set[str] = set()
        self._winner: str | None = None
        if required and not self.api_key:
            raise RuntimeError("--require-gemini was passed but GEMINI_API_KEY is not set.")

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _generate(
        self,
        payload: dict[str, Any] | str,
        *,
        model: str | None = None,
        temperature: float = 0.85,
        system: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        prompt = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        chosen = model or self.model
        models_to_try = [
            name for name in gemini_model_chain(self._winner, chosen, self.script_model, self.model)
            if name not in self._blocked
        ]
        if not models_to_try:
            self._blocked.clear()
            models_to_try = gemini_model_chain(chosen, self.script_model, self.model)
        for model_name in models_to_try:
            skip_schema = False
            retried_json = False
            while True:
                try:
                    config: dict[str, Any] = {
                        "response_mime_type": "application/json",
                        "temperature": temperature,
                    }
                    if system:
                        config["system_instruction"] = system
                    if response_schema and not skip_schema:
                        config["response_schema"] = response_schema
                    response = self._get_client().models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    parsed = loads_model_json(response.text or "")
                    if not isinstance(parsed, dict):
                        raise ValueError("Gemini JSON was not an object")
                    if model_name != chosen:
                        print(f"  [gemini] using {model_name}")
                    self._winner = model_name
                    self.last_error = ""
                    return parsed
                except Exception as exc:  # noqa: BLE001 - the SDK raises many types
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    action = gemini_failure_action(
                        self.last_error, can_strip_schema=bool(response_schema) and not skip_schema,
                    )
                    if action == "strip_schema":
                        skip_schema = True
                        print(f"  [gemini] {model_name} rejected the response schema; retrying without it")
                        continue
                    if action == "retry_json" and not retried_json:
                        retried_json = True
                        print(f"  [gemini] {model_name} returned unusable JSON; retrying once")
                        continue
                    if action == "switch":
                        self._blocked.add(model_name)
                        print(f"  [gemini] {model_name} unavailable ({self.last_error[:70]}); next model")
                    else:
                        print(f"  [gemini] {model_name} failed ({self.last_error[:70]})")
                    break
        if self.required:
            raise RuntimeError(f"Gemini was required but every attempt failed. Last error: {self.last_error}")
        print(f"  [gemini] unavailable, using the deterministic script. Last error: {self.last_error[:110]}")
        return None

    # -- calls --------------------------------------------------------------

    def choose_visualizations(
        self,
        bundle: MatchBundle,
        audit: dict[str, Any],
        candidates: list[dict[str, Any]],
        count: int,
        instruction: str,
        angle: str = "",
    ) -> list[str]:
        payload = {
            "task": (
                "You are the director of a short-form football analytics video. Choose the "
                f"{count} visualizations that best prove THIS match's angle."
            ),
            "angle": angle or pick_angle(bundle, audit),
            "rules": [
                "Only choose candidates where available is true.",
                "A candidate can be available and still be a bad fit; use best_for and avoid_when.",
                "Prefer a set that tells one coherent story rather than three versions of the same point.",
                "Do not pick two scenes from the same shape family.",
                f"Return exactly {count} ids.",
            ],
            "editor_note": instruction,
            "match": _brief(bundle, audit, angle=angle),
            "candidates": candidates,
            "response_schema": {"selected": ["visualization_id"], "angle": "one sentence"},
        }
        parsed = self._generate(payload, model=self.model, temperature=0.4)
        if not parsed:
            return []
        raw = parsed.get("selected") or []
        ids = []
        for item in raw:
            value = item.get("id") if isinstance(item, dict) else item
            if value:
                ids.append(str(value))
        return ids

    def choose_angle(
        self,
        bundle: MatchBundle,
        audit: dict[str, Any],
        language: str = "en",
        hook: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        hook = hook or build_hook(bundle, audit)
        payload = {
            "task": "Pick ONE recap angle for this football match.",
            "language": i18n.normalize_language(language),
            "hook": {"kind": hook.get("kind"), "punch": hook.get("punch"), "lines": hook.get("lines")},
            "match": _brief(bundle, audit),
            "response_schema": {
                "angle": "keeper_masterclass|xg_robbery|press_pin|waste|comeback|chain_shock|blowout|stoppage|one_moment|upset|siege|stalemate|two_halves|keeper",
                "why": "one sentence",
            },
        }
        parsed = self._generate(
            payload, model=self.script_model, temperature=0.55, system=SYSTEM_PROMPT,
        )
        if isinstance(parsed, dict) and parsed.get("angle"):
            return parsed
        return {"angle": hook.get("kind") or pick_angle(bundle, audit), "why": ""}

    def write_script(
        self,
        bundle: MatchBundle,
        audit: dict[str, Any],
        scenes: list[dict[str, Any]],
        words_per_scene: int,
        instruction: str,
        language: str = "en",
        angle: str = "",
        audit_notes: list[str] | None = None,
    ) -> dict[str, dict[str, str]]:
        lang = i18n.normalize_language(language)
        lang_name = i18n.language_name(lang)
        # The original product's charm was one compact, evidence-rich sentence
        # per card. Seventeen words is the center, not a vague upper bound.
        target_words = max(10, min(24, words_per_scene))
        lo = max(10, target_words - 1)
        hi = min(24, target_words + 2)
        language_rule = (
            "Write in plain English. No hashtags, no emoji, no 'in this video'. "
            "The hook already ran. Do not repeat the score until the closing card."
            if lang == "en"
            else (
                f"COMPOSE originally in {lang_name} (language code `{lang}`). "
                "Do not translate current_title / current_insight / current_narration — "
                "those fields are structure and numbers only. "
                f"Write a new title, insight and narration the way a native {lang_name} "
                "football editor would. Titles especially must be a native headline, "
                "not a calque of an English label. "
                "Keep team names, player surnames and digits unchanged. "
                f"Every kicker/title/subtitle/insight/narration field must be in {lang_name}. "
                "Empty subtitle is better than leftover English. "
                "Do not mention the score until the closing card."
            )
        )
        payload = {
            "task": (
                "Rewrite the on-screen copy and narration for a football analytics short. "
                "Keep the analysis sharp and specific; this is for viewers who want to know WHY "
                "the match finished the way it did."
            ),
            "angle": angle,
            "few_shots": SCRIPT_FEW_SHOTS,
            "rules": [
                "Return exactly one JSON object with a scenes array. Nothing else.",
                "Never state a number that is not in the scene's fact_pack.numbers.",
                "Never say 'possession' unless match.data_health.has_vendor_possession is true.",
                "Never mention expected goals, xG or xGOT unless match.data_health.has_vendor_xg is true.",
                f"Narration for each analysis scene must be {lo} to {hi} words, aiming at {target_words}. "
                "Use one or two numbers from that exact scene's fact_pack and explain what they prove. "
                "The line must be useless on any other card: statistic and interpretation belong together. "
                "Mix rhythms. "
                "Do not start every line with a team name. Do not tease the next card unless it earns it. "
                "Do not use the word 'but' more than once across the whole script.",
                "title is shown in heavy display type; keep it under 28 characters and do not end it with a full stop. "
                "When the fact pack has a number or a surname, the title must contain one.",
                "insight IS shown on screen as a two-line caption stamped late. Make it the sharpest sentence.",
                "Do not open any analysis scene with the scoreline. The score is the closing payoff only.",
                "Never write a score such as 2-1 on hook_claim, hook_punch, micro_hook or live_clip scenes.",
                "You MAY rephrase hook_claim and hook_punch using only numbers in their fact packs. "
                "Do not invent a new hook kind.",
                "Return one object per input scene id, same ids, no extras.",
                "The few_shots are English style samples only. Mirror their sharpness, not their language.",
                language_rule,
            ],
            "language": lang,
            "editor_note": instruction,
            "audit_notes": audit_notes or [],
            "match": _brief(bundle, audit, angle=angle),
            "scenes": [
                {
                    "id": scene["id"],
                    "visualization": scene["visualization"],
                    "hook": bool(scene.get("hook")),
                    "what_it_shows": (scene.get("fact_pack") or {}).get("what_the_picture_shows")
                    or scene.get("subtitle")
                    or scene["visualization"],
                    "fact_pack": scene.get("fact_pack") or {},
                    "current_title": scene.get("title", ""),
                    "current_insight": scene.get("insight", ""),
                    "current_narration": scene.get("narration", ""),
                }
                for scene in scenes
                if scene.get("visualization") != "live_clip"
            ],
            "response_schema": {
                "scenes": [
                    {"id": "scene id", "kicker": "", "title": "", "subtitle": "", "insight": "", "narration": ""}
                ]
            },
        }
        system = SYSTEM_PROMPT
        if lang != "en":
            system = (
                SYSTEM_PROMPT
                + f" Compose every user-facing string in {lang_name}. "
                + "Do not translate an English draft. Titles are native headlines, not calques."
            )
        parsed = self._generate(
            payload,
            model=self.script_model,
            temperature=0.7,
            system=system,
            response_schema=SCRIPT_RESPONSE_SCHEMA,
        )
        result = self._script_overrides(parsed)
        wanted = {
            scene["id"]
            for scene in scenes
            if scene.get("visualization") != "live_clip"
        }
        # A total failure already walked the model list. Repairing would walk it again.
        if parsed and wanted and len(result) < max(1, len(wanted) // 2):
            repair = {
                "task": (
                    "Your previous reply was unusable. Return ONE JSON object only, "
                    "with a scenes array covering every required id."
                ),
                "required_ids": sorted(wanted),
                "rules": payload["rules"],
                "scenes": payload["scenes"],
                "response_schema": payload["response_schema"],
            }
            parsed = self._generate(
                repair,
                model=self.script_model,
                temperature=0.45,
                system=system,
                response_schema=SCRIPT_RESPONSE_SCHEMA,
            )
            repaired = self._script_overrides(parsed)
            if len(repaired) > len(result):
                result = repaired
        return result

    @staticmethod
    def _script_overrides(parsed: dict[str, Any] | None) -> dict[str, dict[str, str]]:
        if not parsed:
            return {}
        result: dict[str, dict[str, str]] = {}
        rows = parsed.get("scenes")
        if not isinstance(rows, list):
            return {}
        for scene in rows:
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("id") or "")
            if scene_id:
                result[scene_id] = {
                    key: sanitize(scene.get(key), "")
                    for key in ("kicker", "title", "subtitle", "insight", "narration")
                }
        return result

    def rephrase_hook(self, hook: dict[str, Any], language: str = "en") -> dict[str, Any]:
        lang = i18n.normalize_language(language)
        lang_name = i18n.language_name(lang)
        task = (
            "Rewrite the hook punch and claim lines. Keep every number from the pack."
            if lang == "en"
            else (
                f"Write the hook punch and claim lines originally in {lang_name}. "
                "Do not translate an English draft. Keep every number from the pack."
            )
        )
        system = SYSTEM_PROMPT
        if lang != "en":
            system = SYSTEM_PROMPT + f" Write the hook in {lang_name}. Do not translate English."
        payload = {
            "task": task,
            "language": lang,
            "kind": hook.get("kind"),
            "numbers": hook.get("numbers") or [],
            "never_say": hook.get("never_say") or [],
            "pool": hook.get("variants") or [],
            "current": {"lines": hook.get("lines"), "punch": hook.get("punch")},
            "response_schema": {"lines": ["claim line"], "punch": "punch line"},
        }
        parsed = self._generate(
            payload, model=self.script_model, temperature=0.8, system=system,
        )
        return parsed if isinstance(parsed, dict) else {}

    def translate_script(
        self,
        scenes: list[dict[str, Any]],
        language: str,
    ) -> dict[str, dict[str, str]]:
        """Translate already-audited English copy into ``language``.

        Numbers, scorelines, player names and team names must stay byte-for-byte
        the same; only the surrounding wording may change.
        """
        lang = i18n.normalize_language(language)
        if lang == "en":
            return {}
        lang_name = i18n.language_name(lang)
        payload = {
            "task": (
                f"Translate the football analytics on-screen copy and narration into {lang_name} "
                f"(language code `{lang}`)."
            ),
            "rules": [
                "Preserve every digit, scoreline (e.g. 1-4), minute marker and percentage exactly.",
                "Preserve team names and player names exactly as written.",
                "Never invent statistics. Never say possession, xG or xGOT.",
                "title under 34 characters; kicker under 22; insight under 70.",
                "On the title scene, keep the kicker as the score and leave subtitle empty.",
                "Keep the tone sharp and analytical, not marketing copy.",
                "Return one object per input scene id.",
            ],
            "language": lang,
            "scenes": [
                {
                    "id": scene["id"],
                    "kicker": scene.get("kicker", ""),
                    "title": scene.get("title", ""),
                    "subtitle": scene.get("subtitle", ""),
                    "insight": scene.get("insight", ""),
                    "narration": scene.get("narration", ""),
                }
                for scene in scenes
                if not scene.get("hook")
            ],
            "response_schema": {
                "scenes": [
                    {"id": "scene id", "kicker": "", "title": "", "subtitle": "", "insight": "", "narration": ""}
                ]
            },
        }
        parsed = self._generate(payload, model=self.script_model, temperature=0.4, system=SYSTEM_PROMPT)
        if not parsed:
            return {}
        result: dict[str, dict[str, str]] = {}
        for scene in parsed.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("id") or "")
            if scene_id:
                result[scene_id] = {
                    key: sanitize(scene.get(key), "")
                    for key in ("kicker", "title", "subtitle", "insight", "narration")
                }
        return result

    def translate_contextual_script(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Translate the complete story in one request using its audit context."""
        return self._generate(
            payload,
            model=self.script_model,
            temperature=0.25,
            system=(
                "You are a native football editor translating one complete recap. "
                "Keep every scene attached to its audited statistic. Return strict JSON. "
                "Never invent or alter a number, score, minute, player or team."
            ),
        )


def _brief(bundle: MatchBundle, audit: dict[str, Any], angle: str = "") -> dict[str, Any]:
    """The compact, numbers-only view of the match given to the model."""
    momentum = sorted(audit["momentum"], key=lambda row: abs(row["swing"]), reverse=True)[:4]
    hook = audit.get("hook") if isinstance(audit.get("hook"), dict) else {}
    tilt = audit.get("field_tilt") or []
    peak_tilt = 50.0
    if tilt:
        peak_tilt = max(max(row.get("home_tilt_pct") or 50, row.get("away_tilt_pct") or 50) for row in tilt)
    chain = best_goal_chain(audit) or {}
    leaders = audit.get("player_leaders") or {}
    spike = leaders.get("spike") if isinstance(leaders, dict) else None
    return {
        "home": bundle.home,
        "away": bundle.away,
        "score": audit["match"]["score_display"],
        "score_qualifier": audit["match"]["score_qualifier"],
        "competition": bundle.competition_line(),
        "angle": angle,
        "hook_kind": hook.get("kind") if hook else None,
        "facts": audit["facts"],
        "stats": audit["team_stats"],
        "timeline": audit["goal_timeline"],
        "biggest_pressure_windows": momentum,
        "best_chain": {
            "passes": chain.get("passes"),
            "metres": chain.get("pass_distance_m"),
            "seconds": chain.get("duration_seconds"),
            "scorer": chain.get("scorer"),
        } if chain else None,
        "field_tilt_peak": peak_tilt,
        "player_leaders": spike,
        "unavailable_metrics": audit["data_health"]["blocked_claims"],
        "data_health": {
            "has_vendor_xg": bool((audit.get("data_health") or {}).get("has_vendor_xg")),
            "has_vendor_xgot": bool((audit.get("data_health") or {}).get("has_vendor_xgot")),
            "has_vendor_possession": bool((audit.get("data_health") or {}).get("has_vendor_possession")),
        },
        "definitions": audit["definitions"],
    }


def _extract_json(raw: str) -> str:
    from .jsonutil import extract_json

    return extract_json(raw)


_POLITE_TITLE = re.compile(
    r"\b("
    r"match result|match recap|full[- ]?time|oyun n[əe]tic[əe]si|mat[cç] x[üu]las|"
    r"resultado( del partido)?|результат( матча)?"
    r")\b",
    re.IGNORECASE,
)


def _is_polite_title(text: str, bundle: MatchBundle) -> bool:
    """True when a title is a competition/result label, not a claim."""
    raw = (text or "").strip()
    if not raw:
        return True
    if _POLITE_TITLE.search(raw):
        return True
    compact = re.sub(r"[^a-z0-9]+", "", raw.lower())
    vs = re.sub(r"[^a-z0-9]+", "", f"{bundle.home}vs{bundle.away}".lower())
    return bool(vs) and compact == vs


def lock_hook_cards(
    scenes: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep the open on the contradiction. Gemini may rephrase; numbers stay locked."""
    hook = build_hook(bundle, audit)
    locked = []
    for scene in scenes:
        updated = dict(scene)
        viz = scene.get("visualization")
        pack = {
            "numbers": hook.get("numbers") or [],
            "never_say": hook.get("never_say") or [],
        }
        if viz == "hook_claim":
            lines = list(updated.get("lines") or hook["lines"])
            if not lines or not all(hooks.hook_passes_lock(line, pack) for line in lines):
                lines = list(hook["lines"])
            updated["kicker"] = hook["matchup"]
            updated["lines"] = lines
            updated["title"] = lines[0] if lines else hook["matchup"]
            updated["subtitle"] = lines[1] if len(lines) > 1 else ""
            updated["insight"] = lines[2] if len(lines) > 2 else ""
            if not hooks.hook_passes_lock(str(updated.get("narration") or ""), pack):
                updated["narration"] = hook["narration_claim"]
        elif viz == "hook_punch":
            punch = str(updated.get("title") or "")
            if not hooks.hook_passes_lock(punch, pack):
                punch = hook["punch"]
            updated["kicker"] = hook["matchup"]
            updated["title"] = punch
            updated["subtitle"] = ""
            updated["insight"] = ""
            updated["lines"] = [punch]
            if not hooks.hook_passes_lock(str(updated.get("narration") or ""), pack):
                updated["narration"] = hook["narration_punch"]
        elif viz == "live_clip":
            updated["kicker"] = hook["matchup"]
            if _SCORELINE.search(str(updated.get("title") or "")):
                updated["title"] = hook["matchup"]
            updated["subtitle"] = ""
        elif viz == "micro_hook":
            opens = str(scene.get("opens") or "close")
            bridge = build_bridge(bundle, audit, opens)
            current = str(updated.get("title") or "")
            if not hooks.hook_passes_lock(current, {"numbers": hooks.collect_numbers(bridge["line"], current), "never_say": hook.get("never_say") or []}):
                current = bridge["line"]
            updated["opens"] = opens
            updated["title"] = current
            updated["lines"] = [current]
            updated["subtitle"] = ""
            updated["insight"] = ""
            if _SCORELINE.search(str(updated.get("narration") or "")):
                updated["narration"] = current.rstrip(".")
        locked.append(updated)
    return attach_handoffs(locked, bundle, audit)


def storyboard_by_id(
    scenes: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Rebuild the audited storyboard in the current language, keyed by scene id."""
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    clip_beats: list[dict[str, Any]] = []
    skip = {"live_clip", "hook_claim", "hook_punch", "micro_hook", "close"}
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "live_clip":
            if scene.get("clip_path"):
                clip_beats.append({
                    "path": scene.get("clip_path"),
                    "start": scene.get("clip_offset", 0),
                    "duration": scene.get("seconds") or 0.55,
                    "label": scene.get("title") or "",
                })
            continue
        if viz in skip or not viz or viz in seen:
            continue
        seen.add(viz)
        selected.append({"id": viz})
    built = build_storyboard(bundle, audit, selected, clip_beats=clip_beats or None)
    return {str(scene.get("id")): scene for scene in built}


def lock_title_card(
    scenes: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
) -> list[dict[str, Any]]:
    """Back-compat alias. The opener is no longer a score title card."""
    return lock_hook_cards(scenes, bundle, audit)


def apply_script(
    scenes: list[dict[str, Any]],
    overrides: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Merge Gemini wording over the deterministic scenes.

    Only these five text fields can be replaced. Visualization ids, stat keys
    and every number stay exactly as the audit produced them. Extra digits
    revert that field to the deterministic copy.
    """
    merged = []
    for scene in scenes:
        override = overrides.get(scene["id"], {})
        updated = dict(scene)
        pack = scene.get("fact_pack") or {}
        allowed = hooks.allowed_number_tokens(pack.get("numbers") or scene.get("allowed_numbers") or [])
        never_say = list(pack.get("never_say") or [])
        close = scene.get("visualization") == "close"
        hookish = bool(scene.get("hook"))
        for field in ("kicker", "title", "subtitle", "insight", "narration"):
            value = override.get(field, "").strip()
            if not value:
                continue
            if i18n.get_language() != "en" and i18n.leftover_english(value, i18n.get_language()):
                continue
            if not close and _SCORELINE.search(value):
                continue
            if not close and any(token and token in value for token in never_say):
                continue
            if allowed and hooks.extra_numbers(value, allowed):
                continue
            if hookish and not hooks.hook_passes_lock(value, pack or {"numbers": scene.get("allowed_numbers") or [], "never_say": never_say}):
                continue
            updated[field] = value
            if hookish and field == "title":
                if scene.get("visualization") == "hook_claim":
                    lines = list(updated.get("lines") or [])
                    if lines:
                        lines[0] = value
                    else:
                        lines = [value]
                    updated["lines"] = lines
                elif scene.get("visualization") in {"hook_punch", "micro_hook"}:
                    updated["lines"] = [value]
        merged.append(updated)
    return _dedupe_insights(merged)


def _dedupe_insights(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stop the same closing line appearing on three different cards."""
    seen: set[str] = set()
    for scene in scenes:
        insight = clean_text(scene.get("insight"))
        fingerprint = re.sub(r"[^a-z0-9]+", "", insight.lower())
        if fingerprint and fingerprint in seen:
            scene["insight"] = ""
        elif fingerprint:
            seen.add(fingerprint)
    return scenes
