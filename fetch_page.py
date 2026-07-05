# -*- coding: utf-8 -*-
"""
fetch_page.py — Fetch WhoScored match page source and extract raw match data.

Two strategies:
  1. nodriver  — stealth browser (bypasses Cloudflare)
  2. file      — read a saved "View Page Source" HTML file

Both produce the same output: a Python dict with ALL embedded match data.
"""

import re
import json
import asyncio
from pathlib import Path
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
#  HTML → match‑data extraction
# ---------------------------------------------------------------------------

def extract_match_data_from_html(html_source: str) -> dict:
    """
    Extract the match data dictionary from raw WhoScored HTML.

    WhoScored embeds all event data inside a <script> tag within
    #layout-wrapper.  This function finds that script, parses the JS
    object literal, and returns it as a Python dict.
    """
    script_text = _find_match_script(html_source)
    if script_text is None:
        raise ValueError(
            "Could not find match data script in the page source.\n"
            "Make sure the page has fully loaded and contains match centre data.\n"
            "Tip: the page title should show team names, NOT 'Attention Required'."
        )
    return _parse_script_content(script_text)


def extract_breadcrumb_from_html(html_source: str) -> dict:
    """Extract region / league / season from the breadcrumb bar."""
    soup = BeautifulSoup(html_source, "html.parser")
    breadcrumb = soup.find(id="breadcrumb-nav")

    info = {
        "region": "",
        "league": "",
        "season": "",
        "competitionType": "League",
        "competitionStage": "",
    }
    if not breadcrumb:
        return info

    span = breadcrumb.find("span")
    if span:
        info["region"] = span.get_text(strip=True)

    link = breadcrumb.find("a")
    if link:
        parts = link.get_text(strip=True).split(" - ")
        if len(parts) >= 1:
            info["league"] = parts[0]
        if len(parts) >= 2:
            info["season"] = parts[1]
        if len(parts) >= 3:
            info["competitionType"] = "Knock Out"
            info["competitionStage"] = parts[2]

    return info


# ---------------------------------------------------------------------------
#  Strategy A — nodriver (stealth browser, async)
# ---------------------------------------------------------------------------

async def fetch_with_nodriver(url: str, wait_seconds: int = 12) -> str:
    """
    Launch a real Chrome window via *nodriver*, navigate to *url*,
    wait for the JS data to load, and return the full page source.
    """
    try:
        import nodriver as uc
    except ImportError:
        raise ImportError(
            "nodriver is not installed.  Run:\n"
            "    pip install nodriver\n"
            "Or use --file mode with a saved HTML page source instead."
        )

    print("[nodriver] Launching Chrome …")
    browser = await uc.start(headless=False)

    print(f"[nodriver] Navigating to {url}")
    tab = await browser.get(url)

    print(f"[nodriver] Waiting {wait_seconds}s for page to fully render …")
    await asyncio.sleep(wait_seconds)

    # Grab full page HTML
    source = await tab.get_content()
    print(f"[nodriver] Got page source ({len(source):,} chars)")

    browser.stop()
    return source


# ---------------------------------------------------------------------------
#  Strategy B — read from a saved file
# ---------------------------------------------------------------------------

def fetch_from_file(filepath: str) -> str:
    """Read page source from a saved HTML file (View Page Source → Save As)."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text(encoding="utf-8", errors="ignore")
    print(f"[file] Read {len(content):,} chars from {filepath}")
    return content


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _find_match_script(html: str) -> str | None:
    """Locate the <script> tag containing 'matchId' inside #layout-wrapper."""
    soup = BeautifulSoup(html, "html.parser")

    # Try #layout-wrapper first (the expected location)
    layout = soup.find(id="layout-wrapper")
    if layout:
        for script in layout.find_all("script"):
            text = script.string or ""
            if "matchId" in text and "matchCentre" in text:
                return text

    # Fallback: search every <script> on the page
    for script in soup.find_all("script"):
        text = script.string or ""
        if "matchId" in text and "matchCentre" in text:
            return text

    # Second fallback: regex search in raw HTML (handles minified pages)
    match = re.search(
        r"matchId\s*[=:]\s*\d+.*?matchCentre", html, re.DOTALL
    )
    if match:
        # Find the enclosing script boundaries
        start = html.rfind("<script", 0, match.start())
        end = html.find("</script>", match.end())
        if start != -1 and end != -1:
            tag_content = html[start:end]
            inner_start = tag_content.find(">") + 1
            return tag_content[inner_start:]

    return None


def _parse_script_content(script_content: str) -> dict:
    """
    Parse WhoScored's embedded script block into a match‑data dict.

    The script contains something like:
        matchId = 123456,            require.config.params["args"] = { ...huge JSON... },            field = value, ...
    We split on the unique 12‑space‑after‑comma delimiter, extract the
    main JSON blob, and parse all remaining key:value pairs.
    """
    # Strip tabs / newlines
    cleaned = re.sub(r"[\n\t]+", "", script_content)

    # Narrow to the data region
    try:
        start = cleaned.index("matchId")
    except ValueError:
        raise ValueError("'matchId' not found in script content")

    end = cleaned.rindex("}")
    cleaned = cleaned[start : end + 1]

    # ---- Primary strategy: split on ,<12 spaces> ----
    delimiter = ",            "
    parts = list(filter(None, cleaned.strip().split(delimiter)))

    if len(parts) < 2:
        # Fallback: try a regex split for varied whitespace
        parts = re.split(r",\s{4,}", cleaned.strip())

    if len(parts) < 2:
        raise ValueError(
            "Could not split match script into key:value pairs. "
            "WhoScored may have changed their page structure."
        )

    # The second part typically contains the main JSON blob
    metadata_part = parts.pop(1)
    json_start = metadata_part.index("{")
    match_data = json.loads(metadata_part[json_start:])

    # Parse remaining simple key : value pairs
    for part in parts:
        colon = part.find(":")
        if colon == -1:
            continue
        key = part[:colon].strip()
        val_str = part[colon + 1 :].strip()
        try:
            match_data[key] = json.loads(val_str)
        except (json.JSONDecodeError, ValueError):
            match_data[key] = val_str

    return match_data
