"""Match-specific hook engine.

Every opening is built from audited counts. Phrase pools and a hashed pick
make two similar upsets look different; Gemini may only rephrase inside the
fact pack. The score stays off these cards.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from . import i18n
from .audit import best_goal_chain, result_context
from .data import MatchBundle, clean_text

_SCORELINE = re.compile(r"\b\d+\s*[-–:/]\s*\d+\b")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")
_ARTICLES = {"fc", "cf", "afc", "the", "de", "cd", "sc", "ac"}

BRIDGE_SECONDS = 0.45
CLAIM_SECONDS = 0.85
PUNCH_SECONDS = 0.70

# Stronger kinds first. one_moment is the last resort for a decisive win.
KIND_PRIORITY = (
    "own_goal",
    "penalty",
    "red_or_card",
    "blowout",
    "comeback",
    "stoppage",
    "xg_robbery",
    "keeper_wall",
    "waste",
    "chain_shock",
    "press_pin",
    "volume_upset",
    "sterile_upset",
    "late_turn",
    "one_moment",
    "stalemate",
    "level",
)

NUMBER_SLAM_KINDS = {
    "volume_upset", "waste", "chain_shock", "xg_robbery",
    "keeper_wall", "press_pin", "stalemate",
}
SPLIT_SMASH_KINDS = {"sterile_upset", "volume_upset", "waste"}
# Remaining kinds use stamp (team-color flash).

PUNCH_POOLS = {
    "lost": [
        "hook_punch_lost_0", "hook_punch_lost_1", "hook_punch_lost_2",
        "hook_punch_lost_3", "hook_punch_lost_4", "hook_punch_lost_5",
        "hook_punch_lost_6", "hook_punch_lost_7",
    ],
    "over": [
        "hook_punch_over_0", "hook_punch_over_1", "hook_punch_over_2",
        "hook_punch_over_3", "hook_punch_over_4", "hook_punch_over_5",
    ],
    "level": [
        "hook_punch_level_0", "hook_punch_level_1", "hook_punch_level_2",
        "hook_punch_level_3", "hook_punch_level_4",
    ],
    "blank": [
        "hook_punch_blank_0", "hook_punch_blank_1", "hook_punch_blank_2",
        "hook_punch_blank_3",
    ],
}

CLAIM_POOLS = {
    "shots": ["hook_claim_shots_0", "hook_claim_shots_1", "hook_claim_shots_2"],
    "corners": ["hook_claim_corners_0", "hook_claim_corners_1"],
    "blocked": ["hook_claim_blocked_0", "hook_claim_blocked_1"],
    "chances": ["hook_claim_chances_0", "hook_claim_chances_1", "hook_claim_chances_2"],
    "box": ["hook_claim_box_0", "hook_claim_box_1"],
    "pressure": ["hook_claim_pressure_0", "hook_claim_pressure_1"],
    "ball": ["hook_claim_ball_0", "hook_claim_ball_1", "hook_claim_ball_2"],
    "not_chances": ["hook_claim_not_chances_0", "hook_claim_not_chances_1"],
    "late": ["hook_claim_late_0", "hook_claim_late_1", "hook_claim_late_2"],
    "one": ["hook_claim_one_0", "hook_claim_one_1", "hook_claim_one_2"],
    "shots_total": ["hook_claim_nshots_0", "hook_claim_nshots_1"],
    "comeback": ["hook_claim_comeback_0", "hook_claim_comeback_1", "hook_claim_comeback_2"],
    "stoppage": ["hook_claim_stoppage_0", "hook_claim_stoppage_1", "hook_claim_stoppage_2"],
    "blowout": ["hook_claim_blowout_0", "hook_claim_blowout_1", "hook_claim_blowout_2"],
    "xg": ["hook_claim_xg_0", "hook_claim_xg_1"],
    "keeper": ["hook_claim_keeper_0", "hook_claim_keeper_1", "hook_claim_keeper_2"],
    "waste": ["hook_claim_waste_0", "hook_claim_waste_1"],
    "chain": ["hook_claim_chain_0", "hook_claim_chain_1", "hook_claim_chain_2"],
    "pin": ["hook_claim_pin_0", "hook_claim_pin_1"],
    "red": ["hook_claim_red_0", "hook_claim_red_1"],
    "own_goal": ["hook_claim_og_0", "hook_claim_og_1"],
    "penalty": ["hook_claim_pen_0", "hook_claim_pen_1"],
    "level": ["hook_claim_level_0", "hook_claim_level_1"],
}

BRIDGE_POOLS = {
    "zone_control": ["bridge_zone_0", "bridge_zone_1", "bridge_zone_2", "bridge_zone_3"],
    "touch_heatmap": ["bridge_heat_0", "bridge_heat_1", "bridge_heat_2"],
    "sterile_domination": ["bridge_ball_0", "bridge_ball_1", "bridge_ball_2"],
    "chance_funnel": ["bridge_funnel_0", "bridge_funnel_1", "bridge_funnel_2"],
    "goalmouth": ["bridge_keeper_0", "bridge_keeper_1", "bridge_keeper_2"],
    "keeper_frame": ["bridge_frame_0", "bridge_frame_1", "bridge_frame_2"],
    "goal_timeline": ["bridge_board_0", "bridge_board_1", "bridge_board_2"],
    "shot_map": ["bridge_shots_0", "bridge_shots_1", "bridge_shots_2", "bridge_shots_3"],
    "momentum": ["bridge_pressure_0", "bridge_pressure_1", "bridge_pressure_2"],
    "field_tilt_wave": ["bridge_tilt_0", "bridge_tilt_1", "bridge_tilt_2"],
    "goal_chain": ["bridge_chain_0", "bridge_chain_1", "bridge_chain_2"],
    "pass_network": ["bridge_pass_0", "bridge_pass_1", "bridge_pass_2"],
    "match_radar": ["bridge_radar_0", "bridge_radar_1", "bridge_radar_2"],
    "stat_slam": ["bridge_slam_0", "bridge_slam_1", "bridge_slam_2"],
    "conversion_gauges": ["bridge_gauge_0", "bridge_gauge_1", "bridge_gauge_2"],
    "xg_race": ["bridge_race_0", "bridge_race_1"],
    "time_zones": ["bridge_halves_0", "bridge_halves_1", "bridge_halves_2"],
    "player_spike": ["bridge_player_0", "bridge_player_1", "bridge_player_2"],
    "standard_stats": ["bridge_numbers_0", "bridge_numbers_1"],
    "close": ["bridge_close_0", "bridge_close_1", "bridge_close_2", "bridge_close_3"],
}


def hook_team_name(name: str) -> str:
    """Short enough to scream in 72pt. 'Aston Villa' becomes VILLA."""
    raw = (name or "").strip()
    if len(raw) <= 10:
        return raw.upper()
    parts = [part for part in re.split(r"\s+", raw) if part.lower() not in _ARTICLES]
    return (parts[-1] if parts else raw).upper()


def match_seed(bundle: MatchBundle) -> str:
    return Path(str(bundle.match_dir)).name


def pick_index(seed: str, count: int) -> int:
    if count <= 1:
        return 0
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest, 16) % count


def pool_line(keys: list[str], seed: str, **kwargs: Any) -> str:
    key = keys[pick_index(seed, len(keys))]
    return i18n.t(key, **kwargs)


def collect_numbers(*values: Any) -> list[Any]:
    numbers: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            token = str(value)
            if token not in seen:
                seen.add(token)
                numbers.append(value)
            continue
        for match in _DIGITS.findall(str(value)):
            if match not in seen:
                seen.add(match)
                numbers.append(float(match) if "." in match else int(match))
    return numbers


def allowed_number_tokens(numbers: list[Any]) -> set[str]:
    tokens: set[str] = set()
    for value in numbers:
        tokens.add(str(value))
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        tokens.add(str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip("."))
        tokens.add(f"{number:.0f}")
        tokens.add(f"{number:.1f}")
        tokens.add(f"{number:.2f}")
    return tokens


def extra_numbers(text: str, allowed: set[str]) -> set[str]:
    found = set()
    for match in _DIGITS.findall(text or ""):
        token = match.lstrip("0") or "0"
        if match not in allowed and token not in allowed:
            # Ordinals like 81st still extract 81.
            found.add(match)
    return found


def score_variants(bundle: MatchBundle) -> list[str]:
    score = bundle.score
    return [
        score.display,
        f"{score.home}-{score.away}",
        f"{score.home}–{score.away}",
        f"{score.home}:{score.away}",
        f"{score.away}-{score.home}",
    ]


def _pressure_totals(audit: dict[str, Any]) -> tuple[float, float]:
    rows = audit.get("momentum") or []
    return (
        sum(float(row.get("home_pressure") or 0) for row in rows),
        sum(float(row.get("away_pressure") or 0) for row in rows),
    )


def _winner_trailed(audit: dict[str, Any], winner: str) -> bool:
    home_goals = away_goals = 0
    trailed = False
    for goal in audit.get("goal_timeline") or []:
        before_home, before_away = home_goals, away_goals
        if goal.get("h_a") == "h":
            home_goals += 1
        else:
            away_goals += 1
        if winner == goal.get("team"):
            if goal.get("h_a") == "h" and before_home < before_away:
                trailed = True
            if goal.get("h_a") == "a" and before_away < before_home:
                trailed = True
    return trailed


def _tilt_peak(audit: dict[str, Any]) -> float:
    rows = audit.get("field_tilt") or []
    if not rows:
        return 50.0
    return max(
        max(float(row.get("home_tilt_pct") or 50), float(row.get("away_tilt_pct") or 50))
        for row in rows
    )


def qualifying_kinds(bundle: MatchBundle, audit: dict[str, Any]) -> list[str]:
    """Every kind the data actually supports, strongest first."""
    context = result_context(bundle, audit)
    stats = audit["team_stats"]
    home_stats = stats.get(bundle.home, {})
    away_stats = stats.get(bundle.away, {})
    winner = context["winner"]
    loser = context["loser"]
    health = audit.get("data_health") or {}
    timeline = audit.get("goal_timeline") or []
    last = timeline[-1] if timeline else None
    found: list[str] = []

    if not winner:
        total_shots = int(home_stats.get("shots") or 0) + int(away_stats.get("shots") or 0)
        if context["total_goals"] == 0 and total_shots:
            found.append("stalemate")
        else:
            found.append("level")
        return found

    loser_stats = context["loser_stats"]
    winner_stats = context["winner_stats"]

    if any(goal.get("own_goal") for goal in timeline):
        found.append("own_goal")
    if last and last.get("penalty") and last.get("team") == winner:
        found.append("penalty")
    reds = int(home_stats.get("red_cards") or 0) + int(away_stats.get("red_cards") or 0)
    if reds:
        found.append("red_or_card")
    if context["margin"] >= 3:
        found.append("blowout")
    if _winner_trailed(audit, winner):
        found.append("comeback")
    if last and last.get("team") == winner and int(last.get("minute") or 0) >= 85:
        found.append("stoppage")

    if health.get("has_vendor_xg"):
        loser_xg = float(loser_stats.get("xg") or 0)
        winner_xg = float(winner_stats.get("xg") or 0)
        if loser_xg > winner_xg + 0.15:
            found.append("xg_robbery")

    loser_on = int(loser_stats.get("shots_on_target") or 0)
    winner_on = int(winner_stats.get("shots_on_target") or 0)
    winner_saves = int(winner_stats.get("saves") or 0)
    if loser_on >= winner_on + 2 and winner_saves >= 4:
        found.append("keeper_wall")

    if (
        int(loser_stats.get("shots") or 0) > int(winner_stats.get("shots") or 0)
        and int(loser_stats.get("big_chances") or 0) >= int(winner_stats.get("big_chances") or 0)
        and int(loser_stats.get("shots") or 0) >= 8
    ):
        found.append("waste")

    chain = best_goal_chain(audit)
    if chain and (int(chain.get("passes") or 0) >= 8 or float(chain.get("duration_seconds") or 0) >= 20):
        found.append("chain_shock")

    if _tilt_peak(audit) >= 68:
        found.append("press_pin")

    volume_edges = 0
    for key in ("shots", "corners", "shots_blocked", "big_chances", "penalty_box_touches"):
        if int(loser_stats.get(key) or 0) > int(winner_stats.get(key) or 0):
            volume_edges += 1
    home_p, away_p = _pressure_totals(audit)
    if loser == bundle.home and home_p > away_p * 1.05:
        volume_edges += 1
    elif loser == bundle.away and away_p > home_p * 1.05:
        volume_edges += 1
    if volume_edges >= 2:
        found.append("volume_upset")

    loser_shots = int(loser_stats.get("shots") or 0)
    winner_share = float(winner_stats.get("pass_share_pct") or 0)
    loser_share = float(loser_stats.get("pass_share_pct") or 0)
    if loser_shots > int(winner_stats.get("shots") or 0) and winner_share > loser_share + 4:
        found.append("sterile_upset")

    if last and last.get("team") == winner and int(last.get("minute") or 0) >= 55:
        found.append("late_turn")

    found.append("one_moment")
    ordered = [kind for kind in KIND_PRIORITY if kind in found]
    return ordered or ["one_moment"]


def visual_language_for(kind: str, seed: str) -> str:
    options = []
    if kind in NUMBER_SLAM_KINDS:
        options.append("number_slam")
    if kind in SPLIT_SMASH_KINDS:
        options.append("split_smash")
    options.append("stamp")
    return options[pick_index(f"{seed}:lang:{kind}", len(options))]


def _volume_edges(bundle: MatchBundle, context: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    loser_stats = context["loser_stats"]
    winner_stats = context["winner_stats"]
    mapping = [
        ("shots", "shots", "SHOTS"),
        ("corners", "corners", "CORNERS"),
        ("shots_blocked", "blocked", "BLOCKED"),
        ("big_chances", "chances", "BIG CHANCES"),
        ("penalty_box_touches", "box", "BOX TOUCHES"),
    ]
    edges = []
    for key, pool, label in mapping:
        loser_n = int(loser_stats.get(key) or 0)
        winner_n = int(winner_stats.get(key) or 0)
        if loser_n > winner_n:
            edges.append({"key": key, "pool": pool, "label": label, "n": loser_n, "other": winner_n})
    home_p, away_p = _pressure_totals(audit)
    loser = context["loser"]
    if loser == bundle.home and home_p > away_p * 1.05:
        edges.append({"key": "pressure", "pool": "pressure", "label": "PRESSURE", "n": round(home_p, 1), "other": round(away_p, 1)})
    elif loser == bundle.away and away_p > home_p * 1.05:
        edges.append({"key": "pressure", "pool": "pressure", "label": "PRESSURE", "n": round(away_p, 1), "other": round(home_p, 1)})
    return edges


def build_hook(bundle: MatchBundle, audit: dict[str, Any], *, variant: int = 0) -> dict[str, Any]:
    """Contradiction open: claim card, punch card, fact pack, visual language.

    ``variant`` 0 is the hashed default. 1 and 2 (and further salts) walk the
    phrase pools so the A/B picker can score alternates without a new match.
    """
    context = result_context(bundle, audit)
    stats = audit["team_stats"]
    home_stats = stats.get(bundle.home, {})
    away_stats = stats.get(bundle.away, {})
    qualified = qualifying_kinds(bundle, audit)
    kind = qualified[0]
    seed = match_seed(bundle)
    variant = int(variant or 0)
    if variant:
        seed = f"{seed}:ab{variant}"
    winner = context["winner"]
    loser = context["loser"]
    matchup = f"{bundle.home} — {bundle.away}"
    language = visual_language_for(kind, seed)
    never_say = score_variants(bundle)
    timeline = audit.get("goal_timeline") or []
    last = timeline[-1] if timeline else None
    chain = best_goal_chain(audit)

    def pack(
        lines: list[str],
        punch: str,
        numbers: list[Any],
        *,
        hero_number: Any = None,
        hero_label: str = "",
        split: dict[str, Any] | None = None,
        team: str = "",
    ) -> dict[str, Any]:
        clean_lines = [line for line in lines if line][:3]
        if not clean_lines:
            clean_lines = [matchup]
        return {
            "kind": kind,
            "qualified": qualified,
            "matchup": matchup,
            "lines": clean_lines,
            "punch": punch,
            "narration_claim": " ".join(clean_lines),
            "narration_punch": punch.rstrip("."),
            "seconds_claim": CLAIM_SECONDS,
            "seconds_punch": PUNCH_SECONDS,
            "visual_language": language,
            "hero_number": hero_number,
            "hero_label": hero_label,
            "split": split or {},
            "team": team,
            "numbers": collect_numbers(*numbers, hero_number),
            "never_say": never_say,
            "variant": variant,
            "seed": seed,
        }

    if kind == "stalemate":
        total = int(home_stats.get("shots") or 0) + int(away_stats.get("shots") or 0)
        line = pool_line(CLAIM_POOLS["shots_total"], f"{seed}:stalemate", n=total)
        punch = pool_line(PUNCH_POOLS["blank"], f"{seed}:blank")
        return pack([line], punch, [total], hero_number=total, hero_label=i18n.t("shots").upper())

    if kind == "level":
        line = pool_line(CLAIM_POOLS["level"], f"{seed}:level", home=hook_team_name(bundle.home), away=hook_team_name(bundle.away))
        punch = pool_line(PUNCH_POOLS["level"], f"{seed}:levelpunch")
        return pack([line], punch, [], split={
            "home": int(home_stats.get("shots") or 0),
            "away": int(away_stats.get("shots") or 0),
            "label": i18n.t("shots").upper(),
        })

    short_loser = hook_team_name(loser)
    short_winner = hook_team_name(winner)
    loser_stats = context["loser_stats"]
    winner_stats = context["winner_stats"]
    punch_lost = pool_line(PUNCH_POOLS["lost"], f"{seed}:lost")
    punch_over = pool_line(PUNCH_POOLS["over"], f"{seed}:over")

    if kind == "volume_upset":
        edges = _volume_edges(bundle, context, audit)
        lines = []
        numbers: list[Any] = []
        for index, edge in enumerate(edges[:3]):
            key = edge["pool"] if index == 0 else edge["pool"]
            if index == 0:
                lines.append(pool_line(CLAIM_POOLS[key], f"{seed}:vol:{key}", team=short_loser, n=edge["n"]))
            else:
                more_key = {
                    "shots": "hook_more_shots",
                    "corners": "hook_more_corners",
                    "blocked": "hook_more_blocked",
                    "chances": "hook_more_chances",
                    "box": "hook_more_box",
                    "pressure": "hook_more_pressure",
                }.get(key, "hook_more_shots")
                lines.append(i18n.t(more_key) if key != "pressure" else i18n.t("hook_more_pressure"))
            numbers.extend([edge["n"], edge["other"]])
        hero = edges[0] if edges else {"n": int(loser_stats.get("shots") or 0), "label": "SHOTS", "other": 0}
        split = {
            "home": int(home_stats.get(edges[0]["key"], 0) if edges else home_stats.get("shots") or 0),
            "away": int(away_stats.get(edges[0]["key"], 0) if edges else away_stats.get("shots") or 0),
            "label": hero.get("label") or "SHOTS",
        }
        return pack(lines, punch_lost, numbers, hero_number=hero["n"], hero_label=str(hero.get("label") or "SHOTS"),
                    split=split, team=short_loser)

    if kind == "sterile_upset":
        share = float(winner_stats.get("pass_share_pct") or 0)
        shots = int(loser_stats.get("shots") or 0)
        lines = [
            pool_line(CLAIM_POOLS["ball"], f"{seed}:ball", team=short_winner, n=int(share)),
            pool_line(CLAIM_POOLS["not_chances"], f"{seed}:notc", team=short_loser, n=shots),
        ]
        return pack(lines, punch_lost, [share, shots], hero_number=int(share), hero_label=i18n.t("pass_share").upper(),
                    split={"home": float(home_stats.get("pass_share_pct") or 0),
                           "away": float(away_stats.get("pass_share_pct") or 0),
                           "label": i18n.t("pass_share").upper()},
                    team=short_winner)

    if kind == "waste":
        shots = int(loser_stats.get("shots") or 0)
        chances = int(loser_stats.get("big_chances") or 0)
        lines = [
            pool_line(CLAIM_POOLS["waste"], f"{seed}:waste", team=short_loser, n=shots),
            pool_line(CLAIM_POOLS["chances"], f"{seed}:wastec", team=short_loser, n=chances),
        ]
        return pack(lines, punch_lost, [shots, chances], hero_number=shots, hero_label=i18n.t("shots").upper(),
                    split={"home": int(home_stats.get("shots") or 0), "away": int(away_stats.get("shots") or 0),
                           "label": i18n.t("shots").upper()},
                    team=short_loser)

    if kind == "xg_robbery":
        xg = float(loser_stats.get("xg") or 0)
        line = pool_line(CLAIM_POOLS["xg"], f"{seed}:xg", team=short_loser, n=f"{xg:.2f}")
        return pack([line], punch_lost, [xg], hero_number=round(xg, 2), hero_label="xG", team=short_loser)

    if kind == "keeper_wall":
        saves = int(winner_stats.get("saves") or 0)
        faced = int(loser_stats.get("shots_on_target") or 0)
        line = pool_line(CLAIM_POOLS["keeper"], f"{seed}:keep", team=short_winner, n=saves)
        return pack([line], punch_over, [saves, faced], hero_number=saves, hero_label=i18n.t("saves").upper(),
                    team=short_winner)

    if kind == "chain_shock" and chain:
        n = int(chain.get("passes") or 0)
        metres = int(round(float(chain.get("pass_distance_m") or 0)))
        seconds = int(round(float(chain.get("duration_seconds") or 0)))
        line = pool_line(CLAIM_POOLS["chain"], f"{seed}:chain", team=hook_team_name(str(chain.get("team") or "")), n=n)
        return pack([line], punch_over, [n, metres, seconds], hero_number=n, hero_label=i18n.t("passes"),
                    team=hook_team_name(str(chain.get("team") or "")))

    if kind == "press_pin":
        peak = _tilt_peak(audit)
        tilt_rows = audit.get("field_tilt") or []
        home_lead = sum(float(r.get("home_tilt_pct") or 50) for r in tilt_rows)
        pin_team = bundle.home if home_lead >= 50 * max(1, len(tilt_rows)) else bundle.away
        line = pool_line(CLAIM_POOLS["pin"], f"{seed}:pin", team=hook_team_name(pin_team), n=int(peak))
        return pack([line], punch_over if pin_team == winner else punch_lost, [int(peak)],
                    hero_number=int(peak), hero_label="TILT", team=hook_team_name(pin_team))

    if kind == "blowout":
        margin = context["margin"]
        line = pool_line(CLAIM_POOLS["blowout"], f"{seed}:blow", team=short_winner, n=margin)
        return pack([line], punch_over, [margin], hero_number=margin, hero_label=i18n.t("goals").upper(),
                    team=short_winner)

    if kind == "comeback":
        minute = int((last or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["comeback"], f"{seed}:come", team=short_winner, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute or None, hero_label="MIN",
                    team=short_winner)

    if kind == "stoppage":
        minute = int((last or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["stoppage"], f"{seed}:stop", team=short_winner, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute, hero_label="MIN", team=short_winner)

    if kind == "late_turn":
        minute = int((last or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["late"], f"{seed}:late", team=short_winner, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute, hero_label="MIN", team=short_winner)

    if kind == "red_or_card":
        reds = int(home_stats.get("red_cards") or 0) + int(away_stats.get("red_cards") or 0)
        line = pool_line(CLAIM_POOLS["red"], f"{seed}:red", n=reds)
        return pack([line], punch_over, [reds], hero_number=reds, hero_label="RED", team=short_winner)

    if kind == "own_goal":
        og = next((g for g in timeline if g.get("own_goal")), last)
        minute = int((og or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["own_goal"], f"{seed}:og", n=minute)
        return pack([line], punch_over, [minute], hero_number=minute or None, hero_label="OG", team=short_winner)

    if kind == "penalty":
        minute = int((last or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["penalty"], f"{seed}:pen", team=short_winner, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute, hero_label="PEN", team=short_winner)

    line = pool_line(CLAIM_POOLS["one"], f"{seed}:one", team=short_winner)
    return pack([line], punch_over, [], team=short_winner)


def build_bridge(bundle: MatchBundle, audit: dict[str, Any], viz_id: str) -> dict[str, Any]:
    """One screamable line that introduces the next card. Never a scoreline."""
    stats = audit["team_stats"]
    home, away = stats.get(bundle.home, {}), stats.get(bundle.away, {})
    context = result_context(bundle, audit)
    seed = f"{match_seed(bundle)}:bridge:{viz_id}"
    keys = BRIDGE_POOLS.get(viz_id) or ["bridge_look_0", "bridge_look_1", "bridge_look_2"]
    kwargs: dict[str, Any] = {}

    if viz_id in {"zone_control", "touch_heatmap", "time_zones"}:
        zones = audit.get("zone_control") or []
        home_t = sum(int(z.get("home_touches") or 0) for z in zones)
        away_t = sum(int(z.get("away_touches") or 0) for z in zones)
        leader = bundle.home if home_t >= away_t else bundle.away
        kwargs = {"team": hook_team_name(leader), "n": max(home_t, away_t)}
    elif viz_id in {"sterile_domination", "chance_funnel", "pass_network"}:
        leader = bundle.home if float(home.get("pass_share_pct") or 0) >= float(away.get("pass_share_pct") or 0) else bundle.away
        kwargs = {"team": hook_team_name(leader), "n": int(max(home.get("pass_share_pct") or 0, away.get("pass_share_pct") or 0))}
    elif viz_id in {"goalmouth", "keeper_frame"}:
        keeper = bundle.home if int(away.get("shots_on_target") or 0) >= int(home.get("shots_on_target") or 0) else bundle.away
        kwargs = {"team": hook_team_name(keeper), "n": int(max(home.get("saves") or 0, away.get("saves") or 0))}
    elif viz_id == "goal_timeline":
        n = len(audit.get("goal_timeline") or [])
        kwargs = {"n": n}
    elif viz_id in {"shot_map", "stat_slam"}:
        leader = bundle.home if int(home.get("shots") or 0) >= int(away.get("shots") or 0) else bundle.away
        kwargs = {"team": hook_team_name(leader), "n": int(max(home.get("shots") or 0, away.get("shots") or 0))}
    elif viz_id == "goal_chain":
        chain = best_goal_chain(audit)
        n = int((chain or {}).get("passes") or 0)
        kwargs = {"n": n, "team": hook_team_name(str((chain or {}).get("team") or bundle.home))}
    elif viz_id == "player_spike":
        spike = (audit.get("player_leaders") or {}).get("spike") or {}
        kwargs = {"team": hook_team_name(str(spike.get("team") or bundle.home)), "n": int(spike.get("count") or 0)}
    elif viz_id == "close":
        if context["winner"]:
            kwargs = {"team": hook_team_name(context["winner"])}
        elif context["total_goals"] == 0:
            keys = ["hook_punch_blank_0", "hook_punch_blank_1"]
        else:
            keys = PUNCH_POOLS["level"]
    else:
        kwargs = {"team": hook_team_name(bundle.home), "n": int(home.get("shots") or 0)}

    try:
        line = pool_line(keys, seed, **kwargs)
    except Exception:
        line = i18n.t("bridge_look_at_this")
    return {
        "opens": viz_id,
        "line": line,
        "lines": [line],
        "seconds": BRIDGE_SECONDS,
    }


def hook_passes_lock(text: str, fact_pack: dict[str, Any]) -> bool:
    raw = clean_text(text)
    if not raw:
        return False
    if _SCORELINE.search(raw):
        return False
    for banned in fact_pack.get("never_say") or []:
        if banned and banned in raw:
            return False
    allowed = allowed_number_tokens(fact_pack.get("numbers") or [])
    extras = extra_numbers(raw, allowed)
    return not extras


def apply_hook_rephrase(hook: dict[str, Any], rewrite: dict[str, Any] | None) -> dict[str, Any]:
    """Accept Gemini wording only when every number is in the fact pack."""
    if not rewrite:
        return hook
    updated = dict(hook)
    lines = rewrite.get("lines")
    if isinstance(lines, list):
        clean = [clean_text(item) for item in lines if clean_text(item)][:3]
        if clean and all(hook_passes_lock(line, hook) for line in clean):
            updated["lines"] = clean
            updated["narration_claim"] = " ".join(clean)
            updated["hook_source"] = "gemini"
    punch = clean_text(rewrite.get("punch"))
    if punch and hook_passes_lock(punch, hook):
        updated["punch"] = punch
        updated["narration_punch"] = punch.rstrip(".")
        updated["hook_source"] = "gemini"
    return updated
