# -*- coding: utf-8 -*-
import sys as _sys, os as _os
if _sys.platform == 'win32':
    try:
        _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        _sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
"""
json_summarizer.py -- Advanced Tactical Engine
Calculates 10 advanced metrics (Momentum, PPDA, Field Tilt, etc.) 
and generates a deep tactical dossier for LLM script generation.
"""

import os
import json
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0

def calculate_momentum(events: pd.DataFrame, home_id: str, away_id: str) -> dict:
    """Calculates 5-minute rolling momentum/danger score."""
    momentum = []
    max_min = int(events['minute'].max())
    
    for m in range(0, max_min + 5, 5):
        bucket = events[(events['minute'] >= m) & (events['minute'] < m + 5)]
        
        home_score = 0
        away_score = 0
        
        for _, row in bucket.iterrows():
            team = home_id if row['h_a'] == 'h' else away_id
            score = 0
            
            # Weighted events
            if row['type'] == 'Pass' and row['x'] >= 66.6:
                score += 1
            elif row['type'] == 'SavedShot':
                score += 5
            elif row['type'] == 'MissedShots' or row.get('isShot', False):
                score += 3
            elif row['type'] == 'Goal' or row.get('isGoal', False):
                score += 10
            elif row['type'] == 'BallRecovery' and row['x'] >= 50:
                score += 2
            elif row['type'] == 'Dispossessed':
                score -= 1
                
            if team == home_id:
                home_score += score
            else:
                away_score += score
                
        momentum.append({
            "minute_block": f"{m}-{m+4}",
            "home_score": max(0, home_score),
            "away_score": max(0, away_score)
        })
    return momentum

def calculate_ppda(events: pd.DataFrame, home_id: str, away_id: str) -> dict:
    """Passes Per Defensive Action (15-min buckets)."""
    ppda = []
    max_min = int(events['minute'].max())
    def_types = ['Tackle', 'Interception', 'Foul', 'Challenge']
    
    for m in range(0, max_min + 15, 15):
        bucket = events[(events['minute'] >= m) & (events['minute'] < m + 15)]
        
        # Passes allowed by Home = Away passes in Away's own half (x < 40)
        away_passes = len(bucket[(bucket['h_a'] == 'a') & (bucket['type'] == 'Pass') & (bucket['x'] < 40)])
        # Home defensive actions in opponent half (x > 60)
        home_def = len(bucket[(bucket['h_a'] == 'h') & (bucket['type'].isin(def_types)) & (bucket['x'] > 60)])
        
        # Passes allowed by Away = Home passes in Home's own half (x < 40)
        home_passes = len(bucket[(bucket['h_a'] == 'h') & (bucket['type'] == 'Pass') & (bucket['x'] < 40)])
        away_def = len(bucket[(bucket['h_a'] == 'a') & (bucket['type'].isin(def_types)) & (bucket['x'] > 60)])
        
        h_ppda = round(away_passes / home_def, 1) if home_def > 0 else 50.0
        a_ppda = round(home_passes / away_def, 1) if away_def > 0 else 50.0
        
        ppda.append({
            "minute_block": f"{m}-{m+14}",
            "home_ppda": h_ppda,
            "away_ppda": a_ppda
        })
    return ppda

def calculate_field_tilt(events: pd.DataFrame, home_id: str, away_id: str) -> dict:
    """Final third passes ratio (10-min buckets)."""
    tilt = []
    max_min = int(events['minute'].max())
    
    for m in range(0, max_min + 10, 10):
        bucket = events[(events['minute'] >= m) & (events['minute'] < m + 10)]
        passes = bucket[(bucket['type'] == 'Pass') & (bucket['x'] >= 66.6)]
        
        home_p = len(passes[passes['h_a'] == 'h'])
        away_p = len(passes[passes['h_a'] == 'a'])
        total = home_p + away_p
        
        tilt.append({
            "minute_block": f"{m}-{m+9}",
            "home_tilt_pct": round((home_p / total * 100), 1) if total > 0 else 50.0,
            "away_tilt_pct": round((away_p / total * 100), 1) if total > 0 else 50.0
        })
    return tilt

def extract_goal_chains(events: pd.DataFrame) -> list:
    """Traces events backwards from a goal."""
    chains = []
    goals = events[events['type'] == 'Goal']
    
    for _, goal in goals.iterrows():
        g_idx = goal.name
        team = goal['h_a']
        
        # Walk backwards up to 10 events
        chain_events = []
        for i in range(g_idx, max(-1, g_idx - 10), -1):
            if i not in events.index: continue
            ev = events.loc[i]
            if ev['h_a'] != team and ev['type'] not in ['BallTouch']:
                break # Turnover broke the chain
            chain_events.append(f"{ev['playerName']} ({ev['type']})")
            
        chains.append({
            "minute": int(goal['minute']),
            "scorer": str(goal['playerName']),
            "buildup": " -> ".join(reversed(chain_events))
        })
    return chains

def summarize_match(match_dir: str):
    path = Path(match_dir)
    if not path.is_dir():
        print(f"Error: {match_dir} is not a directory.")
        return

    try:
        with open(path / "match_summary.json", "r", encoding="utf-8") as f:
            summary = json.load(f)
        events = pd.read_csv(path / "all_events.csv")
        passes = pd.read_csv(path / "passes.csv")
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    home_team = summary.get("home", {}).get("name", "Home")
    away_team = summary.get("away", {}).get("name", "Away")
    
    # Base Stats
    tactical_data = {
        "match_info": {
            "teams": f"{home_team} vs {away_team}",
            "score": summary.get("score"),
            "home_formation": summary.get("home", {}).get("formations", [{}])[0].get("formationName", ""),
            "away_formation": summary.get("away", {}).get("formations", [{}])[0].get("formationName", "")
        },
        "team_stats": {
            home_team: {"possession_pct": 0, "total_passes": 0, "shots": 0},
            away_team: {"possession_pct": 0, "total_passes": 0, "shots": 0}
        }
    }

    # Calculate precise possession based on total passes
    h_passes = len(passes[passes['h_a'] == 'h'])
    a_passes = len(passes[passes['h_a'] == 'a'])
    t_passes = h_passes + a_passes
    if t_passes > 0:
        tactical_data["team_stats"][home_team]["possession_pct"] = round((h_passes / t_passes) * 100, 1)
        tactical_data["team_stats"][away_team]["possession_pct"] = round((a_passes / t_passes) * 100, 1)
        
    tactical_data["team_stats"][home_team]["total_passes"] = h_passes
    tactical_data["team_stats"][away_team]["total_passes"] = a_passes
    tactical_data["team_stats"][home_team]["shots"] = len(events[(events['h_a'] == 'h') & (events['isShot'] == True)])
    tactical_data["team_stats"][away_team]["shots"] = len(events[(events['h_a'] == 'a') & (events['isShot'] == True)])

    # Advanced Metrics
    tactical_data["momentum_curve"] = calculate_momentum(events, home_team, away_team)
    tactical_data["ppda"] = calculate_ppda(events, home_team, away_team)
    tactical_data["field_tilt"] = calculate_field_tilt(events, home_team, away_team)
    tactical_data["goal_chains"] = extract_goal_chains(events)

    # Find Top Progressive Passers
    prog_passes = passes[passes['endX'] - passes['x'] >= 20]
    tactical_data["progressive_passers"] = {
        home_team: prog_passes[prog_passes['h_a'] == 'h'].groupby('playerName').size().sort_values(ascending=False).head(3).to_dict(),
        away_team: prog_passes[prog_passes['h_a'] == 'a'].groupby('playerName').size().sort_values(ascending=False).head(3).to_dict()
    }

    with open(path / "match_dossier.json", "w", encoding="utf-8") as f:
        json.dump(tactical_data, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Generated match_dossier.json")

    # Generate Detailed Narrative Text
    lines = [f"TACTICAL MINUTE-BY-MINUTE: {home_team} vs {away_team}", "="*50]
    
    max_min = int(events['minute'].max())
    for m in range(max_min + 1):
        bucket = events[events['minute'] == m]
        if bucket.empty: continue
        
        key_events = bucket[bucket['type'].isin(['Goal', 'Card', 'SubstitutionOff', 'MissedShots', 'SavedShot']) | (bucket['isShot'] == True)]
        
        narrative = []
        for _, row in key_events.iterrows():
            p = row['playerName'] if pd.notna(row['playerName']) else "Unknown"
            t = home_team if row['h_a'] == 'h' else away_team
            if row['type'] == 'Goal' or row.get('isGoal', False):
                narrative.append(f"GOAL {t} by {p}!")
            elif row.get('isShot', False) or 'Shot' in str(row['type']):
                narrative.append(f"Shot by {p} ({t}).")
            elif row['type'] == 'Card':
                narrative.append(f"Card for {p} ({t}).")
                
        h_touches = len(bucket[bucket['h_a'] == 'h'])
        a_touches = len(bucket[bucket['h_a'] == 'a'])
        dom = home_team if h_touches > a_touches else (away_team if a_touches > h_touches else "Even")
        
        if narrative:
            lines.append(f"Min {m}: {' | '.join(narrative)} (Possession: {dom})")
        elif m % 5 == 0: # Print a summary every 5 mins even if no key events
            lines.append(f"Min {m}: Ball mostly controlled by {dom}.")

    with open(path / "tactical_play_by_play.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [OK] Generated tactical_play_by_play.txt")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate LLM-optimized tactical summaries.")
    parser.add_argument("--dir", required=True, help="Path to the output directory of a scraped match.")
    args = parser.parse_args()
    
    summarize_match(args.dir)
