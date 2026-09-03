"""Resolve a Livescore.com match URL into a local recap export.

Pipeline:

    1. Parse the Livescore URL → teams / date / competition (no coordinates).
    2. Health-check a WhoScored-shaped export: full event stream **and**
       precise tracking x/y, not Opta-zone centroids.
    3. If WhoScored is missing or reconstructed, try adapters in order:
       Sofascore → FotMob → Understat / official import
       (``tools/import_laliga_match.py`` + ``scrape_match.py``).
    4. Never invent coordinates. An adapter that cannot supply real x/y
       returns None; a reconstructed local export may still be used, marked
       unhealthy, so the farm can render maps that the director already skips.

Studio probes this module as ``recap.livescore.resolve_url``.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from recap import audit as audit_mod
from recap import colors
from recap.data import list_match_dirs, load_match, read_json

REPO_ROOT = Path(__file__).resolve().parent.parent

# A full WhoScored chalkboard has hundreds of events and a real pass map.
# The La Liga official import for 1993920 has ~100 commentary rows / ~20 passes.
FULL_EVENT_ROWS = 400
FULL_EVENT_PASSES = 100

LIVESCORE_HOSTS = {"livescore.com", "www.livescore.com", "m.livescore.com"}
WHOSCORED_HOSTS = {"whoscored.com", "www.whoscored.com"}

# Canonical Livescore path:
#   /{locale}/football/{country}/{comp}/{home}-vs-{away}/{event_id}/
_LIVESCORE_PATH = re.compile(
    r"""
    ^/
    (?:(?P<locale>[a-z]{2})/)?
    (?P<sport>football|soccer)/
    (?:(?P<country>[a-z0-9-]+)/)?
    (?:(?P<comp>[a-z0-9-]+)/)?
    (?P<slug>[a-z0-9-]+-vs-[a-z0-9-]+)
    (?:/(?P<event_id>\d{4,}))?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_VS_SLUG = re.compile(r"^(?P<home>.+)-vs-(?P<away>.+)$", re.IGNORECASE)
_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_WHO_ID = re.compile(r"/matches?/(\d{5,10})", re.I)
_TAB_SEGMENTS = {
    "lineups", "line-ups", "h2h", "table", "news", "prediction", "odds",
    "info", "summary", "stats", "player-stats", "commentary", "preview",
}

COMP_LABELS = {
    "laliga": "LaLiga",
    "la-liga": "LaLiga",
    "primera-division": "LaLiga",
    "premier-league": "Premier League",
    "serie-a": "Serie A",
    "bundesliga": "Bundesliga",
    "ligue-1": "Ligue 1",
    "world-cup": "World Cup",
    "fifa-world-cup": "World Cup",
    "champions-league": "Champions League",
    "europa-league": "Europa League",
    "conference-league": "Conference League",
}


def _load_module(name: str, path: Path) -> Any | None:
    """Import a repo-root / tools script without requiring a package."""
    path = Path(path)
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    if name in sys.modules:
        return sys.modules[name]
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        return None
    return mod


def slug_to_name(slug: str) -> str:
    raw = re.sub(r"[-_]+", " ", str(slug or "")).strip()
    if not raw:
        return ""
    titled = " ".join(part.capitalize() for part in raw.split())
    key = colors.canonical_key(titled)
    if key in colors.CLUB_KITS or key in colors.NATIONAL_KITS:
        return " ".join(word.capitalize() for word in key.split())
    return titled


def competition_label(slug: str | None) -> str:
    if not slug:
        return ""
    key = str(slug).strip().lower()
    if key in COMP_LABELS:
        return COMP_LABELS[key]
    return slug_to_name(key)


@dataclass(frozen=True)
class LivescoreFixture:
    url: str
    home: str
    away: str
    date: str | None = None
    competition: str | None = None
    country: str | None = None
    event_id: str | None = None
    sport: str = "football"
    locale: str | None = None
    whoscored_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceHealth:
    source: str
    healthy: bool
    full_events: bool
    has_precise_coordinates: bool
    coordinate_source: str
    event_rows: int = 0
    pass_rows: int = 0
    shot_rows: int = 0
    unique_xy: int = 0
    notes: list[str] = field(default_factory=list)
    invented_coordinates: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedMatch:
    fixture: LivescoreFixture
    match_dir: Path
    health: SourceHealth
    adapter: str
    fallbacks_tried: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture.as_dict(),
            "match_dir": str(self.match_dir),
            "path": str(self.match_dir),
            "health": self.health.as_dict(),
            "adapter": self.adapter,
            "fallbacks_tried": list(self.fallbacks_tried),
        }


class EventAdapter(Protocol):
    name: str

    def can_handle(self, fixture: LivescoreFixture) -> bool: ...

    def fetch(
        self,
        fixture: LivescoreFixture,
        dest: Path,
        *,
        allow_scrape: bool = False,
        official_json: Path | None = None,
    ) -> Path | None: ...


def parse_livescore_url(url: str) -> LivescoreFixture:
    """Pull teams / date / competition out of a Livescore.com match URL.

    Canonical path: ``/{locale}/football/{country}/{comp}/{home}-vs-{away}/{id}/``.
    Livescore pages do not carry pitch coordinates. This function never
    fabricates x/y — it only reads the path and query string.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Empty Livescore URL.")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if "livescore.com" not in host:
        raise ValueError(f"Not a Livescore.com URL: {url!r}")
    parts = [p for p in (parsed.path or "").split("/") if p]
    locale = None
    if parts and len(parts[0]) == 2 and parts[0].isalpha():
        locale = parts.pop(0).lower()
    sport = "football"
    if parts and parts[0].lower() in {"football", "soccer"}:
        sport = parts.pop(0).lower()
    else:
        raise ValueError(f"Could not parse Livescore match path: {url!r}")
    while parts and parts[-1].lower() in _TAB_SEGMENTS:
        parts.pop()
    date = None
    kept: list[str] = []
    for part in parts:
        found = _DATE.fullmatch(part)
        if found:
            date = found.group(1)
        else:
            kept.append(part)
    parts = kept
    event_id = None
    if parts and parts[-1].isdigit() and len(parts[-1]) >= 4:
        event_id = parts.pop()
    slug_index = next((i for i, part in enumerate(parts) if "-vs-" in part.lower()), None)
    if slug_index is None:
        raise ValueError(f"Livescore slug is missing home-vs-away: {url!r}")
    slug = parts[slug_index]
    prefix = parts[:slug_index]
    country = prefix[0] if len(prefix) >= 1 else None
    comp = prefix[1] if len(prefix) >= 2 else None
    vs = _VS_SLUG.match(slug)
    if not vs:
        raise ValueError(f"Livescore slug is missing home-vs-away: {slug!r}")
    home = slug_to_name(vs.group("home"))
    away = slug_to_name(vs.group("away"))
    if not home or not away:
        raise ValueError(f"Could not read team names from {slug!r}")
    query = parse_qs(parsed.query or "")
    if date is None:
        for key in ("date", "kickoff", "utcDate"):
            if query.get(key):
                found = _DATE.search(query[key][0])
                if found:
                    date = found.group(1)
                    break
    if date is None:
        found = _DATE.search(raw)
        date = found.group(1) if found else None
    return LivescoreFixture(
        url=raw,
        home=home,
        away=away,
        date=date,
        competition=competition_label(comp),
        country=slug_to_name(country or "") or None,
        event_id=event_id,
        sport=sport,
        locale=locale,
    )


def assess_source(match_dir: Path | str) -> SourceHealth:
    """WhoScored health: full events + precise x/y vs reconstructed centroids.

    Uses the same classifier as ``recap.audit.detect_data_health`` so the
    1993920 La Liga import (zone centroids) and 1953861 Scotland chalkboard
    (tracking points) stay on opposite sides of the line.
    """
    bundle = load_match(Path(match_dir))
    raw = audit_mod.detect_data_health(bundle)
    full_events = (
        int(raw.get("event_rows") or 0) >= FULL_EVENT_ROWS
        and int(raw.get("pass_rows") or 0) >= FULL_EVENT_PASSES
    )
    coord_source = str(raw.get("coordinate_source") or "unknown")
    precise = bool(raw.get("has_precise_coordinates")) and coord_source == "whoscored"
    notes: list[str] = []
    if not full_events:
        notes.append(
            f"Event stream is thin ({raw.get('event_rows')} rows, "
            f"{raw.get('pass_rows')} passes); WhoScored chalkboard not present."
        )
    if coord_source == "reconstructed":
        notes.append("Coordinates are Opta-zone centroids, not tracking x/y.")
    elif not precise:
        notes.append(f"Coordinate source is {coord_source!r}, not WhoScored tracking.")
    healthy = full_events and precise
    source = "whoscored" if healthy else coord_source
    return SourceHealth(
        source=source,
        healthy=healthy,
        full_events=full_events,
        has_precise_coordinates=precise,
        coordinate_source=coord_source,
        event_rows=int(raw.get("event_rows") or 0),
        pass_rows=int(raw.get("pass_rows") or 0),
        shot_rows=int(raw.get("shot_rows") or 0),
        unique_xy=int(raw.get("coordinate_unique_xy") or 0),
        notes=notes,
        invented_coordinates=False,
    )


def find_local_export(fixture: LivescoreFixture, output_root: Path) -> Path | None:
    """Match a parsed fixture against ``output/<id>_Home_vs_Away`` folders."""
    home_key = colors.canonical_key(fixture.home)
    away_key = colors.canonical_key(fixture.away)
    ranked: list[tuple[int, Path]] = []
    for path in list_match_dirs(output_root):
        try:
            summary = read_json(path / "match_summary.json")
        except Exception:
            continue
        sh = colors.canonical_key((summary.get("home") or {}).get("name") or "")
        sa = colors.canonical_key((summary.get("away") or {}).get("name") or "")
        if {sh, sa} != {home_key, away_key}:
            continue
        score = 4 if (sh, sa) == (home_key, away_key) else 2
        date = str(summary.get("startDate") or "")[:10]
        if fixture.date and date == fixture.date:
            score += 3
        match_id = str(summary.get("matchId") or "")
        if fixture.event_id and (
            path.name.startswith(f"{fixture.event_id}_") or match_id == fixture.event_id
        ):
            score += 2
        ranked.append((score, path))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].name))
    return ranked[0][1]


def find_export_by_whoscored_id(match_id: str, output_root: Path) -> Path | None:
    if not match_id:
        return None
    for path in list_match_dirs(output_root):
        if path.name == match_id or path.name.startswith(f"{match_id}_"):
            return path
        try:
            summary = read_json(path / "match_summary.json")
        except Exception:
            continue
        if str(summary.get("matchId") or "") == str(match_id):
            return path
    return None


class LocalWhoScoredAdapter:
    """Already-scraped chalkboard under output/. No network."""

    name = "whoscored_local"

    def can_handle(self, fixture: LivescoreFixture) -> bool:
        return True

    def fetch(
        self,
        fixture: LivescoreFixture,
        dest: Path,
        *,
        allow_scrape: bool = False,
        official_json: Path | None = None,
    ) -> Path | None:
        return find_local_export(fixture, dest)


class WhoScoredScrapeAdapter:
    """Optional live scrape via ``scrape_match.py``. Off unless allow_scrape."""

    name = "whoscored_scrape"

    def can_handle(self, fixture: LivescoreFixture) -> bool:
        url = fixture.whoscored_url or os.environ.get("WHOSCORED_MATCH_URL", "")
        return bool(str(url).strip())

    def fetch(
        self,
        fixture: LivescoreFixture,
        dest: Path,
        *,
        allow_scrape: bool = False,
        official_json: Path | None = None,
    ) -> Path | None:
        if not allow_scrape:
            return None
        url = (fixture.whoscored_url or os.environ.get("WHOSCORED_MATCH_URL") or "").strip()
        if not url:
            return None
        mod = _load_module("scrape_match", REPO_ROOT / "scrape_match.py")
        if mod is None:
            return None
        scrape = getattr(mod, "_scrape_url", None)
        if scrape is None:
            return None
        import asyncio

        before = {p.resolve() for p in list_match_dirs(dest)}
        try:
            asyncio.run(scrape(url, str(dest), False, 12, False, None))
        except Exception:
            return None
        after = [p for p in list_match_dirs(dest) if p.resolve() not in before]
        if after:
            return after[0]
        return find_local_export(fixture, dest)


class SofascoreAdapter:
    """Sofascore event dump. Refuses to synthesise x/y."""

    name = "sofascore"

    def can_handle(self, fixture: LivescoreFixture) -> bool:
        return True

    def fetch(
        self,
        fixture: LivescoreFixture,
        dest: Path,
        *,
        allow_scrape: bool = False,
        official_json: Path | None = None,
    ) -> Path | None:
        # A future worker can drop sofascore_events.json next to the export.
        # Without a real payload we do not invent shot locations.
        hint = dest / "sofascore_events.json"
        if hint.exists():
            return dest if (dest / "all_events.csv").exists() else None
        return None


class FotMobAdapter:
    """FotMob stats (see verify_stats.py) are not pitch coordinates."""

    name = "fotmob"

    def can_handle(self, fixture: LivescoreFixture) -> bool:
        return True

    def fetch(
        self,
        fixture: LivescoreFixture,
        dest: Path,
        *,
        allow_scrape: bool = False,
        official_json: Path | None = None,
    ) -> Path | None:
        # verify_stats.py cross-checks counts, not x/y. Do not treat that as a map.
        return None


class OfficialUnderstatAdapter:
    """La Liga official / Understat-style import via tools/import_laliga_match.py.

    Zone centroids in that importer are labelled reconstructed — they are not
    invented event rows, but they are also not WhoScored tracking points.
    """

    name = "understat_official"

    def can_handle(self, fixture: LivescoreFixture) -> bool:
        home = colors.canonical_key(fixture.home)
        away = colors.canonical_key(fixture.away)
        laliga = (fixture.competition or "").lower() in {"laliga", "la liga", "primera division"}
        barca_rayo = {home, away} == {"barcelona", "rayo vallecano"}
        return laliga or barca_rayo or official_json_ready()

    def fetch(
        self,
        fixture: LivescoreFixture,
        dest: Path,
        *,
        allow_scrape: bool = False,
        official_json: Path | None = None,
    ) -> Path | None:
        existing = find_local_export(fixture, dest)
        json_path = Path(official_json) if official_json else None
        if json_path and json_path.exists():
            mod = _load_module(
                "import_laliga_match",
                REPO_ROOT / "tools" / "import_laliga_match.py",
            )
            if mod is None:
                return existing
            load_pp = getattr(mod, "load_pageprops", None)
            export = getattr(mod, "export_match", None)
            if load_pp and export:
                folder = dest / f"{getattr(mod, 'MATCH_ID', 'official')}_Barcelona_vs_Rayo_Vallecano"
                try:
                    return Path(export(load_pp(json_path), folder))
                except Exception:
                    return existing
        return existing


def official_json_ready() -> bool:
    return False


def default_adapters() -> list[EventAdapter]:
    return [
        LocalWhoScoredAdapter(),
        WhoScoredScrapeAdapter(),
        SofascoreAdapter(),
        FotMobAdapter(),
        OfficialUnderstatAdapter(),
    ]


def resolve_from_livescore(
    url: str,
    *,
    output_root: Path | str | None = None,
    allow_scrape: bool = False,
    official_json: Path | str | None = None,
    adapters: list[EventAdapter] | None = None,
) -> ResolvedMatch:
    """Parse *url*, health-check WhoScored, then walk fallback adapters."""
    fixture = parse_livescore_url(url)
    dest = Path(output_root) if output_root else REPO_ROOT / "output"
    chain = adapters if adapters is not None else default_adapters()
    json_path = Path(official_json) if official_json else None
    tried: list[str] = []
    best: tuple[str, Path, SourceHealth] | None = None

    for adapter in chain:
        if not adapter.can_handle(fixture):
            continue
        tried.append(adapter.name)
        try:
            path = adapter.fetch(
                fixture, dest, allow_scrape=allow_scrape, official_json=json_path,
            )
        except Exception:
            continue
        if path is None:
            continue
        path = Path(path)
        if not (path / "match_summary.json").exists() or not (path / "all_events.csv").exists():
            continue
        health = assess_source(path)
        candidate = (adapter.name, path, health)
        if health.healthy:
            return ResolvedMatch(
                fixture=fixture, match_dir=path, health=health,
                adapter=adapter.name, fallbacks_tried=tried,
            )
        if best is None:
            best = candidate
        elif health.full_events and not best[2].full_events:
            best = candidate
        elif health.has_precise_coordinates and not best[2].has_precise_coordinates:
            best = candidate

    if best is None:
        raise FileNotFoundError(
            "No local WhoScored export and no fallback adapter returned real "
            f"events for {fixture.home} vs {fixture.away}. Tried: {tried or ['(none)']}. "
            "Coordinates are never invented — scrape or import a chalkboard first."
        )
    name, path, health = best
    return ResolvedMatch(
        fixture=fixture, match_dir=path, health=health,
        adapter=name, fallbacks_tried=tried,
    )


def resolve_url(
    url: str,
    output_root: Path | str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Studio / CLI entry: Livescore (or WhoScored id) → export dict.

    Return shape matches ``recap.studio_api._try_sibling_scrape``
    (``match_dir`` / ``path``).
    """
    raw = (url or "").strip()
    dest = Path(output_root) if output_root else REPO_ROOT / "output"
    host = (urlparse(raw).hostname or "").lower()
    if "whoscored.com" in host:
        found = _WHO_ID.search(raw)
        if not found:
            raise ValueError(f"WhoScored URL is missing a match id: {url!r}")
        path = find_export_by_whoscored_id(found.group(1), dest)
        if path is None:
            raise FileNotFoundError(f"No local export for WhoScored match {found.group(1)}")
        health = assess_source(path)
        fixture = LivescoreFixture(
            url=raw, home="", away="", event_id=found.group(1),
            whoscored_url=raw,
        )
        try:
            summary = read_json(path / "match_summary.json")
            fixture = LivescoreFixture(
                url=raw,
                home=(summary.get("home") or {}).get("name") or "",
                away=(summary.get("away") or {}).get("name") or "",
                date=str(summary.get("startDate") or "")[:10] or None,
                competition=str(summary.get("league") or "") or None,
                event_id=found.group(1),
                whoscored_url=raw,
            )
        except Exception:
            pass
        return ResolvedMatch(
            fixture=fixture, match_dir=path, health=health,
            adapter="whoscored_local", fallbacks_tried=["whoscored_local"],
        ).as_dict()
    return resolve_from_livescore(raw, output_root=dest).as_dict()
