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
from . import i18n

DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_ATTEMPTS = 4


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
    return f"{number:.0f}"


def pick_stat_rows(bundle: MatchBundle, audit: dict[str, Any], limit: int = 5) -> list[str]:
    """Rank stat keys by how much they separate the two teams for this match."""
    stats = audit["team_stats"]
    home = stats.get(bundle.home, {})
    away = stats.get(bundle.away, {})

    ranked: list[tuple[float, str]] = []
    for key in STAT_CATALOG:
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
    allow_xg = health.get("has_vendor_xg") and health.get("has_vendor_xgot")
    problems: list[str] = []
    for scene in scenes:
        for field in ("kicker", "title", "subtitle", "insight", "narration"):
            text = clean_text(scene.get(field))
            if not text:
                continue
            for pattern, reason in _FORBIDDEN:
                if allow_xg and "expected" in reason:
                    continue
                if re.search(pattern, text, flags=re.IGNORECASE):
                    problems.append(f"{scene.get('id', '?')}.{field} uses {reason}: {text[:70]!r}")
    return problems


# ---------------------------------------------------------------------------
# visualization candidates
# ---------------------------------------------------------------------------

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
            "score": 84 + min(14, score.total_goals * 3) + (6 if score.margin <= 1 else 0),
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
            "available": max(home.get("pass_attempts", 0), away.get("pass_attempts", 0)) >= 150,
            "score": 44 + pass_gap,
            "reason": "Average positions and the strongest passing links.",
            "best_for": "Build-up identity and control stories.",
            "avoid_when": "Goals and shots explain the result more directly.",
        },
        {
            "id": "sterile_domination",
            "title": "Control vs Threat",
            "available": max(home.get("pass_share_pct", 0), away.get("pass_share_pct", 0)) >= 56,
            "score": 54 + pass_gap,
            "reason": "Tests whether the team with the ball turned it into shots.",
            "best_for": "One-sided pass share that did not become chances.",
            "avoid_when": "The pass-share edge is small.",
        },
    ]
    for candidate in candidates:
        candidate["score"] = round(float(candidate["score"]), 1)
    return candidates


def select_visualizations(
    bundle: MatchBundle,
    audit: dict[str, Any],
    count: int,
    gemini: "Gemini | None" = None,
    instruction: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (selected, all_candidates)."""
    candidates = visualization_candidates(bundle, audit)
    available = {c["id"]: c for c in candidates if c["available"]}

    chosen_ids: list[str] = []
    if gemini is not None and gemini.enabled:
        chosen_ids = gemini.choose_visualizations(bundle, audit, candidates, count, instruction)
        chosen_ids = [vid for vid in chosen_ids if vid in available]

    if not chosen_ids:
        ranked = sorted(available.values(), key=lambda c: c["score"], reverse=True)
        chosen_ids = [c["id"] for c in ranked[:count]]

    seen: set[str] = set()
    selected = []
    for vid in chosen_ids:
        if vid in available and vid not in seen:
            seen.add(vid)
            selected.append(available[vid])
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


def _headline_copy(bundle: MatchBundle, audit: dict[str, Any]) -> tuple[str, str]:
    """Return (title, insight) for the opening card."""
    context = result_context(bundle, audit)
    score = bundle.score
    winner = context["winner"]
    stats = audit["team_stats"]

    if winner:
        winner_stats = context["winner_stats"]
        if score.after_shootout:
            return f"{winner.upper()} SURVIVE THE SHOOTOUT", "Level after 120 minutes, settled from the spot."
        if score.after_extra_time:
            return f"{winner.upper()} NEEDED EXTRA TIME", "Ninety minutes could not separate them."
        if score.margin >= 3:
            return f"{winner.upper()} RAN RIOT", f"{score.margin} goals of daylight by the final whistle."
        if score.total_goals >= 4:
            return f"{score.total_goals} GOALS, {winner.upper()} TAKE IT", "A shootout of a match, decided in open play."
        return (
            f"{winner.upper()} FOUND A WAY",
            f"{winner_stats.get('shots_on_target', 0)} shots on target turned into the win.",
        )

    if score.total_goals == 0:
        total_shots = sum(team.get("shots", 0) for team in stats.values())
        return "NOBODY BLINKED", f"{total_shots} attempts and not one of them counted."
    return f"HONOURS EVEN AT {score.display}", "Two teams, two answers, one point each."


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
                f"{surname(first)} opened it in the {_ordinal(first['minute'])} minute. "
                f"{len(timeline)} goals later it finished {last['score_after']}, "
                f"{surname(last)} having the final say in the {_ordinal(last['minute'])}."
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
            "title": f"{leader.upper()} KEPT TESTING THE KEEPER",
            "subtitle": "Every attempt, by outcome",
            "insight": (
                f"{home['shots']} against {away['shots']} shots, "
                f"{home['shots_on_target']} against {away['shots_on_target']} on target."
            ),
            "narration": (
                f"{bundle.home} took {home['shots']} shots and put {home['shots_on_target']} on target. "
                f"{bundle.away} took {away['shots']} and hit the target {away['shots_on_target']} times. "
                f"Blocked efforts are marked separately, because a block is not a save."
            ),
        }

    if viz_id == "momentum":
        momentum = audit["momentum"]
        peak = max(momentum, key=lambda row: abs(row["swing"])) if momentum else None
        leader = bundle.home if peak and peak["swing"] > 0 else bundle.away
        return {
            "kicker": "PRESSURE",
            "title": _momentum_title(audit),
            "subtitle": f"{bundle.home} above the line, {bundle.away} below",
            "insight": (
                f"The heaviest spell fell to {leader} between minutes {peak['minute_block']}."
                if peak else "Pressure stayed level throughout."
            ),
            "narration": (
                f"This is attacking pressure in five minute blocks, built from final-third passes, "
                f"box entries, shots and goals. "
                + (f"The biggest surge belongs to {leader} in the {peak['minute_block']} minute window."
                   if peak else "")
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
            "subtitle": "Touch volume across eighteen zones",
            "insight": f"{leader} touched the ball in more of the dangerous grid than anyone else.",
            "narration": (
                f"Every touch, dropped into eighteen zones. The colour of each cell is whoever "
                f"had more of the ball there. {leader} controlled the majority of the map, "
                f"{home_touches} touches against {away_touches}."
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
                    f"One goal, traced backwards. {chain['team']} strung {chain['passes']} passes together "
                    f"across {chain['pass_distance_m']:.0f} metres before {chain['scorer']} finished it "
                    f"in the {_ordinal(int(chain['minute'] or 0))} minute."
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
            "subtitle": "Where on-target shots crossed the line",
            "insight": f"{faced} shots at the frame, {keeper_stats['saves']} of them saved.",
            "narration": (
                f"This is the goal frame, split into the six zones a keeper has to protect. "
                f"{keeper_side} faced {faced} shots on target and saved "
                f"{keeper_stats['saves']} of them. The rest are marked as goals."
            ),
        }

    if viz_id == "pass_network":
        leader = dominant_team(bundle, audit, "pass_attempts") or bundle.home
        leader_stats = stats[leader]
        return {
            "kicker": "PASS NETWORK",
            "title": f"HOW {leader.upper()} MOVED THE BALL",
            "subtitle": "Average positions and strongest links",
            "insight": f"{leader_stats['passes_completed']} completed passes at {leader_stats['pass_accuracy_pct']:.0f}% accuracy.",
            "narration": (
                f"{leader} completed {leader_stats['passes_completed']} passes. Each circle sits at a "
                f"player's average position and grows with their involvement; the thick lines are the "
                f"combinations they went back to most."
            ),
        }

    if viz_id == "sterile_domination":
        leader = dominant_team(bundle, audit, "pass_share_pct") or bundle.home
        leader_stats = stats[leader]
        other = away if leader == bundle.home else home
        return {
            "kicker": "CONTROL VS THREAT",
            "title": f"{leader.upper()} HAD THE BALL",
            "subtitle": "Pass share against what it produced",
            "insight": (
                f"{leader_stats['pass_share_pct']:.0f}% of the passing, "
                f"{leader_stats['shots_on_target']} shots on target to show for it."
            ),
            "narration": (
                f"{leader} played {leader_stats['pass_share_pct']:.0f} percent of the passes in this match. "
                f"The question is what it bought: {leader_stats['final_third_passes']} final-third passes, "
                f"{leader_stats['penalty_box_touches']} touches in the box, and "
                f"{leader_stats['shots_on_target']} shots on target against {other['shots_on_target']}."
            ),
        }

    return {
        "kicker": "EVENT DATA",
        "title": viz_id.replace("_", " ").upper(),
        "subtitle": "",
        "insight": "",
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
        return "THEY CAME OUT SWINGING"
    if minute <= 45:
        return "THE FIRST HALF SET THE TONE"
    if minute <= 70:
        return "THE GAME TURNED AFTER THE BREAK"
    return "IT WAS DECIDED LATE"


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
    if winner:
        winner_stats = context["winner_stats"]
        narration = (
            f"{winner} win it {score.display}"
            + (f" {score.qualifier.lower()}" if score.qualifier else "")
            + f". {winner_stats.get('shots_on_target', 0)} shots on target, "
            f"{winner_stats.get('big_chances', 0)} big chances, and a result that matches the map."
        )
        insight = f"{winner} took the result and the numbers."
    elif score.total_goals == 0:
        narration = f"Goalless, but not chanceless. The map shows exactly where it stalled."
        insight = "Nothing separated them, on the board or on the pitch."
    else:
        narration = f"It finishes {score.display}. Two teams that could not be separated."
        insight = "A point each, and an even map to go with it."
    return {
        "kicker": i18n.t("full_time") if not score.qualifier else score.qualifier,
        "title": f"{bundle.home.upper()} {score.display} {bundle.away.upper()}",
        "subtitle": "",
        "insight": insight,
        "narration": narration,
    }


def build_storyboard(
    bundle: MatchBundle,
    audit: dict[str, Any],
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The deterministic script. Every string here comes from the audit."""
    score = bundle.score
    title, title_insight = _headline_copy(bundle, audit)
    stats_title, stats_insight = _stats_copy(bundle, audit)
    stat_keys = pick_stat_rows(bundle, audit)

    scenes: list[dict[str, Any]] = [
        {
            "id": "title",
            "visualization": "title",
            "kicker": bundle.competition_line().upper() or i18n.t("match_recap"),
            "title": title,
            "subtitle": "",
            "insight": title_insight,
            "narration": (
                f"{bundle.home} {score.home}, {bundle.away} {score.away}"
                + (f", {score.qualifier.lower()}" if score.qualifier else "")
                + f". {title_insight}"
            ),
        },
        {
            "id": "standard_stats",
            "visualization": "standard_stats",
            "kicker": i18n.t("the_baseline"),
            "title": stats_title,
            "subtitle": "",
            "insight": stats_insight,
            "stat_keys": stat_keys,
            "narration": (
                f"Start with the baseline. {stats_insight} "
                f"Pass share was {audit['team_stats'][bundle.home]['pass_share_pct']:.0f} to "
                f"{audit['team_stats'][bundle.away]['pass_share_pct']:.0f}."
            ),
        },
    ]

    for item in selected:
        copy = _visual_copy(bundle, audit, item["id"])
        scenes.append({"id": item["id"], "visualization": item["id"], **copy})

    closing = _closing_copy(bundle, audit)
    scenes.append({"id": "close", "visualization": "close", "stat_keys": stat_keys[:4], **closing})
    return scenes


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class Gemini:
    """Thin, retrying wrapper around google-genai.

    Every call degrades to ``None`` rather than raising, unless the caller asked
    for Gemini to be mandatory.
    """

    def __init__(self, enabled: bool = True, required: bool = False, model: str | None = None) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
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

    def _generate(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        prompt = json.dumps(payload, ensure_ascii=False)
        delay = 2.0
        for attempt in range(1, GEMINI_ATTEMPTS + 1):
            try:
                response = self._get_client().models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config={"response_mime_type": "application/json", "temperature": 0.85},
                )
                return json.loads(_extract_json(response.text or ""))
            except Exception as exc:  # noqa: BLE001 - the SDK raises many types
                self.last_error = f"{type(exc).__name__}: {exc}"
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
    ) -> list[str]:
        payload = {
            "task": (
                "You are the director of a short-form football analytics video. Choose the "
                f"{count} visualizations that best explain THIS match."
            ),
            "rules": [
                "Only choose candidates where available is true.",
                "A candidate can be available and still be a bad fit; use best_for and avoid_when.",
                "Prefer a set that tells one coherent story rather than three versions of the same point.",
                f"Return exactly {count} ids.",
            ],
            "editor_note": instruction,
            "match": _brief(bundle, audit),
            "candidates": candidates,
            "response_schema": {"selected": ["visualization_id"], "angle": "one sentence"},
        }
        parsed = self._generate(payload)
        if not parsed:
            return []
        raw = parsed.get("selected") or []
        ids = []
        for item in raw:
            value = item.get("id") if isinstance(item, dict) else item
            if value:
                ids.append(str(value))
        return ids

    def write_script(
        self,
        bundle: MatchBundle,
        audit: dict[str, Any],
        scenes: list[dict[str, Any]],
        words_per_scene: int,
        instruction: str,
        language: str = "en",
    ) -> dict[str, dict[str, str]]:
        lang = i18n.normalize_language(language)
        lang_name = i18n.language_name(lang)
        language_rule = (
            "Write in plain English. No hashtags, no emoji, no 'in this video'."
            if lang == "en"
            else (
                f"Write ALL kicker/title/subtitle/insight/narration fields in {lang_name} "
                f"(language code `{lang}`). Keep team names, player surnames and digits unchanged. "
                "Do not mix English into the copy except for those proper nouns and numbers."
            )
        )
        payload = {
            "task": (
                "Rewrite the on-screen copy and narration for a football analytics short. "
                "Keep the analysis sharp and specific; this is for viewers who want to know WHY "
                "the match finished the way it did."
            ),
            "rules": [
                "Never state a number that is not in match.stats, match.timeline or the scene's own data.",
                "Never say 'possession'. The export measures pass share, and they are not the same thing.",
                "Never mention expected goals, xG or xGOT. That data does not exist here.",
                f"Narration for each scene must be {max(12, words_per_scene - 8)} to {words_per_scene + 8} words.",
                "title is shown in heavy display type; keep it under 34 characters and do not end it with a full stop.",
                "kicker is a tiny label above the title; under 22 characters.",
                "insight is one short sentence shown at the bottom of the frame; under 70 characters.",
                "Every scene needs a DIFFERENT insight. Do not repeat a line across scenes.",
                language_rule,
            ],
            "language": lang,
            "editor_note": instruction,
            "match": _brief(bundle, audit),
            "scenes": [
                {
                    "id": scene["id"],
                    "visualization": scene["visualization"],
                    "what_it_shows": scene.get("subtitle") or scene["visualization"],
                    "current_title": scene.get("title", ""),
                    "current_narration": scene.get("narration", ""),
                }
                for scene in scenes
            ],
            "response_schema": {
                "scenes": [
                    {"id": "scene id", "kicker": "", "title": "", "subtitle": "", "insight": "", "narration": ""}
                ]
            },
        }
        parsed = self._generate(payload)
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
            ],
            "response_schema": {
                "scenes": [
                    {"id": "scene id", "kicker": "", "title": "", "subtitle": "", "insight": "", "narration": ""}
                ]
            },
        }
        parsed = self._generate(payload)
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


def _brief(bundle: MatchBundle, audit: dict[str, Any]) -> dict[str, Any]:
    """The compact, numbers-only view of the match given to the model."""
    momentum = sorted(audit["momentum"], key=lambda row: abs(row["swing"]), reverse=True)[:4]
    return {
        "home": bundle.home,
        "away": bundle.away,
        "score": audit["match"]["score_display"],
        "score_qualifier": audit["match"]["score_qualifier"],
        "competition": bundle.competition_line(),
        "facts": audit["facts"],
        "stats": audit["team_stats"],
        "timeline": audit["goal_timeline"],
        "biggest_pressure_windows": momentum,
        "unavailable_metrics": audit["data_health"]["blocked_claims"],
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


def apply_script(
    scenes: list[dict[str, Any]],
    overrides: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Merge Gemini wording over the deterministic scenes.

    Only these five text fields can be replaced. Visualization ids, stat keys
    and every number stay exactly as the audit produced them.
    """
    merged = []
    for scene in scenes:
        override = overrides.get(scene["id"], {})
        updated = dict(scene)
        for field in ("kicker", "title", "subtitle", "insight", "narration"):
            value = override.get(field, "").strip()
            if value:
                updated[field] = value
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
