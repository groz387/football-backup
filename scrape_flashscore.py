#!/usr/bin/env python
"""Scrape or import a Flashscore match as an honest fallback export."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from fetch_page import fetch_from_file, fetch_with_nodriver
from recap.flashscore import export_flashscore, parse_flashscore_html


async def _url(url: str, output_dir: str, wait: int) -> Path:
    print(f"[*] Loading Flashscore: {url}")
    html = await fetch_with_nodriver(url, wait_seconds=wait)
    dest = export_flashscore(parse_flashscore_html(html, url=url), output_dir)
    print(f"[*] Export ready: {dest}")
    return dest


def _file(path: str, output_dir: str, url: str = "") -> Path:
    print(f"[*] Importing Flashscore HTML: {path}")
    html = fetch_from_file(path)
    dest = export_flashscore(parse_flashscore_html(html, url=url), output_dir)
    print(f"[*] Export ready: {dest}")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Flashscore fallback → recap export")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Flashscore match URL")
    source.add_argument("--file", help="Saved rendered Flashscore HTML")
    parser.add_argument("--source-url", default="", help="Original URL when using --file")
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--wait", type=int, default=15)
    args = parser.parse_args()
    if args.file:
        _file(args.file, args.output_dir, args.source_url)
    else:
        asyncio.run(_url(args.url, args.output_dir, args.wait))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
