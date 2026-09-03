"""WhoScored scrape runner used by the studio console and CLI.

Lookup (``resolve_source``) never hits the network. This module is the
explicit scrape path:

  * WhoScored live URL
  * bare WhoScored match id (``1821295`` → ``/matches/1821295/live``)
  * saved "View Page Source" HTML (Cloudflare-safe)
  * Livescore URL only as a pointer — it has no chalkboard; we still need
    a WhoScored URL or HTML unless the path already contains a 5–10 digit id
    that you confirm is a WhoScored id.

Never invents events or coordinates.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from recap.data import list_match_dirs

REPO_ROOT = Path(__file__).resolve().parent.parent
_WHO_ID = re.compile(r"/matches?/(\d{5,10})", re.I)
_BARE_ID = re.compile(r"^\d{5,10}$")
_ANY_ID = re.compile(r"(\d{5,10})")


def scrape_script_path() -> Path:
    return REPO_ROOT / "scrape_match.py"


def scrape_available() -> bool:
    return scrape_script_path().exists()


def _load_scrape_match() -> Any:
    path = scrape_script_path()
    if not path.exists():
        raise FileNotFoundError(f"scrape_match.py is missing at {path}")
    if "scrape_match" in sys.modules:
        return sys.modules["scrape_match"]
    spec = importlib.util.spec_from_file_location("scrape_match", path)
    if spec is None or spec.loader is None:
        raise ImportError("Could not load scrape_match.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scrape_match"] = mod
    spec.loader.exec_module(mod)
    return mod


def extract_match_id(url_or_id: str) -> str | None:
    raw = (url_or_id or "").strip()
    if not raw:
        return None
    if _BARE_ID.fullmatch(raw):
        return raw
    found = _WHO_ID.search(raw)
    if found:
        return found.group(1)
    digits = _ANY_ID.search(raw)
    return digits.group(1) if digits else None


def whoscored_live_url(match_id: str) -> str:
    mid = str(match_id or "").strip()
    if not _BARE_ID.fullmatch(mid):
        raise ValueError(f"Not a WhoScored match id: {match_id!r}")
    return f"https://www.whoscored.com/matches/{mid}/live"


def classify_source(url: str = "", html_path: str = "") -> dict[str, Any]:
    """Decide how we can get a chalkboard. Never guesses x/y."""
    raw = (url or "").strip()
    html = Path(html_path).expanduser() if html_path else None
    if html and html.is_file():
        return {
            "kind": "html",
            "match_id": extract_match_id(html.name) or extract_match_id(raw),
            "whoscored_url": _whoscored_url(raw),
            "html_path": str(html.resolve()),
            "can_scrape": True,
            "hint": f"Will import saved WhoScored page source: {html.name}",
        }
    if not raw:
        return {
            "kind": "empty",
            "match_id": None,
            "whoscored_url": "",
            "html_path": "",
            "can_scrape": False,
            "hint": "Paste a WhoScored live URL, a match id, or a saved HTML path.",
        }
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    match_id = extract_match_id(raw)
    if "whoscored.com" in host:
        ws = raw if raw.startswith("http") else f"https://{raw}"
        if "/live" not in ws and match_id:
            ws = whoscored_live_url(match_id)
        return {
            "kind": "whoscored",
            "match_id": match_id,
            "whoscored_url": ws,
            "html_path": "",
            "can_scrape": bool(match_id),
            "hint": f"Will scrape WhoScored match {match_id}." if match_id else "WhoScored URL is missing a match id.",
        }
    if _BARE_ID.fullmatch(raw):
        return {
            "kind": "match_id",
            "match_id": raw,
            "whoscored_url": whoscored_live_url(raw),
            "html_path": "",
            "can_scrape": True,
            "hint": f"Will scrape https://www.whoscored.com/matches/{raw}/live",
        }
    if "livescore.com" in host:
        ws = whoscored_live_url(match_id) if match_id else ""
        return {
            "kind": "livescore",
            "match_id": match_id,
            "whoscored_url": ws,
            "html_path": "",
            "can_scrape": bool(match_id),
            "hint": (
                f"Livescore has no chalkboard. If {match_id} is the WhoScored id, "
                f"scrape {ws}. Otherwise paste the WhoScored /matches/<id>/live URL "
                "or a saved page-source HTML."
                if match_id
                else "Livescore has no chalkboard. Paste the WhoScored live URL or a saved HTML file."
            ),
        }
    if match_id:
        return {
            "kind": "match_id",
            "match_id": match_id,
            "whoscored_url": whoscored_live_url(match_id),
            "html_path": "",
            "can_scrape": True,
            "hint": f"Will scrape {whoscored_live_url(match_id)}",
        }
    return {
        "kind": "unknown",
        "match_id": None,
        "whoscored_url": "",
        "html_path": "",
        "can_scrape": False,
        "hint": "Need a WhoScored live URL, a 5–10 digit match id, or saved HTML.",
    }


def _whoscored_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    host = (urlparse(raw if "://" in raw else f"https://{raw}").hostname or "").lower()
    if "whoscored.com" in host:
        return raw if raw.startswith("http") else f"https://{raw}"
    mid = extract_match_id(raw)
    return whoscored_live_url(mid) if mid else ""


def _newest_export(output_root: Path, before: set[Path], match_id: str | None) -> Path | None:
    after = [p for p in list_match_dirs(output_root) if p.resolve() not in before]
    if after:
        after.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return after[0]
    if match_id:
        for path in list_match_dirs(output_root):
            if path.name == match_id or path.name.startswith(f"{match_id}_"):
                return path
    return None


def run_scrape(
    *,
    url: str = "",
    html_path: str = "",
    output_root: Path | str | None = None,
    wait: int = 15,
    log: Callable[[str], None] | None = None,
    scrape_url_fn: Callable | None = None,
    process_file_fn: Callable | None = None,
) -> dict[str, Any]:
    """Run WhoScored scrape or HTML import. Returns match_dir on success."""
    say = log or (lambda _line: None)
    dest = Path(output_root) if output_root else REPO_ROOT / "output"
    dest.mkdir(parents=True, exist_ok=True)
    classified = classify_source(url, html_path)
    say(classified["hint"])
    if not classified["can_scrape"] and classified["kind"] != "html":
        raise ValueError(classified["hint"])

    before = {p.resolve() for p in list_match_dirs(dest)}
    html = classified.get("html_path") or (html_path or "").strip()
    if html:
        path = Path(html).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"HTML file not found: {path}")
        say(f"Importing page source {path.name} …")
        fn = process_file_fn
        if fn is None:
            fn = getattr(_load_scrape_match(), "_process_file")
        fn(str(path), str(dest), False, False, None)
    else:
        ws = classified.get("whoscored_url") or ""
        if not ws:
            raise ValueError(classified["hint"])
        say(f"Scraping {ws} (wait={wait}s, nodriver) …")
        fn = scrape_url_fn
        if fn is None:
            fn = getattr(_load_scrape_match(), "_scrape_url")
        result = fn(ws, str(dest), False, int(wait), False, None)
        if asyncio.iscoroutine(result):
            asyncio.run(result)

    match_dir = _newest_export(dest, before, classified.get("match_id"))
    if match_dir is None:
        raise FileNotFoundError(
            "Scrape finished but no output/<id>_Home_vs_Away/ export appeared. "
            "Cloudflare may have blocked the page, or the HTML is not a WhoScored match centre."
        )
    say(f"Export ready: {match_dir.name}")
    return {
        "ok": True,
        "match_dir": str(match_dir),
        "match_id": classified.get("match_id"),
        "whoscored_url": classified.get("whoscored_url") or "",
        "kind": classified["kind"],
        "source": "html" if html else "whoscored",
    }
