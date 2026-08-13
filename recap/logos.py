"""Resolve and cache club crest images for ``--team club`` mode.

Lookup order for a club crest:

1. ``assets/logos/<canonical-key>.png`` (hand-dropped assets)
2. ``.cache/logos/<canonical-key>.png`` (previous download)
3. ESPN soccer logo CDN, when we know the ESPN team id
4. TheSportsDB team search (free demo endpoint), using the badge URL
5. ``None`` — callers draw a circular initials crest instead
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from .theme import canonical_team_key, normalize_team_key

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets" / "logos"
CACHE_DIR = ROOT / ".cache" / "logos"

# ESPN soccer logo ids for clubs we care about. Extend as needed.
_ESPN_IDS: dict[str, int] = {
    "arsenal": 359,
    "aston villa": 362,
    "atletico madrid": 1068,
    "barcelona": 83,
    "bayern munich": 132,
    "borussia dortmund": 124,
    "chelsea": 363,
    "inter": 110,
    "inter milan": 110,
    "internazionale": 110,
    "juventus": 111,
    "liverpool": 364,
    "manchester city": 382,
    "manchester united": 360,
    "milan": 103,
    "ac milan": 103,
    "napoli": 114,
    "newcastle united": 361,
    "paris saint germain": 160,
    "psg": 160,
    "paris sg": 160,
    "porto": 437,
    "real madrid": 86,
    "sevilla": 243,
    "tottenham": 367,
    "tottenham hotspur": 367,
    "benfica": 1929,
    "ajax": 139,
    "lyon": 167,
    "marseille": 176,
    "monaco": 166,
    "leverkusen": 131,
    "rb leipzig": 11471,
    "wolfsburg": 138,
    "kairat": 8326,
}

_USER_AGENT = "Mozilla/5.0 (compatible; MatchRecap/1.0)"


def _ensure_dirs() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def logo_candidates(name: str) -> list[Path]:
    key = canonical_team_key(name)
    compact = key.replace(" ", "_")
    names = [f"{key}.png", f"{compact}.png", f"{key}.webp", f"{compact}.webp"]
    out: list[Path] = []
    for folder in (ASSET_DIR, CACHE_DIR):
        for filename in names:
            out.append(folder / filename)
    return out


def _http_get(url: str, timeout: float = 12.0) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            if not data or len(data) < 64:
                return None
            # Reject tiny placeholders / HTML error pages.
            head = data[:16]
            if head.startswith(b"<!DOCTYPE") or head.startswith(b"<html"):
                return None
            return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None


def _espn_url(team_key: str) -> str | None:
    espn_id = _ESPN_IDS.get(team_key)
    if espn_id is None:
        compact = team_key.replace(" ", "")
        for key, value in _ESPN_IDS.items():
            if key.replace(" ", "") == compact:
                espn_id = value
                break
    if espn_id is None:
        return None
    return f"https://a.espncdn.com/i/teamlogos/soccer/500/{espn_id}.png"


def _sportsdb_badge(name: str) -> str | None:
    """Best-effort badge URL from TheSportsDB search."""
    queries = [name]
    key = normalize_team_key(name)
    if key in ("psg", "paris sg"):
        queries = ["Paris Saint Germain", "Paris SG"]
    elif "united" in key or "city" in key:
        queries = [name, name.replace(" Utd", " United")]

    for query in queries:
        url = "https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t=" + urllib.parse.quote(query)
        raw = _http_get(url, timeout=10.0)
        if not raw:
            continue
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        teams = payload.get("teams") or []
        if not teams:
            continue
        # Prefer the closest name match so "Paris SG" does not latch onto a
        # random amateur side that also matched the search.
        needle = normalize_team_key(name)
        ranked = sorted(
            teams,
            key=lambda row: _name_distance(needle, normalize_team_key(row.get("strTeam") or "")),
        )
        badge = ranked[0].get("strBadge") or ranked[0].get("strTeamBadge")
        if badge and str(badge).startswith("http"):
            return str(badge)
    return None


def _name_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if a in b or b in a:
        return 1
    a_tokens, b_tokens = set(a.split()), set(b.split())
    return 10 - len(a_tokens & b_tokens)


def _write_logo(path: Path, data: bytes) -> Path | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    except OSError:
        return None


@lru_cache(maxsize=128)
def resolve_logo(name: str, team_id: int | None = None) -> str | None:
    """Return a filesystem path to a crest PNG, or None."""
    _ensure_dirs()
    for candidate in logo_candidates(name):
        if candidate.exists() and candidate.stat().st_size > 64:
            return str(candidate)

    key = canonical_team_key(name)
    cache_path = CACHE_DIR / f"{key.replace(' ', '_')}.png"

    sources: list[str] = []
    espn = _espn_url(key)
    if espn:
        sources.append(espn)
    badge = _sportsdb_badge(name)
    if badge:
        sources.append(badge)

    for url in sources:
        data = _http_get(url)
        if not data:
            continue
        written = _write_logo(cache_path, data)
        if written is not None:
            return str(written)
    return None


def warm_logos(home: str, away: str, home_id: int | None = None, away_id: int | None = None) -> dict[str, str | None]:
    """Download both crests up front so renderers never block mid-frame."""
    return {
        home: resolve_logo(home, home_id),
        away: resolve_logo(away, away_id),
    }


def clear_logo_cache() -> None:
    resolve_logo.cache_clear()
