"""Choosing what to show and writing what to say.

Gemini is optional throughout. Every function here has a deterministic path
that produces a complete, match-specific script from the audit alone, and the
Gemini path can only ever override *wording* — never numbers, never which
metric a label is attached to.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Any

from .audit import best_goal_chain, credible_goal_chains, dominant_team, result_context
from .data import MatchBundle, clean_text
from . import hooks, i18n

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_SCRIPT_MODEL = "gemini-2.5-pro"
GEMINI_ATTEMPTS = 4

SYSTEM_PROMPT = (
    "You write short-form football voiceover. Specific names and minutes. "
    "Titles are claims, not labels. No hashtags, no emoji, no 'in this video'. "
    "Never invent a number. The score stays off every card except close. "
    "Vary sentence openings. Do not start every line with a team name. "
    "Do not tease the next card unless it earns it. Do not use the word 'but' "
    "more than once across the whole script."
)

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
    for key in STAT_CATALOG:
        if key in skip:
            continue
        if key == "xg" and not health.get("has_vendor_xg"):
            continue
        if key == "xgot" and not health.get("has_vendor_xgot"):
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
    "sterile_domination": "hero",
    "chance_funnel": "hero",
    "match_radar": "hero",
    "stat_slam": "hero",
    "conversion_gauges": "hero",
    "player_spike": "pitch",
    "standard_stats": "bars",
    "box_score": "bars",
}

ANGLE_VIZ = {
    "upset": ["stat_slam", "shot_map", "chance_funnel", "match_radar", "touch_heatmap"],
    "robbery": ["conversion_gauges", "xg_race", "shot_map", "keeper_frame", "stat_slam"],
    "siege": ["field_tilt_wave", "touch_heatmap", "zone_control", "momentum", "goalmouth"],
    "blowout": ["goal_timeline", "stat_slam", "shot_map", "match_radar", "goal_chain"],
    "comeback": ["momentum", "goal_timeline", "field_tilt_wave", "shot_map", "stat_slam"],
    "stalemate": ["shot_map", "chance_funnel", "match_radar", "zone_control", "keeper_frame"],
    "two_halves": ["time_zones", "field_tilt_wave", "momentum", "shot_map", "match_radar"],
    "keeper": ["keeper_frame", "goalmouth", "conversion_gauges", "shot_map", "stat_slam"],
}


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
    pass_gap = abs(home.get("pass_share_pct", 50) - away.get("pass_share_pct", 50))
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
            "available": total_shots >= 6,
            "score": 70 + min(16, total_shots * 0.6) + min(10, shot_gap + on_target_gap),
            "reason": "Where both teams shot from and what happened to each attempt.",
            "best_for": "Volume mismatches, wasteful finishing, or a goal glut.",
            "avoid_when": "Too few shots to fill the pitch.",
        },
        {
            "id": "momentum",
            "title": "Momentum Swing",
            "available": len(momentum) >= 6,
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
            "available": (
                max(home.get("pass_attempts", 0), away.get("pass_attempts", 0)) >= 150
                and int(health.get("pass_rows") or 0) >= 150
            ),
            "score": 44 + pass_gap,
            "reason": "Average positions and the strongest passing links.",
            "best_for": "Build-up identity and control stories.",
            "avoid_when": "Goals and shots explain the result more directly.",
        },
        {
            "id": "sterile_domination",
            "title": "Control vs Threat",
            "available": max(home.get("pass_share_pct", 0), away.get("pass_share_pct", 0)) >= 56,
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
            "available": total_shots >= 4,
            "score": 66 + min(10, pass_gap * 0.2),
            "reason": "Six axes, two overlays — the shape of the night.",
            "best_for": "A one-look profile of both teams.",
            "avoid_when": "Too few comparable stats.",
        },
        {
            "id": "touch_heatmap",
            "title": "Touch Heat",
            "available": bool((audit.get("touch_heatmap") or {}).get("home")),
            "score": 64 + min(16, max(0.0, max_tilt - 50) * 0.35),
            "reason": "True pitch gradient from every touch.",
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
            "available": max(home.get("pass_share_pct", 0), away.get("pass_share_pct", 0)) >= 54,
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
    ]
    for candidate in candidates:
        candidate["shape"] = SHAPE_FAMILY.get(candidate["id"], "other")
        candidate["score"] = round(float(candidate["score"]), 1)
    return candidates


def _diverse_pick(available: dict[str, dict[str, Any]], count: int, preferred: list[str]) -> list[str]:
    """Greedy: preferred order, then score, skipping duplicate shapes when possible."""
    picked: list[str] = []
    used_shapes: set[str] = set()

    def try_add(vid: str) -> None:
        if vid not in available or vid in picked:
            return
        shape = SHAPE_FAMILY.get(vid, "other")
        if shape in used_shapes and len(picked) < count - 1:
            # Keep a slot; we'll fill leftover shapes later.
            return
        picked.append(vid)
        used_shapes.add(shape)

    for vid in preferred:
        if len(picked) >= count:
            return picked
        try_add(vid)

    ranked = sorted(available.values(), key=lambda c: c["score"], reverse=True)
    for candidate in ranked:
        if len(picked) >= count:
            break
        try_add(candidate["id"])
    # Fill remaining even if shapes collide.
    for candidate in ranked:
        if len(picked) >= count:
            break
        if candidate["id"] not in picked:
            picked.append(candidate["id"])
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
        # Re-apply diversity: drop later ids that collide on shape when a substitute exists.
        chosen_ids = _diverse_pick(
            available, count, chosen_ids + preferred
        )

    if not chosen_ids:
        chosen_ids = _diverse_pick(available, count, preferred)

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
            "kicker": "EVERY GOAL",
            "title": f"{len(timeline)} GOALS, ONE RUNNING SCORE" if timeline else "THE GOAL TIMELINE",
            "subtitle": "",
            "insight": (
                f"{last['team']} had the last word in the {_ordinal(last['minute'])} minute."
                if last else "Every finish moved the board."
            ),
            "narration": narration,
        }

    if viz_id == "shot_map":
        leader = dominant_team(bundle, audit, "shots_on_target") or bundle.home
        return {
            "kicker": "SHOT MAP",
            "title": f"{home['shots']}-{away['shots']} ON THE MAP",
            "subtitle": i18n.t("sub_shot_map"),
            "insight": (
                f"{home['shots']} against {away['shots']} shots, "
                f"{home['shots_on_target']} against {away['shots_on_target']} on target."
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
            "kicker": "PRESSURE",
            "title": _momentum_title(audit),
            "subtitle": i18n.t("sub_momentum", home=bundle.home, away=bundle.away),
            "insight": (
                f"The heaviest spell fell to {leader} between minutes {peak['minute_block']}."
                if peak else "Pressure stayed level throughout."
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
            "kicker": "TERRITORY",
            "title": _zone_title(bundle, audit),
            "subtitle": i18n.t("sub_zone"),
            "insight": f"{leader} touched the ball in more of the dangerous grid than anyone else.",
            "narration": (
                f"{leader} owned the map, {home_touches} touches against {away_touches}."
            ),
        }

    if viz_id == "goal_chain":
        chain = best_goal_chain(audit)
        if chain:
            return {
                "kicker": "ONE GOAL, TRACED",
                "title": f"{chain['passes']} PASSES TO THE FINISH",
                "subtitle": f"{chain['team']} / {chain['scorer']}",
                "insight": f"{chain['pass_distance_m']:.0f} metres of passing in {chain['duration_seconds']:.0f} seconds.",
                "narration": (
                    f"{chain['team']} strung {chain['passes']} passes across "
                    f"{chain['pass_distance_m']:.0f} metres before {chain['scorer']} finished it."
                ),
            }
        return {
            "kicker": "BUILD-UP",
            "title": "THE MOVE BEFORE THE GOAL",
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
            "kicker": "THE FRAME",
            "title": f"{keeper_side.upper()} HAD WORK TO DO",
            "subtitle": i18n.t("sub_goalmouth"),
            "insight": f"{faced} shots at the frame, {keeper_stats['saves']} of them saved.",
            "narration": (
                f"{keeper_side} faced {faced} shots on target and saved {keeper_stats['saves']} of them."
            ),
        }

    if viz_id == "pass_network":
        leader = dominant_team(bundle, audit, "pass_attempts") or bundle.home
        leader_stats = stats[leader]
        return {
            "kicker": "PASS NETWORK",
            "title": f"HOW {leader.upper()} MOVED THE BALL",
            "subtitle": i18n.t("sub_pass_network"),
            "insight": f"{leader_stats['passes_completed']} completed passes at {leader_stats['pass_accuracy_pct']:.0f}% accuracy.",
            "narration": (
                f"{leader} completed {leader_stats['passes_completed']} passes at "
                f"{leader_stats['pass_accuracy_pct']:.0f} percent accuracy."
            ),
        }

    if viz_id == "sterile_domination":
        leader = dominant_team(bundle, audit, "pass_share_pct") or bundle.home
        leader_stats = stats[leader]
        return {
            "kicker": "CONTROL VS THREAT",
            "title": f"{leader.upper()} HAD THE BALL",
            "subtitle": i18n.t("sub_sterile"),
            "insight": (
                f"{leader_stats['pass_share_pct']:.0f}% of the passing, "
                f"{leader_stats['shots_on_target']} shots on target to show for it."
            ),
            "narration": (
                f"{leader} played {leader_stats['pass_share_pct']:.0f} percent of the passes "
                f"and still only put {leader_stats['shots_on_target']} on target."
            ),
        }

    if viz_id == "stat_slam":
        key = pick_stat_rows(bundle, audit, limit=1)[0]
        leader = dominant_team(bundle, audit, key) or bundle.home
        other = bundle.away if leader == bundle.home else bundle.home
        n = int(round(float(stats[leader].get(key) or 0)))
        return {
            "kicker": stat_label(key).upper(),
            "title": f"{n} {stat_label(key).upper()}",
            "subtitle": i18n.t("sub_slam"),
            "insight": (
                f"{leader} led {stat_label(key).lower()} "
                f"{format_stat(key, stats[leader].get(key))} to "
                f"{format_stat(key, stats[other].get(key))}."
            ),
            "narration": (
                f"{leader} put {format_stat(key, stats[leader].get(key))} {stat_label(key).lower()} "
                f"on the tape, the number that defined the night."
            ),
            "stat_keys": [key],
            "hero_number": n,
            "hero_label": stat_label(key).upper(),
            "hero_team": leader,
        }

    if viz_id == "match_radar":
        return {
            "kicker": "PROFILE",
            "title": "THE SHAPE OF THE MATCH",
            "subtitle": i18n.t("sub_radar"),
            "insight": f"{bundle.home} {home['shots']} shots, {bundle.away} {away['shots']}. The radar is the rest.",
            "narration": (
                f"Six axes, two teams. {bundle.home} {home['shots']} shots to {away['shots']}, "
                f"{home['pass_share_pct']:.0f} percent of the passes against {away['pass_share_pct']:.0f}."
            ),
        }

    if viz_id == "touch_heatmap":
        zones = audit.get("zone_control") or []
        home_t = sum(int(z.get("home_touches") or 0) for z in zones)
        away_t = sum(int(z.get("away_touches") or 0) for z in zones)
        leader = bundle.home if home_t >= away_t else bundle.away
        return {
            "kicker": "HEAT",
            "title": f"{max(home_t, away_t)} TOUCHES. THE PIN.",
            "subtitle": i18n.t("sub_heatmap"),
            "insight": f"{home_t} touches against {away_t}. The colour is the pin.",
            "narration": f"{leader} left the hotter footprint, {home_t} touches against {away_t}.",
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
            "kicker": "TILT",
            "title": f"{int(pct)}% TILT IN THE {peak['minute_block'] if peak else 'MATCH'}",
            "subtitle": i18n.t("sub_tilt"),
            "insight": f"{leader} owned the dangerous third in that window.",
            "narration": f"{leader} hit {int(pct)} percent field tilt in the {peak['minute_block'] if peak else 'match'} window.",
        }

    if viz_id == "conversion_gauges":
        return {
            "kicker": "CONVERSION",
            "title": f"{home['shots_on_target']}-{away['shots_on_target']} ON TARGET",
            "subtitle": i18n.t("sub_gauges"),
            "insight": f"{home['shots_on_target']} on target against {away['shots_on_target']}. Conversion did the rest.",
            "narration": (
                f"{bundle.home} {home['shots_on_target']} on target to {away['shots_on_target']}. "
                f"The finishing was not the same."
            ),
        }

    if viz_id == "chance_funnel":
        leader = dominant_team(bundle, audit, "pass_share_pct") or bundle.home
        leader_stats = stats[leader]
        return {
            "kicker": "FUNNEL",
            "title": f"{int(leader_stats['pass_share_pct'])}% THEN THE DROP",
            "subtitle": i18n.t("sub_funnel"),
            "insight": f"{leader} had the ball. The funnel shows where it died.",
            "narration": (
                f"{leader} played {leader_stats['pass_share_pct']:.0f} percent of the passes "
                f"and put {leader_stats['shots_on_target']} on target."
            ),
        }

    if viz_id == "keeper_frame":
        if away["shots_on_target"] >= home["shots_on_target"]:
            keeper_side, faced = bundle.home, away["shots_on_target"]
        else:
            keeper_side, faced = bundle.away, home["shots_on_target"]
        return {
            "kicker": "THE WALL",
            "title": f"{stats[keeper_side]['saves']} SAVES FOR {keeper_side.upper()}",
            "subtitle": i18n.t("sub_keeper_frame"),
            "insight": f"{faced} shots at the frame. {stats[keeper_side]['saves']} of them stopped.",
            "narration": f"{keeper_side} faced {faced} on target and saved {stats[keeper_side]['saves']}.",
        }

    if viz_id == "xg_race":
        return {
            "kicker": "xG RACE",
            "title": "THE RACE THE SCORE IGNORED",
            "subtitle": i18n.t("sub_race"),
            "insight": f"xG {home.get('xg', 0)} against {away.get('xg', 0)}. The board ignored the race.",
            "narration": (
                f"Expected goals ran {home.get('xg', 0)} to {away.get('xg', 0)}. "
                f"The scoreline did not follow the race."
            ),
        }

    if viz_id == "time_zones":
        return {
            "kicker": "THREE SLICES",
            "title": "THE MAP CHANGED",
            "subtitle": i18n.t("sub_zones_time"),
            "insight": "Three windows. The colour says who owned each one.",
            "narration": "Territory in three slices: the first half hour, the middle, and the close.",
        }

    if viz_id == "player_spike":
        spike = (audit.get("player_leaders") or {}).get("spike") or {}
        surname = spike.get("surname") or spike.get("player") or "A player"
        count = int(spike.get("count") or 0)
        action = spike.get("action") or "actions"
        return {
            "kicker": "THE SPIKE",
            "title": f"{str(surname).upper()} HAD {count}",
            "subtitle": i18n.t("sub_player"),
            "insight": f"{spike.get('player') or surname} led {action} with {count}.",
            "narration": f"{spike.get('player') or surname} put {count} {action} on the tape, the spike of the night.",
        }

    return {
        "kicker": "EVENT DATA",
        "title": viz_id.replace("_", " ").upper(),
        "subtitle": "",
        "insight": "Built directly from the match event feed.",
        "narration": "Built directly from the match event feed.",
    }


def _block_minute(row: dict[str, Any]) -> int:
    """Leading real minute of a bucket label such as ``"66-70"``."""
    digits = re.findall(r"\d+", str(row.get("minute_block", "")))
    return int(digits[0]) if digits else 0


def _momentum_title(audit: dict[str, Any]) -> str:
    momentum = audit.get("momentum") or []
    if not momentum:
        return "PRESSURE THROUGH THE MATCH"
    peak = max(momentum, key=lambda row: abs(row["swing"]))
    period = str(peak.get("period", ""))
    if period.endswith("PeriodOfExtraTime"):
        return "EXTRA TIME BROKE THE DEADLOCK"
    minute = _block_minute(peak)
    if minute <= 20:
        return f"MINUTE {minute} SET THE TONE"
    if minute <= 45:
        return f"THE {minute}TH MINUTE SET THE TONE"
    if minute <= 70:
        return f"IT TURNED AFTER {minute}"
    return f"SETTLED IN THE {minute}TH"


def _zone_title(bundle: MatchBundle, audit: dict[str, Any]) -> str:
    zones = audit.get("zone_control") or []
    if not zones:
        return "WHERE THE MATCH WAS PLAYED"
    home_touches = sum(z["home_touches"] for z in zones)
    away_touches = sum(z["away_touches"] for z in zones)
    if home_touches > away_touches * 1.15:
        return f"{bundle.home.upper()} OWNED THE MAP"
    if away_touches > home_touches * 1.15:
        return f"{bundle.away.upper()} OWNED THE MAP"
    return "EVERY ZONE WAS CONTESTED"


def _closing_copy(bundle: MatchBundle, audit: dict[str, Any]) -> dict[str, str]:
    context = result_context(bundle, audit)
    score = bundle.score
    winner = context["winner"]
    loser = context["loser"]
    hook = build_hook(bundle, audit)
    if winner and loser:
        loser_shots = int(context["loser_stats"].get("shots") or 0)
        narration = f"{hook_team_name(loser)} had the shots. {winner} had the night."
        if hook["kind"] in {"volume_upset", "waste", "sterile_upset"}:
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
        insight = f"{winner} took the result. The numbers tell you how."
    elif score.total_goals == 0:
        total = sum(int(team.get("shots") or 0) for team in audit["team_stats"].values())
        narration = f"Goalless. {total} shots, and the net never moved."
        insight = "Nothing on the board. Plenty on the tape."
    else:
        narration = f"It finishes {score.display}. A point each."
        insight = "Level on the board. Split on the map."
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
    """At most one analysis card ends on a 'but'. The rest keep their own rhythm."""
    bodies = [scene for scene in scenes if not scene.get("hook")]
    if len(bodies) < 2:
        return scenes
    scene = bodies[0]
    nxt = bodies[1]
    if "but " in str(scene.get("narration") or "").lower():
        return scenes
    line = str(nxt.get("title") or "")
    if nxt.get("visualization") in _PACKAGE:
        line = build_bridge(bundle, audit, nxt["visualization"])["line"]
    next_bit = line.strip().rstrip(". ")
    proof = str(scene.get("narration") or "").strip()
    if proof:
        proof = re.split(r"(?<=[.!?])\s+", proof)[0].strip().rstrip(". ")
    if proof and next_bit and next_bit.lower() not in proof.lower():
        scene["narration"] = i18n.t("handoff_but", proof=proof, next=next_bit)
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
    # A single smash sits BETWEEN claim and punch. A second beat can cold-open.
    if len(beats) <= 1:
        pre_beats, mid_beats = [], beats[:1]
    else:
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
        add_stat("shots", "shots_on_target", "big_chances", "pass_share_pct", "saves",
                 "penalty_box_touches", "tackles_won", "dribbles_won")
    elif viz_id in {"goalmouth", "keeper_frame"}:
        add_stat("saves", "shots_on_target", "shots")
    elif viz_id in {"sterile_domination", "chance_funnel", "pass_network"}:
        add_stat("pass_share_pct", "final_third_passes", "box_entry_passes", "shots", "shots_on_target", "goals")
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
        if spike.get("surname"):
            surnames.append(str(spike["surname"]))
    elif viz_id == "xg_race":
        add_stat("xg", "xgot", "goals", "shots")
    elif viz_id == "conversion_gauges":
        add_stat("shots", "shots_on_target", "big_chances", "xg")
    elif viz_id == "momentum":
        peak = max(audit.get("momentum") or [{"swing": 0}], key=lambda row: abs(row.get("swing") or 0))
        numbers.append(_block_minute(peak))
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
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self.script_model = (
            script_model or os.getenv("GEMINI_SCRIPT_MODEL") or DEFAULT_SCRIPT_MODEL
        )
        self.required = required
        self.enabled = bool(enabled and self.api_key)
        self._client: Any = None
        self.last_error = ""
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
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        prompt = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        chosen = model or self.model
        delay = 2.0
        models_to_try = [chosen]
        if chosen != self.model:
            models_to_try.append(self.model)
        last_exc = ""
        for model_name in models_to_try:
            for attempt in range(1, GEMINI_ATTEMPTS + 1):
                try:
                    config: dict[str, Any] = {
                        "response_mime_type": "application/json",
                        "temperature": temperature,
                    }
                    if system:
                        config["system_instruction"] = system
                    response = self._get_client().models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    return json.loads(_extract_json(response.text or ""))
                except Exception as exc:  # noqa: BLE001 - the SDK raises many types
                    last_exc = f"{type(exc).__name__}: {exc}"
                    self.last_error = last_exc
                    lowered = str(exc).lower()
                    if any(token in lowered for token in ("not found", "not supported", "unknown model")):
                        break
                    retryable = any(
                        token in str(exc).upper()
                        for token in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE", "INTERNAL", "500")
                    )
                    if attempt == GEMINI_ATTEMPTS or not retryable:
                        break
                    sleep_for = delay + random.uniform(0, 0.8)
                    print(f"  [gemini] attempt {attempt} failed ({self.last_error[:70]}); retrying in {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                    delay *= 2
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
                "Do not pick more than two scenes from the same family "
                "(pitch, bars, time, territory, hero).",
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
        lo = max(14, min(18, words_per_scene))
        hi = max(18, min(28, words_per_scene + 6))
        language_rule = (
            "Write in plain English. No hashtags, no emoji, no 'in this video'. "
            "The hook already ran. Do not repeat the score until the closing card."
            if lang == "en"
            else (
                f"Write ALL kicker/title/subtitle/insight/narration fields in {lang_name} "
                f"(language code `{lang}`). Keep team names, player surnames and digits unchanged. "
                "Do not mix English into the copy except for those proper nouns and numbers. "
                "Never leave an English subtitle under a translated title — use an empty "
                "subtitle rather than leftover English. Do not mention the score until the "
                "closing card."
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
                "Never state a number that is not in the scene's fact_pack.numbers.",
                "Never say 'possession' unless match.data_health.has_vendor_possession is true.",
                "Never mention expected goals, xG or xGOT unless match.data_health.has_vendor_xg is true.",
                f"Narration for each analysis scene must be {lo} to {hi} words. Mix rhythms. "
                "Do not start every line with a team name. Do not tease the next card unless it earns it. "
                "Do not use the word 'but' more than once across the whole script.",
                "title is shown in heavy display type; keep it under 28 characters and do not end it with a full stop. "
                "When the fact pack has a number or a surname, the title must contain one.",
                "insight IS shown on screen as a two-line caption stamped late. Make it the sharpest sentence.",
                "Do not open any analysis scene with the scoreline. The score is the closing payoff only.",
                "Never write a score such as 2-1 on hook_claim, hook_punch, micro_hook or live_clip scenes.",
                "You MAY rephrase hook_claim and hook_punch using only numbers in their fact packs. "
                "Do not invent a new hook kind.",
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
        parsed = self._generate(
            payload, model=self.script_model, temperature=0.7, system=SYSTEM_PROMPT,
        )
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

    def rephrase_hook(self, hook: dict[str, Any], language: str = "en") -> dict[str, Any]:
        payload = {
            "task": "Rewrite the hook punch and claim lines. Keep every number from the pack.",
            "language": i18n.normalize_language(language),
            "kind": hook.get("kind"),
            "numbers": hook.get("numbers") or [],
            "never_say": hook.get("never_say") or [],
            "pool": hook.get("variants") or [],
            "current": {"lines": hook.get("lines"), "punch": hook.get("punch")},
            "response_schema": {"lines": ["claim line"], "punch": "punch line"},
        }
        parsed = self._generate(
            payload, model=self.script_model, temperature=0.8, system=SYSTEM_PROMPT,
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
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start: end + 1]
    return text


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
            if field == "subtitle" and i18n.get_language() != "en" and i18n.looks_english(value):
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
