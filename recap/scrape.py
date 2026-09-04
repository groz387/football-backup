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
from urllib.parse import parse_qs, urlparse

from recap.data import list_match_dirs

REPO_ROOT = Path(__file__).resolve().parent.parent
_WHO_ID = re.compile(r"/matches?/(\d{5,10})", re.I)
_BARE_ID = re.compile(r"^\d{5,10}$")
_ANY_ID = re.compile(r"(\d{5,10})")
_FLASHSCORE_MID = re.compile(r"(?:[?&]mid=|/match/(?:[^/?#]+/)*)([A-Za-z0-9_-]{6,})")


def scrape_script_path() -> Path:
    return REPO_ROOT / "scrape_match.py"


def scrape_available() -> bool:
    return scrape_script_path().exists() or (REPO_ROOT / "scrape_flashscore.py").exists()


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


def extract_flashscore_id(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    query_mid = (parse_qs(urlparse(raw if "://" in raw else f"https://{raw}").query).get("mid") or [""])[0]
    if query_mid:
        return query_mid
    found = re.search(r"/match/(?:football/)?(?:[^/?#]+/)*([A-Za-z0-9_-]{6,})", raw)
    return found.group(1) if found else None


def _flashscore_host(url: str) -> bool:
    host = (urlparse((url or "").strip() if "://" in (url or "") else f"https://{url or ''}").hostname or "").lower()
    return "flashscore.com" in host


def _is_flashscore_html(path: Path) -> bool:
    try:
        snippet = path.read_text(encoding="utf-8", errors="ignore")[:12000].lower()
    except OSError:
        return False
    return any(
        token in snippet
        for token in ("flashscore", "duelparticipant", "wcl-statistics", "detailscore__wrapper")
    )


def classify_source(url: str = "", html_path: str = "") -> dict[str, Any]:
    """Decide how we can get a chalkboard. Never guesses x/y."""
    raw = (url or "").strip()
    html = Path(html_path).expanduser() if html_path else None
    if html and html.is_file():
        flash_html = _flashscore_host(raw) or _is_flashscore_html(html)
        return {
            "kind": "html",
            "match_id": extract_match_id(html.name) or extract_match_id(raw),
            "whoscored_url": "" if flash_html else _whoscored_url(raw),
            "flashscore_url": raw if _flashscore_host(raw) else "",
            "html_path": str(html.resolve()),
            "can_scrape": True,
            "hint": (
                f"Will import saved Flashscore page source: {html.name}"
                if flash_html else
                f"Will import saved WhoScored page source: {html.name}"
            ),
        }
    if not raw:
        return {
            "kind": "empty",
            "match_id": None,
            "whoscored_url": "",
            "flashscore_url": "",
            "html_path": "",
            "can_scrape": False,
            "hint": "Paste a Livescore, WhoScored, or Flashscore URL, a match id, or a saved HTML path.",
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
            "flashscore_url": "",
            "html_path": "",
            "can_scrape": bool(match_id),
            "hint": f"Will scrape WhoScored match {match_id}." if match_id else "WhoScored URL is missing a match id.",
        }
    if _BARE_ID.fullmatch(raw):
        return {
            "kind": "match_id",
            "match_id": raw,
            "whoscored_url": whoscored_live_url(raw),
            "flashscore_url": "",
            "html_path": "",
            "can_scrape": True,
            "hint": f"Will scrape https://www.whoscored.com/matches/{raw}/live",
        }
    if "livescore.com" in host:
        return {
            "kind": "livescore",
            "match_id": match_id,
            "whoscored_url": "",
            "flashscore_url": "",
            "html_path": "",
            "can_scrape": True,
            "hint": (
                "Livescore ids are not WhoScored ids. The source chain will search "
                "WhoScored by teams/date, verify a full chalkboard, then try "
                "Flashscore if WhoScored is missing or limited."
            ),
        }
    if "flashscore.com" in host:
        href = raw if raw.startswith("http") else f"https://{raw}"
        return {
            "kind": "flashscore",
            "match_id": extract_flashscore_id(href),
            "whoscored_url": "",
            "flashscore_url": href,
            "html_path": "",
            "can_scrape": True,
            "hint": (
                "Will scrape Flashscore as an honest fallback "
                "(score/incidents/stats only; coordinates are never invented)."
            ),
        }
    if match_id:
        return {
            "kind": "match_id",
            "match_id": match_id,
            "whoscored_url": whoscored_live_url(match_id),
            "flashscore_url": "",
            "html_path": "",
            "can_scrape": True,
            "hint": f"Will scrape {whoscored_live_url(match_id)}",
        }
    return {
        "kind": "unknown",
        "match_id": None,
        "whoscored_url": "",
        "flashscore_url": "",
        "html_path": "",
        "can_scrape": False,
        "hint": "Need a Livescore, WhoScored, or Flashscore URL, a 5–10 digit match id, or saved HTML.",
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


def _load_flashscore_scrape() -> Any:
    path = REPO_ROOT / "scrape_flashscore.py"
    if not path.exists():
        raise FileNotFoundError(f"scrape_flashscore.py is missing at {path}")
    if "scrape_flashscore" in sys.modules:
        return sys.modules["scrape_flashscore"]
    spec = importlib.util.spec_from_file_location("scrape_flashscore", path)
    if spec is None or spec.loader is None:
        raise ImportError("Could not load scrape_flashscore.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scrape_flashscore"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_flashscore_export(
    *,
    url: str,
    html_path: str,
    output_root: Path,
    wait: int,
    log: Callable[[str], None],
) -> None:
    mod = _load_flashscore_scrape()
    if html_path:
        log(f"Importing Flashscore page source {Path(html_path).name} …")
        getattr(mod, "_file")(html_path, str(output_root), url)
        return
    log(f"Scraping Flashscore {url} (wait={wait}s, nodriver) …")
    result = getattr(mod, "_url")(url, str(output_root), int(wait))
    if asyncio.iscoroutine(result):
        asyncio.run(result)


def run_scrape(
    *,
    url: str = "",
    html_path: str = "",
    output_root: Path | str | None = None,
    wait: int = 15,
    log: Callable[[str], None] | None = None,
    scrape_url_fn: Callable | None = None,
    process_file_fn: Callable | None = None,
    flashscore_fn: Callable | None = None,
) -> dict[str, Any]:
    """Run WhoScored / Flashscore scrape or HTML import. Returns match_dir on success."""
    say = log or (lambda _line: None)
    dest = Path(output_root) if output_root else REPO_ROOT / "output"
    dest.mkdir(parents=True, exist_ok=True)
    classified = classify_source(url, html_path)
    say(classified["hint"])
    if not classified["can_scrape"] and classified["kind"] != "html":
        raise ValueError(classified["hint"])

    before = {p.resolve() for p in list_match_dirs(dest)}
    html = classified.get("html_path") or (html_path or "").strip()
    html_path_obj = Path(html).expanduser() if html else None
    use_flashscore = classified["kind"] == "flashscore" or (
        bool(html_path_obj and html_path_obj.is_file())
        and (_flashscore_host(url) or _is_flashscore_html(html_path_obj))
    )
    source = "whoscored"
    if use_flashscore:
        source = "flashscore"
        fn = flashscore_fn or _run_flashscore_export
        fn(
            url=str(classified.get("flashscore_url") or url),
            html_path=str(html_path_obj) if html_path_obj else "",
            output_root=dest,
            wait=int(wait),
            log=say,
        )
    elif html:
        path = Path(html).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"HTML file not found: {path}")
        say(f"Importing page source {path.name} …")
        fn = process_file_fn
        if fn is None:
            fn = getattr(_load_scrape_match(), "_process_file")
        fn(str(path), str(dest), False, False, None)
        source = "html"
    else:
        ws = classified.get("whoscored_url") or ""
        if not ws:
            raise ValueError(classified["hint"])
        say(f"Scraping {ws} (wait={wait}s, nodriver) …")
        fn = scrape_url_fn
        if fn is None:
            fn = getattr(_load_scrape_match(), "_scrape_url")
        try:
            result = fn(ws, str(dest), False, int(wait), False, None)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except Exception as exc:
            text = str(exc)
            blocked = any(
                needle in text.lower()
                for needle in ("cloudflare", "attention required", "expecting value", "just a moment")
            )
            if blocked:
                raise RuntimeError(
                    "WhoScored blocked the browser (Cloudflare) or returned no match JSON. "
                    "On your own PC this usually works. If it fails: open the live page, "
                    "Ctrl+U, save the HTML, then paste/upload it in the scrape panel."
                ) from exc
            raise

    match_dir = _newest_export(dest, before, classified.get("match_id"))
    if match_dir is None:
        raise FileNotFoundError(
            "Scrape finished but no output/<id>_Home_vs_Away/ export appeared. "
            "Cloudflare may have blocked the page, or the HTML is not a match centre."
        )
    say(f"Export ready: {match_dir.name}")
    return {
        "ok": True,
        "match_dir": str(match_dir),
        "match_id": classified.get("match_id"),
        "whoscored_url": classified.get("whoscored_url") or "",
        "flashscore_url": classified.get("flashscore_url") or "",
        "kind": classified["kind"],
        "source": source,
    }
