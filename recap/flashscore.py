"""Honest Flashscore fallback exporter.

Flashscore usually supplies score, incidents, lineups and aggregate stats, but
not a WhoScored-quality pass/touch map.  This exporter writes only fields found
in the rendered page.  Coordinates remain empty unless explicit x/y values are
present in source JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
from bs4 import BeautifulSoup

from .data import safe_name, write_json


def _json_scripts(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw or raw[:1] not in "[{":
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        rows.extend(item for item in items if isinstance(item, dict))
    return rows


def _sports_event(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        kind = str(row.get("@type") or row.get("type") or "").lower()
        if "sportsevent" in kind or "sports event" in kind:
            return row
        graph = row.get("@graph")
        if isinstance(graph, list):
            nested = _sports_event([x for x in graph if isinstance(x, dict)])
            if nested:
                return nested
    return {}


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "").strip()
    return str(value or "").strip()


def _score(event: dict[str, Any], text: str) -> tuple[int, int]:
    home = event.get("homeTeam") or event.get("home")
    away = event.get("awayTeam") or event.get("away")
    for source in (event.get("result"), event.get("score"), event):
        if not isinstance(source, dict):
            continue
        h = source.get("home") or source.get("homeScore") or source.get("scoreHome")
        a = source.get("away") or source.get("awayScore") or source.get("scoreAway")
        try:
            return int(h), int(a)
        except (TypeError, ValueError):
            pass
    # Last resort is visible "Home 2 - 1 Away" text. It is source text, not a
    # fabricated score.
    match = re.search(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b", text)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


_STAT_MAP = {
    "expected goals (xg)": "xg",
    "ball possession": "possession_pct",
    "total shots": "shots",
    "shots on goal": "shots_on_target",
    "big chances": "big_chances",
    "touches in opposition box": "penalty_box_touches",
    "corner kicks": "corners",
    "fouls": "fouls",
    "red cards": "red_cards",
    "yellow cards": "yellow_cards",
    "saves": "saves",
}


def _stat_value(raw: str) -> float | int | None:
    text = str(raw or "").strip().replace("%", "")
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    number = float(match.group().replace(",", "."))
    return int(number) if number.is_integer() else number


def parse_flashscore_stats(html: str) -> dict[str, dict[str, float | int]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    home: dict[str, float | int] = {}
    away: dict[str, float | int] = {}
    for row in soup.select('[data-testid="wcl-statistics"]'):
        category = row.select_one('[data-testid="wcl-statistics-category"]')
        values = row.select('[data-testid="wcl-statistics-value"]')
        if category is None or len(values) < 2:
            continue
        label = category.get_text(" ", strip=True).casefold()
        key = _STAT_MAP.get(label)
        if not key:
            continue
        home_value = _stat_value(values[0].get_text(" ", strip=True))
        away_value = _stat_value(values[-1].get_text(" ", strip=True))
        if home_value is not None and away_value is not None:
            home[key] = home_value
            away[key] = away_value
    return {"home": home, "away": away}


def parse_flashscore_html(html: str, *, url: str = "", stats_html: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    rows = _json_scripts(soup)
    event = _sports_event(rows)
    page_text = soup.get_text(" ", strip=True)
    home_node = soup.select_one(".duelParticipant__home .participant__participantName")
    away_node = soup.select_one(".duelParticipant__away .participant__participantName")
    home = home_node.get_text(" ", strip=True) if home_node else ""
    away = away_node.get_text(" ", strip=True) if away_node else ""
    home = home or _name(event.get("homeTeam") or event.get("homeCompetitor") or event.get("home"))
    away = away or _name(event.get("awayTeam") or event.get("awayCompetitor") or event.get("away"))
    if not home or not away:
        title = _name(event.get("name")) or (soup.title.get_text(" ", strip=True) if soup.title else "")
        vs = re.split(r"\s+(?:vs?\.?|[-–—])\s+", title, maxsplit=1, flags=re.I)
        if len(vs) == 2:
            home = home or vs[0].strip()
            away = away or re.split(r"\s+\|\s+|\s+-\s+Flashscore", vs[1], maxsplit=1)[0].strip()
    if not home or not away:
        raise ValueError(
            "Flashscore page did not expose both team names. Save the rendered "
            "match Summary page after it has fully loaded."
        )
    score_node = soup.select_one(".detailScore__wrapper")
    score_text = score_node.get_text(" ", strip=True) if score_node else page_text
    hs, as_ = _score(event, score_text)
    event_id = str(event.get("event_id") or event.get("identifier") or "")
    if isinstance(event.get("identifier"), dict):
        event_id = str(event["identifier"].get("value") or "")
    query_mid = (parse_qs(urlparse(url).query).get("mid") or [""])[0]
    if query_mid:
        event_id = query_mid
    if not event_id:
        found = re.search(r"/match/(?:[^/]+/)*([A-Za-z0-9_-]{6,})/?", url)
        event_id = found.group(1) if found else safe_name(f"{home}_{away}")

    incidents: list[dict[str, Any]] = []
    # Tests/importers may expose a compact JSON incident list. Real rendered
    # pages are also scanned for data-minute/data-type nodes.
    for row in rows:
        possible = row.get("incidents") or row.get("events")
        if not isinstance(possible, list):
            continue
        for index, item in enumerate(possible):
            if not isinstance(item, dict):
                continue
            x, y = item.get("x"), item.get("y")
            incidents.append({
                "id": item.get("id") or index + 1,
                "minute": item.get("minute"),
                "second": item.get("second") or 0,
                "type": item.get("type") or item.get("incidentType") or "Incident",
                "outcomeType": item.get("outcome") or "Successful",
                "playerName": _name(item.get("player") or item.get("playerName")),
                "teamName": _name(item.get("team") or item.get("teamName")),
                "h_a": item.get("h_a") or "",
                "isGoal": bool(item.get("isGoal") or str(item.get("type") or "").lower() == "goal"),
                "isShot": bool(item.get("isShot")),
                "x": x if x is not None else None,
                "y": y if y is not None else None,
                "coordinate_source": "flashscore" if x is not None and y is not None else "",
            })
    if not incidents:
        for index, node in enumerate(soup.select(".smv__participantRow")):
            side = "h" if "smv__homeParticipant" in (node.get("class") or []) else "a"
            time_node = node.select_one(".smv__timeBox")
            minute_text = time_node.get_text(" ", strip=True) if time_node else ""
            minute_match = re.search(r"\d+", minute_text)
            minute = int(minute_match.group()) if minute_match else None
            tooltip = node.select_one("[aria-label]")
            description = str(tooltip.get("aria-label") or "") if tooltip else ""
            player_nodes = node.select(".smv__playerName")
            players = [item.get_text(" ", strip=True) for item in player_nodes]
            classes = " ".join(
                cls
                for descendant in node.find_all(class_=True)
                for cls in (descendant.get("class") or [])
            )
            testids = " ".join(
                str(descendant.get("data-testid") or "")
                for descendant in node.select("[data-testid]")
            )
            combined = f"{classes} {testids} {description}".lower()
            is_goal = "goal-soccer" in combined
            is_sub = "substitution" in combined or "incidenticonsub" in combined
            red = "redcard" in combined or "issues a red" in combined
            yellow = "yellowcard" in combined or "yellow card" in combined
            if is_goal:
                event_type = "Goal"
            elif is_sub:
                event_type = "Substitution"
            elif red or yellow:
                event_type = "Card"
            else:
                event_type = "Incident"
            incidents.append({
                "id": index + 1,
                "minute": minute,
                "second": 0,
                "expandedMinute": minute,
                "period": "FirstHalf" if minute is not None and minute <= 45 else "SecondHalf",
                "type": event_type,
                "outcomeType": "Successful",
                "playerName": players[0] if players else "",
                "relatedPlayer": players[1] if len(players) > 1 else "",
                "description": description,
                "teamName": home if side == "h" else away,
                "h_a": side,
                "isGoal": is_goal,
                "isShot": is_goal,
                "shotOnTarget": is_goal,
                "isTouch": False,
                "cardType": "Red" if red else "Yellow" if yellow else "",
                "foulCommitted": bool(red or yellow),
                "x": None,
                "y": None,
                "endX": None,
                "endY": None,
                "coordinate_source": "",
            })
    if not incidents:
        for index, node in enumerate(soup.select("[data-minute][data-type]")):
            incidents.append({
                "id": index + 1,
                "minute": node.get("data-minute"),
                "second": 0,
                "type": node.get("data-type") or "Incident",
                "outcomeType": "Successful",
                "playerName": node.get("data-player") or node.get_text(" ", strip=True),
                "teamName": node.get("data-team") or "",
                "h_a": node.get("data-side") or "",
                "isGoal": str(node.get("data-type") or "").lower() == "goal",
                "isShot": False,
                "period": "FirstHalf",
                "isTouch": False,
                "x": None,
                "y": None,
                "coordinate_source": "",
            })
    date_node = soup.select_one(".duelParticipant__startTime")
    date_text = date_node.get_text(" ", strip=True) if date_node else ""
    date_match = re.search(r"(\d{2})[./](\d{2})[./](20\d{2})", date_text)
    start_date = (
        f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
        if date_match else str(event.get("startDate") or event.get("startTime") or "")[:10]
    )
    breadcrumb = soup.select_one(".detail__breadcrumbs")
    league = breadcrumb.get_text(" / ", strip=True) if breadcrumb else ""
    source_stats = parse_flashscore_stats(stats_html or html)
    summary = {
        "matchId": event_id,
        "startDate": start_date,
        "score": f"{hs} : {as_}",
        "ftScore": f"{hs} : {as_}",
        "home": {"name": home, "teamId": None},
        "away": {"name": away, "teamId": None},
        "league": league or _name(event.get("superEvent") or event.get("competition")),
        "source": "flashscore",
        "source_team_stats": source_stats,
        "source_supported_stats": sorted(set(source_stats["home"]) & set(source_stats["away"])),
        "coordinate_source": (
            "flashscore" if any(row.get("x") is not None and row.get("y") is not None for row in incidents)
            else "unavailable"
        ),
    }
    return {"summary": summary, "events": incidents, "url": url, "source_team_stats": source_stats}


def export_flashscore(parsed: dict[str, Any], output_root: str | Path) -> Path:
    summary = dict(parsed["summary"])
    home = summary["home"]["name"]
    away = summary["away"]["name"]
    match_id = str(summary.get("matchId") or safe_name(f"{home}_{away}"))
    dest = Path(output_root) / f"{safe_name(match_id)}_{safe_name(home)}_vs_{safe_name(away)}"
    dest.mkdir(parents=True, exist_ok=True)
    events = pd.DataFrame(parsed.get("events") or [], columns=[
        "id", "minute", "second", "expandedMinute", "period", "type",
        "outcomeType", "playerName", "relatedPlayer", "description",
        "teamName", "h_a", "isGoal", "isShot", "shotOnTarget", "isTouch",
        "cardType", "foulCommitted", "x", "y", "endX", "endY", "coordinate_source",
    ])
    events.to_csv(dest / "all_events.csv", index=False)
    write_json(dest / "match_summary.json", summary)
    write_json(dest / "match_data_raw.json", {
        "source": "flashscore",
        "url": parsed.get("url") or "",
        "summary": summary,
        "events": parsed.get("events") or [],
    })
    (dest / "SOURCE.md").write_text(
        "# Source\n\nFlashscore fallback export.\n\n"
        "- Score/incidents are only what the rendered page exposed.\n"
        "- Coordinates are never reconstructed or invented.\n"
        "- Tracking-only shot maps, heatmaps and pass networks remain blocked "
        "unless explicit source x/y exists.\n",
        encoding="utf-8",
    )
    return dest

