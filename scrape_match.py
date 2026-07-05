#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
"""
scrape_match.py — Complete WhoScored match‑data scraper & exporter.

USAGE
─────
  # Strategy A  ── automated via nodriver (bypasses Cloudflare)
  python scrape_match.py --url "https://www.whoscored.com/matches/1953854/live/..."

  # Strategy B  ── from a saved "View Page Source" HTML file
  python scrape_match.py --file saved_page.html

  # Batch mode  ── one URL per line in a text file
  python scrape_match.py --urls-file match_urls.txt

  # With EPV calculation
  python scrape_match.py --file saved_page.html --epv

  # Custom output directory
  python scrape_match.py --url "..." --output-dir ./my_data
"""

import argparse
import asyncio
import os
import re
import sys
import time

from fetch_page import (
    extract_match_data_from_html,
    extract_breadcrumb_from_html,
    fetch_from_file,
    fetch_with_nodriver,
)
from parse_export import export_all
from json_summarizer import summarize_match
from verify_stats import verify_match


# -------------------------------------------------------------------
#  Helpers
# -------------------------------------------------------------------

def _match_id_from_url(url: str) -> str:
    m = re.search(r"/matches/(\d+)/", url, re.IGNORECASE)
    return m.group(1) if m else "unknown"


def _safe_filename(name: str) -> str:
    return re.sub(r'[^\w\-]', '_', name)


def _process_html(html: str, output_dir: str, match_id: str | None = None,
                  add_epv: bool = False) -> dict:
    """Shared pipeline: HTML → match_data dict → export files."""
    # 1. extract match data from page source
    match_data = extract_match_data_from_html(html)

    # 2. extract breadcrumb metadata (region / league / season)
    bc = extract_breadcrumb_from_html(html)
    for k, v in bc.items():
        if v and (k not in match_data or not match_data.get(k)):
            match_data[k] = v

    # 3. determine output folder name
    if not match_id:
        match_id = str(match_data.get("matchId", "unknown"))
    home = _safe_filename(match_data.get("home", {}).get("name", "Unknown"))
    away = _safe_filename(match_data.get("away", {}).get("name", "Unknown"))
    folder = f"{match_id}_{home}_vs_{away}"
    match_dir = os.path.join(output_dir, folder)

    # 4. export
    epv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EPV_grid.csv")
    result = export_all(
        match_data,
        match_dir,
        add_epv=add_epv,
        epv_grid_path=epv_path if os.path.exists(epv_path) else None,
    )
    
    return result, match_dir


# -------------------------------------------------------------------
#  Strategy A — nodriver
# -------------------------------------------------------------------

async def _scrape_url(url: str, output_dir: str, add_epv: bool, wait: int, summarize: bool = False, verify_url: str = None):
    mid = _match_id_from_url(url)
    print(f"\n[*] Scraping match {mid}: {url}")
    html = await fetch_with_nodriver(url, wait_seconds=wait)
    res, m_dir = _process_html(html, output_dir, mid, add_epv)
    if summarize:
        summarize_match(m_dir)
    if verify_url:
        await verify_match(m_dir, verify_url)
    return res


# -------------------------------------------------------------------
#  Strategy B — saved file
# -------------------------------------------------------------------

def _process_file(filepath: str, output_dir: str, add_epv: bool, summarize: bool = False, verify_url: str = None):
    print(f"\n[*] Processing file: {filepath}")
    html = fetch_from_file(filepath)
    mid = re.search(r"(\d{5,})", os.path.basename(filepath))
    res, m_dir = _process_html(html, output_dir, mid.group(1) if mid else None, add_epv)
    if summarize:
        summarize_match(m_dir)
    if verify_url:
        asyncio.run(verify_match(m_dir, verify_url))
    return res


# -------------------------------------------------------------------
#  CLI
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape WhoScored match data → JSON + CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url",       type=str, help="Single WhoScored match URL")
    src.add_argument("--file",      type=str, help="Saved HTML page‑source file")
    src.add_argument("--urls-file", type=str, help="Text file with one URL per line")

    parser.add_argument("--output-dir", type=str, default="./output",
                        help="Root output directory  (default: ./output)")
    parser.add_argument("--epv", action="store_true",
                        help="Calculate Expected Possession Value for passes")
    parser.add_argument("--summarize", action="store_true",
                        help="Generate tactical JSON summary and play-by-play for LLMs")
    parser.add_argument("--verify-url", type=str,
                        help="FotMob URL to cross-reference and verify scraped stats")
    parser.add_argument("--wait", type=int, default=12,
                        help="Page‑load wait in seconds for nodriver  (default: 12)")

    args = parser.parse_args()
    out = os.path.abspath(args.output_dir)

    # ---- single file ----
    if args.file:
        _process_file(args.file, out, args.epv, args.summarize, args.verify_url)

    # ---- single URL ----
    elif args.url:
        asyncio.run(_scrape_url(args.url, out, args.epv, args.wait, args.summarize, args.verify_url))

    # ---- batch ----
    elif args.urls_file:
        with open(args.urls_file) as fh:
            urls = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
        print(f"[*] Batch mode: {len(urls)} match(es)")

        async def _batch():
            for i, url in enumerate(urls, 1):
                print(f"\n{'═' * 60}")
                print(f"  Match {i} / {len(urls)}")
                print(f"{'═' * 60}")
                try:
                    await _scrape_url(url, out, args.epv, args.wait, args.summarize, args.verify_url)
                except Exception as exc:
                    print(f"  [!] Failed: {exc}")
                if i < len(urls):
                    print("  ... Cooling down 7 s ...")
                    time.sleep(7)

        asyncio.run(_batch())


if __name__ == "__main__":
    main()
