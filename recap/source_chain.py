"""Livescore → WhoScored-first → Flashscore fallback orchestration.

Search and scrape happen only after an explicit operator action. On Windows,
scrapers open in a visible CMD window. The watcher then health-checks the
export; no adapter invents coordinates.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from .data import list_match_dirs
from .resolve_match import (
    LivescoreFixture,
    assess_source,
    find_local_export,
    parse_livescore_url,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def parse_search_candidates(
    html: str,
    base_url: str,
    *,
    source: str,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if source == "whoscored" and not re.search(r"/matches?/\d{5,10}", href, re.I):
            continue
        if source == "flashscore" and "/match/" not in href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        text = " ".join(anchor.get_text(" ", strip=True).split())
        context = " ".join((anchor.parent.get_text(" ", strip=True) if anchor.parent else text).split())
        date = ""
        date_match = re.search(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", context)
        if date_match:
            date = date_match.group(1).replace(".", "-").replace("/", "-")
        out.append({"url": url, "text": text, "context": context[:500], "date": date})
    return out


def rank_candidates(
    candidates: list[dict[str, str]],
    fixture: LivescoreFixture,
) -> dict[str, Any]:
    home = _tokens(fixture.home)
    away = _tokens(fixture.away)
    ranked: list[dict[str, Any]] = []
    for item in candidates:
        hay = _tokens(f"{item.get('text', '')} {item.get('context', '')} {item.get('url', '')}")
        home_hit = bool(home) and len(home & hay) >= max(1, min(2, len(home)))
        away_hit = bool(away) and len(away & hay) >= max(1, min(2, len(away)))
        score = (4 if home_hit else 0) + (4 if away_hit else 0)
        if fixture.date and fixture.date == item.get("date"):
            score += 4
        elif fixture.date and fixture.date in item.get("context", ""):
            score += 3
        row = dict(item)
        row["score"] = score
        ranked.append(row)
    ranked.sort(key=lambda row: (-int(row["score"]), row["url"]))
    viable = [row for row in ranked if row["score"] >= 8]
    if not viable:
        return {"status": "not_found", "candidate": None, "candidates": ranked[:8]}
    if len(viable) > 1 and viable[0]["score"] == viable[1]["score"]:
        return {"status": "ambiguous", "candidate": None, "candidates": viable[:8]}
    return {"status": "found", "candidate": viable[0], "candidates": viable[:8]}


def _fetch_rendered(url: str, wait: int) -> str:
    from fetch_page import fetch_with_nodriver
    return asyncio.run(fetch_with_nodriver(url, wait_seconds=wait))


def search_source(
    fixture: LivescoreFixture,
    source: str,
    *,
    wait: int = 12,
    fetcher: Callable[[str, int], str] | None = None,
) -> dict[str, Any]:
    query = quote_plus(f"{fixture.home} {fixture.away}")
    if source == "whoscored":
        url = f"https://www.whoscored.com/search/?t={query}"
        base = "https://www.whoscored.com"
    elif source == "flashscore":
        url = f"https://www.flashscore.com/search/?q={query}"
        base = "https://www.flashscore.com"
    else:
        raise ValueError(f"Unknown source {source!r}")
    html = (fetcher or _fetch_rendered)(url, wait)
    result = rank_candidates(
        parse_search_candidates(html, base, source=source),
        fixture,
    )
    result.update({"source": source, "search_url": url})
    return result


def scraper_argv(source: str, url: str, output_root: str | Path, wait: int = 15) -> list[str]:
    script = "scrape_match.py" if source == "whoscored" else "scrape_flashscore.py"
    return [
        sys.executable,
        str(REPO_ROOT / script),
        "--url", url,
        "--output-dir", str(Path(output_root)),
        "--wait", str(int(wait)),
        *(["--summarize"] if source == "whoscored" else []),
    ]


def visible_command(source: str, url: str, output_root: str | Path, wait: int = 15) -> list[str]:
    argv = scraper_argv(source, url, output_root, wait)
    if os.name == "nt":
        command = subprocess.list2cmdline(argv)
        return ["cmd", "/c", "start", "", "cmd", "/k", command]
    return argv


def spawn_scraper(
    source: str,
    url: str,
    output_root: str | Path,
    *,
    wait: int = 15,
    popen: Callable[..., Any] = subprocess.Popen,
) -> Any:
    command = visible_command(source, url, output_root, wait)
    kwargs: dict[str, Any] = {"cwd": str(REPO_ROOT)}
    if os.name != "nt":
        kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True})
    return popen(command, **kwargs)


def watch_export(
    output_root: str | Path,
    before: set[Path],
    *,
    fixture: LivescoreFixture,
    timeout: float = 300,
    interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Path | None:
    root = Path(output_root)
    started = clock()
    while clock() - started < timeout:
        new = [path for path in list_match_dirs(root) if path.resolve() not in before]
        if new:
            new.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            return new[0]
        matched = find_local_export(fixture, root)
        if matched is not None and matched.resolve() not in before:
            return matched
        sleeper(interval)
    return None


def resolve_chain(
    livescore_url: str,
    *,
    output_root: str | Path = "output",
    wait: int = 15,
    timeout: float = 300,
    allow_spawn: bool = True,
    on_log: Callable[[str], None] | None = None,
    searcher: Callable[..., dict[str, Any]] | None = None,
    spawner: Callable[..., Any] | None = None,
    watcher: Callable[..., Path | None] | None = None,
) -> dict[str, Any]:
    log = on_log or (lambda _line: None)
    fixture = parse_livescore_url(livescore_url)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = [{
        "name": "livescore_parse", "status": "ok",
        "detail": f"{fixture.home} vs {fixture.away}",
    }]
    local = find_local_export(fixture, root)
    best: Path | None = local
    if local is not None:
        health = assess_source(local)
        steps.append({
            "name": "whoscored_local", "status": "full" if health.healthy else "limited",
            "detail": "; ".join(health.notes) or "full event map",
            "health": health.as_dict(),
        })
        if health.healthy:
            return {
                "ok": True, "match_dir": str(local), "source": "whoscored",
                "full": True, "fixture": asdict(fixture), "health": health.as_dict(),
                "steps": steps,
            }
    search = searcher or search_source
    spawn = spawner or spawn_scraper
    watch = watcher or watch_export
    for source in ("whoscored", "flashscore"):
        log(f"Searching {source.title()} for {fixture.home} vs {fixture.away}…")
        try:
            found = search(fixture, source, wait=wait)
        except Exception as exc:  # browser/Cloudflare failure
            steps.append({
                "name": f"{source}_search", "status": "failed",
                "detail": f"{type(exc).__name__}: {exc}",
            })
            continue
        steps.append({
            "name": f"{source}_search", "status": found.get("status"),
            "detail": (found.get("candidate") or {}).get("url") or "No unambiguous match",
            "candidates": found.get("candidates") or [],
        })
        if found.get("status") != "found":
            continue
        candidate_url = found["candidate"]["url"]
        if not allow_spawn:
            steps.append({
                "name": f"{source}_scrape", "status": "ready",
                "detail": candidate_url, "command": visible_command(source, candidate_url, root, wait),
            })
            continue
        before = {path.resolve() for path in list_match_dirs(root)}
        log(f"Opening visible CMD scraper for {source.title()}…")
        spawn(source, candidate_url, root, wait=wait)
        path = watch(
            root, before, fixture=fixture, timeout=timeout,
        )
        if path is None:
            steps.append({
                "name": f"{source}_scrape", "status": "timeout",
                "detail": f"No export appeared within {int(timeout)} seconds.",
            })
            continue
        health = assess_source(path)
        best = path
        full = source == "whoscored" and health.healthy
        steps.append({
            "name": f"{source}_health", "status": "full" if full else "limited",
            "detail": "; ".join(health.notes) or "full event map",
            "health": health.as_dict(),
        })
        if full or source == "flashscore":
            return {
                "ok": True, "match_dir": str(path), "source": source,
                "full": full, "fixture": asdict(fixture), "health": health.as_dict(),
                "steps": steps,
            }
    if best is not None:
        health = assess_source(best)
        return {
            "ok": True, "match_dir": str(best),
            "source": health.source, "full": health.healthy,
            "fixture": asdict(fixture), "health": health.as_dict(), "steps": steps,
        }
    return {
        "ok": False, "match_dir": None, "source": None, "full": False,
        "fixture": asdict(fixture), "health": {}, "steps": steps,
        "message": (
            "No unambiguous source match was found. Paste the WhoScored or "
            "Flashscore match URL manually; the system will not guess the fixture."
        ),
    }

