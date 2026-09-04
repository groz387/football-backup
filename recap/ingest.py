"""Livescore URL parse + WhoScored health + honest fallback adapters.

Priority after a Livescore.com paste:
  1. Parse teams / date / competition / score (never invent).
  2. WhoScored — existing scrape_match.py + local output/ health check.
     FULL means enough events AND precise x/y (not reconstructed centroids).
  3. Sofascore / FotMob / Understat adapters — stubbed until a real scraper
     exists. They do not invent coordinates. They tell the operator where to
     drop an export.

WhoScored remains primary. Adapters never fabricate x/y.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import audit as audit_mod
from . import colors
from .data import describe_match_dir, list_match_dirs, load_match, safe_name
from .theme import normalize_team_key as _theme_key

REPO_ROOT = Path(__file__).resolve().parent.parent

MIN_EVENTS_FULL = 180
MIN_PASSES_FULL = 100
DROP_HINT = (
    "No usable event export for this fixture. Drop a WhoScored (or Opta) folder "
    "under output/<id>_<Home>_vs_<Away>/ with match_data_raw.json + events CSV, "
    "then re-run. Fallback scrapers (Sofascore / FotMob / Understat) are stubbed "
    "and will not invent coordinates."
)

_VS = re.compile(r"(.+?)-vs-(.+)$", re.IGNORECASE)
_DATE = re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})")
_SCORE = re.compile(r"\b(\d{1,2})[-:_](\d{1,2})\b")
_ID = re.compile(r"\b(\d{5,})\b")


def _slug_team(value: str) -> str:
    text = unquote(str(value or "")).replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # livescore slugs are lowercase; title-case for display without inventing.
    return " ".join(part.capitalize() for part in text.split()) if text else ""


def parse_livescore_url(url: str) -> dict[str, Any]:
    """Extract what the URL actually contains. Missing fields stay None."""
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("Empty Livescore URL.")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower().split(":")[0]
    if "livescore.com" not in host:
        raise ValueError(f"Not a livescore.com URL: {url!r}")
    path = unquote(parsed.path or "").strip("/")
    parts = [p for p in path.split("/") if p]
    query = parse_qs(parsed.query)

    home = away = None
    competition = None
    country = None
    date = None
    score_home = score_away = None
    match_id = None
    lang = None

    if parts and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0], re.I):
        lang = parts[0].lower()
        parts = parts[1:]

    # Typical: football/<country>/<competition>/<home>-vs-<away>/[<id>]
    sport = parts[0] if parts else None
    rest = parts[1:] if len(parts) > 1 else []

    for part in rest:
        date_match = _DATE.search(part)
        if date_match and date is None:
            y, m, d = date_match.group(1), date_match.group(2).zfill(2), date_match.group(3).zfill(2)
            date = f"{y}-{m}-{d}"
        vs = _VS.match(part)
        if vs and home is None:
            home = _slug_team(vs.group(1))
            away = _slug_team(vs.group(2))
            continue
        score_match = _SCORE.fullmatch(part.replace(":", "-"))
        if score_match and score_home is None:
            score_home = int(score_match.group(1))
            score_away = int(score_match.group(2))
            continue
        id_match = _ID.fullmatch(part)
        if id_match and match_id is None:
            match_id = id_match.group(1)

    tokens = []
    for part in rest:
        if _VS.match(part) or _DATE.search(part) or _SCORE.fullmatch(part.replace(":", "-")) or _ID.fullmatch(part):
            continue
        if part.lower() in {"live", "match", "details", "info", "football", "soccer"}:
            continue
        tokens.append(part)
    if tokens:
        country = country or _slug_team(tokens[0])
        competition = competition or _slug_team(tokens[1] if len(tokens) > 1 else tokens[0])

    if not home and query.get("home"):
        home = _slug_team(query["home"][0])
    if not away and query.get("away"):
        away = _slug_team(query["away"][0])
    if not date and query.get("date"):
        date = query["date"][0]
    if (query.get("score") or [None])[0]:
        sm = _SCORE.search(query["score"][0])
        if sm:
            score_home, score_away = int(sm.group(1)), int(sm.group(2))

    return {
        "url": raw,
        "host": host,
        "sport": sport,
        "language": lang,
        "home": home,
        "away": away,
        "competition": competition,
        "country": country,
        "date": date,
        "score_home": score_home,
        "score_away": score_away,
        "match_id": match_id,
        "source": "livescore",
    }


def _load_script(name: str, rel: str) -> Any | None:
    """Import scrape_match.py / tools/import_laliga_match.py from the repo root."""
    path = REPO_ROOT / rel
    if not path.exists():
        return None
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        return None
    return mod


def _try_whoscored_scrape(output_root: Path) -> Path | None:
    """Reuse scrape_match.py when a WhoScored URL is explicitly provided.

    Livescore pages have no x/y. We never guess a chalkboard from the slug.
    """
    url = (os.environ.get("WHOSCORED_MATCH_URL") or "").strip()
    if not url:
        return None
    mod = _load_script("scrape_match", "scrape_match.py")
    scrape = getattr(mod, "_scrape_url", None) if mod else None
    if scrape is None:
        return None
    import asyncio

    before = {p.resolve() for p in list_match_dirs(output_root)}
    try:
        asyncio.run(scrape(url, str(output_root), False, 12, False, None))
    except Exception:
        return None
    after = [p for p in list_match_dirs(output_root) if p.resolve() not in before]
    return after[0] if after else None


def _try_official_import(output_root: Path) -> Path | None:
    """Reuse tools/import_laliga_match.py when an official JSON dump is present."""
    raw = (os.environ.get("LALIGA_OFFICIAL_JSON") or "").strip()
    if not raw:
        return None
    json_path = Path(raw)
    if not json_path.exists():
        return None
    mod = _load_script("import_laliga_match", "tools/import_laliga_match.py")
    if mod is None:
        return None
    load_pp = getattr(mod, "load_pageprops", None)
    export = getattr(mod, "export_match", None)
    match_id = getattr(mod, "MATCH_ID", "official")
    if not load_pp or not export:
        return None
    dest = output_root / f"{match_id}_Barcelona_vs_Rayo_Vallecano"
    try:
        return Path(export(load_pp(json_path), dest))
    except Exception:
        return None


def _names_close(a: str, b: str) -> bool:
    left = colors.canonical_key(a)
    right = colors.canonical_key(b)
    if not left or not right:
        return False
    if left == right:
        return True
    compact_a, compact_b = left.replace(" ", ""), right.replace(" ", "")
    if compact_a == compact_b:
        return True
    return left in right or right in left


def health_check_export(match_dir: str | Path) -> dict[str, Any]:
    """WhoScored-style health against an existing output folder."""
    path = Path(match_dir)
    result: dict[str, Any] = {
        "match_dir": str(path),
        "exists": path.is_dir(),
        "ok": False,
        "full": False,
        "coordinate_source": None,
        "has_precise_coordinates": False,
        "event_rows": 0,
        "shot_rows": 0,
        "home": None,
        "away": None,
        "reason": "",
    }
    if not path.is_dir():
        result["reason"] = "match dir missing"
        return result
    try:
        bundle = load_match(path)
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"load failed: {type(exc).__name__}"
        return result
    health = audit_mod.detect_data_health(bundle)
    source = str(health.get("coordinate_source") or "unknown")
    precise = bool(health.get("has_precise_coordinates"))
    events = int(health.get("event_rows") or 0)
    full = (
        events >= MIN_EVENTS_FULL
        and int(health.get("pass_rows") or 0) >= MIN_PASSES_FULL
        and precise
        and source == "whoscored"
    )
    result.update({
        "ok": True,
        "full": full,
        "coordinate_source": source,
        "has_precise_coordinates": precise,
        "event_rows": events,
        "shot_rows": int(health.get("shot_rows") or 0),
        "pass_rows": int(health.get("pass_rows") or 0),
        "coordinate_unique_xy": health.get("coordinate_unique_xy"),
        "coordinate_sample_n": health.get("coordinate_sample_n"),
        "home": bundle.home,
        "away": bundle.away,
        "kickoff": bundle.kickoff,
        "label": describe_match_dir(path),
        "reason": (
            "full WhoScored event map"
            if full
            else (
                f"limited ({source}, events={events}, precise={precise}) "
                "— maps that need tracking x/y stay blocked"
            )
        ),
    })
    return result


def inspect_output_root(output_root: str | Path = "output") -> list[dict[str, Any]]:
    root = Path(output_root)
    if not root.is_dir():
        return []
    return [health_check_export(path) for path in list_match_dirs(root)]


def find_local_match(
    fixture: dict[str, Any],
    output_root: str | Path = "output",
) -> Path | None:
    home = str(fixture.get("home") or "")
    away = str(fixture.get("away") or "")
    if not home or not away:
        return None
    root = Path(output_root)
    if not root.is_dir():
        return None
    for path in list_match_dirs(root):
        try:
            bundle = load_match(path)
        except Exception:
            name = path.name.lower()
            if _theme_key(home).replace(" ", "") in name and _theme_key(away).replace(" ", "") in name:
                return path
            continue
        if _names_close(bundle.home, home) and _names_close(bundle.away, away):
            return path
        if _names_close(bundle.home, away) and _names_close(bundle.away, home):
            return path
    return None


@dataclass
class AdapterResult:
    name: str
    status: str  # used | skipped | unavailable | stub
    match_dir: Path | None = None
    reason: str = ""
    drop_hint: str = ""
    health: dict[str, Any] = field(default_factory=dict)


class SourceAdapter:
    name = "base"

    def available(self) -> bool:
        return False

    def fetch(self, fixture: dict[str, Any], output_root: Path) -> AdapterResult:
        return AdapterResult(
            name=self.name,
            status="unavailable",
            reason="adapter has no scraper",
            drop_hint=DROP_HINT,
        )


class WhoScoredAdapter(SourceAdapter):
    name = "whoscored"

    def available(self) -> bool:
        return True

    def fetch(self, fixture: dict[str, Any], output_root: Path) -> AdapterResult:
        local = find_local_match(fixture, output_root)
        if local is None:
            local = _try_whoscored_scrape(output_root)
        if local is None:
            return AdapterResult(
                name=self.name,
                status="unavailable",
                reason="no local WhoScored export matched this fixture",
                drop_hint=DROP_HINT,
            )
        health = health_check_export(local)
        status = "used" if health.get("full") else "skipped"
        reason = health.get("reason") or ""
        if status == "skipped":
            reason = (
                f"WhoScored export found but not full event data ({reason}). "
                "Trying fallbacks; will still use this folder if nothing better exists."
            )
        return AdapterResult(
            name=self.name,
            status=status,
            match_dir=local,
            reason=reason,
            health=health,
            drop_hint="" if status == "used" else DROP_HINT,
        )


class _StubAdapter(SourceAdapter):
    def __init__(self, name: str) -> None:
        self.name = name

    def fetch(self, fixture: dict[str, Any], output_root: Path) -> AdapterResult:
        dest = Path(output_root) / "_drop_exports_here"
        return AdapterResult(
            name=self.name,
            status="stub",
            reason=(
                f"{self.name} scraper is not wired. Will not invent x/y. "
                f"If you have an official JSON dump, drop it under {dest}/."
            ),
            drop_hint=DROP_HINT,
        )


class OfficialImportAdapter(SourceAdapter):
    """La Liga official / Understat-style import. Zone centroids, never invented rows."""

    name = "laliga_official"

    def available(self) -> bool:
        return (REPO_ROOT / "tools" / "import_laliga_match.py").exists()

    def fetch(self, fixture: dict[str, Any], output_root: Path) -> AdapterResult:
        imported = _try_official_import(output_root)
        if imported is None:
            return AdapterResult(
                name=self.name,
                status="stub",
                reason=(
                    "Official La Liga importer is idle (set LALIGA_OFFICIAL_JSON). "
                    "Will not invent x/y."
                ),
                drop_hint=DROP_HINT,
            )
        health = health_check_export(imported)
        return AdapterResult(
            name=self.name,
            status="used" if health.get("ok") else "skipped",
            match_dir=imported,
            reason=health.get("reason") or "official Opta commentary import",
            health=health,
            drop_hint="" if health.get("full") else DROP_HINT,
        )


ADAPTERS: list[SourceAdapter] = [
    WhoScoredAdapter(),
    _StubAdapter("sofascore"),
    _StubAdapter("fotmob"),
    _StubAdapter("understat"),
    OfficialImportAdapter(),
]


def resolve(
    *,
    livescore_url: str | None = None,
    match_dir: str | Path | None = None,
    output_root: str | Path = "output",
) -> dict[str, Any]:
    """Resolve a fixture to a local export. Never invents coordinates."""
    root = Path(output_root)
    fixture: dict[str, Any] = {}
    if livescore_url:
        fixture = parse_livescore_url(livescore_url)

    if match_dir:
        path = Path(match_dir)
        health = health_check_export(path)
        return {
            "ok": bool(health.get("ok")),
            "match_dir": str(path) if path.exists() else None,
            "fixture": fixture,
            "coordinate_source": health.get("coordinate_source"),
            "health": health,
            "adapters": [],
            "drop_hint": "" if health.get("ok") else DROP_HINT,
        }

    if not fixture:
        raise ValueError("Pass --livescore-url or --match-dir.")

    trail: list[dict[str, Any]] = []
    chosen: AdapterResult | None = None
    fallback: AdapterResult | None = None
    for adapter in ADAPTERS:
        result = adapter.fetch(fixture, root)
        trail.append({
            "name": result.name,
            "status": result.status,
            "reason": result.reason,
            "match_dir": str(result.match_dir) if result.match_dir else None,
        })
        if result.status == "used" and result.match_dir:
            chosen = result
            break
        if result.match_dir and fallback is None:
            fallback = result

    picked = chosen or fallback
    health = picked.health if picked and picked.health else {}
    if picked and picked.match_dir and not health:
        health = health_check_export(picked.match_dir)

    if picked and picked.match_dir:
        if health:
            health = dict(health)
            # Honour the actual coordinate classifier; do not upgrade stubs.
            if not chosen:
                health["coordinate_source"] = health.get("coordinate_source") or "unknown"
        return {
            "ok": True,
            "match_dir": str(picked.match_dir),
            "fixture": fixture,
            "coordinate_source": health.get("coordinate_source"),
            "health": health,
            "adapters": trail,
            "used_adapter": picked.name,
            "full": bool(health.get("full")),
            "drop_hint": "" if health.get("full") else DROP_HINT,
        }

    return {
        "ok": False,
        "match_dir": None,
        "fixture": fixture,
        "coordinate_source": None,
        "health": {},
        "adapters": trail,
        "drop_hint": DROP_HINT,
        "drop_slug": safe_name(
            f"{fixture.get('home') or 'Home'}_vs_{fixture.get('away') or 'Away'}"
        ),
    }


# Back-compat alias used by tests / studio.
resolve_match = resolve
health_check_whoscored = health_check_export


def resolve_url(url: str, output_root: Path | str | None = None, **_: Any) -> dict[str, Any]:
    """Studio scrape probe: Livescore URL → export dict with match_dir/path."""
    result = resolve(livescore_url=url, output_root=output_root or "output")
    if result.get("match_dir"):
        result.setdefault("path", result["match_dir"])
    return result
