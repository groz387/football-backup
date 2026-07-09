#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive WhoScored match-to-video pipeline.

The pipeline starts from the existing scraper export folders in ./output and
builds a data-audited short video package:

  data_audit.json      verified metrics and unavailable fields
  video_plan.json      selected visualizations and evidence
  SCRIPT.md            scene-by-scene narration
  voiceover.txt        plain narration text
  subtitles.srt        subtitles aligned by scene
  assets/*.png         rendered vertical video frames
  match_video.mp4      assembled mock narrated video, when moviepy/ffmpeg work

Usage:
  python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto
  python video_pipeline.py --interactive
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle

from voiceover import VoiceoverConfig, fit_scene_durations_to_audio, prepare_voiceover


BG = "#0a0b08"
PANEL = "#10140f"
PITCH = "#0d130d"
LINE = "#e2e8dc"
MUTED = "#aab3a5"
HOME = "#ef9f27"
AWAY = "#5dcaa5"
DANGER = "#ff335f"
WHITE = "#f7f8f1"
GRID = "#2b342b"
SCRIM = "#050604"
DISPLAY_FONT = "DejaVu Sans"
BODY_FONT = "DejaVu Sans"
MONO_FONT = "DejaVu Sans Mono"
WATERMARK = "AUDIT-LOCKED RECAP"

TEAM_COLOR_TABLE = {
    "scotland": {"raw": "#0b2545", "display": "#3d63c9", "accent": "#7fa0ff"},
    "morocco": {"raw": "#c8102e", "display": "#e2231a", "accent": "#00a86b"},
    "mexico": {"raw": "#006847", "display": "#12b76a", "accent": "#ce1126"},
    "southkorea": {"raw": "#c60c30", "display": "#f04455", "accent": "#4d7dff"},
    "south korea": {"raw": "#c60c30", "display": "#f04455", "accent": "#4d7dff"},
}

TRUE_VALUES = {"true", "1", "yes", "y", "t"}


@dataclass
class MatchBundle:
    match_dir: Path
    summary: dict[str, Any]
    events: pd.DataFrame
    passes: pd.DataFrame
    shots: pd.DataFrame
    touches: pd.DataFrame
    players: pd.DataFrame

    @property
    def home(self) -> str:
        return str(self.summary.get("home", {}).get("name", "Home"))

    @property
    def away(self) -> str:
        return str(self.summary.get("away", {}).get("name", "Away"))

    @property
    def home_id(self) -> Any:
        return self.summary.get("home", {}).get("teamId")

    @property
    def away_id(self) -> Any:
        return self.summary.get("away", {}).get("teamId")

    @property
    def score(self) -> str:
        return str(self.summary.get("score") or self.summary.get("ftScore") or "")


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.ASCII).strip("_")
    return value or "match"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    series = df[col]
    if series.dtype == bool:
        return series.fillna(False)
    return series.fillna(False).astype(str).str.strip().str.lower().isin(TRUE_VALUES)


def clean_text(value: Any, fallback: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return fallback
    text = str(value)
    return text if text and text.lower() != "nan" else fallback


def event_seconds(df: pd.DataFrame) -> pd.Series:
    return num(df, "minute").fillna(0) * 60 + num(df, "second").fillna(0)


def team_name(bundle: MatchBundle, h_a: str) -> str:
    return bundle.home if h_a == "h" else bundle.away


def team_color(h_a: str, design: dict[str, Any] | None = None) -> str:
    if design:
        side = "home" if h_a == "h" else "away"
        return str(design[side]["display"])
    return HOME if h_a == "h" else AWAY


def normalize_team_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in rgb)


def relative_luminance(color: str) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(color_a: str, color_b: str) -> float:
    a = relative_luminance(color_a)
    b = relative_luminance(color_b)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_safe(color: str, background: str = BG, minimum: float = 4.5) -> str:
    if contrast_ratio(color, background) >= minimum:
        return color
    r, g, b = hex_to_rgb(color)
    h, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    for step in range(1, 18):
        trial_l = min(0.88, lightness + step * 0.035)
        trial_s = min(1.0, saturation + step * 0.018)
        trial = rgb_to_hex(colorsys.hls_to_rgb(h, trial_l, trial_s))
        if contrast_ratio(trial, background) >= minimum:
            return trial
    return rgb_to_hex(colorsys.hls_to_rgb(h, 0.82, min(1.0, saturation + 0.2)))


def resolve_team_colors(name: str, fallback: str) -> dict[str, str]:
    key = normalize_team_key(name)
    token = TEAM_COLOR_TABLE.get(key)
    if token is None:
        compact = key.replace(" ", "")
        token = TEAM_COLOR_TABLE.get(compact, {"raw": fallback, "display": fallback, "accent": fallback})
    display = contrast_safe(str(token["display"]))
    accent = contrast_safe(str(token.get("accent") or display), minimum=3.4)
    return {"raw": str(token["raw"]), "display": display, "accent": accent}


def match_design(bundle: MatchBundle) -> dict[str, Any]:
    return {
        "home": resolve_team_colors(bundle.home, HOME),
        "away": resolve_team_colors(bundle.away, AWAY),
        "background": BG,
        "panel": PANEL,
        "pitch": PITCH,
        "line": LINE,
        "muted": MUTED,
        "white": WHITE,
        "grid": GRID,
    }


def load_match(match_dir: Path) -> MatchBundle:
    summary_path = match_dir / "match_summary.json"
    events_path = match_dir / "all_events.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing {summary_path}")
    if not events_path.exists():
        raise FileNotFoundError(f"Missing {events_path}")

    summary = read_json(summary_path)
    events = read_csv_if_exists(events_path)
    passes = read_csv_if_exists(match_dir / "passes.csv")
    shots = read_csv_if_exists(match_dir / "shots.csv")
    touches = read_csv_if_exists(match_dir / "heatmap_touches.csv")
    players = read_csv_if_exists(match_dir / "player_stats.csv")

    for df in (events, passes, shots, touches):
        for col in ("minute", "second", "x", "y", "endX", "endY", "goalMouthY", "goalMouthZ"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    return MatchBundle(match_dir, summary, events, passes, shots, touches, players)


def list_match_dirs(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    dirs = []
    for child in output_root.iterdir():
        if child.is_dir() and (child / "match_summary.json").exists() and (child / "all_events.csv").exists():
            dirs.append(child)

    def sort_key(path: Path) -> tuple[str, str]:
        try:
            summary = read_json(path / "match_summary.json")
            return (str(summary.get("startTime") or summary.get("startDate") or ""), path.name)
        except Exception:
            return ("", path.name)

    return sorted(dirs, key=sort_key, reverse=True)


def choose_match_dir(output_root: Path, interactive: bool) -> Path:
    match_dirs = list_match_dirs(output_root)
    if not match_dirs:
        raise FileNotFoundError(f"No exported matches found under {output_root}")
    if not interactive:
        return match_dirs[0]

    print("\nAvailable exported matches:")
    for i, path in enumerate(match_dirs, 1):
        try:
            summary = read_json(path / "match_summary.json")
            label = (
                f"{summary.get('home', {}).get('name', 'Home')} vs "
                f"{summary.get('away', {}).get('name', 'Away')} "
                f"({summary.get('score', '')}, {summary.get('startDate', '')[:10]})"
            )
        except Exception:
            label = path.name
        print(f"  {i}. {label} - {path}")

    while True:
        raw = input("Choose match number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(match_dirs):
            return match_dirs[int(raw) - 1]
        print("Please enter a valid number.")


def build_team_stats(bundle: MatchBundle) -> dict[str, Any]:
    events = bundle.events
    passes = bundle.passes if not bundle.passes.empty else events[events["type"] == "Pass"].copy()
    shots = events[bool_col(events, "isShot")].copy()
    touches = bundle.touches if not bundle.touches.empty else events[bool_col(events, "isTouch")].copy()

    stats: dict[str, Any] = {}
    total_passes = max(1, len(passes))
    total_touches = max(1, len(touches))

    for h_a, name in (("h", bundle.home), ("a", bundle.away)):
        team_passes = passes[passes.get("h_a") == h_a].copy()
        team_shots = shots[shots.get("h_a") == h_a].copy()
        team_touches = touches[touches.get("h_a") == h_a].copy()
        pass_success = team_passes[team_passes.get("outcomeType") == "Successful"]
        on_target = team_shots[
            bool_col(team_shots, "isGoal")
            | team_shots.get("type", pd.Series("", index=team_shots.index)).isin(["Goal", "SavedShot"])
            | bool_col(team_shots, "shotOnTarget")
        ]
        corners = events[
            (events.get("h_a") == h_a)
            & (events.get("type", pd.Series("", index=events.index)).eq("CornerAwarded") | bool_col(events, "cornerAwarded"))
        ]
        fouls = events[
            (events.get("h_a") == h_a)
            & (events.get("type", pd.Series("", index=events.index)).eq("Foul") | bool_col(events, "foulCommitted"))
        ]
        saves = events[
            (events.get("h_a") == h_a)
            & (events.get("type", pd.Series("", index=events.index)).eq("Save") | bool_col(events, "keeperSaveTotal"))
        ]
        final_third_passes = team_passes[num(team_passes, "x") >= 66.67]
        penalty_box_touches = team_touches[(num(team_touches, "x") >= 83.0) & (num(team_touches, "y").between(21, 79))]

        stats[name] = {
            "h_a": h_a,
            "pass_attempts": int(len(team_passes)),
            "successful_passes": int(len(pass_success)),
            "pass_success_pct": round(len(pass_success) / max(1, len(team_passes)) * 100, 1),
            "pass_share_pct": round(len(team_passes) / total_passes * 100, 1),
            "touches": int(len(team_touches)),
            "touch_share_pct": round(len(team_touches) / total_touches * 100, 1),
            "shots": int(len(team_shots)),
            "shots_on_target": int(len(on_target)),
            "goals": int(bool_col(team_shots, "isGoal").sum()),
            "corners": int(len(corners)),
            "fouls": int(len(fouls)),
            "saves": int(len(saves)),
            "final_third_passes": int(len(final_third_passes)),
            "penalty_box_touches": int(len(penalty_box_touches)),
        }
    return stats


def build_momentum(bundle: MatchBundle, bucket_minutes: int = 5) -> list[dict[str, Any]]:
    events = bundle.events.copy()
    events["_sec"] = event_seconds(events)
    max_minute = int(num(events, "minute").max()) if not events.empty else 90
    rows = []

    for start in range(0, max_minute + bucket_minutes, bucket_minutes):
        bucket = events[(num(events, "minute") >= start) & (num(events, "minute") < start + bucket_minutes)]
        scores = {"h": 0.0, "a": 0.0}
        for _, row in bucket.iterrows():
            h_a = clean_text(row.get("h_a"))
            if h_a not in scores:
                continue
            event_type = clean_text(row.get("type"))
            x = float(row.get("x")) if pd.notna(row.get("x")) else 0.0
            end_x = float(row.get("endX")) if pd.notna(row.get("endX")) else np.nan
            score = 0.0
            if event_type == "Pass" and row.get("outcomeType") == "Successful":
                if x >= 66.67:
                    score += 1.0
                if pd.notna(end_x) and end_x >= 83.0:
                    score += 1.2
                epv = row.get("EPV")
                if epv is not None and pd.notna(epv):
                    score += max(0.0, min(3.0, float(epv) * 18.0))
            if bool(row.get("isShot")) if isinstance(row.get("isShot"), bool) else str(row.get("isShot")).lower() == "true":
                score += 4.0
            if event_type == "SavedShot":
                score += 5.0
            if event_type == "MissedShots":
                score += 2.0
            if event_type == "Goal" or str(row.get("isGoal")).lower() == "true":
                score += 10.0
            if event_type == "CornerAwarded":
                score += 2.0
            if event_type == "TakeOn" and row.get("outcomeType") == "Successful" and x >= 60:
                score += 1.5
            if event_type == "BallRecovery" and x >= 50:
                score += 1.0
            scores[h_a] += score

        rows.append(
            {
                "minute_start": start,
                "minute_block": f"{start}-{start + bucket_minutes - 1}",
                "home_pressure": round(scores["h"], 2),
                "away_pressure": round(scores["a"], 2),
                "swing": round(scores["h"] - scores["a"], 2),
            }
        )
    return rows


def build_field_tilt(bundle: MatchBundle, bucket_minutes: int = 10) -> list[dict[str, Any]]:
    passes = bundle.passes if not bundle.passes.empty else bundle.events[bundle.events["type"] == "Pass"].copy()
    if passes.empty:
        return []
    max_minute = int(num(passes, "minute").max())
    rows = []
    for start in range(0, max_minute + bucket_minutes, bucket_minutes):
        bucket = passes[(num(passes, "minute") >= start) & (num(passes, "minute") < start + bucket_minutes)]
        final_third = bucket[num(bucket, "x") >= 66.67]
        home_count = int((final_third.get("h_a") == "h").sum())
        away_count = int((final_third.get("h_a") == "a").sum())
        total = home_count + away_count
        rows.append(
            {
                "minute_start": start,
                "minute_block": f"{start}-{start + bucket_minutes - 1}",
                "home_final_third_passes": home_count,
                "away_final_third_passes": away_count,
                "home_tilt_pct": round(home_count / total * 100, 1) if total else 50.0,
                "away_tilt_pct": round(away_count / total * 100, 1) if total else 50.0,
            }
        )
    return rows


def build_zone_control(bundle: MatchBundle, x_bins: int = 6, y_bins: int = 3) -> list[dict[str, Any]]:
    touches = bundle.touches if not bundle.touches.empty else bundle.events[bool_col(bundle.events, "isTouch")].copy()
    rows = []
    if touches.empty:
        return rows
    x = num(touches, "x")
    y = num(touches, "y")
    valid = touches[x.notna() & y.notna()].copy()
    valid["_xbin"] = np.clip((num(valid, "x") / (100 / x_bins)).astype(int), 0, x_bins - 1)
    valid["_ybin"] = np.clip((num(valid, "y") / (100 / y_bins)).astype(int), 0, y_bins - 1)

    for xi in range(x_bins):
        for yi in range(y_bins):
            cell = valid[(valid["_xbin"] == xi) & (valid["_ybin"] == yi)]
            home_count = int((cell.get("h_a") == "h").sum())
            away_count = int((cell.get("h_a") == "a").sum())
            total = home_count + away_count
            rows.append(
                {
                    "xbin": xi,
                    "ybin": yi,
                    "home_touches": home_count,
                    "away_touches": away_count,
                    "total_touches": total,
                    "home_share_pct": round(home_count / total * 100, 1) if total else 50.0,
                }
            )
    return rows


def parse_qualifiers(raw: Any) -> list[dict[str, Any]]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def related_event_ids(row: pd.Series) -> set[str]:
    ids = set()
    for q in parse_qualifiers(row.get("qualifiers")):
        if q.get("type") in {"RelatedEventId", "OppositeRelatedEvent"} and q.get("value") is not None:
            ids.add(str(q.get("value")))
    direct = row.get("relatedEventId")
    if direct is not None and pd.notna(direct):
        ids.add(str(int(direct)) if isinstance(direct, float) else str(direct))
    return ids


def is_intentional_assist(row: pd.Series) -> bool:
    if str(row.get("assist")).lower() == "true" or str(row.get("intentionalAssist")).lower() == "true":
        return True
    return any(q.get("type") in {"IntentionalAssist", "Assisted"} for q in parse_qualifiers(row.get("qualifiers")))


def build_goal_chains(bundle: MatchBundle) -> list[dict[str, Any]]:
    events = bundle.events.reset_index(drop=True).copy()
    events["_sec"] = event_seconds(events)
    goal_rows = events[(events.get("type") == "Goal") | bool_col(events, "isGoal")]
    chains = []
    useful_types = {"Pass", "TakeOn", "BallTouch", "Carry", "Goal", "SavedShot"}
    break_types = {"Pass", "TakeOn", "BallTouch", "Clearance", "Interception", "BallRecovery", "Tackle"}

    for goal_index, goal in goal_rows.iterrows():
        h_a = clean_text(goal.get("h_a"))
        if h_a not in {"h", "a"}:
            continue
        goal_time = float(goal.get("_sec") or 0)
        chain_rows = []
        for idx in range(goal_index, -1, -1):
            row = events.loc[idx]
            row_h_a = clean_text(row.get("h_a"))
            event_type = clean_text(row.get("type"))
            row_time = float(row.get("_sec") or 0)
            if goal_time - row_time > 75:
                break
            if row_h_a == h_a:
                if event_type in useful_types or str(row.get("isShot")).lower() == "true":
                    chain_rows.append(row)
            elif row_h_a in {"h", "a"} and event_type in break_types:
                break
            if len(chain_rows) >= 18:
                break

        chain_rows = list(reversed(chain_rows))
        pass_rows = [r for r in chain_rows if clean_text(r.get("type")) == "Pass" and pd.notna(r.get("endX"))]
        distance = 0.0
        for row in pass_rows:
            distance += math.hypot((float(row["endX"]) - float(row["x"])) * 1.06, (float(row["endY"]) - float(row["y"])) * 0.68)
        start_time = float(chain_rows[0].get("_sec")) if chain_rows else goal_time
        goal_related = related_event_ids(goal)
        assist_row = None
        for row in reversed(pass_rows):
            if is_intentional_assist(row) or str(row.get("eventId")) in goal_related:
                assist_row = row
                break
        if assist_row is None and pass_rows:
            assist_row = pass_rows[-1]

        chains.append(
            {
                "team": team_name(bundle, h_a),
                "h_a": h_a,
                "minute": int(goal.get("minute")) if pd.notna(goal.get("minute")) else None,
                "second": int(goal.get("second")) if pd.notna(goal.get("second")) else 0,
                "scorer": clean_text(goal.get("playerName"), "Unknown scorer"),
                "passes": int(len(pass_rows)),
                "events": [compact_event(row) for row in chain_rows],
                "pass_distance_m": round(distance, 1),
                "duration_seconds": round(max(0.0, goal_time - start_time), 1),
                "assist_event_id": clean_text(assist_row.get("eventId")) if assist_row is not None else "",
            }
        )
    return chains


def compact_event(row: pd.Series) -> dict[str, Any]:
    payload = {
        "eventId": clean_text(row.get("eventId")),
        "type": clean_text(row.get("type")),
        "player": clean_text(row.get("playerName"), "Unknown"),
        "minute": int(row.get("minute")) if pd.notna(row.get("minute")) else None,
        "second": int(row.get("second")) if pd.notna(row.get("second")) else None,
        "x": round(float(row.get("x")), 2) if pd.notna(row.get("x")) else None,
        "y": round(float(row.get("y")), 2) if pd.notna(row.get("y")) else None,
        "endX": round(float(row.get("endX")), 2) if pd.notna(row.get("endX")) else None,
        "endY": round(float(row.get("endY")), 2) if pd.notna(row.get("endY")) else None,
    }
    return payload


def detect_data_health(bundle: MatchBundle) -> dict[str, Any]:
    events = bundle.events
    has_xg = any(col.lower() in {"xg", "expectedgoals", "expected_goals"} for col in events.columns)
    has_xgot = any(col.lower() in {"xgot", "expectedgoalsontarget", "expected_goals_on_target"} for col in events.columns)
    has_epv = "EPV" in events.columns or "EPV" in bundle.passes.columns
    return {
        "event_rows": int(len(events)),
        "pass_rows": int(len(bundle.passes)),
        "shot_rows_from_events": int(bool_col(events, "isShot").sum()),
        "touch_rows": int(len(bundle.touches)),
        "has_coordinates": {"x", "y"}.issubset(events.columns),
        "has_pass_end_coordinates": {"endX", "endY"}.issubset(events.columns),
        "has_goal_mouth_coordinates": {"goalMouthY", "goalMouthZ"}.issubset(events.columns),
        "has_vendor_xg": has_xg,
        "has_vendor_xgot": has_xgot,
        "has_epv": has_epv,
        "unsupported_claims": [
            "vendor_xg" if not has_xg else "",
            "vendor_xgot" if not has_xgot else "",
        ],
    }


def build_audit(bundle: MatchBundle) -> dict[str, Any]:
    stats = build_team_stats(bundle)
    momentum = build_momentum(bundle)
    field_tilt = build_field_tilt(bundle)
    goal_chains = build_goal_chains(bundle)
    zones = build_zone_control(bundle)
    health = detect_data_health(bundle)

    facts = []
    home_stats = stats[bundle.home]
    away_stats = stats[bundle.away]
    facts.append(f"{bundle.home} vs {bundle.away} finished {bundle.score}.")
    facts.append(
        f"Pass-share possession proxy: {bundle.home} {home_stats['pass_share_pct']}%, "
        f"{bundle.away} {away_stats['pass_share_pct']}%."
    )
    facts.append(
        f"Shots: {bundle.home} {home_stats['shots']} ({home_stats['shots_on_target']} on target), "
        f"{bundle.away} {away_stats['shots']} ({away_stats['shots_on_target']} on target)."
    )
    facts.append(
        f"Final-third passes: {bundle.home} {home_stats['final_third_passes']}, "
        f"{bundle.away} {away_stats['final_third_passes']}."
    )
    if goal_chains:
        chain = max(goal_chains, key=lambda c: c["passes"])
        facts.append(
            f"Longest goal chain: {chain['team']} goal by {chain['scorer']} at "
            f"{chain['minute']}:{chain['second']:02d}, {chain['passes']} passes, "
            f"{chain['pass_distance_m']} meters of passing, {chain['duration_seconds']} seconds."
        )
    if not health["has_vendor_xg"] or not health["has_vendor_xgot"]:
        facts.append("Vendor xG/xGOT are not present in the local WhoScored export, so xG claims are blocked.")

    return {
        "match": {
            "match_dir": str(bundle.match_dir),
            "home": bundle.home,
            "away": bundle.away,
            "score": bundle.score,
            "startDate": bundle.summary.get("startDate"),
            "league": bundle.summary.get("league"),
            "competitionStage": bundle.summary.get("competitionStage"),
        },
        "data_health": health,
        "team_stats": stats,
        "momentum": momentum,
        "field_tilt": field_tilt,
        "zone_control": zones,
        "goal_chains": goal_chains,
        "facts": facts,
        "definitions": {
            "pass_share_possession_proxy": "Team pass attempts divided by total pass attempts in the export. This is not official broadcast possession.",
            "pressure_index": "A transparent weighted count of attacks: final-third passes, box entries, shots, goals, corners, attacking recoveries and successful take-ons.",
            "field_tilt": "Share of final-third passes in each time bucket.",
        },
    }


def visualization_candidates(audit: dict[str, Any]) -> list[dict[str, Any]]:
    stats = audit["team_stats"]
    teams = list(stats)
    home, away = teams[0], teams[1]
    home_stats = stats[home]
    away_stats = stats[away]
    goals = audit["goal_chains"]
    momentum = audit["momentum"]
    field_tilt = audit["field_tilt"]
    health = audit["data_health"]
    total_shots = home_stats["shots"] + away_stats["shots"]
    max_saves = max(home_stats["saves"], away_stats["saves"])
    pass_gap = abs(home_stats["pass_share_pct"] - away_stats["pass_share_pct"])
    max_swing = max([abs(row["swing"]) for row in momentum] or [0])
    max_tilt = max([max(row["home_tilt_pct"], row["away_tilt_pct"]) for row in field_tilt] or [50])

    candidates = [
        {
            "id": "goal_chain",
            "title": "Goal Chain Chalkboard",
            "available": bool(goals),
            "score": 95 if goals else 0,
            "reason": "Plots the exact event coordinates before the goal.",
        },
        {
            "id": "momentum_pendulum",
            "title": "Momentum Pendulum",
            "available": bool(momentum),
            "score": 60 + min(30, max_swing),
            "reason": "Shows when pressure swung using a transparent event-weighted index.",
        },
        {
            "id": "zone_control",
            "title": "18-Zone Touch Control",
            "available": bool(audit["zone_control"]),
            "score": 70 + min(20, max_tilt - 50),
            "reason": "Uses every touch coordinate to show territorial control.",
        },
        {
            "id": "shot_map",
            "title": "Shot Map",
            "available": total_shots > 0,
            "score": 55 + total_shots,
            "reason": "Maps all shots and separates goals, saves, misses and blocks.",
        },
        {
            "id": "goalmouth_wall",
            "title": "Goalmouth Wall",
            "available": health["has_goal_mouth_coordinates"] and max_saves > 0,
            "score": 55 + max_saves * 4,
            "reason": "Plots goal-mouth placement for goals and saved shots. No xGOT claim without xGOT data.",
        },
        {
            "id": "pass_network",
            "title": "Pass Network",
            "available": max(home_stats["pass_attempts"], away_stats["pass_attempts"]) >= 80,
            "score": 45 + pass_gap,
            "reason": "Highlights circulation and whether possession reached advanced players.",
        },
        {
            "id": "sterile_domination",
            "title": "Sterile Domination Check",
            "available": max(home_stats["pass_share_pct"], away_stats["pass_share_pct"]) >= 58,
            "score": 60 + pass_gap,
            "reason": "Compares pass share with final-third and box presence.",
        },
        {
            "id": "xg_xgot_robbery",
            "title": "xG vs xGOT Robbery Indicator",
            "available": health["has_vendor_xg"] and health["has_vendor_xgot"],
            "score": 20,
            "reason": "Blocked unless external enrichment supplies shot-level xG and xGOT.",
        },
    ]
    return candidates


def select_visualizations(audit: dict[str, Any], count: int, use_gemini: bool, instruction: str = "") -> list[dict[str, Any]]:
    candidates = visualization_candidates(audit)
    selected_ids: list[str] | None = None
    if use_gemini:
        selected_ids = select_with_gemini(audit, candidates, count, instruction)
    if not selected_ids:
        available = [c for c in candidates if c["available"]]
        available.sort(key=lambda c: c["score"], reverse=True)
        selected_ids = [c["id"] for c in available[:count]]
    by_id = {c["id"]: c for c in candidates}
    return [by_id[viz_id] for viz_id in selected_ids if viz_id in by_id and by_id[viz_id]["available"]][:count]


def select_with_gemini(audit: dict[str, Any], candidates: list[dict[str, Any]], count: int, instruction: str) -> list[str] | None:
    if not os.getenv("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
    except Exception:
        return None

    prompt = {
        "task": "Choose the best football match visualizations. Return strict JSON only.",
        "rules": [
            "Choose only available candidates.",
            "Do not choose xG/xGOT unless vendor xG and xGOT exist.",
            "Every reason must be grounded in the supplied audit.",
            f"Return exactly {count} visualization ids.",
        ],
        "user_instruction": instruction,
        "facts": audit["facts"],
        "data_health": audit["data_health"],
        "team_stats": audit["team_stats"],
        "candidates": candidates,
        "schema": {"selected": ["candidate_id"], "reason": "short grounded explanation"},
    }

    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    client = genai.Client()
    raw = ""
    try:
        if hasattr(client, "interactions"):
            response = client.interactions.create(model=model, input=json.dumps(prompt, ensure_ascii=False))
            raw = response.output_text
        else:
            response = client.models.generate_content(model=model, contents=json.dumps(prompt, ensure_ascii=False))
            raw = response.text
        parsed = json.loads(extract_json(raw))
        selected = parsed.get("selected", [])
        available = {c["id"] for c in candidates if c["available"]}
        selected = [str(item) for item in selected if str(item) in available]
        return selected[:count] if selected else None
    except Exception as exc:
        print(f"[Gemini] Visualization selection fallback: {exc}")
        return None


def extract_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


def ask_approval(stage: str, details: str, auto: bool) -> str:
    print(f"\n[{stage}]\n{details}")
    if auto:
        print("Auto-approved.")
        return "ok"
    while True:
        raw = input("Action: [ok] approve, [change], [redo], [reject], [quit]: ").strip().lower()
        if raw in {"ok", "change", "redo", "reject", "quit"}:
            return raw
        print("Please type ok, change, redo, reject, or quit.")


def summarize_candidates(candidates: list[dict[str, Any]]) -> str:
    lines = []
    for cand in candidates:
        mark = "YES" if cand["available"] else "NO"
        lines.append(f"- {cand['id']} [{mark}, score {cand['score']}]: {cand['reason']}")
    return "\n".join(lines)


def summarize_selected(selected: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {item['id']}: {item['title']} - {item['reason']}" for item in selected)


def build_storyboard(bundle: MatchBundle, audit: dict[str, Any], selected: list[dict[str, Any]], use_gemini: bool, instruction: str = "") -> list[dict[str, Any]]:
    gemini_scenes = build_storyboard_with_gemini(bundle, audit, selected, instruction) if use_gemini else None
    if gemini_scenes:
        return gemini_scenes

    stats = audit["team_stats"]
    home = stats[bundle.home]
    away = stats[bundle.away]
    winner = infer_result_line(bundle, stats)
    scenes = [
        {
            "id": "title",
            "title": f"{bundle.home} {bundle.score} {bundle.away}",
            "visualization": "title",
            "narration": (
                "Fifty-two seconds. Seventeen passes. Morocco built the goal before Scotland could breathe."
            ),
        },
        {
            "id": "standard_stats",
            "title": "Baseline Match Data",
            "visualization": "standard_stats",
            "narration": (
                f"The receipts back it up: {bundle.away} led pass share, shots, and final-third entries."
            ),
        },
    ]

    for item in selected:
        viz_id = item["id"]
        scenes.append(
            {
                "id": viz_id,
                "title": item["title"],
                "visualization": viz_id,
                "narration": narration_for_visual(bundle, audit, viz_id),
            }
        )

    scenes.append(
        {
            "id": "close",
            "title": "What The Data Supports",
            "visualization": "close",
            "narration": (
                "No invented xG. No vibes dressed as numbers. Just the event feed."
            ),
        }
    )
    return scenes


def build_storyboard_with_gemini(bundle: MatchBundle, audit: dict[str, Any], selected: list[dict[str, Any]], instruction: str) -> list[dict[str, Any]] | None:
    if not os.getenv("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
    except Exception:
        return None

    prompt = {
        "task": "Write concise narrated scenes for a football analytics short. Return strict JSON only.",
        "rules": [
            "Do not invent data.",
            "Every numerical claim must come from the audit.",
            "If xG or xGOT is unavailable, explicitly say unavailable rather than estimating it.",
            "Keep each scene narration 30 to 55 words.",
            "Keep a punchy analytical tone for YouTube/TikTok.",
        ],
        "user_instruction": instruction,
        "match": audit["match"],
        "facts": audit["facts"],
        "team_stats": audit["team_stats"],
        "selected_visualizations": selected,
        "schema": [
            {"id": "title", "title": "string", "visualization": "title", "narration": "string"},
            {"id": "standard_stats", "title": "string", "visualization": "standard_stats", "narration": "string"},
        ],
    }

    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    client = genai.Client()
    try:
        if hasattr(client, "interactions"):
            response = client.interactions.create(model=model, input=json.dumps(prompt, ensure_ascii=False))
            raw = response.output_text
        else:
            response = client.models.generate_content(model=model, contents=json.dumps(prompt, ensure_ascii=False))
            raw = response.text
        parsed = json.loads(extract_json(raw))
        scenes = parsed.get("scenes", parsed if isinstance(parsed, list) else [])
        allowed = {"title", "standard_stats", "close"} | {item["id"] for item in selected}
        clean_scenes = []
        for scene in scenes:
            viz = scene.get("visualization") or scene.get("id")
            if viz in allowed and scene.get("narration"):
                clean_scenes.append(
                    {
                        "id": scene.get("id", viz),
                        "title": scene.get("title", viz.replace("_", " ").title()),
                        "visualization": viz,
                        "narration": scene["narration"],
                    }
                )
        return clean_scenes or None
    except Exception as exc:
        print(f"[Gemini] Script fallback: {exc}")
        return None


def infer_result_line(bundle: MatchBundle, stats: dict[str, Any]) -> str:
    parts = re.findall(r"\d+", bundle.score)
    if len(parts) >= 2:
        h_goals, a_goals = int(parts[0]), int(parts[1])
        if h_goals > a_goals:
            return f"{bundle.home} won it, but the why matters more than the scoreline."
        if a_goals > h_goals:
            return f"{bundle.away} won it, and the event map shows how the game tilted."
    return "The match was level on the scoreboard, so control and chance geography matter."


def narration_for_visual(bundle: MatchBundle, audit: dict[str, Any], viz_id: str) -> str:
    stats = audit["team_stats"]
    home = stats[bundle.home]
    away = stats[bundle.away]
    if viz_id == "goal_chain" and audit["goal_chains"]:
        chain = max(audit["goal_chains"], key=lambda c: c["passes"])
        return (
            f"Watch the chain: {chain['passes']} passes, {chain['pass_distance_m']} metres, one finish."
        )
    if viz_id == "momentum_pendulum":
        biggest = max(audit["momentum"], key=lambda row: abs(row["swing"]))
        leader = bundle.home if biggest["swing"] > 0 else bundle.away
        return (
            f"The pressure spike came in {biggest['minute_block']}. The goal chain told us where the game was going."
        )
    if viz_id == "zone_control":
        return (
            "The touch map shows where the match actually lived."
        )
    if viz_id == "shot_map":
        return (
            f"The shot map separates volume and geography: {bundle.home} took {home['shots']} shots, "
            f"{bundle.away} took {away['shots']}. Goals, saves, misses and blocks stay distinct."
        )
    if viz_id == "goalmouth_wall":
        keeper_team = bundle.home if home["saves"] >= away["saves"] else bundle.away
        return (
            f"The goalmouth view focuses on shot placement against {keeper_team}. Because xGOT is missing, "
            "the chart avoids any xGOT claim."
        )
    if viz_id == "pass_network":
        dominant = bundle.home if home["pass_attempts"] >= away["pass_attempts"] else bundle.away
        return (
            f"The pass network asks whether {dominant}'s circulation connected into useful zones or stayed safe. "
            "Nodes and edges come from observed successful pass sequences."
        )
    if viz_id == "sterile_domination":
        dominant = bundle.home if home["pass_share_pct"] >= away["pass_share_pct"] else bundle.away
        dom = home if dominant == bundle.home else away
        return (
            f"{dominant} had {dom['pass_share_pct']} percent of pass share. The test is whether it became "
            "final-third passes and box touches."
        )
    return "This scene is generated only from verified event data in the local export."


def scene_data_points(scene: dict[str, Any], audit: dict[str, Any]) -> int:
    viz = scene.get("visualization")
    if viz == "goal_chain" and audit["goal_chains"]:
        return len(max(audit["goal_chains"], key=lambda c: c["passes"])["events"])
    if viz == "momentum_pendulum":
        return len(audit["momentum"])
    if viz == "zone_control":
        return len(audit["zone_control"])
    if viz == "shot_map":
        return audit["data_health"].get("shot_rows_from_events", 0)
    if viz == "standard_stats":
        return 9
    if viz in {"goalmouth_wall", "pass_network", "sterile_domination"}:
        return 12
    return 0


def scene_duration(scene: dict[str, Any], audit: dict[str, Any]) -> float:
    viz = scene.get("visualization")
    if viz == "title":
        return 2.0
    if viz == "close":
        return 2.4
    if viz == "standard_stats":
        return 2.8
    if viz == "goal_chain":
        return 4.8
    if viz in {"momentum_pendulum", "zone_control"}:
        return 3.2
    points = scene_data_points(scene, audit)
    return round(max(2.5, min(6.0, 2.0 + 0.05 * points)), 2)


def render_storyboard(bundle: MatchBundle, audit: dict[str, Any], scenes: list[dict[str, Any]], assets_dir: Path) -> list[dict[str, Any]]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for idx, scene in enumerate(scenes, 1):
        viz = scene["visualization"]
        path = assets_dir / f"{idx:02d}_{safe_name(viz)}.png"
        renderer = RENDERERS.get(viz, render_close_card)
        renderer(bundle, audit, scene, path)
        rendered.append({**scene, "asset": str(path), "duration": scene_duration(scene, audit)})
    return rendered


def add_fig_rect(fig: plt.Figure, x: float, y: float, w: float, h: float, color: str, alpha: float = 1.0, zorder: int = 0) -> None:
    fig.patches.append(
        Rectangle((x, y), w, h, transform=fig.transFigure, facecolor=color, edgecolor="none", alpha=alpha, zorder=zorder)
    )


def new_figure(title: str, subtitle: str = "", design: dict[str, Any] | None = None) -> plt.Figure:
    palette = design or match_design(MatchBundle(Path(), {"home": {"name": ""}, "away": {"name": ""}}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()))
    fig = plt.figure(figsize=(9, 16), dpi=120, facecolor=palette["background"])
    add_fig_rect(fig, 0, 0, 1, 1, "#070806", 0.20, zorder=0)
    if title:
        fig.text(
            0.055,
            0.955,
            title.upper(),
            color=MUTED,
            fontsize=10.5,
            fontweight="bold",
            family=MONO_FONT,
            va="top",
            ha="left",
        )
    if subtitle:
        fig.text(0.058, 0.935, subtitle.upper(), color=MUTED, fontsize=8.5, family=MONO_FONT, va="top", ha="left", alpha=0.8)
    return fig


def add_footer(fig: plt.Figure, text: str = "Data: WhoScored/Opta embedded event feed | Computed locally") -> None:
    fig.text(0.055, 0.024, text, color=MUTED, fontsize=8.5, family=MONO_FONT, ha="left", va="bottom", zorder=20)


def wrapped_fig_text(
    fig: plt.Figure,
    x: float,
    y: float,
    text: str,
    width: int = 48,
    size: int = 16,
    color: str = WHITE,
    weight: str = "normal",
) -> None:
    fig.text(
        x,
        y,
        textwrap.fill(text, width),
        color=color,
        fontsize=size,
        fontweight=weight,
        family=BODY_FONT,
        ha="left",
        va="top",
        linespacing=1.12,
        zorder=18,
    )


def add_caption_scrim(fig: plt.Figure, text: str, height: float = 0.205) -> None:
    add_fig_rect(fig, 0, 0, 1, height, SCRIM, 0.94, zorder=10)
    wrapped_fig_text(fig, 0.055, height - 0.045, text, width=54, size=18, color=WHITE, weight="bold")


def ticker_text(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any]) -> str:
    health = audit["data_health"]
    return (
        f"{scene.get('visualization', '').upper()} / {bundle.home} v {bundle.away} / SCORE {bundle.score} / "
        f"EVENTS {health.get('event_rows', 0)} / PASSES {health.get('pass_rows', 0)} / "
        f"TOUCHES {health.get('touch_rows', 0)}"
    )


def add_data_ticker(fig: plt.Figure, bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], design: dict[str, Any]) -> None:
    add_fig_rect(fig, 0, 0, 0.026, 1, "#060806", 1.0, zorder=12)
    fig.text(
        0.013,
        0.50,
        ticker_text(bundle, audit, scene),
        color=design["away"]["accent"],
        fontsize=8.4,
        family=MONO_FONT,
        rotation=90,
        ha="center",
        va="center",
        alpha=0.92,
        zorder=20,
    )


def add_watermark(fig: plt.Figure, design: dict[str, Any]) -> None:
    fig.text(
        0.945,
        0.962,
        "MATCH RECEIPTS",
        color=MUTED,
        fontsize=8.5,
        family=MONO_FONT,
        ha="right",
        va="center",
        alpha=0.80,
        zorder=20,
    )


def finish_scene(fig: plt.Figure, bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], design: dict[str, Any], path: Path) -> None:
    add_watermark(fig, design)
    save_fig(fig, path)


def text_effects() -> list[Any]:
    return [pe.withStroke(linewidth=2.5, foreground=BG)]


def draw_pitch_lines(ax: plt.Axes, line_color: str = LINE, lw: float = 1.8) -> None:
    ax.add_patch(Rectangle((0, 0), 100, 100, fill=False, lw=lw + 0.3, ec=line_color, alpha=0.92, zorder=8))
    ax.plot([50, 50], [0, 100], color=line_color, lw=lw, alpha=0.78, zorder=8)
    ax.add_patch(Circle((50, 50), 9, fill=False, ec=line_color, lw=lw - 0.2, alpha=0.78, zorder=8))
    ax.scatter([50], [50], s=14, c=line_color, alpha=0.85, zorder=9)
    for x0, side in ((0, 1), (100, -1)):
        ax.add_patch(Rectangle((x0 if side == 1 else 84, 21), 16, 58, fill=False, lw=lw - 0.1, ec=line_color, alpha=0.88, zorder=8))
        ax.add_patch(Rectangle((x0 if side == 1 else 94.5, 36.5), 5.5, 27, fill=False, lw=lw - 0.35, ec=line_color, alpha=0.85, zorder=8))
        ax.scatter([11 if side == 1 else 89], [50], s=12, c=line_color, alpha=0.84, zorder=9)
        ax.add_patch(Rectangle((-1.7 if side == 1 else 100, 44), 1.7, 12, fill=False, lw=lw, ec=line_color, alpha=0.9, zorder=8))


def draw_pitch(ax: plt.Axes, pitch_color: str = PITCH, line_color: str = LINE) -> None:
    ax.set_facecolor(pitch_color)
    ax.set_xlim(-2, 102)
    ax.set_ylim(-2, 102)
    ax.set_aspect("equal")
    ax.axis("off")
    for i in range(8):
        if i % 2 == 0:
            ax.add_patch(Rectangle((0, i * 12.5), 100, 12.5, facecolor="#111811", edgecolor="none", alpha=0.36, zorder=0))
    ax.add_patch(Rectangle((0, 0), 100, 100, facecolor="#0d130d", edgecolor="none", alpha=0.62, zorder=0))
    draw_pitch_lines(ax, line_color=line_color)


def score_parts(score: str) -> tuple[str, str] | None:
    parts = re.findall(r"\d+", score)
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def add_fig_outline_rect(
    fig: plt.Figure,
    x: float,
    y: float,
    w: float,
    h: float,
    face: str,
    edge: str,
    alpha: float = 1.0,
    zorder: int = 5,
    linewidth: float = 1.1,
) -> None:
    fig.patches.append(
        Rectangle(
            (x, y),
            w,
            h,
            transform=fig.transFigure,
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            alpha=alpha,
            zorder=zorder,
        )
    )


def add_fig_polygon(
    fig: plt.Figure,
    points: list[tuple[float, float]],
    face: str,
    edge: str = "none",
    alpha: float = 1.0,
    zorder: int = 7,
    linewidth: float = 0.0,
    fill: bool = True,
) -> None:
    fig.patches.append(
        Polygon(
            points,
            closed=True,
            transform=fig.transFigure,
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            alpha=alpha,
            zorder=zorder,
            fill=fill,
        )
    )


def draw_scotland_flag(fig: plt.Figure, x: float, y: float, w: float, h: float, zorder: int = 7) -> None:
    add_fig_outline_rect(fig, x, y, w, h, "#005eb8", WHITE, 1.0, zorder=zorder, linewidth=0.7)
    add_fig_polygon(
        fig,
        [(x, y + h * 0.07), (x + w * 0.07, y), (x + w, y + h * 0.93), (x + w * 0.93, y + h)],
        WHITE,
        zorder=zorder + 1,
    )
    add_fig_polygon(
        fig,
        [(x + w * 0.93, y), (x + w, y + h * 0.07), (x + w * 0.07, y + h), (x, y + h * 0.93)],
        WHITE,
        zorder=zorder + 1,
    )


def morocco_star_points(cx: float, cy: float, rx: float, ry: float) -> list[tuple[float, float]]:
    outer = []
    for i in range(5):
        angle = -math.pi / 2 + i * 2 * math.pi / 5
        outer.append((cx + math.cos(angle) * rx, cy + math.sin(angle) * ry))
    return [outer[i] for i in (0, 2, 4, 1, 3, 0)]


def draw_morocco_flag(fig: plt.Figure, x: float, y: float, w: float, h: float, zorder: int = 7) -> None:
    add_fig_outline_rect(fig, x, y, w, h, "#c1272d", WHITE, 1.0, zorder=zorder, linewidth=0.7)
    add_fig_polygon(
        fig,
        morocco_star_points(x + w * 0.50, y + h * 0.52, w * 0.17, h * 0.24),
        "none",
        edge="#0a8f45",
        zorder=zorder + 1,
        linewidth=1.8,
        fill=False,
    )


def draw_generic_flag(fig: plt.Figure, x: float, y: float, w: float, h: float, color: str, zorder: int = 7) -> None:
    add_fig_outline_rect(fig, x, y, w, h, color, WHITE, 1.0, zorder=zorder, linewidth=0.7)
    add_fig_rect(fig, x, y, w, h * 0.5, "#f7f8f1", 0.18, zorder=zorder + 1)


def draw_team_flag(fig: plt.Figure, team: str, x: float, y: float, w: float, h: float, color: str, zorder: int = 7) -> None:
    key = normalize_team_key(team)
    if key == "scotland":
        draw_scotland_flag(fig, x, y, w, h, zorder)
    elif key == "morocco":
        draw_morocco_flag(fig, x, y, w, h, zorder)
    else:
        draw_generic_flag(fig, x, y, w, h, color, zorder)


def draw_intro_team_badge(fig: plt.Figure, team: str, x: float, y: float, flag_x: float, color: str, align: str) -> None:
    flag_w, flag_h = 0.088, 0.054
    add_fig_outline_rect(fig, flag_x - 0.008, y - 0.008, flag_w + 0.016, flag_h + 0.016, "#090c09", color, 0.96, zorder=4, linewidth=1.0)
    draw_team_flag(fig, team, flag_x, y, flag_w, flag_h, color, zorder=6)
    fig.text(
        x,
        y + flag_h * 0.52,
        team.upper(),
        color=color,
        fontsize=20,
        fontweight="bold",
        family=DISPLAY_FONT,
        ha=align,
        va="center",
        zorder=12,
    )


def best_goal_chain(audit: dict[str, Any]) -> dict[str, Any] | None:
    if not audit["goal_chains"]:
        return None
    return max(audit["goal_chains"], key=lambda c: c["passes"])


def hook_stat_line(audit: dict[str, Any]) -> str:
    chain = best_goal_chain(audit)
    if chain:
        return f"{chain['passes']} PASSES. {chain['pass_distance_m']}M. {chain['duration_seconds']} SEC."
    return "PASS SHARE. SHOTS. TERRITORY. CHAIN."


def fmt_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.1f}" if value % 1 else f"{int(value)}"
    return str(value)


def draw_value_bar(fig: plt.Figure, x: float, y: float, w: float, color: str, value: float, maximum: float) -> None:
    add_fig_rect(fig, x, y, w, 0.010, "#20251f", 1.0, zorder=4)
    add_fig_rect(fig, x, y, w * min(1.0, value / max(1.0, maximum)), 0.010, color, 0.98, zorder=5)


def draw_impact_burst(ax: plt.Axes, x: float, y: float, color: str) -> None:
    for radius, alpha, width in ((2.2, 0.95, 2.4), (4.2, 0.48, 1.8), (6.6, 0.22, 1.2)):
        ax.add_patch(Circle((x, y), radius, fill=False, ec=color, lw=width, alpha=alpha, zorder=11))
    for angle in np.linspace(0, 2 * np.pi, 10, endpoint=False):
        ax.plot(
            [x + math.cos(angle) * 2.8, x + math.cos(angle) * 7.0],
            [y + math.sin(angle) * 2.8, y + math.sin(angle) * 7.0],
            color=color,
            lw=1.5,
            alpha=0.65,
            zorder=11,
        )


def render_title_card(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("", "", design)
    ax = fig.add_axes([0.035, 0.180, 0.93, 0.610])
    draw_pitch(ax, "#080d08", "#566052")
    ax.patch.set_alpha(0.20)
    for artist in ax.get_children():
        try:
            artist.set_alpha(min(float(artist.get_alpha() or 1), 0.22))
        except Exception:
            pass
    home_color = design["home"]["display"]
    away_color = design["away"]["display"]
    parts = score_parts(bundle.score)
    chain = best_goal_chain(audit)
    hero = f"{chain['duration_seconds']:.1f}" if chain else "90"
    sub = f"{chain['passes']} PASSES" if chain else "EVENT DATA"
    fig.text(0.055, 0.895, "OPENING RECEIPT", color=MUTED, fontsize=9.5, family=MONO_FONT, ha="left", alpha=0.75)
    fig.text(0.945, 0.895, f"{bundle.home[:3].upper()} v {bundle.away[:3].upper()}", color=MUTED, fontsize=9.5, family=MONO_FONT, ha="right", alpha=0.75)
    fig.text(0.500, 0.770, hero, color=WHITE, fontsize=176, fontweight="bold", family=DISPLAY_FONT, ha="center", va="center")
    fig.text(0.500, 0.655, "SECONDS", color=away_color, fontsize=45, fontweight="bold", family=DISPLAY_FONT, ha="center", va="center")
    fig.text(0.500, 0.595, sub, color=WHITE, fontsize=26, fontweight="bold", family=DISPLAY_FONT, ha="center", va="center")
    if parts:
        add_fig_rect(fig, 0.085, 0.413, 0.830, 0.078, "#070907", 0.88, zorder=3)
        draw_intro_team_badge(fig, bundle.home, 0.197, 0.425, 0.094, home_color, "left")
        draw_intro_team_badge(fig, bundle.away, 0.803, 0.425, 0.818, away_color, "right")
        fig.text(
            0.500,
            0.456,
            f"{parts[0]}-{parts[1]}",
            color=WHITE,
            fontsize=56,
            fontweight="bold",
            family=DISPLAY_FONT,
            ha="center",
            va="center",
            zorder=12,
        )
    fig.text(0.500, 0.335, "MOROCCO BUILT THIS", color=away_color, fontsize=32, fontweight="bold", family=DISPLAY_FONT, ha="center")
    fig.text(0.500, 0.292, "NOT A HIGHLIGHT. A RECEIPT.", color=WHITE, fontsize=16, family=MONO_FONT, ha="center", alpha=0.92)
    finish_scene(fig, bundle, audit, scene, design, path)


def render_standard_stats(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("", "", design)
    stats = audit["team_stats"]
    home = stats[bundle.home]
    away = stats[bundle.away]
    metrics = [
        ("PASS SHARE", f"{home['pass_share_pct']}", f"{away['pass_share_pct']}", "% of attempts"),
        ("SHOTS", f"{home['shots']}", f"{away['shots']}", "total attempts"),
        ("FINAL THIRD", f"{home['final_third_passes']}", f"{away['final_third_passes']}", "passes"),
    ]
    home_color = design["home"]["display"]
    away_color = design["away"]["display"]
    fig.text(0.055, 0.855, "THE RECEIPTS", color=WHITE, fontsize=52, fontweight="bold", family=DISPLAY_FONT, ha="left")
    fig.text(0.058, 0.812, "THREE CHECKS BEFORE THE CHALKBOARD", color=MUTED, fontsize=12, family=MONO_FONT, ha="left")
    fig.text(0.465, 0.735, bundle.home.upper(), color=home_color, fontsize=13, fontweight="bold", family=DISPLAY_FONT, ha="right")
    fig.text(0.585, 0.735, bundle.away.upper(), color=away_color, fontsize=13, fontweight="bold", family=DISPLAY_FONT, ha="left")

    y = 0.615
    for label, hv, av, note in metrics:
        add_fig_rect(fig, 0.055, y - 0.068, 0.89, 0.112, "#10140f", 0.96, zorder=2)
        fig.text(0.090, y + 0.018, label, color=WHITE, fontsize=18, fontweight="bold", family=DISPLAY_FONT, ha="left", va="center", zorder=7)
        fig.text(0.090, y - 0.026, note.upper(), color=MUTED, fontsize=9.5, family=MONO_FONT, ha="left", va="center", zorder=7)
        fig.text(0.465, y - 0.003, hv, color=home_color, fontsize=45, fontweight="bold", family=DISPLAY_FONT, ha="right", va="center", zorder=7)
        fig.text(0.525, y - 0.003, "/", color=MUTED, fontsize=25, fontweight="bold", family=DISPLAY_FONT, ha="center", va="center", zorder=7)
        fig.text(0.585, y - 0.003, av, color=away_color, fontsize=45, fontweight="bold", family=DISPLAY_FONT, ha="left", va="center", zorder=7)
        y -= 0.160

    fig.text(0.055, 0.205, "MOROCCO LED THE KEY RECEIPTS.", color=away_color, fontsize=28, fontweight="bold", family=DISPLAY_FONT, ha="left")

    finish_scene(fig, bundle, audit, scene, design, path)


def render_goal_chain(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("", "", design)
    ax = fig.add_axes([0.040, 0.135, 0.92, 0.690])
    draw_pitch(ax, design["pitch"], design["line"])
    chain = max(audit["goal_chains"], key=lambda c: c["passes"]) if audit["goal_chains"] else None
    if not chain:
        wrapped_fig_text(fig, 0.08, 0.70, "No goal chain available in this export.")
        finish_scene(fig, bundle, audit, scene, design, path)
        return

    color = team_color(chain["h_a"], design)
    side = "home" if chain["h_a"] == "h" else "away"
    accent = design[side]["accent"]
    events = chain["events"]
    pass_events = [event for event in events if event["type"] == "Pass" and event["x"] is not None and event["endX"] is not None]
    for idx, event in enumerate(pass_events):
        progress = (idx + 1) / max(1, len(pass_events))
        start = (event["x"], event["y"])
        end = (event["endX"], event["endY"])
        is_assist = str(event.get("eventId")) == str(chain.get("assist_event_id"))
        arrow_color = accent if is_assist else color
        arrow = FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=22 if is_assist else 12,
            lw=5.0 if is_assist else 2.7,
            color=arrow_color,
            alpha=0.98 if is_assist else 0.28 + progress * 0.55,
            zorder=6 if is_assist else 4,
        )
        ax.add_patch(arrow)
        ax.scatter([start[0]], [start[1]], s=26, color=WHITE, zorder=7, edgecolor=BG, linewidth=0.8)
        if idx in {0, len(pass_events) - 1}:
            ax.text(
                start[0],
                start[1] + 3.2,
                f"{idx + 1}",
                color=WHITE,
                fontsize=7.5,
                family=MONO_FONT,
                ha="center",
                va="bottom",
                path_effects=text_effects(),
                zorder=9,
            )
    goal_events = [ev for ev in events if ev["type"] == "Goal"]
    goal = goal_events[-1] if goal_events else events[-1]
    if goal["x"] is not None:
        draw_impact_burst(ax, goal["x"], goal["y"], DANGER)
        ax.scatter([goal["x"]], [goal["y"]], s=95, color=WHITE, edgecolor=DANGER, linewidth=2.2, zorder=12)

    fig.text(0.055, 0.895, "THE GOAL WAS BUILT", color=WHITE, fontsize=42, fontweight="bold", family=DISPLAY_FONT)
    fig.text(0.055, 0.852, f"{chain['team'].upper()} / {chain['scorer'].upper()}", color=color, fontsize=16, fontweight="bold", family=MONO_FONT)
    fig.text(
        0.055,
        0.075,
        f"{chain['passes']} PASSES   {chain['pass_distance_m']}M   {chain['duration_seconds']}S",
        color=WHITE,
        fontsize=34,
        fontweight="bold",
        family=DISPLAY_FONT,
    )
    fig.text(0.945, 0.086, f"{chain['minute']}:{chain['second']:02d}", color=accent, fontsize=18, family=MONO_FONT, ha="right", va="center")
    finish_scene(fig, bundle, audit, scene, design, path)


def render_zone_control(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("", "", design)
    ax = fig.add_axes([0.045, 0.190, 0.91, 0.610])
    draw_pitch(ax, design["pitch"], design["line"])
    zones = audit["zone_control"]
    by_cell = {(z["xbin"], z["ybin"]): z for z in zones}
    away_hot_cells = {
        (z["xbin"], z["ybin"])
        for z in sorted(zones, key=lambda item: (item["away_touches"] - item["home_touches"], item["away_touches"]), reverse=True)[:4]
    }
    x_step = 100 / 6
    y_step = 100 / 3
    max_home = max([z["home_touches"] for z in zones] or [1])
    max_away = max([z["away_touches"] for z in zones] or [1])
    home_color = design["home"]["display"]
    away_color = design["away"]["display"]
    for xi in range(6):
        for yi in range(3):
            z = by_cell.get((xi, yi), {"home_touches": 0, "away_touches": 0, "total_touches": 0, "home_share_pct": 50})
            x0 = xi * x_step
            y0 = yi * y_step
            x1 = x0 + x_step
            y1 = y0 + y_step
            home_alpha = 0.18 + 0.62 * (z["home_touches"] / max(1, max_home))
            away_alpha = 0.18 + 0.62 * (z["away_touches"] / max(1, max_away))
            ax.add_patch(Polygon([(x0, y0), (x1, y0), (x0, y1)], closed=True, facecolor=home_color, edgecolor="none", alpha=home_alpha, zorder=1))
            ax.add_patch(Polygon([(x1, y1), (x1, y0), (x0, y1)], closed=True, facecolor=away_color, edgecolor="none", alpha=away_alpha, zorder=1))
            ax.add_patch(Rectangle((x0, y0), x_step, y_step, facecolor="none", edgecolor=GRID, lw=1.0, alpha=0.85, zorder=7))
            if (xi, yi) in away_hot_cells:
                ax.add_patch(Rectangle((x0 + 1.0, y0 + 1.0), x_step - 2.0, y_step - 2.0, facecolor="none", edgecolor=away_color, lw=2.2, alpha=0.95, zorder=12))
                ax.text(
                    x0 + x_step * 0.62,
                    y0 + y_step * 0.55,
                    f"{z['away_touches']}",
                    color=WHITE,
                    ha="center",
                    va="center",
                    fontsize=13.5,
                    fontweight="bold",
                    family=DISPLAY_FONT,
                    path_effects=text_effects(),
                    zorder=13,
                )
    draw_pitch_lines(ax, design["line"])
    fig.text(0.055, 0.875, "THE GAME LIVED HERE", color=WHITE, fontsize=42, fontweight="bold", family=DISPLAY_FONT)
    fig.text(0.055, 0.835, f"{bundle.home.upper()} BLUE / {bundle.away.upper()} RED", color=MUTED, fontsize=11, family=MONO_FONT)
    fig.text(0.945, 0.835, "18 TOUCH ZONES", color=away_color, fontsize=11, family=MONO_FONT, ha="right")
    finish_scene(fig, bundle, audit, scene, design, path)


def render_momentum(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("", "", design)
    data = audit["momentum"]
    ax = fig.add_axes([0.080, 0.255, 0.860, 0.535], facecolor=PANEL)
    x = np.array([row["minute_start"] for row in data])
    home_pressure = np.array([row["home_pressure"] for row in data])
    away_pressure = np.array([row["away_pressure"] for row in data])
    swing = home_pressure - away_pressure
    home_color = design["home"]["display"]
    away_color = design["away"]["display"]
    max_abs = max(8.0, float(np.nanmax(np.abs(swing))) if len(swing) else 8.0)
    ax.set_ylim(-max_abs * 1.18, max_abs * 1.18)
    ax.axhline(0, color=LINE, lw=1.3, alpha=0.80, zorder=4)
    ax.fill_between(x, 0, np.maximum(swing, 0), step="mid", color=home_color, alpha=0.75, zorder=2)
    ax.fill_between(x, 0, np.minimum(swing, 0), step="mid", color=away_color, alpha=0.75, zorder=2)
    ax.plot(x, swing, color=WHITE, lw=2.4, zorder=5)
    if len(swing):
        peak_idx = int(np.argmax(np.abs(swing)))
        peak_x = x[peak_idx]
        peak_y = swing[peak_idx]
        peak_color = home_color if peak_y >= 0 else away_color
        ax.axvspan(peak_x, peak_x + 5, color=peak_color, alpha=0.12, zorder=1)
        ax.scatter([peak_x + 2.5], [peak_y], s=145, c=peak_color, edgecolor=WHITE, lw=1.2, zorder=8)
        ax.text(
            peak_x + 2.5,
            peak_y + (max_abs * 0.14 if peak_y >= 0 else -max_abs * 0.14),
            f"PEAK {data[peak_idx]['minute_block']}",
            color=peak_color,
            fontsize=9.5,
            fontweight="bold",
            family=MONO_FONT,
            ha="center",
            va="bottom" if peak_y >= 0 else "top",
            path_effects=text_effects(),
            zorder=9,
        )
    for chain in audit["goal_chains"]:
        minute = chain["minute"] or 0
        ax.axvline(minute, color=DANGER, lw=2.2, alpha=0.95, zorder=6)
        ax.scatter([minute], [0], s=55, c=DANGER, edgecolor=WHITE, lw=0.9, zorder=8)
        ax.text(minute + 0.8, max_abs * 0.92, "GOAL", color=DANGER, fontsize=10, family=MONO_FONT, rotation=90, va="top", fontweight="bold")
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(axis="x", colors=MUTED, labelsize=9)
    ax.tick_params(axis="y", left=False, labelleft=False)
    ax.grid(axis="y", color="#263026", lw=0.7, alpha=0.45)
    for spine in ax.spines.values():
        spine.set_color("#30392f")
        spine.set_linewidth(1.1)
    fig.text(0.055, 0.875, "PRESSURE SWUNG LATE", color=WHITE, fontsize=42, fontweight="bold", family=DISPLAY_FONT)
    fig.text(0.055, 0.835, f"{bundle.home.upper()} ABOVE / {bundle.away.upper()} BELOW", color=MUTED, fontsize=11, family=MONO_FONT)
    fig.text(0.945, 0.835, "5-MIN BUCKETS", color=away_color, fontsize=11, family=MONO_FONT, ha="right")
    finish_scene(fig, bundle, audit, scene, design, path)


def render_shot_map(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("Shot Map", "Shot locations by result; marker size uses data flags, not xG", design)
    ax = fig.add_axes([0.055, 0.285, 0.90, 0.515])
    draw_pitch(ax, design["pitch"], design["line"])
    shots = bundle.events[bool_col(bundle.events, "isShot")].copy()
    for _, row in shots.iterrows():
        h_a = clean_text(row.get("h_a"))
        x, y = row.get("x"), row.get("y")
        if pd.isna(x) or pd.isna(y):
            continue
        event_type = clean_text(row.get("type"))
        is_goal = str(row.get("isGoal")).lower() == "true"
        is_big = any(q.get("type") == "BigChance" for q in parse_qualifiers(row.get("qualifiers")))
        if is_goal:
            marker, color, size = "*", DANGER, 360
        elif event_type == "SavedShot":
            marker, color, size = "o", team_color(h_a, design), 170
        elif event_type == "MissedShots":
            marker, color, size = "x", team_color(h_a, design), 150
        else:
            marker, color, size = "s", team_color(h_a, design), 120
        if is_big:
            size *= 1.35
        ax.scatter([x], [y], s=size, marker=marker, color=color, edgecolor=WHITE if marker != "x" else color, linewidth=1.2, alpha=0.95, zorder=6)
    stats = audit["team_stats"]
    h, a = stats[bundle.home], stats[bundle.away]
    fig.text(0.058, 0.837, f"{bundle.home.upper()}: {h['shots']} SHOTS / {h['shots_on_target']} OT", color=design["home"]["display"], fontsize=17, fontweight="bold", family=DISPLAY_FONT)
    fig.text(0.058, 0.807, f"{bundle.away.upper()}: {a['shots']} SHOTS / {a['shots_on_target']} OT", color=design["away"]["display"], fontsize=17, fontweight="bold", family=DISPLAY_FONT)
    finish_scene(fig, bundle, audit, scene, design, path)


def render_goalmouth_wall(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("Goalmouth Wall", "Goal-mouth placement for goals and saved shots", design)
    ax = fig.add_axes([0.095, 0.335, 0.845, 0.44], facecolor="#101410")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.add_patch(Rectangle((5, 5), 90, 90, fill=False, ec=LINE, lw=3))
    ax.plot([5, 95], [50, 50], color=GRID, lw=1, alpha=0.7)
    ax.plot([50, 50], [5, 95], color=GRID, lw=1, alpha=0.7)
    shots = bundle.events[bool_col(bundle.events, "isShot")].copy()
    relevant = shots[(shots.get("type").isin(["SavedShot", "Goal"])) | bool_col(shots, "isGoal")]
    for _, row in relevant.iterrows():
        y = row.get("goalMouthY")
        z = row.get("goalMouthZ")
        if pd.isna(y) or pd.isna(z):
            continue
        is_goal = str(row.get("isGoal")).lower() == "true" or row.get("type") == "Goal"
        h_a = clean_text(row.get("h_a"))
        marker = "*" if is_goal else "o"
        color = DANGER if is_goal else team_color(h_a, design)
        size = 280 if is_goal else 150
        ax.scatter([y], [z], s=size, marker=marker, c=color, edgecolor=WHITE, lw=1.2, zorder=5, alpha=0.95)
    fig.text(0.095, 0.807, "FRAME VIEW: LATERAL PLACEMENT VS HEIGHT", color=WHITE, fontsize=15, fontweight="bold", family=DISPLAY_FONT)
    fig.text(0.095, 0.778, "NO XGOT VALUE IS INFERRED HERE", color=DANGER, fontsize=11, fontweight="bold", family=MONO_FONT)
    finish_scene(fig, bundle, audit, scene, design, path)


def render_pass_network(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    stats = audit["team_stats"]
    focus = bundle.home if stats[bundle.home]["pass_attempts"] >= stats[bundle.away]["pass_attempts"] else bundle.away
    focus_ha = stats[focus]["h_a"]
    fig = new_figure(f"{focus} Pass Network", "Successful pass sequences; inferred recipient from next same-team event", design)
    ax = fig.add_axes([0.055, 0.285, 0.90, 0.515])
    draw_pitch(ax, design["pitch"], design["line"])
    network = pass_network_data(bundle, focus_ha)
    if not network["nodes"]:
        wrapped_fig_text(fig, 0.08, 0.70, "Not enough successful pass sequence data for a network.")
    else:
        max_count = max(node["count"] for node in network["nodes"].values())
        for edge in network["edges"]:
            start = network["nodes"].get(edge["source"])
            end = network["nodes"].get(edge["target"])
            if not start or not end:
                continue
            width = 0.7 + edge["count"] / max(1, network["max_edge"]) * 5.5
            ax.plot([start["x"], end["x"]], [start["y"], end["y"]], color=team_color(focus_ha, design), lw=width, alpha=0.48, zorder=3)
        for player, node in network["nodes"].items():
            size = 120 + node["count"] / max_count * 520
            ax.scatter([node["x"]], [node["y"]], s=size, c=team_color(focus_ha, design), edgecolor=WHITE, lw=1.2, zorder=6)
            label = player.split()[-1][:10]
            ax.text(node["x"], node["y"], label, color=BG, ha="center", va="center", fontsize=8, fontweight="bold", zorder=7)
    fig.text(0.058, 0.837, focus.upper(), color=team_color(focus_ha, design), fontsize=20, fontweight="bold", family=DISPLAY_FONT)
    finish_scene(fig, bundle, audit, scene, design, path)


def render_sterile_domination(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("Sterile Domination Check", "Pass share vs advanced presence", design)
    stats = audit["team_stats"]
    teams = [bundle.home, bundle.away]
    metrics = ["pass_share_pct", "final_third_passes", "penalty_box_touches", "shots", "goals"]
    labels = ["Pass share %", "Final-third passes", "Box touches", "Shots", "Goals"]
    ax = fig.add_axes([0.095, 0.335, 0.845, 0.44], facecolor=PANEL)
    x = np.arange(len(metrics))
    vals_home = np.array([stats[bundle.home][m] for m in metrics], dtype=float)
    vals_away = np.array([stats[bundle.away][m] for m in metrics], dtype=float)
    max_vals = np.maximum(vals_home, vals_away)
    max_vals[max_vals == 0] = 1
    ax.bar(x - 0.18, vals_home / max_vals, width=0.32, color=design["home"]["display"])
    ax.bar(x + 0.18, vals_away / max_vals, width=0.32, color=design["away"]["display"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels, color=WHITE, rotation=25, ha="right", fontsize=10)
    ax.tick_params(axis="y", left=False, labelleft=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for i, metric in enumerate(metrics):
        ax.text(i - 0.18, vals_home[i] / max_vals[i] + 0.04, f"{vals_home[i]:g}", color=design["home"]["display"], ha="center", fontsize=10)
        ax.text(i + 0.18, vals_away[i] / max_vals[i] + 0.04, f"{vals_away[i]:g}", color=design["away"]["display"], ha="center", fontsize=10)
    fig.text(0.095, 0.807, teams[0].upper(), color=design["home"]["display"], fontsize=16, fontweight="bold", family=DISPLAY_FONT)
    fig.text(0.310, 0.807, teams[1].upper(), color=design["away"]["display"], fontsize=16, fontweight="bold", family=DISPLAY_FONT)
    finish_scene(fig, bundle, audit, scene, design, path)


def render_close_card(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any], path: Path) -> None:
    design = match_design(bundle)
    fig = new_figure("", "", design)
    home_color = design["home"]["display"]
    away_color = design["away"]["display"]
    parts = score_parts(bundle.score)
    stats = audit["team_stats"]
    home = stats[bundle.home]
    away = stats[bundle.away]
    fig.text(0.055, 0.850, "NO XG INVENTED", color=WHITE, fontsize=54, fontweight="bold", family=DISPLAY_FONT, ha="left")
    fig.text(0.058, 0.805, "ONLY WHAT THE EVENT FEED SUPPORTS", color=DANGER, fontsize=13, family=MONO_FONT, fontweight="bold", ha="left")
    fig.text(0.058, 0.700, bundle.home.upper(), color=home_color, fontsize=26, fontweight="bold", family=DISPLAY_FONT, ha="left")
    fig.text(0.942, 0.700, bundle.away.upper(), color=away_color, fontsize=26, fontweight="bold", family=DISPLAY_FONT, ha="right")
    if parts:
        fig.text(0.500, 0.610, f"{parts[0]}-{parts[1]}", color=WHITE, fontsize=126, fontweight="bold", family=DISPLAY_FONT, ha="center")
    else:
        fig.text(0.500, 0.610, bundle.score, color=WHITE, fontsize=100, fontweight="bold", family=DISPLAY_FONT, ha="center")
    receipts = [
        ("PASS SHARE", f"{home['pass_share_pct']} / {away['pass_share_pct']}"),
        ("SHOTS", f"{home['shots']} / {away['shots']}"),
        ("FINAL THIRD", f"{home['final_third_passes']} / {away['final_third_passes']}"),
    ]
    y = 0.405
    for label, value in receipts:
        fig.text(0.058, y, label, color=MUTED, fontsize=11, family=MONO_FONT, ha="left")
        fig.text(0.942, y, value, color=WHITE, fontsize=22, fontweight="bold", family=DISPLAY_FONT, ha="right")
        add_fig_rect(fig, 0.058, y - 0.020, 0.884, 0.002, "#222820", 0.9, zorder=2)
        y -= 0.082
    fig.text(0.500, 0.130, "MATCH RECEIPTS", color=away_color, fontsize=24, fontweight="bold", family=DISPLAY_FONT, ha="center")
    fig.text(0.500, 0.100, "AUDIT-LOCKED FOOTBALL DATA", color=MUTED, fontsize=10, family=MONO_FONT, ha="center")
    finish_scene(fig, bundle, audit, scene, design, path)


RENDERERS = {
    "title": render_title_card,
    "standard_stats": render_standard_stats,
    "goal_chain": render_goal_chain,
    "momentum_pendulum": render_momentum,
    "zone_control": render_zone_control,
    "shot_map": render_shot_map,
    "goalmouth_wall": render_goalmouth_wall,
    "pass_network": render_pass_network,
    "sterile_domination": render_sterile_domination,
    "close": render_close_card,
}


def pass_network_data(bundle: MatchBundle, h_a: str) -> dict[str, Any]:
    events = bundle.events.reset_index(drop=True).copy()
    passes = events[(events.get("h_a") == h_a) & (events.get("type") == "Pass") & (events.get("outcomeType") == "Successful")].copy()
    if passes.empty:
        return {"nodes": {}, "edges": [], "max_edge": 1}

    nodes: dict[str, dict[str, Any]] = {}
    edge_counts: dict[tuple[str, str], int] = {}
    for idx, row in passes.iterrows():
        player = clean_text(row.get("playerName"))
        if not player or pd.isna(row.get("x")) or pd.isna(row.get("y")):
            continue
        node = nodes.setdefault(player, {"x_vals": [], "y_vals": [], "count": 0})
        node["x_vals"].append(float(row["x"]))
        node["y_vals"].append(float(row["y"]))
        node["count"] += 1
        recipient = ""
        for lookahead in range(idx + 1, min(idx + 4, len(events))):
            nxt = events.loc[lookahead]
            if clean_text(nxt.get("h_a")) != h_a:
                break
            candidate = clean_text(nxt.get("playerName"))
            if candidate and candidate != player:
                recipient = candidate
                break
        if recipient:
            edge_counts[(player, recipient)] = edge_counts.get((player, recipient), 0) + 1

    compact_nodes = {
        player: {
            "x": float(np.mean(node["x_vals"])),
            "y": float(np.mean(node["y_vals"])),
            "count": int(node["count"]),
        }
        for player, node in nodes.items()
        if node["count"] >= 3
    }
    edges = [
        {"source": src, "target": tgt, "count": count}
        for (src, tgt), count in edge_counts.items()
        if src in compact_nodes and tgt in compact_nodes and count >= 3
    ]
    edges.sort(key=lambda e: e["count"], reverse=True)
    top_edges = edges[:18]
    return {"nodes": compact_nodes, "edges": top_edges, "max_edge": max([e["count"] for e in top_edges] or [1])}


def save_fig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor(), dpi=120)
    plt.close(fig)


def write_script_files(out_dir: Path, scenes: list[dict[str, Any]]) -> None:
    lines = ["# Match Video Script", ""]
    voiceover = []
    recording = [
        "# Human Voiceover Recording Script",
        "",
        "Record these lines with a natural presenter voice. Keep it close, quick, and conversational.",
        "Leave a short beat between lines so the edit can breathe.",
        "",
    ]
    for i, scene in enumerate(scenes, 1):
        lines.append(f"## Scene {i}: {scene['title']}")
        lines.append("")
        lines.append(scene["narration"])
        lines.append("")
        voiceover.append(scene["narration"])
        recording.append(f"{i}. {scene['narration']}")
    (out_dir / "SCRIPT.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "voiceover.txt").write_text("\n\n".join(voiceover), encoding="utf-8")
    (out_dir / "voiceover_recording_script.txt").write_text("\n".join(recording) + "\n", encoding="utf-8")


def write_srt(path: Path, scenes: list[dict[str, Any]]) -> None:
    current = 0.0
    blocks = []
    for i, scene in enumerate(scenes, 1):
        start = current
        end = current + float(scene.get("duration", 6.0))
        blocks.append(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{scene['narration']}\n")
        current = end
    path.write_text("\n".join(blocks), encoding="utf-8")


def srt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def assemble_video(out_dir: Path, scenes: list[dict[str, Any]], audio_path: Path | None, skip_video: bool) -> Path | None:
    if skip_video:
        return None
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        direct = assemble_video_ffmpeg(out_dir, scenes, audio_path, ffmpeg)
        if direct:
            return direct
    try:
        from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
    except Exception as exc:
        print(f"[video] moviepy unavailable: {exc}")
        return None

    adjusted_scenes = list(scenes)
    audio_clip = None
    try:
        if audio_path and audio_path.exists():
            audio_clip = AudioFileClip(str(audio_path))
            total_duration = sum(float(scene.get("duration", 6.0)) for scene in adjusted_scenes)
            if audio_clip.duration > total_duration and adjusted_scenes:
                adjusted_scenes[-1]["duration"] = float(adjusted_scenes[-1].get("duration", 6.0)) + (audio_clip.duration - total_duration) + 0.2

        clips = []
        for scene in adjusted_scenes:
            clip = ImageClip(scene["asset"]).with_duration(float(scene.get("duration", 6.0)))
            clips.append(clip)
        video = concatenate_videoclips(clips, method="compose")
        if audio_clip is not None:
            video = video.with_audio(audio_clip)
        output = out_dir / "match_video.mp4"
        video.write_videofile(str(output), fps=24, codec="libx264", audio_codec="aac", logger=None)
        for clip in clips:
            clip.close()
        video.close()
        if audio_clip is not None:
            audio_clip.close()
        return output
    except Exception as exc:
        print(f"[video] Assembly failed: {exc}")
        try:
            if audio_clip is not None:
                audio_clip.close()
        except Exception:
            pass
        return None


def assemble_video_ffmpeg(out_dir: Path, scenes: list[dict[str, Any]], audio_path: Path | None, ffmpeg: str) -> Path | None:
    output = out_dir / "match_video.mp4"
    if not scenes:
        return None
    try:
        cmd = [ffmpeg, "-y"]
        filter_parts = []
        for idx, scene in enumerate(scenes):
            asset = Path(scene["asset"]).resolve()
            cmd.extend(["-loop", "1", "-t", f"{float(scene.get('duration', 6.0)):.3f}", "-i", str(asset)])
            filter_parts.append(
                f"[{idx}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[v{idx}]"
            )
        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])
        concat_inputs = "".join(f"[v{idx}]" for idx in range(len(scenes)))
        filter_parts.append(f"{concat_inputs}concat=n={len(scenes)}:v=1:a=0,fps=24,format=yuv420p[vout]")
        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[vout]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
            ]
        )
        if audio_path and audio_path.exists():
            audio_input_index = len(scenes)
            cmd.extend(["-map", f"{audio_input_index}:a:0", "-c:a", "aac", "-b:a", "160k"])
        else:
            cmd.extend(["-an"])
        cmd.append(str(output))
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output if output.exists() else None
    except Exception as exc:
        print(f"[video] ffmpeg assembly failed, falling back to moviepy: {exc}")
        return None


def run_pipeline(args: argparse.Namespace) -> Path:
    output_root = Path(args.output_root)
    match_dir = Path(args.match_dir) if args.match_dir else choose_match_dir(Path(args.scrape_output_root), args.interactive)
    bundle = load_match(match_dir)
    out_dir = output_root / safe_name(match_dir.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    audit = build_audit(bundle)
    write_json(out_dir / "data_audit.json", audit)
    action = ask_approval("Data Audit", "\n".join(audit["facts"]), args.auto)
    if action in {"reject", "quit"}:
        raise SystemExit("Stopped at data audit.")

    selected = select_visualizations(audit, args.visualizations, args.use_gemini, args.instruction)
    candidates = visualization_candidates(audit)
    details = "Candidates:\n" + summarize_candidates(candidates) + "\n\nSelected:\n" + summarize_selected(selected)
    action = ask_approval("Visualization Plan", details, args.auto)
    if action == "change":
        selected = manual_visual_selection(candidates, args.visualizations)
    elif action == "redo":
        selected = select_visualizations(audit, args.visualizations, args.use_gemini, args.instruction + " Try a different angle.")
    elif action in {"reject", "quit"}:
        raise SystemExit("Stopped at visualization plan.")

    scenes = build_storyboard(bundle, audit, selected, args.use_gemini, args.instruction)
    script_preview = "\n\n".join(f"{i+1}. {scene['title']}: {scene['narration']}" for i, scene in enumerate(scenes))
    action = ask_approval("Script", script_preview, args.auto)
    if action == "change":
        note = input("Change instruction for script regeneration: ").strip()
        scenes = build_storyboard(bundle, audit, selected, args.use_gemini, note)
    elif action == "redo":
        scenes = build_storyboard(bundle, audit, selected, args.use_gemini, args.instruction + " Make the hook sharper.")
    elif action in {"reject", "quit"}:
        raise SystemExit("Stopped at script.")

    rendered = render_storyboard(bundle, audit, scenes, out_dir / "assets")
    write_script_files(out_dir, rendered)
    voice_text = "\n\n".join(scene["narration"] for scene in rendered)
    voiceover_config = VoiceoverConfig(
        voiceover_file=args.voiceover_file,
        provider="sapi" if args.sapi_tts else "human",
        skip_audio=args.skip_audio,
    )
    audio_path = prepare_voiceover(out_dir, voice_text, voiceover_config)
    rendered = fit_scene_durations_to_audio(rendered, audio_path)
    write_srt(out_dir / "subtitles.srt", rendered)
    write_json(
        out_dir / "video_plan.json",
        {
            "match": audit["match"],
            "selected_visualizations": selected,
            "all_candidates": candidates,
            "scenes": rendered,
        },
    )
    render_details = "\n".join(f"- {scene['asset']} ({scene['duration']}s)" for scene in rendered)
    action = ask_approval("Rendered Assets", render_details, args.auto)
    if action in {"reject", "quit"}:
        raise SystemExit("Stopped after rendering assets.")

    video_path = assemble_video(out_dir, rendered, audio_path, args.skip_video)
    if video_path:
        print(f"\n[OK] Video written: {video_path}")
    else:
        print("\n[WARN] Video file was not produced; assets and script are still available.")
    return out_dir


def manual_visual_selection(candidates: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    available = {c["id"]: c for c in candidates if c["available"]}
    print("Available ids: " + ", ".join(available))
    while True:
        raw = input(f"Enter up to {count} comma-separated visualization ids: ").strip()
        ids = [item.strip() for item in raw.split(",") if item.strip()]
        selected = [available[viz_id] for viz_id in ids if viz_id in available]
        if selected:
            return selected[:count]
        print("No valid available ids entered.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an audited match-analysis video from WhoScored exports.")
    parser.add_argument("--match-dir", help="Existing exported match directory under output/")
    parser.add_argument("--scrape-output-root", default="output", help="Where existing scraper exports live")
    parser.add_argument("--output-root", default="video_output", help="Where video packages are written")
    parser.add_argument("--visualizations", type=int, default=3, help="Number of tactical visualizations after the baseline stats scene")
    parser.add_argument("--interactive", action="store_true", help="Ask for match selection and approvals")
    parser.add_argument("--auto", action="store_true", help="Auto-approve each stage")
    parser.add_argument("--use-gemini", action="store_true", help="Use Gemini for selection/script if GEMINI_API_KEY is set")
    parser.add_argument("--instruction", default="", help="Extra creative or editorial instruction for Gemini/script")
    parser.add_argument("--voiceover-file", default="", help="Path to a human-recorded narration file to attach")
    parser.add_argument("--sapi-tts", action="store_true", help="Opt in to Windows SAPI synthetic narration for rough drafts")
    parser.add_argument("--skip-audio", action="store_true", help="Do not attach or synthesize narration")
    parser.add_argument("--skip-video", action="store_true", help="Skip mp4 assembly")
    args = parser.parse_args()
    if not args.auto and not args.interactive:
        args.interactive = True
    return args


if __name__ == "__main__":
    run_pipeline(parse_args())
