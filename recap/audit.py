"""Every number the video is allowed to say.

The renderers and the script writer both read from the audit and nothing else.
If a metric is not in here, it cannot appear on screen.

Two rules shape the definitions below:

* Nothing is inferred from a model. There is no xG in a WhoScored event export,
  so there is no xG anywhere in the output.
* Where a metric only approximates the broadcast statistic, it is named for
  what it actually measures. "Pass share" is pass share, not possession.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .data import (
    MatchBundle,
    clean_text,
    event_seconds,
    flag,
    num,
    parse_qualifiers,
    text_col,
)

# Pitch is normalised 0-100 in both axes, attacking left to right.
FINAL_THIRD_X = 66.67
BOX_X = 83.0
BOX_Y_MIN, BOX_Y_MAX = 21.1, 78.9

# WhoScored goal-mouth space: the frame sits at these coordinates.
GOAL_Y_MIN, GOAL_Y_MAX = 45.2, 54.8
GOAL_Z_MAX = 38.0

# WhoScored restarts `minute` at the top of each period, so first-half stoppage
# collides with the start of the second half and extra time collides with
# second-half stoppage. `expandedMinute` is continuous across the whole match,
# which makes it the only safe axis for anything time-bucketed.
PERIOD_SEQUENCE = (
    "PreMatch",
    "FirstHalf",
    "HalfTime",
    "SecondHalf",
    "FirstPeriodOfExtraTime",
    "SecondPeriodOfExtraTime",
    "PenaltyShootout",
    "PostGame",
)
PLAYING_PERIODS = (
    "FirstHalf",
    "SecondHalf",
    "FirstPeriodOfExtraTime",
    "SecondPeriodOfExtraTime",
)
PERIOD_BOUNDARY_LABEL = {
    "SecondHalf": "HT",
    "FirstPeriodOfExtraTime": "FT",
    "SecondPeriodOfExtraTime": "ET",
}
PERIOD_DISPLAY = {
    "FirstHalf": "First half",
    "SecondHalf": "Second half",
    "FirstPeriodOfExtraTime": "Extra time 1",
    "SecondPeriodOfExtraTime": "Extra time 2",
}

MOMENTUM_WEIGHTS = {
    "final_third_pass": 1.0,
    "box_entry_pass": 1.2,
    "shot": 3.0,
    "shot_on_target_bonus": 1.5,
    "goal_bonus": 8.0,
    "corner": 1.5,
    "successful_take_on": 1.0,
    "attacking_recovery": 0.8,
}


# ---------------------------------------------------------------------------
# team statistics
# ---------------------------------------------------------------------------

def _team_mask(df: pd.DataFrame, h_a: str) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index, dtype=bool)
    return text_col(df, "h_a").eq(h_a)


def corners_won(df: pd.DataFrame) -> pd.Series:
    """A corner awarded to the event's own team.

    WhoScored writes one CornerAwarded event per side for the same corner; the
    team that won it is the one with a Successful outcome. Counting the raw
    flag would credit both teams for every corner in the match.
    """
    return text_col(df, "type").eq("CornerAwarded") & text_col(df, "outcomeType").eq("Successful")


def keeper_saves(df: pd.DataFrame) -> pd.Series:
    """Save events made by the goalkeeper."""
    return text_col(df, "type").eq("Save") & flag(df, "keeperSaveTotal")


def outfield_blocks(df: pd.DataFrame) -> pd.Series:
    """Save events that are actually an outfield player blocking a shot."""
    return text_col(df, "type").eq("Save") & flag(df, "outfielderBlock")


def build_team_stats(bundle: MatchBundle) -> dict[str, dict[str, Any]]:
    events = bundle.events
    if events.empty:
        return {}

    is_pass = text_col(events, "type").eq("Pass")
    is_shot = flag(events, "isShot")
    is_touch = flag(events, "isTouch")
    successful = text_col(events, "outcomeType").eq("Successful")

    x = num(events, "x")
    end_x = num(events, "endX")
    end_y = num(events, "endY")

    # An own goal is recorded against the scoring player's own team, so it has
    # to be credited to the opponent when counting goals.
    scored = flag(events, "isGoal")
    own_goal = flag(events, "goalOwn")

    total_passes = max(1, int(is_pass.sum()))
    total_touches = max(1, int(is_touch.sum()))

    stats: dict[str, dict[str, Any]] = {}
    for h_a, opponent in (("h", "a"), ("a", "h")):
        side = _team_mask(events, h_a)
        other = _team_mask(events, opponent)

        team_passes = side & is_pass
        team_shots = side & is_shot
        team_touches = side & is_touch

        on_target = team_shots & flag(events, "shotOnTarget")
        blocked = team_shots & flag(events, "shotBlocked")
        woodwork = team_shots & flag(events, "shotOnPost")
        off_target = team_shots & flag(events, "shotOffTarget") & ~blocked

        goals = int((side & scored & ~own_goal).sum()) + int((other & scored & own_goal).sum())

        stats[bundle.team(h_a)] = {
            "h_a": h_a,
            "goals": goals,
            "shots": int(team_shots.sum()),
            "shots_on_target": int(on_target.sum()),
            "shots_blocked": int(blocked.sum()),
            "shots_off_target": int(off_target.sum()),
            "woodwork": int(woodwork.sum()),
            "big_chances": int((side & (flag(events, "bigChanceScored") | flag(events, "bigChanceMissed"))).sum()),
            "big_chances_created": int((side & flag(events, "bigChanceCreated")).sum()),
            "pass_attempts": int(team_passes.sum()),
            "passes_completed": int((team_passes & successful).sum()),
            "pass_accuracy_pct": _pct(int((team_passes & successful).sum()), int(team_passes.sum())),
            "pass_share_pct": _pct(int(team_passes.sum()), total_passes),
            "key_passes": int((side & flag(events, "passKey")).sum()),
            "touches": int(team_touches.sum()),
            "touch_share_pct": _pct(int(team_touches.sum()), total_touches),
            "final_third_passes": int((team_passes & successful & x.ge(FINAL_THIRD_X)).sum()),
            "box_entry_passes": int(
                (team_passes & successful & end_x.ge(BOX_X) & end_y.between(BOX_Y_MIN, BOX_Y_MAX)).sum()
            ),
            "penalty_box_touches": int(
                (team_touches & x.ge(BOX_X) & num(events, "y").between(BOX_Y_MIN, BOX_Y_MAX)).sum()
            ),
            "corners": int((side & corners_won(events)).sum()),
            "corners_taken": int((side & flag(events, "passCorner")).sum()),
            "fouls": int((side & flag(events, "foulCommitted")).sum()),
            "offsides": int((side & flag(events, "offsideGiven")).sum()),
            # A WhoScored `Save` event covers both goalkeeper saves and outfield
            # blocks, so counting them together inflates saves past the number
            # of shots the keeper actually faced. The flags separate them, and
            # keeperSaveTotal reconciles exactly with (opponent on target - goals).
            "saves": int((side & keeper_saves(events)).sum()),
            "blocks": int((side & outfield_blocks(events)).sum()),
            "tackles_won": int((side & flag(events, "tackleWon")).sum()),
            "interceptions": int((side & flag(events, "interceptionWon")).sum()),
            "dribbles_won": int((side & text_col(events, "type").eq("TakeOn") & successful).sum()),
            "dispossessed": int((side & text_col(events, "type").eq("Dispossessed")).sum()),
            "yellow_cards": int((side & text_col(events, "cardType").isin(["Yellow", "SecondYellow"])).sum()),
            "red_cards": int((side & text_col(events, "cardType").eq("Red")).sum()),
        }
        xg_col = next((col for col in events.columns if col.lower() in {"xg", "expectedgoals", "expected_goals"}), "")
        if xg_col:
            stats[bundle.team(h_a)]["xg"] = round(float(num(events, xg_col)[team_shots].fillna(0).sum()), 2)
        xgot_col = next((col for col in events.columns if col.lower() in {"xgot", "expectedgoalsontarget", "expected_goals_on_target"}), "")
        if xgot_col:
            stats[bundle.team(h_a)]["xgot"] = round(float(num(events, xgot_col)[team_shots].fillna(0).sum()), 2)
    return stats


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


# ---------------------------------------------------------------------------
# momentum
# ---------------------------------------------------------------------------

def _event_pressure(events: pd.DataFrame) -> pd.Series:
    """Per-event attacking pressure, vectorised and free of double counting."""
    weights = MOMENTUM_WEIGHTS
    is_pass = text_col(events, "type").eq("Pass")
    successful = text_col(events, "outcomeType").eq("Successful")
    x = num(events, "x")
    end_x = num(events, "endX")
    end_y = num(events, "endY")

    score = pd.Series(0.0, index=events.index)

    good_pass = is_pass & successful
    score += (good_pass & x.ge(FINAL_THIRD_X)).astype(float) * weights["final_third_pass"]
    score += (
        good_pass & end_x.ge(BOX_X) & end_y.between(BOX_Y_MIN, BOX_Y_MAX)
    ).astype(float) * weights["box_entry_pass"]

    is_shot = flag(events, "isShot")
    score += is_shot.astype(float) * weights["shot"]
    score += (is_shot & flag(events, "shotOnTarget")).astype(float) * weights["shot_on_target_bonus"]
    score += flag(events, "isGoal").astype(float) * weights["goal_bonus"]

    score += corners_won(events).astype(float) * weights["corner"]
    score += (
        text_col(events, "type").eq("TakeOn") & successful & x.ge(FINAL_THIRD_X - 6)
    ).astype(float) * weights["successful_take_on"]
    score += (
        text_col(events, "type").eq("BallRecovery") & x.ge(50)
    ).astype(float) * weights["attacking_recovery"]

    return score


def clock(events: pd.DataFrame) -> pd.Series:
    """Continuous match minute, safe to bucket on."""
    return num(events, "expandedMinute").fillna(num(events, "minute")).fillna(0)


def periods_present(events: pd.DataFrame) -> list[str]:
    found = set(text_col(events, "period").unique())
    return [name for name in PLAYING_PERIODS if name in found]


def build_clock_axis(events: pd.DataFrame, tick_every: int = 15) -> dict[str, Any]:
    """Positions and labels for a continuous-minute x axis.

    Ticks and period boundaries are looked up in the data, so a chart drawn on
    the continuous axis can still be labelled with the real match clock.
    """
    if events.empty:
        return {"end": 90.0, "ticks": [], "boundaries": []}

    clock_series = clock(events)
    minute = num(events, "minute")
    period = text_col(events, "period")

    ticks: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    end = 0.0

    for name in periods_present(events):
        segment = period.eq(name)
        if not segment.any():
            continue
        seg_clock = clock_series[segment]
        seg_minute = minute[segment]
        start_clock = float(seg_clock.min())
        start_minute = int(seg_minute.min())
        end = max(end, float(seg_clock.max()))

        if name in PERIOD_BOUNDARY_LABEL:
            boundaries.append({"at": start_clock, "label": PERIOD_BOUNDARY_LABEL[name]})
        ticks.append({"at": start_clock, "label": f"{start_minute}'"})

        top = int(seg_minute.max())
        for mark in range(start_minute + tick_every, top + 1, tick_every):
            at = seg_clock[seg_minute.ge(mark)]
            if not at.empty:
                ticks.append({"at": float(at.min()), "label": f"{mark}'"})

    final_minute = int(minute[period.isin(PLAYING_PERIODS)].max() or 90)
    ticks.append({"at": end, "label": f"{final_minute}'"})

    # Drop ticks that would print on top of each other, and never repeat a
    # label: second-half stoppage and the start of extra time are both "90'".
    ticks.sort(key=lambda item: item["at"])
    spaced: list[dict[str, Any]] = []
    used_labels: set[str] = set()
    minimum_gap = max(4.0, end * 0.05)
    for tick in ticks:
        if tick["label"] in used_labels:
            continue
        if spaced and tick["at"] - spaced[-1]["at"] < minimum_gap:
            continue
        spaced.append(tick)
        used_labels.add(tick["label"])
    return {"end": end, "ticks": spaced, "boundaries": boundaries}


def event_clock_position(events: pd.DataFrame, mask: pd.Series) -> float | None:
    """Continuous-minute position of the first event matching *mask*."""
    if not mask.any():
        return None
    return float(clock(events)[mask].min())


def build_momentum(bundle: MatchBundle, bucket_minutes: int = 5) -> list[dict[str, Any]]:
    events = bundle.events
    if events.empty:
        return []

    positions = clock(events)
    minute = num(events, "minute")
    period = text_col(events, "period")
    playing = period.isin(PLAYING_PERIODS)
    pressure = _event_pressure(events)
    side = text_col(events, "h_a")
    end = float(positions[playing].max() or 90)

    rows: list[dict[str, Any]] = []
    start = 0.0
    while start < end:
        stop = start + bucket_minutes
        in_bucket = playing & positions.ge(start) & positions.lt(stop)
        home = float(pressure[in_bucket & side.eq("h")].sum())
        away = float(pressure[in_bucket & side.eq("a")].sum())
        bucket_minutes_real = minute[in_bucket]
        if bucket_minutes_real.empty:
            label = f"{int(start)}'"
        else:
            low, high = int(bucket_minutes_real.min()), int(bucket_minutes_real.max())
            label = f"{low}-{high}" if high > low else f"{low}"
        rows.append(
            {
                "start": round(start, 2),
                "end": round(min(stop, end), 2),
                "minute_block": label,
                "period": (period[in_bucket].mode().iat[0] if in_bucket.any() else ""),
                "home_pressure": round(home, 2),
                "away_pressure": round(away, 2),
                "swing": round(home - away, 2),
            }
        )
        start = stop
    return rows


def build_field_tilt(bundle: MatchBundle, bucket_minutes: int = 10) -> list[dict[str, Any]]:
    events = bundle.events
    if events.empty:
        return []
    positions = clock(events)
    minute = num(events, "minute")
    playing = text_col(events, "period").isin(PLAYING_PERIODS)
    final_third = text_col(events, "type").eq("Pass") & num(events, "x").ge(FINAL_THIRD_X)
    side = text_col(events, "h_a")
    end = float(positions[playing].max() or 90)

    rows: list[dict[str, Any]] = []
    start = 0.0
    while start < end:
        stop = start + bucket_minutes
        window = playing & final_third & positions.ge(start) & positions.lt(stop)
        home = int((window & side.eq("h")).sum())
        away = int((window & side.eq("a")).sum())
        total = home + away
        span = minute[playing & positions.ge(start) & positions.lt(stop)]
        label = f"{int(span.min())}-{int(span.max())}" if not span.empty else f"{int(start)}'"
        rows.append(
            {
                "start": round(start, 2),
                "end": round(min(stop, end), 2),
                "minute_block": label,
                "home_final_third_passes": home,
                "away_final_third_passes": away,
                "home_tilt_pct": _pct(home, total) if total else 50.0,
                "away_tilt_pct": _pct(away, total) if total else 50.0,
            }
        )
        start = stop
    return rows


def build_phase_pressure(bundle: MatchBundle) -> list[dict[str, Any]]:
    """Pressure split by actual period, rather than by ambiguous minute ranges."""
    events = bundle.events
    if events.empty:
        return []
    pressure = _event_pressure(events)
    period = text_col(events, "period")
    side = text_col(events, "h_a")

    rows = []
    for name in periods_present(events):
        segment = period.eq(name)
        home = float(pressure[segment & side.eq("h")].sum())
        away = float(pressure[segment & side.eq("a")].sum())
        total = home + away
        rows.append(
            {
                "period": name,
                "label": PERIOD_DISPLAY.get(name, name),
                "home_pressure": round(home, 2),
                "away_pressure": round(away, 2),
                "home_share_pct": _pct(home, total) if total else 50.0,
            }
        )
    # Extra time reads better as one block than as two fifteen-minute halves.
    extra = [row for row in rows if row["period"].endswith("PeriodOfExtraTime")]
    if len(extra) == 2:
        home = sum(row["home_pressure"] for row in extra)
        away = sum(row["away_pressure"] for row in extra)
        total = home + away
        rows = [row for row in rows if row not in extra]
        rows.append(
            {
                "period": "ExtraTime",
                "label": "Extra time",
                "home_pressure": round(home, 2),
                "away_pressure": round(away, 2),
                "home_share_pct": _pct(home, total) if total else 50.0,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# territory
# ---------------------------------------------------------------------------

def build_zone_control(bundle: MatchBundle, x_bins: int = 6, y_bins: int = 3) -> list[dict[str, Any]]:
    touches = bundle.touches if not bundle.touches.empty else bundle.events[flag(bundle.events, "isTouch")]
    if touches.empty:
        return []

    x = num(touches, "x")
    y = num(touches, "y")
    valid = x.notna() & y.notna()
    if not valid.any():
        return []

    x_bin = np.clip((x[valid] / (100 / x_bins)).astype(int), 0, x_bins - 1)
    y_bin = np.clip((y[valid] / (100 / y_bins)).astype(int), 0, y_bins - 1)
    side = text_col(touches, "h_a")[valid]

    frame = pd.DataFrame({"xbin": x_bin, "ybin": y_bin, "side": side})
    grouped = frame.groupby(["xbin", "ybin", "side"]).size().unstack(fill_value=0)

    rows: list[dict[str, Any]] = []
    for xi in range(x_bins):
        for yi in range(y_bins):
            home = int(grouped.get("h", pd.Series(dtype=int)).get((xi, yi), 0))
            away = int(grouped.get("a", pd.Series(dtype=int)).get((xi, yi), 0))
            total = home + away
            rows.append(
                {
                    "xbin": xi,
                    "ybin": yi,
                    "home_touches": home,
                    "away_touches": away,
                    "total_touches": total,
                    "home_share_pct": _pct(home, total) if total else 50.0,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# shots
# ---------------------------------------------------------------------------

def _shot_outcome(row: pd.Series) -> str:
    if str(row.get("isGoal")).lower() == "true":
        return "goal"
    if str(row.get("shotBlocked")).lower() == "true":
        return "blocked"
    if str(row.get("shotOnPost")).lower() == "true":
        return "woodwork"
    if str(row.get("shotOnTarget")).lower() == "true":
        return "saved"
    return "off_target"


def build_shots(bundle: MatchBundle) -> list[dict[str, Any]]:
    events = bundle.events
    shots = events[flag(events, "isShot")]
    if shots.empty:
        return []

    records: list[dict[str, Any]] = []
    for _, row in shots.iterrows():
        x, y = row.get("x"), row.get("y")
        if pd.isna(x) or pd.isna(y):
            continue
        goal_y, goal_z = row.get("goalMouthY"), row.get("goalMouthZ")
        records.append(
            {
                "h_a": clean_text(row.get("h_a")),
                "team": bundle.team(clean_text(row.get("h_a"))),
                "player": clean_text(row.get("playerName"), "Unknown"),
                "minute": int(row["minute"]) if pd.notna(row.get("minute")) else None,
                "x": round(float(x), 2),
                "y": round(float(y), 2),
                "outcome": _shot_outcome(row),
                "big_chance": str(row.get("bigChanceScored")).lower() == "true"
                or str(row.get("bigChanceMissed")).lower() == "true",
                "situation": clean_text(row.get("situation"), "OpenPlay"),
                "goal_mouth_y": round(float(goal_y), 2) if pd.notna(goal_y) else None,
                "goal_mouth_z": round(float(goal_z), 2) if pd.notna(goal_z) else None,
                "xg": _shot_xg(row, "xg"),
                "xgot": _shot_xg(row, "xgot"),
            }
        )
    return records


def _shot_xg(row: pd.Series, kind: str) -> float | None:
    aliases = {
        "xg": ("xg", "expectedGoals", "expected_goals", "xG"),
        "xgot": ("xgot", "expectedGoalsOnTarget", "expected_goals_on_target", "xGOT"),
    }
    for name in aliases.get(kind, ()):
        value = row.get(name)
        if value is not None and pd.notna(value):
            try:
                return round(float(value), 3)
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# goal build-up chains
# ---------------------------------------------------------------------------

CHAIN_KEEP_TYPES = {"Pass", "TakeOn", "BallTouch", "Carry", "Goal", "SavedShot", "MissedShots"}
CHAIN_BREAK_TYPES = {"Pass", "TakeOn", "BallTouch", "Clearance", "Interception", "BallRecovery", "Tackle"}
MAX_CHAIN_SECONDS = 75.0
MAX_CHAIN_EVENTS = 18


def _related_event_ids(row: pd.Series) -> set[str]:
    ids: set[str] = set()
    for qualifier in parse_qualifiers(row.get("qualifiers")):
        if qualifier.get("type") in {"RelatedEventId", "OppositeRelatedEvent"} and qualifier.get("value") is not None:
            ids.add(str(qualifier["value"]))
    direct = row.get("relatedEventId")
    if direct is not None and pd.notna(direct):
        ids.add(str(int(direct)) if isinstance(direct, float) else str(direct))
    return ids


def _is_assist(row: pd.Series) -> bool:
    if str(row.get("assist")).lower() == "true" or str(row.get("intentionalAssist")).lower() == "true":
        return True
    return any(q.get("type") in {"IntentionalAssist", "Assisted"} for q in parse_qualifiers(row.get("qualifiers")))


def _compact_event(row: pd.Series) -> dict[str, Any]:
    def coord(key: str) -> float | None:
        value = row.get(key)
        return round(float(value), 2) if pd.notna(value) else None

    return {
        "eventId": clean_text(row.get("eventId")),
        "type": clean_text(row.get("type")),
        "player": clean_text(row.get("playerName"), "Unknown"),
        "minute": int(row["minute"]) if pd.notna(row.get("minute")) else None,
        "second": int(row["second"]) if pd.notna(row.get("second")) else None,
        "x": coord("x"),
        "y": coord("y"),
        "endX": coord("endX"),
        "endY": coord("endY"),
    }


def build_goal_chains(bundle: MatchBundle) -> list[dict[str, Any]]:
    events = bundle.events.reset_index(drop=True).copy()
    if events.empty:
        return []
    events["_sec"] = event_seconds(events)

    goal_rows = events[flag(events, "isGoal")]
    chains: list[dict[str, Any]] = []

    for goal_index, goal in goal_rows.iterrows():
        h_a = clean_text(goal.get("h_a"))
        if h_a not in {"h", "a"}:
            continue
        own_goal = str(goal.get("goalOwn")).lower() == "true"
        goal_time = float(goal.get("_sec") or 0)

        collected: list[pd.Series] = []
        for idx in range(int(goal_index), -1, -1):
            row = events.loc[idx]
            if goal_time - float(row.get("_sec") or 0) > MAX_CHAIN_SECONDS:
                break
            row_side = clean_text(row.get("h_a"))
            row_type = clean_text(row.get("type"))
            if row_side == h_a:
                if row_type in CHAIN_KEEP_TYPES or str(row.get("isShot")).lower() == "true":
                    collected.append(row)
            elif row_side in {"h", "a"} and row_type in CHAIN_BREAK_TYPES:
                break
            if len(collected) >= MAX_CHAIN_EVENTS:
                break

        chain_rows = list(reversed(collected))
        pass_rows = [
            row for row in chain_rows
            if clean_text(row.get("type")) == "Pass" and pd.notna(row.get("endX")) and pd.notna(row.get("x"))
        ]

        # 105x68 m pitch, coordinates are percentages of each axis.
        distance = sum(
            math.hypot(
                (float(row["endX"]) - float(row["x"])) * 1.05,
                (float(row["endY"]) - float(row["y"])) * 0.68,
            )
            for row in pass_rows
        )

        related = _related_event_ids(goal)
        assist_row = next(
            (row for row in reversed(pass_rows) if _is_assist(row) or str(row.get("eventId")) in related),
            pass_rows[-1] if pass_rows else None,
        )
        start_time = float(chain_rows[0].get("_sec")) if chain_rows else goal_time

        chains.append(
            {
                "team": bundle.team(h_a) if not own_goal else bundle.team("a" if h_a == "h" else "h"),
                "h_a": h_a if not own_goal else ("a" if h_a == "h" else "h"),
                "minute": int(goal["minute"]) if pd.notna(goal.get("minute")) else None,
                "second": int(goal["second"]) if pd.notna(goal.get("second")) else 0,
                # Position on the continuous axis, for time-based charts.
                "clock": float(
                    goal["expandedMinute"] if pd.notna(goal.get("expandedMinute"))
                    else (goal.get("minute") or 0)
                ),
                "scorer": clean_text(goal.get("playerName"), "Unknown"),
                "own_goal": own_goal,
                "penalty": str(goal.get("penaltyScored")).lower() == "true",
                "situation": clean_text(goal.get("situation"), "OpenPlay"),
                "passes": len(pass_rows),
                "events": [_compact_event(row) for row in chain_rows],
                "pass_distance_m": round(distance, 1),
                "duration_seconds": round(max(0.0, goal_time - start_time), 1),
                "assist_event_id": clean_text(assist_row.get("eventId")) if assist_row is not None else "",
                "assist_player": clean_text(assist_row.get("playerName")) if assist_row is not None else "",
            }
        )
    return chains


def goal_timeline(audit: dict[str, Any]) -> list[dict[str, Any]]:
    goals = sorted(
        audit.get("goal_chains", []),
        key=lambda item: (float(item.get("clock") or 0), int(item.get("second") or 0)),
    )
    home_goals = away_goals = 0
    timeline: list[dict[str, Any]] = []
    for index, goal in enumerate(goals, 1):
        if goal.get("h_a") == "h":
            home_goals += 1
        else:
            away_goals += 1
        timeline.append(
            {
                "index": index,
                "team": goal.get("team", ""),
                "h_a": goal.get("h_a"),
                "minute": int(goal.get("minute") or 0),
                "second": int(goal.get("second") or 0),
                "clock": float(goal.get("clock") or 0),
                "scorer": goal.get("scorer", ""),
                "own_goal": bool(goal.get("own_goal")),
                "penalty": bool(goal.get("penalty")),
                "score_after": f"{home_goals}-{away_goals}",
                "passes": int(goal.get("passes") or 0),
                "duration_seconds": float(goal.get("duration_seconds") or 0),
                "pass_distance_m": float(goal.get("pass_distance_m") or 0),
            }
        )
    return timeline


def credible_goal_chains(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Chains with enough recorded build-up to be worth drawing on a pitch."""
    chains = [
        chain
        for chain in audit.get("goal_chains", [])
        if int(chain.get("passes") or 0) >= 4 and len(chain.get("events") or []) >= 5
    ]
    return sorted(
        chains,
        key=lambda item: (int(item.get("passes") or 0), float(item.get("pass_distance_m") or 0)),
        reverse=True,
    )


def best_goal_chain(audit: dict[str, Any]) -> dict[str, Any] | None:
    credible = credible_goal_chains(audit)
    if credible:
        return credible[0]
    chains = audit.get("goal_chains") or []
    return max(chains, key=lambda c: int(c.get("passes") or 0)) if chains else None


# ---------------------------------------------------------------------------
# pass network
# ---------------------------------------------------------------------------

def build_pass_network(bundle: MatchBundle, h_a: str, max_edges: int = 16) -> dict[str, Any]:
    events = bundle.events
    passes = events[
        text_col(events, "type").eq("Pass")
        & text_col(events, "outcomeType").eq("Successful")
        & text_col(events, "h_a").eq(h_a)
    ].copy()
    if passes.empty:
        return {"nodes": {}, "edges": [], "max_edge": 1}

    # A pass is a connection when the next event by the same team is a touch by
    # a different player; that receiver is the edge target.
    passes = passes.sort_values(["minute", "second"], kind="stable")
    team_events = events[text_col(events, "h_a").eq(h_a)].reset_index(drop=True)
    order = {index: position for position, index in enumerate(team_events.index)}

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str], int] = {}

    names = text_col(team_events, "playerName")
    for position, row in team_events.iterrows():
        player = clean_text(row.get("playerName"))
        if not player or clean_text(row.get("type")) != "Pass":
            continue
        if clean_text(row.get("outcomeType")) != "Successful":
            continue
        x, y = row.get("x"), row.get("y")
        if pd.isna(x) or pd.isna(y):
            continue
        node = nodes.setdefault(player, {"x": 0.0, "y": 0.0, "count": 0})
        node["x"] += float(x)
        node["y"] += float(y)
        node["count"] += 1

        receiver = ""
        for offset in (1, 2):
            if position + offset < len(names):
                candidate = clean_text(names.iloc[position + offset])
                if candidate and candidate != player:
                    receiver = candidate
                    break
        if receiver:
            key = tuple(sorted((player, receiver)))
            edges[key] = edges.get(key, 0) + 1  # type: ignore[index]

    compact = {
        player: {
            "x": round(node["x"] / node["count"], 2),
            "y": round(node["y"] / node["count"], 2),
            "count": node["count"],
        }
        for player, node in nodes.items()
        if node["count"] >= 6
    }
    ranked = sorted(
        ({"source": a, "target": b, "count": count} for (a, b), count in edges.items() if count >= 3),
        key=lambda edge: edge["count"],
        reverse=True,
    )
    ranked = [edge for edge in ranked if edge["source"] in compact and edge["target"] in compact][:max_edges]
    return {
        "nodes": compact,
        "edges": ranked,
        "max_edge": max((edge["count"] for edge in ranked), default=1),
    }


# ---------------------------------------------------------------------------
# data health and assembly
# ---------------------------------------------------------------------------

def build_player_leaders(bundle: MatchBundle) -> dict[str, Any]:
    """Top named actors for the player-spike card."""
    events = bundle.events
    if events.empty or "playerName" not in events.columns:
        return {}
    names = text_col(events, "playerName")
    side = text_col(events, "h_a")
    types = text_col(events, "type")
    successful = text_col(events, "outcomeType").eq("Successful")
    shots = flag(events, "isShot")
    tackles = flag(events, "tackleWon")
    take_ons = types.eq("TakeOn") & successful

    def top_for(mask: pd.Series, action: str) -> dict[str, Any] | None:
        subset = names[mask & names.ne("")]
        if subset.empty:
            return None
        counts = subset.value_counts()
        player = str(counts.index[0])
        count = int(counts.iloc[0])
        if count < 2:
            return None
        h_a = str(side[names.eq(player)].mode().iat[0]) if (names.eq(player)).any() else "h"
        coords = events.loc[mask & names.eq(player), ["x", "y"]].dropna()
        points = [
            {"x": round(float(row.x), 2), "y": round(float(row.y), 2)}
            for row in coords.itertuples(index=False)
        ]
        team_total = int((mask & side.eq(h_a)).sum())
        rest = max(0, team_total - count)
        return {
            "player": player,
            "surname": player.split()[-1] if player else "",
            "shirt": _shirt_no(bundle, player),
            "team": bundle.team(h_a),
            "h_a": h_a,
            "action": action,
            "count": count,
            "team_total": team_total,
            "rest": rest,
            "points": points[:40],
        }

    goals_mask = flag(events, "isGoal") & ~flag(events, "goalOwn")
    assists = flag(events, "assist") | flag(events, "intentionalAssist")
    saves = keeper_saves(events)
    key_passes = flag(events, "passKey")
    candidates = [
        top_for(shots, "shots"),
        top_for(tackles, "tackles"),
        top_for(take_ons, "dribbles"),
        top_for(goals_mask, "goals"),
        top_for(assists, "assists"),
        top_for(saves, "saves"),
        top_for(key_passes, "key_passes"),
    ]
    ranked = sorted((item for item in candidates if item), key=lambda item: item["count"], reverse=True)
    spike = ranked[0] if ranked else None
    return {
        "spike": spike,
        "shots": candidates[0],
        "tackles": candidates[1],
        "dribbles": candidates[2],
        "goals": candidates[3],
        "assists": candidates[4],
        "saves": candidates[5],
        "key_passes": candidates[6],
    }


def build_time_zones(bundle: MatchBundle) -> list[dict[str, Any]]:
    """Territory in three 30-minute slices of the continuous clock."""
    events = bundle.events
    if events.empty:
        return []
    positions = clock(events)
    playing = text_col(events, "period").isin(PLAYING_PERIODS)
    touches = flag(events, "isTouch")
    x = num(events, "x")
    y = num(events, "y")
    side = text_col(events, "h_a")
    windows = ((0, 30, "0-30"), (30, 60, "30-60"), (60, 200, "60-90"))
    x_bins, y_bins = 6, 3
    slices: list[dict[str, Any]] = []
    for start, stop, label in windows:
        mask = playing & touches & x.notna() & y.notna() & positions.ge(start) & positions.lt(stop)
        if not mask.any():
            slices.append({"label": label, "start": start, "end": stop, "zones": [], "home_touches": 0, "away_touches": 0})
            continue
        x_bin = np.clip((x[mask] / (100 / x_bins)).astype(int), 0, x_bins - 1)
        y_bin = np.clip((y[mask] / (100 / y_bins)).astype(int), 0, y_bins - 1)
        frame = pd.DataFrame({"xbin": x_bin, "ybin": y_bin, "side": side[mask]})
        grouped = frame.groupby(["xbin", "ybin", "side"]).size().unstack(fill_value=0)
        zones = []
        home_total = away_total = 0
        for xi in range(x_bins):
            for yi in range(y_bins):
                home_n = int(grouped.get("h", pd.Series(dtype=int)).get((xi, yi), 0))
                away_n = int(grouped.get("a", pd.Series(dtype=int)).get((xi, yi), 0))
                total = home_n + away_n
                home_total += home_n
                away_total += away_n
                zones.append({
                    "xbin": xi, "ybin": yi,
                    "home_touches": home_n, "away_touches": away_n,
                    "total_touches": total,
                    "home_share_pct": _pct(home_n, total) if total else 50.0,
                })
        slices.append({
            "label": label, "start": start, "end": stop,
            "zones": zones, "home_touches": home_total, "away_touches": away_total,
        })
    return slices


def build_touch_heatmap(bundle: MatchBundle, x_bins: int = 24, y_bins: int = 16) -> dict[str, Any]:
    """Dense touch grid for a true pitch heatmap."""
    touches = bundle.touches if not bundle.touches.empty else bundle.events[flag(bundle.events, "isTouch")]
    if touches.empty:
        return {"x_bins": x_bins, "y_bins": y_bins, "home": [], "away": []}
    x = num(touches, "x")
    y = num(touches, "y")
    valid = x.notna() & y.notna()
    side = text_col(touches, "h_a")
    grids: dict[str, list[list[float]]] = {}
    for token, key in (("h", "home"), ("a", "away")):
        mask = valid & side.eq(token)
        if not mask.any():
            grids[key] = [[0.0] * y_bins for _ in range(x_bins)]
            continue
        x_bin = np.clip((x[mask] / (100 / x_bins)).astype(int), 0, x_bins - 1)
        y_bin = np.clip((y[mask] / (100 / y_bins)).astype(int), 0, y_bins - 1)
        grid = np.zeros((x_bins, y_bins), dtype=float)
        for xi, yi in zip(x_bin.tolist(), y_bin.tolist()):
            grid[int(xi), int(yi)] += 1.0
        grids[key] = grid.tolist()
    return {"x_bins": x_bins, "y_bins": y_bins, "home": grids["home"], "away": grids["away"]}


PRESS_ACTION_TYPES = frozenset({"Tackle", "Interception", "Foul", "Challenge", "BlockedPass"})
PRESS_MIN_ACTIONS = 5


def _shirt_no(bundle: MatchBundle, player: str) -> int | None:
    """Jersey number from player_stats.csv when the name matches."""
    players = bundle.players
    if players is None or getattr(players, "empty", True) or "playerName" not in getattr(players, "columns", []):
        return None
    if "shirtNo" not in players.columns:
        return None
    names = players["playerName"].astype(str)
    hit = players.loc[names.eq(player)]
    if hit.empty:
        surname = player.split()[-1] if player else ""
        if surname:
            hit = players.loc[names.str.endswith(surname, na=False)]
    if hit.empty:
        return None
    try:
        return int(hit.iloc[0]["shirtNo"])
    except (TypeError, ValueError):
        return None


def build_press_trap(bundle: MatchBundle) -> dict[str, Any]:
    """PPDA-style press intensity. Reported only when a side has enough actions.

    Opponent passes with team-perspective ``x < 40`` over this team's
    Tackle / Interception / Foul / Challenge / BlockedPass with ``x > 60``.
    A side is ``audited`` only with at least ``PRESS_MIN_ACTIONS`` press events.
    Never invent a number from a 50.0 fallback.
    """
    blank = {"ppda": None, "press_actions": 0, "opp_passes": 0, "audited": False}
    empty = {
        "home": dict(blank),
        "away": dict(blank),
        "audited": False,
        "leader": "",
        "leader_ppda": None,
    }
    events = bundle.events
    if events.empty:
        return empty
    types = text_col(events, "type")
    side = text_col(events, "h_a")
    x = num(events, "x")
    is_pass = types.eq("Pass")
    is_press = types.isin(list(PRESS_ACTION_TYPES))
    sides: dict[str, dict[str, Any]] = {}
    for h_a, opp in (("h", "a"), ("a", "h")):
        actions = int((is_press & side.eq(h_a) & x.gt(60)).sum())
        opp_passes = int((is_pass & side.eq(opp) & x.lt(40)).sum())
        audited = actions >= PRESS_MIN_ACTIONS
        ppda = round(opp_passes / actions, 2) if audited and actions else None
        sides[h_a] = {
            "ppda": ppda,
            "press_actions": actions,
            "opp_passes": opp_passes,
            "audited": audited,
        }
    home, away = sides["h"], sides["a"]
    audited = bool(home["audited"] or away["audited"])
    leader = ""
    leader_ppda = None
    if home["audited"] and away["audited"]:
        if (home["ppda"] or 99) <= (away["ppda"] or 99):
            leader, leader_ppda = bundle.home, home["ppda"]
        else:
            leader, leader_ppda = bundle.away, away["ppda"]
    elif home["audited"]:
        leader, leader_ppda = bundle.home, home["ppda"]
    elif away["audited"]:
        leader, leader_ppda = bundle.away, away["ppda"]
    return {
        "home": home,
        "away": away,
        "audited": audited,
        "leader": leader,
        "leader_ppda": leader_ppda,
    }


def build_duels(bundle: MatchBundle) -> dict[str, Any]:
    """Tackles won, aerials won, take-ons won — the duel tower."""
    events = bundle.events
    empty_side = {"tackles": 0, "aerials": 0, "take_ons": 0, "total": 0}
    empty = {"home": dict(empty_side), "away": dict(empty_side), "total": 0}
    if events.empty:
        return empty
    types = text_col(events, "type")
    side = text_col(events, "h_a")
    successful = text_col(events, "outcomeType").eq("Successful")
    tackles = flag(events, "tackleWon")
    aerials = flag(events, "duelAerialWon") | (types.eq("Aerial") & successful)
    take_ons = types.eq("TakeOn") & successful
    sides: dict[str, dict[str, int]] = {}
    for token, key in (("h", "home"), ("a", "away")):
        tck = int((tackles & side.eq(token)).sum())
        aer = int((aerials & side.eq(token)).sum())
        take = int((take_ons & side.eq(token)).sum())
        sides[key] = {"tackles": tck, "aerials": aer, "take_ons": take, "total": tck + aer + take}
    return {"home": sides["home"], "away": sides["away"], "total": sides["home"]["total"] + sides["away"]["total"]}


def build_aerials(bundle: MatchBundle) -> dict[str, Any]:
    """Header events for the aerial-war chevrons."""
    events = bundle.events
    empty = {"events": [], "home_won": 0, "away_won": 0, "total": 0}
    if events.empty:
        return empty
    types = text_col(events, "type")
    mask = types.eq("Aerial")
    if not mask.any():
        return empty
    side = text_col(events, "h_a")
    won_flag = flag(events, "duelAerialWon") | (types.eq("Aerial") & text_col(events, "outcomeType").eq("Successful"))
    records: list[dict[str, Any]] = []
    home_won = away_won = 0
    for _, row in events.loc[mask].iterrows():
        h_a = clean_text(row.get("h_a"))
        won = bool(won_flag.loc[row.name]) if row.name in won_flag.index else False
        if won:
            if h_a == "h":
                home_won += 1
            elif h_a == "a":
                away_won += 1
        minute = int(row["minute"]) if pd.notna(row.get("minute")) else None
        x, y = row.get("x"), row.get("y")
        records.append(
            {
                "h_a": h_a,
                "team": bundle.team(h_a) if h_a in {"h", "a"} else "",
                "player": clean_text(row.get("playerName"), "Unknown"),
                "minute": minute,
                "won": won,
                "x": round(float(x), 2) if pd.notna(x) else None,
                "y": round(float(y), 2) if pd.notna(y) else None,
            }
        )
    return {
        "events": records[:80],
        "home_won": home_won,
        "away_won": away_won,
        "total": len(records),
    }


def build_bench_impact(bundle: MatchBundle) -> dict[str, Any]:
    """Substitution-on timeline. Skip the card when nobody came off the bench."""
    events = bundle.events
    empty = {"subs": [], "home_count": 0, "away_count": 0}
    if events.empty:
        return empty
    types = text_col(events, "type")
    mask = types.eq("SubstitutionOn") | flag(events, "subOn")
    if not mask.any():
        return empty
    shots = flag(events, "isShot")
    side = text_col(events, "h_a")
    minutes = num(events, "minute")
    subs: list[dict[str, Any]] = []
    for _, row in events.loc[mask].iterrows():
        h_a = clean_text(row.get("h_a"))
        if h_a not in {"h", "a"}:
            continue
        minute = int(row["minute"]) if pd.notna(row.get("minute")) else None
        player = clean_text(row.get("playerName"), "Unknown")
        after = 0
        if minute is not None:
            after = int((shots & side.eq(h_a) & minutes.gt(minute)).sum())
        subs.append(
            {
                "h_a": h_a,
                "team": bundle.team(h_a),
                "player": player,
                "surname": player.split()[-1] if player else "",
                "shirt": _shirt_no(bundle, player),
                "minute": minute,
                "shots_after": after,
            }
        )
    subs.sort(key=lambda item: (item.get("minute") is None, item.get("minute") or 0))
    return {
        "subs": subs,
        "home_count": sum(1 for item in subs if item["h_a"] == "h"),
        "away_count": sum(1 for item in subs if item["h_a"] == "a"),
    }


def build_halftime_split(bundle: MatchBundle) -> dict[str, Any]:
    """First half vs second half stamp. Extra time is ignored on this card."""
    events = bundle.events
    blank = {
        "home_shots": 0, "away_shots": 0, "home_goals": 0, "away_goals": 0,
        "home_pressure": 0.0, "away_pressure": 0.0,
    }
    empty = {"first": dict(blank), "second": dict(blank), "ready": False}
    if events.empty:
        return empty
    period = text_col(events, "period")
    side = text_col(events, "h_a")
    shots = flag(events, "isShot")
    scored = flag(events, "isGoal") & ~flag(events, "goalOwn")
    pressure = _event_pressure(events)

    def slice_period(name: str) -> dict[str, Any]:
        mask = period.eq(name)
        return {
            "home_shots": int((mask & shots & side.eq("h")).sum()),
            "away_shots": int((mask & shots & side.eq("a")).sum()),
            "home_goals": int((mask & scored & side.eq("h")).sum()),
            "away_goals": int((mask & scored & side.eq("a")).sum()),
            "home_pressure": round(float(pressure[mask & side.eq("h")].sum()), 2),
            "away_pressure": round(float(pressure[mask & side.eq("a")].sum()), 2),
        }

    first = slice_period("FirstHalf")
    second = slice_period("SecondHalf")
    ready = any(first[key] or second[key] for key in ("home_shots", "away_shots", "home_goals", "away_goals"))
    return {"first": first, "second": second, "ready": ready}


def detect_data_health(bundle: MatchBundle) -> dict[str, Any]:
    events = bundle.events
    columns = {col.lower() for col in events.columns}
    has_xg = bool(columns & {"xg", "expectedgoals", "expected_goals"})
    has_xgot = bool(columns & {"xgot", "expectedgoalsontarget", "expected_goals_on_target"})
    goal_mouth = int(num(events, "goalMouthY").notna().sum())
    return {
        "event_rows": int(len(events)),
        "pass_rows": int(text_col(events, "type").eq("Pass").sum()),
        "shot_rows": int(flag(events, "isShot").sum()),
        "touch_rows": int(flag(events, "isTouch").sum()),
        "goal_mouth_rows": goal_mouth,
        "has_coordinates": {"x", "y"}.issubset(events.columns),
        "has_pass_end_coordinates": {"endX", "endY"}.issubset(events.columns),
        "has_goal_mouth_coordinates": goal_mouth > 0,
        "has_vendor_xg": has_xg,
        "has_vendor_xgot": has_xgot,
        "blocked_claims": [name for name, present in (("xG", has_xg), ("xGOT", has_xgot)) if not present],
    }


def build_audit(bundle: MatchBundle) -> dict[str, Any]:
    stats = build_team_stats(bundle)
    audit: dict[str, Any] = {
        "match": {
            "match_dir": str(bundle.match_dir),
            "home": bundle.home,
            "away": bundle.away,
            "score": bundle.score.as_dict(),
            "score_display": bundle.score.display,
            "score_qualifier": bundle.score.qualifier,
            "kickoff": bundle.kickoff,
            "league": bundle.league,
            "stage": bundle.stage,
            "venue": bundle.venue,
            "last_minute": bundle.last_minute,
        },
        "data_health": detect_data_health(bundle),
        "team_stats": stats,
        "clock_axis": build_clock_axis(bundle.events),
        "momentum": build_momentum(bundle),
        "phase_pressure": build_phase_pressure(bundle),
        "field_tilt": build_field_tilt(bundle),
        "zone_control": build_zone_control(bundle),
        "shots": build_shots(bundle),
        "goal_chains": build_goal_chains(bundle),
        "player_leaders": build_player_leaders(bundle),
        "time_zones": build_time_zones(bundle),
        "touch_heatmap": build_touch_heatmap(bundle),
        "press_trap": build_press_trap(bundle),
        "duels": build_duels(bundle),
        "aerials": build_aerials(bundle),
        "bench_impact": build_bench_impact(bundle),
        "halftime_split": build_halftime_split(bundle),
        "definitions": {
            "pass_share_pct": "Share of all pass attempts in the export. A proxy for territory of the ball, not broadcast possession.",
            "shots_on_target": "WhoScored shotOnTarget flag. Shots blocked by an outfield player are counted separately and are not on target.",
            "saves": "Save events flagged keeperSaveTotal, which is goalkeeper saves only. Outfield blocks are reported as blocks.",
            "pressure_index": "Weighted count of attacking events per five minutes: "
                              + ", ".join(f"{k}={v}" for k, v in MOMENTUM_WEIGHTS.items()),
            "match_clock": "Time buckets use expandedMinute, which runs continuously. Plain minute "
                           "restarts each period, so stoppage time overlaps the next period.",
            "field_tilt": "Share of successful final-third passes in each ten-minute window.",
            "goal_chain": "Uninterrupted possession immediately before a goal, capped at 75 seconds and 18 events.",
            "ppda": (
                "Opponent pass attempts with team-perspective x < 40, divided by this team's "
                "Tackle/Interception/Foul/Challenge/BlockedPass with x > 60. Reported only when "
                "that side has at least five such press actions. Not a broadcast PPDA feed."
            ),
        },
    }
    audit["goal_timeline"] = goal_timeline(audit)
    audit["facts"] = _describe(bundle, audit)
    return audit


def _ordinal_minute(minute: int) -> str:
    if 10 <= minute % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(minute % 10, "th")
    return f"{minute}{suffix}"


def _describe(bundle: MatchBundle, audit: dict[str, Any]) -> list[str]:
    stats = audit["team_stats"]
    if not stats:
        return ["No events were available in this export."]
    home = stats[bundle.home]
    away = stats[bundle.away]
    score = bundle.score

    facts = [score.sentence(bundle.home, bundle.away) + "."]
    facts.append(
        f"Pass share: {bundle.home} {home['pass_share_pct']}%, {bundle.away} {away['pass_share_pct']}%."
    )
    facts.append(
        f"Shots: {bundle.home} {home['shots']} ({home['shots_on_target']} on target, "
        f"{home['shots_blocked']} blocked), {bundle.away} {away['shots']} "
        f"({away['shots_on_target']} on target, {away['shots_blocked']} blocked)."
    )
    facts.append(
        f"Final-third passes: {bundle.home} {home['final_third_passes']}, {bundle.away} {away['final_third_passes']}."
    )
    if home["big_chances"] or away["big_chances"]:
        facts.append(f"Big chances: {bundle.home} {home['big_chances']}, {bundle.away} {away['big_chances']}.")
    chain = best_goal_chain(audit)
    if chain:
        facts.append(
            f"Longest build-up to a goal: {chain['team']}, {chain['passes']} passes over "
            f"{chain['pass_distance_m']} metres, finished by {chain['scorer']} "
            f"in the {_ordinal_minute(int(chain['minute'] or 0))} minute."
        )
    blocked = audit["data_health"]["blocked_claims"]
    if blocked:
        facts.append(f"Not in this export, so never claimed: {', '.join(blocked)}.")
    return facts


def result_context(bundle: MatchBundle, audit: dict[str, Any]) -> dict[str, Any]:
    """Who won, and which stat block belongs to whom."""
    stats = audit["team_stats"]
    home = stats.get(bundle.home, {})
    away = stats.get(bundle.away, {})
    score = bundle.score
    if score.home > score.away:
        winner, loser = bundle.home, bundle.away
        winner_stats, loser_stats = home, away
    elif score.away > score.home:
        winner, loser = bundle.away, bundle.home
        winner_stats, loser_stats = away, home
    else:
        winner = loser = ""
        winner_stats = loser_stats = {}
    return {
        "winner": winner,
        "loser": loser,
        "winner_stats": winner_stats,
        "loser_stats": loser_stats,
        "total_goals": score.total_goals,
        "margin": score.margin,
        "is_draw": score.is_draw,
    }


def dominant_team(bundle: MatchBundle, audit: dict[str, Any], key: str) -> str:
    stats = audit["team_stats"]
    home = float(stats.get(bundle.home, {}).get(key) or 0)
    away = float(stats.get(bundle.away, {}).get(key) or 0)
    if home == away:
        return ""
    return bundle.home if home > away else bundle.away
