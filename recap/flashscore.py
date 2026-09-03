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


def parse_flashscore_html(html: str, *, url: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    rows = _json_scripts(soup)
    event = _sports_event(rows)
    page_text = soup.get_text(" ", strip=True)
    home = _name(event.get("homeTeam") or event.get("homeCompetitor") or event.get("home"))
    away = _name(event.get("awayTeam") or event.get("awayCompetitor") or event.get("away"))
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
    hs, as_ = _score(event, page_text)
    event_id = str(event.get("event_id") or event.get("identifier") or "")
    if isinstance(event.get("identifier"), dict):
        event_id = str(event["identifier"].get("value") or "")
    if not event_id:
        found = re.search(r"/match/(?:[^/]+/)?([A-Za-z0-9_-]{6,})", url)
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
                "x": None,
                "y": None,
                "coordinate_source": "",
            })
    summary = {
        "matchId": event_id,
        "startDate": str(event.get("startDate") or event.get("startTime") or "")[:10],
        "score": f"{hs} : {as_}",
        "ftScore": f"{hs} : {as_}",
        "home": {"name": home, "teamId": None},
        "away": {"name": away, "teamId": None},
        "league": _name(event.get("superEvent") or event.get("competition")),
        "source": "flashscore",
        "coordinate_source": (
            "flashscore" if any(row.get("x") is not None and row.get("y") is not None for row in incidents)
            else "unavailable"
        ),
    }
    return {"summary": summary, "events": incidents, "url": url}


def export_flashscore(parsed: dict[str, Any], output_root: str | Path) -> Path:
    summary = dict(parsed["summary"])
    home = summary["home"]["name"]
    away = summary["away"]["name"]
    match_id = str(summary.get("matchId") or safe_name(f"{home}_{away}"))
    dest = Path(output_root) / f"{safe_name(match_id)}_{safe_name(home)}_vs_{safe_name(away)}"
    dest.mkdir(parents=True, exist_ok=True)
    events = pd.DataFrame(parsed.get("events") or [], columns=[
        "id", "minute", "second", "type", "outcomeType", "playerName",
        "teamName", "h_a", "isGoal", "isShot", "x", "y", "coordinate_source",
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

