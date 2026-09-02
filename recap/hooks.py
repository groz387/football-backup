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
_RESULT_LEAK = re.compile(
    r"\b(won it|win it|lost it|they lost|they won|full[-\s]?time|"
    r"final score|took the (?:points|result)|points went|game\.?\s*gone)\b",
    re.IGNORECASE,
)
_HIDE_ALIASES = {
    "hide", "hidden", "spoiler-free", "spoiler_free", "nospoiler",
    "no-spoiler", "no_spoiler", "free",
}

BRIDGE_SECONDS = 0.45
CLAIM_SECONDS = 0.85
PUNCH_SECONDS = 0.70

# Stronger kinds first. one_moment is the last resort for a decisive win.
KIND_PRIORITY = (
    "last_kick",
    "var_swing",
    "goalkeeper_howler",
    "debut_goal",
    "super_sub",
    "own_goal",
    "penalty",
    "red_or_card",
    "offside_theft",
    "missed_sitter",
    "woodwork_curse",
    "set_piece_clinic",
    "star_player",
    "derby",
    "rival_energy",
    "table_implications",
    "blowout",
    "comeback",
    "stoppage",
    "xg_robbery",
    "xg_overperform",
    "keeper_wall",
    "waste",
    "chain_shock",
    "press_pin",
    "possession_prison",
    "clean_sheet_siege",
    "volume_upset",
    "sterile_upset",
    "late_turn",
    "one_moment",
    "stalemate",
    "level",
)

NUMBER_SLAM_KINDS = {
    "volume_upset", "waste", "chain_shock", "xg_robbery",
    "keeper_wall", "press_pin", "stalemate", "offside_theft",
    "missed_sitter", "woodwork_curse", "set_piece_clinic",
    "possession_prison", "xg_overperform", "clean_sheet_siege",
    "star_player", "last_kick", "table_implications",
}
SPLIT_SMASH_KINDS = {"sterile_upset", "volume_upset", "waste", "possession_prison"}
# Remaining kinds use stamp (team-color flash).

PUNCH_POOLS = {
    "lost": [
        "hook_punch_lost_0", "hook_punch_lost_1", "hook_punch_lost_2",
        "hook_punch_lost_3", "hook_punch_lost_4", "hook_punch_lost_5",
        "hook_punch_lost_6", "hook_punch_lost_7",
        "hook_punch_lost_8", "hook_punch_lost_9", "hook_punch_lost_10",
    ],
    "over": [
        "hook_punch_over_0", "hook_punch_over_1", "hook_punch_over_2",
        "hook_punch_over_3", "hook_punch_over_4", "hook_punch_over_5",
        "hook_punch_over_6", "hook_punch_over_7", "hook_punch_over_8",
    ],
    "level": [
        "hook_punch_level_0", "hook_punch_level_1", "hook_punch_level_2",
        "hook_punch_level_3", "hook_punch_level_4",
        "hook_punch_level_5", "hook_punch_level_6",
    ],
    "blank": [
        "hook_punch_blank_0", "hook_punch_blank_1", "hook_punch_blank_2",
        "hook_punch_blank_3",
        "hook_punch_blank_4", "hook_punch_blank_5",
    ],
    "spoiler": [
        "hook_punch_spoiler_0", "hook_punch_spoiler_1",
        "hook_punch_spoiler_2", "hook_punch_spoiler_3",
    ],
}

CLAIM_POOLS = {
    "shots": ["hook_claim_shots_0", "hook_claim_shots_1", "hook_claim_shots_2",
              "hook_claim_shots_3", "hook_claim_shots_4"],
    "corners": ["hook_claim_corners_0", "hook_claim_corners_1", "hook_claim_corners_2"],
    "blocked": ["hook_claim_blocked_0", "hook_claim_blocked_1", "hook_claim_blocked_2"],
    "chances": ["hook_claim_chances_0", "hook_claim_chances_1", "hook_claim_chances_2",
                "hook_claim_chances_3"],
    "box": ["hook_claim_box_0", "hook_claim_box_1", "hook_claim_box_2"],
    "pressure": ["hook_claim_pressure_0", "hook_claim_pressure_1", "hook_claim_pressure_2"],
    "ball": ["hook_claim_ball_0", "hook_claim_ball_1", "hook_claim_ball_2", "hook_claim_ball_3"],
    "not_chances": ["hook_claim_not_chances_0", "hook_claim_not_chances_1", "hook_claim_not_chances_2"],
    "late": ["hook_claim_late_0", "hook_claim_late_1", "hook_claim_late_2", "hook_claim_late_3"],
    "one": ["hook_claim_one_0", "hook_claim_one_1", "hook_claim_one_2", "hook_claim_one_3"],
    "shots_total": ["hook_claim_nshots_0", "hook_claim_nshots_1", "hook_claim_nshots_2"],
    "comeback": ["hook_claim_comeback_0", "hook_claim_comeback_1", "hook_claim_comeback_2",
                 "hook_claim_comeback_3"],
    "stoppage": ["hook_claim_stoppage_0", "hook_claim_stoppage_1", "hook_claim_stoppage_2",
                 "hook_claim_stoppage_3"],
    "blowout": ["hook_claim_blowout_0", "hook_claim_blowout_1", "hook_claim_blowout_2",
                "hook_claim_blowout_3"],
    "xg": ["hook_claim_xg_0", "hook_claim_xg_1", "hook_claim_xg_2", "hook_claim_xg_3"],
    "keeper": ["hook_claim_keeper_0", "hook_claim_keeper_1", "hook_claim_keeper_2",
               "hook_claim_keeper_3"],
    "waste": ["hook_claim_waste_0", "hook_claim_waste_1", "hook_claim_waste_2"],
    "chain": ["hook_claim_chain_0", "hook_claim_chain_1", "hook_claim_chain_2",
              "hook_claim_chain_3"],
    "pin": ["hook_claim_pin_0", "hook_claim_pin_1", "hook_claim_pin_2"],
    "red": ["hook_claim_red_0", "hook_claim_red_1", "hook_claim_red_2"],
    "own_goal": ["hook_claim_og_0", "hook_claim_og_1", "hook_claim_og_2"],
    "penalty": ["hook_claim_pen_0", "hook_claim_pen_1", "hook_claim_pen_2"],
    "level": ["hook_claim_level_0", "hook_claim_level_1", "hook_claim_level_2"],
    "offside": ["hook_claim_offside_0", "hook_claim_offside_1", "hook_claim_offside_2"],
    "lastkick": ["hook_claim_lastkick_0", "hook_claim_lastkick_1", "hook_claim_lastkick_2"],
    "debut": ["hook_claim_debut_0", "hook_claim_debut_1", "hook_claim_debut_2"],
    "derby": ["hook_claim_derby_0", "hook_claim_derby_1"],
    "table": ["hook_claim_table_0", "hook_claim_table_1"],
    "sitter": ["hook_claim_sitter_0", "hook_claim_sitter_1"],
    "woodwork": ["hook_claim_woodwork_0", "hook_claim_woodwork_1"],
    "setpiece": ["hook_claim_setpiece_0", "hook_claim_setpiece_1"],
    "howler": ["hook_claim_howler_0", "hook_claim_howler_1"],
    "sub": ["hook_claim_sub_0", "hook_claim_sub_1"],
    "var": ["hook_claim_var_0", "hook_claim_var_1"],
    "prison": ["hook_claim_prison_0", "hook_claim_prison_1"],
    "xgover": ["hook_claim_xgover_0", "hook_claim_xgover_1"],
    "siege": ["hook_claim_siege_0", "hook_claim_siege_1"],
    "rival": ["hook_claim_rival_0", "hook_claim_rival_1"],
    "star": ["hook_claim_star_0", "hook_claim_star_1"],
}

OPEN_POOLS = {
    "generic": ["hook_open_generic_0", "hook_open_generic_1", "hook_open_generic_2"],
    "offside_theft": ["hook_open_offside_0"],
    "last_kick": ["hook_open_lastkick_0"],
    "star_player": ["hook_open_star_0"],
    "volume_upset": ["hook_open_generic_0", "hook_open_generic_2"],
    "waste": ["hook_open_generic_0", "hook_open_generic_1"],
    "missed_sitter": ["hook_open_generic_1"],
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
    "shot_clock_spiral": ["bridge_spiral_0", "bridge_spiral_1"],
    "press_trap": ["bridge_trap_0", "bridge_trap_1"],
    "pass_lanes": ["bridge_lanes_0", "bridge_lanes_1"],
    "bench_impact": ["bridge_bench_0", "bridge_bench_1"],
    "duel_tower": ["bridge_duel_0", "bridge_duel_1"],
    "aerial_war": ["bridge_aerial_0", "bridge_aerial_1"],
    "halftime_split": ["bridge_split_0", "bridge_split_1"],
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


def hook_style(seed: str, language: str | None = None) -> str:
    lang = i18n.normalize_language(language or i18n.get_language())
    return "open" if pick_index(f"{seed}:style:{lang}", 2) else "slam"


def parse_spoiler(raw: str | None) -> str:
    """CLI/platform contract. Unknown tokens fall back to show."""
    return resolve_spoiler(raw)


def resolve_spoiler(*sources: Any) -> str:
    """Any hide alias wins. Idempotent across CLI, audit, and platform flags."""
    for source in sources:
        if source is None or source is False:
            continue
        raw = source
        if isinstance(source, dict):
            raw = source.get("spoiler")
        token = str(raw or "").strip().lower().replace(" ", "-")
        if token in _HIDE_ALIASES:
            return "hide"
    return "show"


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


def scorer_names(audit: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for goal in audit.get("goal_timeline") or []:
        raw = clean_text(goal.get("scorer"))
        if not raw:
            continue
        for part in (raw, raw.split()[-1] if raw.split() else raw):
            token = part.strip()
            if len(token) < 3:
                continue
            key = token.lower()
            if key not in seen:
                seen.add(key)
                names.append(token)
    return names


def _name_in_text(name: str, text: str) -> bool:
    if not name or len(name) < 3 or not text:
        return False
    return re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE) is not None


def _int_stat(block: dict[str, Any], key: str) -> int:
    try:
        return int(block.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _is_set_piece_situation(value: Any) -> bool:
    token = str(value or "").lower().replace(" ", "")
    return token in {
        "fromcorner", "setpiece", "directfreekick", "indirectfreekick",
        "fromthrowin", "penalty", "freekick",
    }


def star_from_data(bundle: MatchBundle, audit: dict[str, Any]) -> dict[str, Any] | None:
    """Named spike from events/leaders only. Never invent a surname."""
    leaders = audit.get("player_leaders") or {}
    if not isinstance(leaders, dict):
        return None
    candidates: list[dict[str, Any]] = []
    for key in ("spike", "goals", "assists", "saves", "dribbles", "key_passes", "shots", "tackles"):
        item = leaders.get(key)
        if not isinstance(item, dict):
            continue
        player = clean_text(item.get("player") or item.get("surname"))
        if not player:
            continue
        action = str(item.get("action") or key)
        count = _int_stat(item, "count")
        ok = (
            (action in {"goals", "assists"} and count >= 2)
            or (action == "saves" and count >= 5)
            or (action in {"dribbles", "key_passes", "shots", "tackles"} and count >= 5)
        )
        if not ok:
            continue
        # player_leaders is event-derived. A keeper spike does not have to score.
        candidates.append({
            "player": player,
            "surname": player.split()[-1],
            "action": action,
            "count": count,
            "team": clean_text(item.get("team") or ""),
        })
    candidates.sort(key=lambda row: row["count"], reverse=True)
    if candidates:
        return candidates[0]
    # Timeline brace: two+ goals by the same named scorer still count as a spike.
    tallies: dict[str, int] = {}
    teams: dict[str, str] = {}
    for goal in audit.get("goal_timeline") or []:
        if goal.get("own_goal"):
            continue
        player = clean_text(goal.get("scorer"))
        if not player:
            continue
        tallies[player] = tallies.get(player, 0) + 1
        teams[player] = clean_text(goal.get("team") or teams.get(player) or "")
    named = [
        {
            "player": player,
            "surname": player.split()[-1],
            "action": "goals",
            "count": count,
            "team": teams.get(player) or "",
        }
        for player, count in tallies.items()
        if count >= 2
    ]
    named.sort(key=lambda row: row["count"], reverse=True)
    return named[0] if named else None


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
    stats = audit.get("team_stats") or {}
    home_stats = stats.get(bundle.home, {})
    away_stats = stats.get(bundle.away, {})
    winner = context["winner"]
    loser = context["loser"]
    health = audit.get("data_health") or {}
    timeline = audit.get("goal_timeline") or []
    last = timeline[-1] if timeline else None
    match_meta = audit.get("match") if isinstance(audit.get("match"), dict) else {}
    found: list[str] = []

    last_clock = float((last or {}).get("clock") or 0)
    last_minute = int((last or {}).get("minute") or 0)
    if last and (last_minute >= 90 or last_clock >= 90):
        found.append("last_kick")
    if health.get("has_var"):
        found.append("var_swing")
    if _int_stat(home_stats, "error_leads_to_goal") + _int_stat(away_stats, "error_leads_to_goal"):
        found.append("goalkeeper_howler")
    debuts = {clean_text(name) for name in (audit.get("debut_scorers") or [])}
    if any(goal.get("debut") or clean_text(goal.get("scorer")) in debuts for goal in timeline):
        found.append("debut_goal")
    subs = {clean_text(name) for name in (audit.get("substitute_scorers") or [])}
    if any(goal.get("substitute") or clean_text(goal.get("scorer")) in subs for goal in timeline):
        found.append("super_sub")
    if any(goal.get("own_goal") for goal in timeline):
        found.append("own_goal")
    if last and last.get("penalty") and (not winner or last.get("team") == winner):
        found.append("penalty")
    if _int_stat(home_stats, "red_cards") + _int_stat(away_stats, "red_cards"):
        found.append("red_or_card")
    if max(_int_stat(home_stats, "offsides"), _int_stat(away_stats, "offsides")) >= 5:
        found.append("offside_theft")
    if max(_int_stat(home_stats, "big_chances_missed"), _int_stat(away_stats, "big_chances_missed")) >= 3:
        found.append("missed_sitter")
    if max(_int_stat(home_stats, "woodwork"), _int_stat(away_stats, "woodwork")) >= 2:
        found.append("woodwork_curse")
    set_goals = sum(1 for goal in timeline if _is_set_piece_situation(goal.get("situation")))
    set_shots = max(_int_stat(home_stats, "set_piece_shots"), _int_stat(away_stats, "set_piece_shots"))
    if set_goals >= 2 or set_shots >= 8:
        found.append("set_piece_clinic")
    if star_from_data(bundle, audit):
        found.append("star_player")
    if match_meta.get("derby") or audit.get("derby"):
        found.append("derby")
    if match_meta.get("rival") or audit.get("rival"):
        found.append("rival_energy")
    table = match_meta.get("table")
    if isinstance(table, dict) and table:
        found.append("table_implications")

    if winner:
        loser_stats = context["loser_stats"]
        winner_stats = context["winner_stats"]
        if context["margin"] >= 3:
            found.append("blowout")
        if _winner_trailed(audit, winner):
            found.append("comeback")
        if last and last.get("team") == winner and last_minute >= 85:
            found.append("stoppage")
        if health.get("has_vendor_xg"):
            loser_xg = float(loser_stats.get("xg") or 0)
            winner_xg = float(winner_stats.get("xg") or 0)
            if loser_xg > winner_xg + 0.15:
                found.append("xg_robbery")
            winner_goals = _int_stat(winner_stats, "goals") or (
                bundle.score.home if winner == bundle.home else bundle.score.away
            )
            if winner_goals - winner_xg >= 1.2:
                found.append("xg_overperform")
        loser_on = _int_stat(loser_stats, "shots_on_target")
        if loser_on >= _int_stat(winner_stats, "shots_on_target") + 2 and _int_stat(winner_stats, "saves") >= 4:
            found.append("keeper_wall")
        if (
            _int_stat(loser_stats, "shots") > _int_stat(winner_stats, "shots")
            and _int_stat(loser_stats, "big_chances") >= _int_stat(winner_stats, "big_chances")
            and _int_stat(loser_stats, "shots") >= 8
        ):
            found.append("waste")
        chain = best_goal_chain(audit)
        if chain and (_int_stat(chain, "passes") >= 8 or float(chain.get("duration_seconds") or 0) >= 20):
            found.append("chain_shock")
        if _tilt_peak(audit) >= 68:
            found.append("press_pin")
        loser_share = float(loser_stats.get("pass_share_pct") or 0)
        winner_share = float(winner_stats.get("pass_share_pct") or 0)
        if loser_share >= 58 and _int_stat(loser_stats, "shots") <= _int_stat(winner_stats, "shots"):
            found.append("possession_prison")
        elif min(
            float(home_stats.get("pass_share_pct") or 50),
            float(away_stats.get("pass_share_pct") or 50),
        ) <= 38 and _tilt_peak(audit) >= 65:
            found.append("possession_prison")
        conceded = bundle.score.away if winner == bundle.home else bundle.score.home
        if conceded == 0 and loser_on >= 5:
            found.append("clean_sheet_siege")
        volume_edges = 0
        for key in ("shots", "corners", "shots_blocked", "big_chances", "penalty_box_touches"):
            if _int_stat(loser_stats, key) > _int_stat(winner_stats, key):
                volume_edges += 1
        home_p, away_p = _pressure_totals(audit)
        if loser == bundle.home and home_p > away_p * 1.05:
            volume_edges += 1
        elif loser == bundle.away and away_p > home_p * 1.05:
            volume_edges += 1
        if volume_edges >= 2:
            found.append("volume_upset")
        if _int_stat(loser_stats, "shots") > _int_stat(winner_stats, "shots") and winner_share > loser_share + 4:
            found.append("sterile_upset")
        if last and last.get("team") == winner and last_minute >= 55:
            found.append("late_turn")
        found.append("one_moment")
    else:
        total_shots = _int_stat(home_stats, "shots") + _int_stat(away_stats, "shots")
        found.append("stalemate" if context["total_goals"] == 0 and total_shots else "level")

    ordered = [kind for kind in KIND_PRIORITY if kind in found]
    return ordered or (["one_moment"] if winner else ["level"])


def visual_language_for(kind: str, seed: str, hero_number: Any = None) -> str:
    """First frame is a readable NUMBER or a STAMP. Never a logo-only open."""
    if hero_number is not None:
        options = ["number_slam"]
        if kind in SPLIT_SMASH_KINDS:
            options.append("split_smash")
        return options[pick_index(f"{seed}:lang:{kind}", len(options))]
    if kind in NUMBER_SLAM_KINDS:
        return "number_slam"
    if kind in SPLIT_SMASH_KINDS:
        return "split_smash"
    return "stamp"


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


def comment_bait(bundle: MatchBundle, audit: dict[str, Any], hook: dict[str, Any] | None = None) -> str:
    hook = hook or {}
    kind = str(hook.get("kind") or "")
    star = star_from_data(bundle, audit)
    qualified = hook.get("qualified") or []
    if star and kind in {"star_player", "debut_goal", "super_sub", "keeper_wall", "goalkeeper_howler"}:
        return i18n.t("hook_bait_motm", player=star["surname"])
    if kind in {"volume_upset", "xg_robbery", "waste", "sterile_upset"} or "xg_robbery" in qualified:
        return i18n.t("hook_bait_robbery")
    if kind == "goalkeeper_howler":
        return i18n.t("hook_bait_howler")
    context = result_context(bundle, audit)
    if context["winner"] and context["loser"]:
        if _int_stat(context["loser_stats"], "shots") > _int_stat(context["winner_stats"], "shots"):
            return i18n.t("hook_bait_bottle")
    if star:
        return i18n.t("hook_bait_motm", player=star["surname"])
    return i18n.t("hook_bait_generic")


def localize_hook(
    hook: dict[str, Any] | None,
    bundle: MatchBundle,
    audit: dict[str, Any],
    language: str | None = None,
    spoiler: str | None = None,
) -> dict[str, Any]:
    """Keep A/B kind/variant, but never stamp English copy onto a non-English pack."""
    lang = i18n.normalize_language(language or i18n.get_language())
    if not hook:
        return build_hook(bundle, audit, language=lang, spoiler=spoiler)
    if lang == "en":
        return dict(hook)
    updated = dict(hook)
    for field in ("punch", "narration_claim", "narration_punch", "comment_bait", "hero_label"):
        value = updated.get(field)
        if value:
            updated[field] = i18n.offline_line(str(value), lang=lang)
    if isinstance(updated.get("lines"), list):
        updated["lines"] = [i18n.offline_line(str(item), lang=lang) for item in updated["lines"]]
    leaking = i18n.looks_english(str(updated.get("punch") or "")) or any(
        i18n.looks_english(str(item)) for item in (updated.get("lines") or [])
    )
    if leaking:
        native = build_hook(
            bundle, audit, language=lang, spoiler=spoiler,
            variant=int(hook.get("variant") or 0),
        )
        native["variant"] = hook.get("variant", native.get("variant"))
        native["fingerprint"] = hook.get("fingerprint") or native.get("fingerprint")
        native["source"] = hook.get("source") or native.get("source")
        return native
    updated["language"] = lang
    return updated


def apply_spoiler_hide(
    hook: dict[str, Any],
    bundle: MatchBundle,
    audit: dict[str, Any],
    spoiler: str | None,
) -> dict[str, Any]:
    resolved = resolve_spoiler(spoiler, hook.get("spoiler"))
    updated = dict(hook)
    updated["spoiler"] = resolved
    names = scorer_names(audit)
    updated["never_say_names"] = names if resolved == "hide" else []
    if resolved != "hide":
        updated["spoiler_applied"] = False
        return updated
    if hook.get("spoiler_applied"):
        return updated
    seed = f"{hook.get('seed') or match_seed(bundle)}:spoiler"
    punch = pool_line(PUNCH_POOLS["spoiler"], seed)
    pack = {
        "numbers": hook.get("numbers") or [],
        "never_say": hook.get("never_say") or [],
        "never_say_names": names,
        "spoiler": "hide",
    }
    lines = []
    for line in hook.get("lines") or []:
        cleaned = clean_text(line)
        for name in names:
            cleaned = re.sub(rf"\b{re.escape(name)}\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
        if cleaned and hook_passes_lock(cleaned, pack, beat="claim"):
            lines.append(cleaned)
    if not lines:
        hero = hook.get("hero_number")
        label = hook.get("hero_label") or ""
        lines = [f"{hero} {label}".strip()] if hero is not None else [hook.get("matchup") or f"{bundle.home} — {bundle.away}"]
    if not hook_passes_lock(punch, pack, beat="punch"):
        punch = i18n.t("hook_punch_spoiler_0")
    updated["lines"] = lines[:3]
    updated["punch"] = punch
    updated["narration_claim"] = " ".join(updated["lines"])
    updated["narration_punch"] = punch.rstrip(".")
    updated["spoiler_applied"] = True
    updated["never_say_names"] = names
    return updated


def _apply_open_style(hook: dict[str, Any], seed: str, language: str) -> dict[str, Any]:
    if hook.get("style") != "open":
        return hook
    kind = str(hook.get("kind") or "")
    keys = OPEN_POOLS.get(kind) or OPEN_POOLS["generic"]
    line = pool_line(keys, f"{seed}:open:{language}:{kind}", **{
        "team": hook.get("team") or "",
        "n": hook.get("hero_number") if hook.get("hero_number") is not None else "",
        "player": hook.get("player") or hook.get("team") or "",
        "home": hook_team_name(str(hook.get("home") or "")),
        "away": hook_team_name(str(hook.get("away") or "")),
    })
    pack = {
        "numbers": hook.get("numbers") or [],
        "never_say": hook.get("never_say") or [],
        "never_say_names": hook.get("never_say_names") or [],
        "spoiler": hook.get("spoiler") or "show",
    }
    if not hook_passes_lock(line, pack, beat="claim"):
        return hook
    updated = dict(hook)
    rest = list(hook.get("lines") or [])[1:]
    updated["lines"] = [line] + rest
    updated["narration_claim"] = " ".join(updated["lines"])
    return updated


def build_hook(
    bundle: MatchBundle,
    audit: dict[str, Any],
    language: str | None = None,
    spoiler: str | None = None,
    *,
    variant: int = 0,
) -> dict[str, Any]:
    """Contradiction open: claim card, punch card, fact pack, visual language.

    ``variant`` 0 is the hashed default. 1 and 2 (and further salts) walk the
    phrase pools so the A/B picker can score alternates without a new match.
    """
    lang = i18n.normalize_language(language or i18n.get_language())
    spoiler = resolve_spoiler(
        spoiler,
        audit.get("spoiler"),
        (audit.get("generation") or {}).get("spoiler") if isinstance(audit.get("generation"), dict) else None,
    )
    context = result_context(bundle, audit)
    stats = audit.get("team_stats") or {}
    home_stats = stats.get(bundle.home, {})
    away_stats = stats.get(bundle.away, {})
    qualified = qualifying_kinds(bundle, audit)
    kind = qualified[0]
    seed = match_seed(bundle)
    variant = int(variant or 0)
    if variant:
        seed = f"{seed}:ab{variant}"
    style = hook_style(seed, lang)
    winner = context["winner"]
    loser = context["loser"]
    matchup = f"{bundle.home} — {bundle.away}"
    never_say = score_variants(bundle)
    timeline = audit.get("goal_timeline") or []
    last = timeline[-1] if timeline else None
    chain = best_goal_chain(audit)
    star = star_from_data(bundle, audit)
    match_meta = audit.get("match") if isinstance(audit.get("match"), dict) else {}

    def pack(
        lines: list[str],
        punch: str,
        numbers: list[Any],
        *,
        hero_number: Any = None,
        hero_label: str = "",
        split: dict[str, Any] | None = None,
        team: str = "",
        player: str = "",
    ) -> dict[str, Any]:
        clean_lines = [line for line in lines if line][:3]
        if not clean_lines:
            clean_lines = [matchup]
        payload = {
            "kind": kind,
            "qualified": qualified,
            "matchup": matchup,
            "lines": clean_lines,
            "punch": punch,
            "narration_claim": " ".join(clean_lines),
            "narration_punch": punch.rstrip("."),
            "seconds_claim": CLAIM_SECONDS,
            "seconds_punch": PUNCH_SECONDS,
            "visual_language": visual_language_for(kind, seed, hero_number),
            "hero_number": hero_number,
            "hero_label": hero_label,
            "split": split or {},
            "team": team,
            "player": player,
            "home": bundle.home,
            "away": bundle.away,
            "numbers": collect_numbers(*numbers, hero_number),
            "never_say": never_say,
            "never_say_names": [],
            "variant": variant,
            "seed": seed,
            "style": style,
            "language": lang,
            "spoiler": spoiler,
            "spoiler_applied": False,
            "variants": [{"lines": clean_lines, "punch": punch} for _ in range(3)],
        }
        payload = _apply_open_style(payload, seed, lang)
        payload = apply_spoiler_hide(payload, bundle, audit, spoiler)
        payload["comment_bait"] = comment_bait(bundle, audit, payload)
        payload["visual_language"] = visual_language_for(payload["kind"], seed, payload.get("hero_number"))
        return payload

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

    short_loser = hook_team_name(loser) if loser else hook_team_name(bundle.home)
    short_winner = hook_team_name(winner) if winner else hook_team_name(bundle.away)
    loser_stats = context["loser_stats"] or home_stats
    winner_stats = context["winner_stats"] or away_stats
    punch_lost = pool_line(PUNCH_POOLS["lost"], f"{seed}:lost:{lang}")
    punch_over = pool_line(PUNCH_POOLS["over"], f"{seed}:over:{lang}")

    if kind == "offside_theft":
        home_n, away_n = _int_stat(home_stats, "offsides"), _int_stat(away_stats, "offsides")
        n = max(home_n, away_n)
        team = bundle.home if home_n >= away_n else bundle.away
        line = pool_line(CLAIM_POOLS["offside"], f"{seed}:off:{lang}", team=hook_team_name(team), n=n)
        return pack([line], punch_lost if loser else punch_over, [n],
                    hero_number=n, hero_label=i18n.t("hook_label_offsides"), team=hook_team_name(team))

    if kind == "last_kick":
        minute = int((last or {}).get("minute") or 0)
        team = hook_team_name(str((last or {}).get("team") or short_winner))
        line = pool_line(CLAIM_POOLS["lastkick"], f"{seed}:last:{lang}", team=team, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute, hero_label=i18n.t("hook_label_minute"), team=team)

    if kind == "debut_goal":
        debut = next((g for g in timeline if g.get("debut")), last)
        player = clean_text((debut or {}).get("scorer"))
        minute = int((debut or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["debut"], f"{seed}:debut:{lang}", player=player.split()[-1] if player else short_winner, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute or None, hero_label="DEBUT",
                    team=short_winner, player=player)

    if kind == "super_sub":
        sub = next((g for g in timeline if g.get("substitute")), last)
        player = clean_text((sub or {}).get("scorer"))
        minute = int((sub or {}).get("minute") or 0)
        line = pool_line(CLAIM_POOLS["sub"], f"{seed}:sub:{lang}", player=player.split()[-1] if player else short_winner, n=minute)
        return pack([line], punch_over, [minute], hero_number=minute or None, hero_label="SUB",
                    team=short_winner, player=player)

    if kind == "goalkeeper_howler":
        n = _int_stat(home_stats, "error_leads_to_goal") + _int_stat(away_stats, "error_leads_to_goal") or 1
        line = pool_line(CLAIM_POOLS["howler"], f"{seed}:howl:{lang}", n=n, team=short_loser)
        return pack([line], punch_over, [n], hero_number=n, hero_label="ERR", team=short_winner)

    if kind == "var_swing":
        line = pool_line(CLAIM_POOLS["var"], f"{seed}:var:{lang}", n=1)
        return pack([line], punch_over, [1], hero_number=1, hero_label="VAR", team=short_winner)

    if kind == "missed_sitter":
        home_n, away_n = _int_stat(home_stats, "big_chances_missed"), _int_stat(away_stats, "big_chances_missed")
        n = max(home_n, away_n)
        team = bundle.home if home_n >= away_n else bundle.away
        line = pool_line(CLAIM_POOLS["sitter"], f"{seed}:sit:{lang}", team=hook_team_name(team), n=n)
        return pack([line], punch_lost if team == loser else punch_over, [n],
                    hero_number=n, hero_label=i18n.t("hook_label_sitters"), team=hook_team_name(team))

    if kind == "woodwork_curse":
        home_n, away_n = _int_stat(home_stats, "woodwork"), _int_stat(away_stats, "woodwork")
        n = max(home_n, away_n)
        team = bundle.home if home_n >= away_n else bundle.away
        line = pool_line(CLAIM_POOLS["woodwork"], f"{seed}:wood:{lang}", team=hook_team_name(team), n=n)
        return pack([line], punch_lost if team == loser else punch_over, [n],
                    hero_number=n, hero_label=i18n.t("hook_label_woodwork"), team=hook_team_name(team))

    if kind == "set_piece_clinic":
        n = max(_int_stat(home_stats, "set_piece_shots"), _int_stat(away_stats, "set_piece_shots"))
        goals_n = sum(1 for goal in timeline if _is_set_piece_situation(goal.get("situation")))
        hero = goals_n if goals_n >= 2 else n
        line = pool_line(CLAIM_POOLS["setpiece"], f"{seed}:sp:{lang}", team=short_winner, n=hero)
        return pack([line], punch_over, [hero, n, goals_n],
                    hero_number=hero, hero_label=i18n.t("hook_label_setpiece"), team=short_winner)

    if kind == "star_player" and star:
        player = star["surname"]
        n = star["count"]
        line = pool_line(CLAIM_POOLS["star"], f"{seed}:star:{lang}", player=player, n=n)
        return pack([line], punch_over, [n], hero_number=n, hero_label=star["action"].upper(),
                    team=hook_team_name(star.get("team") or short_winner), player=star["player"])

    if kind == "derby":
        line = pool_line(CLAIM_POOLS["derby"], f"{seed}:derby:{lang}",
                        home=hook_team_name(bundle.home), away=hook_team_name(bundle.away))
        return pack([line], punch_over, [], team=short_winner)

    if kind == "rival_energy":
        line = pool_line(CLAIM_POOLS["rival"], f"{seed}:rival:{lang}",
                        home=hook_team_name(bundle.home), away=hook_team_name(bundle.away))
        return pack([line], punch_over, [], team=short_winner)

    if kind == "table_implications":
        table = match_meta.get("table") or {}
        team = winner or bundle.home
        side = "home" if team == bundle.home else "away"
        block = table.get(side) if isinstance(table, dict) else {}
        pos = block.get("position") if isinstance(block, dict) else None
        n = int(pos) if pos is not None else _int_stat(winner_stats, "goals")
        line = pool_line(CLAIM_POOLS["table"], f"{seed}:table:{lang}", team=hook_team_name(team), n=n)
        return pack([line], punch_over, [n], hero_number=n or None, hero_label="TABLE", team=hook_team_name(team))

    if kind == "possession_prison":
        share = int(round(float(loser_stats.get("pass_share_pct") or home_stats.get("pass_share_pct") or 0)))
        line = pool_line(CLAIM_POOLS["prison"], f"{seed}:prison:{lang}", team=short_loser, n=share)
        return pack([line], punch_lost, [share], hero_number=share, hero_label=i18n.t("pass_share").upper(), team=short_loser)

    if kind == "xg_overperform":
        xg = float(winner_stats.get("xg") or 0)
        line = pool_line(CLAIM_POOLS["xgover"], f"{seed}:xgo:{lang}", team=short_winner, n=f"{xg:.2f}")
        return pack([line], punch_over, [xg], hero_number=round(xg, 2), hero_label="xG", team=short_winner)

    if kind == "clean_sheet_siege":
        faced = _int_stat(loser_stats, "shots_on_target")
        line = pool_line(CLAIM_POOLS["siege"], f"{seed}:siege:{lang}", team=short_winner, n=faced)
        return pack([line], punch_over, [faced], hero_number=faced, hero_label=i18n.t("hook_label_saves"), team=short_winner)

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
    stats = audit.get("team_stats") or {}
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
    elif viz_id == "press_trap":
        trap = audit.get("press_trap") or {}
        kwargs = {
            "team": hook_team_name(str(trap.get("leader") or bundle.home)),
            "n": trap.get("leader_ppda") or 0,
        }
    elif viz_id == "bench_impact":
        n = len((audit.get("bench_impact") or {}).get("subs") or [])
        kwargs = {"n": n, "team": hook_team_name(bundle.home)}
    elif viz_id == "duel_tower":
        duels = audit.get("duels") or {}
        home_d = int((duels.get("home") or {}).get("total") or 0)
        away_d = int((duels.get("away") or {}).get("total") or 0)
        leader = bundle.home if home_d >= away_d else bundle.away
        kwargs = {"team": hook_team_name(leader), "n": max(home_d, away_d)}
    elif viz_id == "aerial_war":
        aerials = audit.get("aerials") or {}
        home_a = int(aerials.get("home_won") or 0)
        away_a = int(aerials.get("away_won") or 0)
        leader = bundle.home if home_a >= away_a else bundle.away
        kwargs = {"team": hook_team_name(leader), "n": max(home_a, away_a)}
    elif viz_id == "halftime_split":
        kwargs = {"team": hook_team_name(bundle.home), "n": 2}
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


def hook_passes_lock(
    text: str,
    fact_pack: dict[str, Any],
    beat: str | None = None,
) -> bool:
    raw = clean_text(text)
    if not raw:
        return False
    if _SCORELINE.search(raw):
        return False
    for banned in fact_pack.get("never_say") or []:
        if banned and banned in raw:
            return False
    for name in fact_pack.get("never_say_names") or []:
        if _name_in_text(str(name), raw):
            return False
    allowed = allowed_number_tokens(fact_pack.get("numbers") or [])
    if extra_numbers(raw, allowed):
        return False
    if resolve_spoiler(fact_pack.get("spoiler")) == "hide" and beat != "close":
        if _RESULT_LEAK.search(raw):
            return False
    return True


def apply_hook_rephrase(hook: dict[str, Any], rewrite: dict[str, Any] | None) -> dict[str, Any]:
    """Accept Gemini wording only when every number is in the fact pack."""
    if not rewrite:
        return hook
    updated = dict(hook)
    pack = {
        "numbers": hook.get("numbers") or [],
        "never_say": hook.get("never_say") or [],
        "never_say_names": hook.get("never_say_names") or [],
        "spoiler": hook.get("spoiler") or "show",
    }
    lines = rewrite.get("lines")
    if isinstance(lines, list):
        clean = [clean_text(item) for item in lines if clean_text(item)][:3]
        if clean and all(hook_passes_lock(line, pack, beat="claim") for line in clean):
            updated["lines"] = clean
            updated["narration_claim"] = " ".join(clean)
            updated["hook_source"] = "gemini"
    punch = clean_text(rewrite.get("punch"))
    if punch and hook_passes_lock(punch, pack, beat="punch"):
        updated["punch"] = punch
        updated["narration_punch"] = punch.rstrip(".")
        updated["hook_source"] = "gemini"
    return updated


SHOCK_POOL_KEYS = ("hook_shock_90", "hook_shock_game_over", "hook_shock_watch_turn")


def shock_pool_lines(language: str | None = None) -> list[dict[str, str]]:
    """Fixed first-second shock options such as '90 Minute' / 'Oyun Qapandi'."""
    lang = i18n.normalize_language(language or i18n.get_language())
    out = []
    for key in SHOCK_POOL_KEYS:
        text = i18n.t(key, lang=lang)
        out.append({"key": key, "kind": "pool", "text": text, "label": text})
    return out


def comment_bait_options(
    bundle: MatchBundle,
    audit: dict[str, Any],
    hook: dict[str, Any] | None = None,
    language: str | None = None,
) -> list[dict[str, str]]:
    """MOTM / robbery / bottle / generic bait lines for the close card."""
    lang = i18n.normalize_language(language or i18n.get_language())
    star = star_from_data(bundle, audit) or {}
    player = str(star.get("surname") or star.get("player") or "").strip() or "MOTM"
    options = [
        {"kind": "motm", "key": "hook_bait_motm", "text": i18n.t("hook_bait_motm", lang=lang, player=player)},
        {"kind": "robbery", "key": "hook_bait_robbery", "text": i18n.t("hook_bait_robbery", lang=lang)},
        {"kind": "bottle", "key": "hook_bait_bottle", "text": i18n.t("hook_bait_bottle", lang=lang)},
        {"kind": "generic", "key": "hook_bait_generic", "text": i18n.t("hook_bait_generic", lang=lang)},
        {"kind": "howler", "key": "hook_bait_howler", "text": i18n.t("hook_bait_howler", lang=lang)},
    ]
    current = ""
    if hook:
        current = str(hook.get("comment_bait") or "")
    if current and all(current != item["text"] for item in options):
        options.insert(0, {"kind": "current", "key": "current", "text": current})
    return options


def apply_shock_text(
    scenes: list[dict[str, Any]],
    texts: list[str] | str | None,
    *,
    slot: str = "auto",
) -> list[dict[str, Any]]:
    """Write chosen first-second shock copy onto claim / punch / micro_hook cards.

    One string applies to claim (and punch if slot is ``all``). A list maps
    ``[claim, punch, ...micro_hooks]``.
    """
    if not texts:
        return scenes
    if isinstance(texts, str):
        chunks = [texts.strip()] if texts.strip() else []
    else:
        chunks = [str(item).strip() for item in texts if str(item).strip()]
    if not chunks:
        return scenes
    claim = punch = None
    micros: list[str] = []
    if slot == "punch":
        punch = chunks[0]
    elif slot == "micro":
        micros = chunks
    elif slot == "all":
        claim = chunks[0]
        punch = chunks[0]
        micros = chunks
    elif len(chunks) == 1:
        claim = chunks[0]
    else:
        claim = chunks[0]
        punch = chunks[1] if len(chunks) > 1 else None
        micros = chunks[2:]
    out = []
    micro_i = 0
    for scene in scenes:
        updated = dict(scene)
        viz = scene.get("visualization")
        if claim and viz == "hook_claim":
            updated["title"] = claim
            lines = list(updated.get("lines") or [])
            if lines:
                lines[0] = claim
            else:
                lines = [claim]
            updated["lines"] = lines
            updated["narration"] = claim.rstrip(".")
            updated["user_locked"] = True
        elif punch and viz == "hook_punch":
            updated["title"] = punch
            updated["lines"] = [punch]
            updated["narration"] = punch.rstrip(".")
            updated["user_locked"] = True
        elif viz == "micro_hook" and micros:
            line = micros[micro_i] if micro_i < len(micros) else micros[-1]
            micro_i += 1
            updated["title"] = line
            updated["lines"] = [line]
            updated["narration"] = line.rstrip(".")
            updated["user_locked"] = True
        out.append(updated)
    return out


def apply_bait_text(scenes: list[dict[str, Any]], text: str | None) -> list[dict[str, Any]]:
    """Write the final comment-bait question onto the close card."""
    bait = clean_text(text)
    if not bait:
        return scenes
    out = []
    for scene in scenes:
        updated = dict(scene)
        if scene.get("visualization") == "close" or scene.get("id") == "close":
            previous = str(updated.get("comment_bait") or "")
            updated["comment_bait"] = bait
            updated["insight"] = bait
            narration = str(updated.get("narration") or "").strip()
            if previous and previous in narration:
                narration = narration.replace(previous, "").strip(" .")
            if bait.lower() not in narration.lower():
                updated["narration"] = (
                    f"{narration.rstrip('. ')}. {bait}".strip() if narration else bait
                )
            else:
                updated["narration"] = narration
            updated["user_locked"] = True
        out.append(updated)
    return out


def apply_cli_copy(
    scenes: list[dict[str, Any]],
    *,
    hook_texts: list[str] | None = None,
    bait_text: str | None = None,
) -> list[dict[str, Any]]:
    """Apply ``--hook-text`` / ``--bait-text`` without stdin."""
    updated = apply_shock_text(scenes, hook_texts or [])
    return apply_bait_text(updated, bait_text)


def shock_menu_options(
    scenes: list[dict[str, Any]],
    ab_report: dict[str, Any] | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Numbered first-second shock choices: A/B variants, pool lines, current."""
    lang = i18n.normalize_language(language or i18n.get_language())
    options: list[dict[str, Any]] = []
    claim = next((s for s in scenes if s.get("visualization") == "hook_claim"), {})
    punch = next((s for s in scenes if s.get("visualization") == "hook_punch"), {})
    current_claim = str(claim.get("title") or "")
    current_punch = str(punch.get("title") or "")
    if current_claim:
        options.append({
            "kind": "current",
            "label": current_claim,
            "claim": current_claim,
            "punch": current_punch,
        })
    for row in (ab_report or {}).get("variants") or []:
        hook = row.get("hook") or row
        lines = hook.get("lines") or []
        line = lines[0] if lines else str(hook.get("punch") or "")
        if not line:
            continue
        if any(item.get("claim") == line for item in options):
            continue
        options.append({
            "kind": "ab",
            "label": line,
            "claim": line,
            "punch": str(hook.get("punch") or current_punch),
        })
    for item in shock_pool_lines(lang):
        if any(opt.get("claim") == item["text"] for opt in options):
            continue
        options.append({
            "kind": "pool",
            "label": item["text"],
            "claim": item["text"],
            "punch": item["text"],
            "key": item["key"],
        })
    options.append({"kind": "custom", "label": "CUSTOM", "claim": "", "punch": ""})
    return options
