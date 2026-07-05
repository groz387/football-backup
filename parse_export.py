# -*- coding: utf-8 -*-
import sys as _sys, os as _os
if _sys.platform == 'win32':
    try:
        _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        _sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
"""
parse_export.py — Parse WhoScored match data and export to JSON / CSV.

Takes a raw match‑data dict (from fetch_page.py) and produces:
  • match_data_raw.json      – complete raw JSON blob
  • match_summary.json       – clean match metadata
  • all_events.csv           – every event with coordinates & ~200+ stat columns
  • passes.csv               – all passes with length, angle, type, direction
  • shots.csv                – all shots/goals with body part, situation, xG
  • defensive_actions.csv    – tackles, interceptions, clearances, blocks
  • player_stats.csv         – per‑player aggregated stats from both teams
  • formations.csv           – formation slots with positional coordinates
  • heatmap_touches.csv      – every touch coordinate per player
"""

import warnings
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd


# ===================================================================
#  1.  ALL EVENTS DataFrame
# ===================================================================

def create_events_df(match_data: dict) -> pd.DataFrame:
    """
    Convert the raw match‑data dict into a comprehensive events DataFrame.
    Replicates and extends the original createEventsDF logic with better
    error handling and additional derived columns.
    """
    events = match_data.get("events", [])
    if not events:
        raise ValueError("No events found in match_data — the match may not have started yet.")

    # ------ inject match metadata into every event row ------
    meta = {
        "matchId":    match_data.get("matchId"),
        "startDate":  match_data.get("startDate"),
        "startTime":  match_data.get("startTime"),
        "score":      match_data.get("score"),
        "ftScore":    match_data.get("ftScore"),
        "htScore":    match_data.get("htScore"),
        "etScore":    match_data.get("etScore"),
        "venueName":  match_data.get("venueName"),
        "maxMinute":  match_data.get("maxMinute"),
    }
    for ev in events:
        ev.update(meta)

    df = pd.DataFrame(events)

    # ------ flatten nested dicts → display names ------
    for col in ("period", "type", "outcomeType"):
        if col in df.columns:
            try:
                df[col] = pd.json_normalize(df[col])["displayName"]
            except Exception:
                pass

    # cardType (may be missing)
    try:
        filled = df["cardType"].fillna({i: {} for i in df.index})
        df["cardType"] = pd.json_normalize(filled)["displayName"].fillna(False)
    except (KeyError, TypeError):
        if "cardType" not in df.columns:
            df["cardType"] = False

    # ------ satisfiedEventsTypes → human‑readable names ------
    evt_dict = match_data.get("matchCentreEventTypeJson", {})
    if evt_dict and "satisfiedEventsTypes" in df.columns:
        inv_map = {v: k for k, v in evt_dict.items()}
        df["satisfiedEventsTypes"] = df["satisfiedEventsTypes"].apply(
            lambda xs: [inv_map.get(x, str(x)) for x in xs] if isinstance(xs, list) else []
        )

    # ------ clean qualifiers (type dict → string) ------
    if "qualifiers" in df.columns:
        for i in df.index:
            quals = df.at[i, "qualifiers"]
            if isinstance(quals, list):
                for q in quals:
                    if isinstance(q, dict) and isinstance(q.get("type"), dict):
                        q["type"] = q["type"].get("displayName", "")

    # ------ boolean shot / goal columns ------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        for col in ("isShot", "isGoal"):
            if col in df.columns:
                df[col] = df[col].fillna(False).infer_objects(copy=False)
            else:
                df[col] = False

    # ------ player name column ------
    pid_name = match_data.get("playerIdNameDictionary", {})
    if "playerId" in df.columns and pid_name:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            mask = df["playerId"].notna()
            df.loc[mask, "playerId"] = df.loc[mask, "playerId"].astype(int).astype(str)
        name_col = df["playerId"].map(pid_name)
        idx = df.columns.get_loc("playerId") + 1
        df.insert(idx, "playerName", name_col)

    # ------ home / away column ------
    home_id = match_data.get("home", {}).get("teamId")
    away_id = match_data.get("away", {}).get("teamId")
    if "teamId" in df.columns:
        ha = df["teamId"].map({home_id: "h", away_id: "a"})
        idx = df.columns.get_loc("teamId") + 1
        df.insert(idx, "h_a", ha)

    # ------ shot body type & situation from qualifiers ------
    df["shotBodyType"] = np.nan
    df["situation"]    = np.nan

    shot_idx = df.index[df["isShot"] == True]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        for i in shot_idx:
            quals = df.at[i, "qualifiers"]
            if not isinstance(quals, list):
                continue
            for q in quals:
                qt = q.get("type", "")
                if qt in ("RightFoot", "LeftFoot", "Head", "OtherBodyPart"):
                    df.at[i, "shotBodyType"] = qt
                if qt in ("FromCorner", "SetPiece", "DirectFreekick"):
                    df.at[i, "situation"] = qt
                if qt == "RegularPlay":
                    df.at[i, "situation"] = "OpenPlay"

    # ------ expand satisfiedEventsTypes to boolean columns ------
    if evt_dict and "satisfiedEventsTypes" in df.columns:
        event_types = list(evt_dict.keys())
        bool_cols = pd.DataFrame(
            {et: [et in row if isinstance(row, list) else False for row in df["satisfiedEventsTypes"]]
             for et in event_types},
            index=df.index,
        )
        df = pd.concat([df, bool_cols], axis=1)

    # ------ serialise complex columns for CSV safety ------
    if "qualifiers" in df.columns:
        df["qualifiers"] = df["qualifiers"].apply(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else x
        )
    if "satisfiedEventsTypes" in df.columns:
        df["satisfiedEventsTypes"] = df["satisfiedEventsTypes"].apply(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else x
        )

    return df


# ===================================================================
#  2.  PASSES DataFrame
# ===================================================================

def create_passes_df(events_df: pd.DataFrame) -> pd.DataFrame:
    """Focused passes CSV with derived metrics."""
    passes = events_df[events_df["type"] == "Pass"].copy()
    if passes.empty:
        return passes

    # ---- derived metrics ----
    if {"endX", "endY", "x", "y"}.issubset(passes.columns):
        dx = passes["endX"] - passes["x"]
        dy = passes["endY"] - passes["y"]
        passes["passLength"] = np.sqrt(dx ** 2 + dy ** 2)
        passes["passAngle"]  = np.degrees(np.arctan2(dy, dx))

        passes["passDirection"] = "Lateral"
        passes.loc[dx >  5, "passDirection"] = "Forward"
        passes.loc[dx < -5, "passDirection"] = "Backward"

    # ---- pass type from qualifiers ----
    type_keywords = {
        "LongBall": "Long", "Cross": "Cross", "ThroughBall": "ThroughBall",
        "Corner": "Corner", "Freekick": "Freekick", "ThrowIn": "ThrowIn",
        "GoalKick": "GoalKick", "Chipped": "Chipped",
    }

    def _pass_type(raw_q):
        if not isinstance(raw_q, str):
            return "Short"
        try:
            quals = json.loads(raw_q)
        except (json.JSONDecodeError, TypeError):
            return "Short"
        if not isinstance(quals, list):
            return "Short"
        for q in quals:
            qt = q.get("type", "")
            if qt in type_keywords:
                return type_keywords[qt]
        return "Short"

    passes["passType"] = passes["qualifiers"].apply(_pass_type)

    # ---- select columns ----
    wanted = [
        "id", "minute", "second", "period",
        "playerName", "playerId", "teamId", "h_a",
        "x", "y", "endX", "endY",
        "outcomeType", "passLength", "passAngle", "passDirection", "passType",
        "qualifiers",
    ]
    if "EPV" in passes.columns:
        wanted.append("EPV")
    cols = [c for c in wanted if c in passes.columns]
    return passes[cols].reset_index(drop=True)


# ===================================================================
#  3.  SHOTS DataFrame
# ===================================================================

def create_shots_df(events_df: pd.DataFrame) -> pd.DataFrame:
    """Focused shots CSV."""
    shots = events_df[events_df["isShot"] == True].copy()
    wanted = [
        "id", "minute", "second", "period",
        "playerName", "playerId", "teamId", "h_a",
        "x", "y", "endX", "endY",
        "goalMouthY", "goalMouthZ", "blockedX", "blockedY",
        "outcomeType", "isGoal", "shotBodyType", "situation",
        "qualifiers",
    ]
    cols = [c for c in wanted if c in shots.columns]
    return shots[cols].reset_index(drop=True)


# ===================================================================
#  4.  DEFENSIVE ACTIONS DataFrame
# ===================================================================

def create_defensive_df(events_df: pd.DataFrame) -> pd.DataFrame:
    """Tackles, interceptions, clearances, blocks, recoveries."""
    core_types = {"Tackle", "Interception", "Clearance", "BlockedPass", "BallRecovery"}
    mask = events_df["type"].isin(core_types)

    # Also include rows flagged by boolean stat columns
    for flag in ("interceptionWon", "clearanceTotal", "outfielderBlock",
                 "tackleWon", "tackleLost", "ballRecovery"):
        if flag in events_df.columns:
            mask = mask | (events_df[flag] == True)

    defensive = events_df[mask].copy()
    wanted = [
        "id", "minute", "second", "period",
        "playerName", "playerId", "teamId", "h_a",
        "x", "y", "type", "outcomeType", "qualifiers",
    ]
    cols = [c for c in wanted if c in defensive.columns]
    return defensive[cols].reset_index(drop=True)


# ===================================================================
#  5.  PLAYER STATS DataFrame
# ===================================================================

def create_player_stats_df(match_data: dict) -> pd.DataFrame:
    """Per‑player aggregated statistics from both teams."""
    rows = []
    for venue in ("home", "away"):
        team = match_data.get(venue, {})
        team_name = team.get("name", "")
        team_id   = team.get("teamId", "")

        for p in team.get("players", []):
            row = {
                "playerId":    p.get("playerId"),
                "playerName":  p.get("name"),
                "shirtNo":     p.get("shirtNo"),
                "position":    p.get("position"),
                "team":        team_name,
                "teamId":      team_id,
                "venue":       venue,
                "isFirstEleven":            p.get("isFirstEleven", False),
                "subbedInExpandedMinute":   p.get("subbedInExpandedMinute"),
                "subbedOutExpandedMinute":  p.get("subbedOutExpandedMinute"),
                "height":      p.get("height"),
                "weight":      p.get("weight"),
                "age":         p.get("age"),
            }
            # Flatten nested stats dict  e.g. {"ratings": {"overall": 7.2}} → ratings_overall
            stats = p.get("stats", {})
            if isinstance(stats, dict):
                for cat, vals in stats.items():
                    if isinstance(vals, dict):
                        for k, v in vals.items():
                            row[f"{cat}_{k}"] = v
                    else:
                        row[cat] = vals
            rows.append(row)

    return pd.DataFrame(rows)


# ===================================================================
#  6.  FORMATIONS DataFrame
# ===================================================================

def create_formations_df(match_data: dict) -> pd.DataFrame:
    """Formation slots with player positions for both teams."""
    pid_name = match_data.get("playerIdNameDictionary", {})
    rows = []
    for venue in ("home", "away"):
        team = match_data.get(venue, {})
        team_name = team.get("name", "")
        for fi, fm in enumerate(team.get("formations", [])):
            fname = fm.get("formationName", [])
            if isinstance(fname, list):
                fname = "-".join(str(x) for x in fname)
            pids = fm.get("playerIds", [])
            positions = fm.get("formationPositions", [])
            for si, (pid, pos) in enumerate(zip(pids, positions)):
                rows.append({
                    "team":           team_name,
                    "venue":          venue,
                    "formationIndex": fi,
                    "formationName":  fname,
                    "playerId":       pid,
                    "playerName":     pid_name.get(str(pid), ""),
                    "slotIndex":      si,
                    "vertical":       pos.get("vertical"),
                    "horizontal":     pos.get("horizontal"),
                    "startMinuteExpanded": fm.get("startMinuteExpanded"),
                    "endMinuteExpanded":   fm.get("endMinuteExpanded"),
                })
    return pd.DataFrame(rows)


# ===================================================================
#  7.  HEATMAP (touches) DataFrame
# ===================================================================

def create_heatmap_df(events_df: pd.DataFrame) -> pd.DataFrame:
    """Every on‑ball touch with player + coordinates."""
    if "isTouch" not in events_df.columns:
        return pd.DataFrame()

    touches = events_df[events_df["isTouch"] == True].copy()
    wanted = [
        "playerName", "playerId", "teamId", "h_a",
        "x", "y", "minute", "second", "type", "period",
    ]
    cols = [c for c in wanted if c in touches.columns]
    return touches[cols].reset_index(drop=True)


# ===================================================================
#  8.  MATCH SUMMARY dict
# ===================================================================

def create_match_summary(match_data: dict) -> dict:
    """Clean, human‑readable match summary."""
    def _fmt_formation(f):
        name = f.get("formationName", [])
        if isinstance(name, list):
            name = "-".join(str(x) for x in name)
        return {
            "formationName":        name,
            "startMinuteExpanded":  f.get("startMinuteExpanded"),
            "endMinuteExpanded":    f.get("endMinuteExpanded"),
        }

    def _fmt_player(p):
        return {
            "playerId":      p.get("playerId"),
            "name":          p.get("name"),
            "shirtNo":       p.get("shirtNo"),
            "position":      p.get("position"),
            "isFirstEleven": p.get("isFirstEleven", False),
        }

    def _fmt_team(venue):
        t = match_data.get(venue, {})
        return {
            "teamId":      t.get("teamId"),
            "name":        t.get("name"),
            "countryName": t.get("countryName"),
            "averageAge":  t.get("averageAge"),
            "formations":  [_fmt_formation(f) for f in t.get("formations", [])],
            "players":     [_fmt_player(p) for p in t.get("players", [])],
        }

    return {
        "matchId":          match_data.get("matchId"),
        "startDate":        match_data.get("startDate"),
        "startTime":        match_data.get("startTime"),
        "score":            match_data.get("score"),
        "ftScore":          match_data.get("ftScore"),
        "htScore":          match_data.get("htScore"),
        "etScore":          match_data.get("etScore"),
        "venueName":        match_data.get("venueName"),
        "attendance":       match_data.get("attendance"),
        "referee":          match_data.get("referee"),
        "maxMinute":        match_data.get("maxMinute"),
        "home":             _fmt_team("home"),
        "away":             _fmt_team("away"),
        "region":           match_data.get("region", ""),
        "league":           match_data.get("league", ""),
        "season":           match_data.get("season", ""),
        "competitionType":  match_data.get("competitionType", ""),
        "competitionStage": match_data.get("competitionStage", ""),
    }


# ===================================================================
#  MAIN EXPORT FUNCTION
# ===================================================================

def export_all(match_data: dict, output_dir: str,
               add_epv: bool = False, epv_grid_path: str | None = None) -> dict:
    """
    Export everything to *output_dir*.  Returns a dict of DataFrames for
    further programmatic use.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    mid  = match_data.get("matchId", "unknown")
    home = match_data.get("home", {}).get("name", "?")
    away = match_data.get("away", {}).get("name", "?")

    print(f"\n{'═' * 60}")
    print(f"  Exporting: {home} vs {away}  (Match {mid})")
    print(f"  → {out}")
    print(f"{'═' * 60}\n")

    # ---- 1. raw JSON ----
    p = out / "match_data_raw.json"
    p.write_text(json.dumps(match_data, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")
    print(f"  ✓ match_data_raw.json          ({p.stat().st_size / 1024:.0f} KB)")

    # ---- 2. match summary ----
    summary = create_match_summary(match_data)
    p = out / "match_summary.json"
    p.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")
    print(f"  ✓ match_summary.json")

    # ---- 3. all events ----
    events_df = create_events_df(match_data)

    # optional EPV
    if add_epv and epv_grid_path and os.path.exists(epv_grid_path):
        try:
            from main import addEpvToDataFrame
            events_df = addEpvToDataFrame(events_df)
            print(f"  ✓ EPV values added to events")
        except Exception as e:
            print(f"  ⚠ EPV calculation skipped: {e}")

    p = out / "all_events.csv"
    events_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  ✓ all_events.csv               ({len(events_df):,} events × {events_df.shape[1]} cols)")

    # ---- 4. passes ----
    passes_df = create_passes_df(events_df)
    p = out / "passes.csv"
    passes_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  ✓ passes.csv                   ({len(passes_df):,} passes)")

    # ---- 5. shots ----
    shots_df = create_shots_df(events_df)
    p = out / "shots.csv"
    shots_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  ✓ shots.csv                    ({len(shots_df):,} shots)")

    # ---- 6. defensive actions ----
    def_df = create_defensive_df(events_df)
    p = out / "defensive_actions.csv"
    def_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  ✓ defensive_actions.csv        ({len(def_df):,} actions)")

    # ---- 7. player stats ----
    pstats_df = create_player_stats_df(match_data)
    p = out / "player_stats.csv"
    pstats_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  ✓ player_stats.csv             ({len(pstats_df):,} players)")

    # ---- 8. formations ----
    form_df = create_formations_df(match_data)
    p = out / "formations.csv"
    form_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  ✓ formations.csv               ({len(form_df):,} slots)")

    # ---- 9. heatmap touches ----
    heat_df = create_heatmap_df(events_df)
    p = out / "heatmap_touches.csv"
    heat_df.to_csv(p, index=False, encoding="utf-8")
    print(f"  [OK] heatmap_touches.csv          ({len(heat_df):,} touches)")

    print(f"\n  [OK] Done — 9 files written to {out}\n")

    return {
        "events_df":      events_df,
        "passes_df":      passes_df,
        "shots_df":       shots_df,
        "defensive_df":   def_df,
        "player_stats_df": pstats_df,
        "formations_df":  form_df,
        "heatmap_df":     heat_df,
        "match_summary":  summary,
    }
