"""Studio probe shim.

``recap.studio_api`` looks for ``recap.livescore.resolve_url``. Parsing,
WhoScored health, and fallback adapters live in ``recap.ingest`` /
``recap.resolve_match``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from recap.ingest import parse_livescore_url, resolve
from recap.resolve_match import resolve_from_livescore, resolve_url as resolve_any_url

__all__ = ["parse_livescore_url", "resolve_url", "resolve_from_livescore"]


def resolve_url(url: str, output_root: Path | str | None = None, **_: Any) -> dict[str, Any]:
    """Lookup-only: existing export for a Livescore or WhoScored URL.

    Does not scrape. Studio's Scrape button calls ``recap.scrape.run_scrape``.
    """
    raw = (url or "").strip()
    dest = Path(output_root) if output_root else Path("output")
    host = raw.lower()
    if "whoscored.com" in host or raw.isdigit():
        result = resolve_any_url(raw, output_root=dest)
        if result.get("match_dir"):
            result.setdefault("path", result["match_dir"])
        return result
    result = resolve(livescore_url=raw, output_root=dest)
    if result.get("match_dir"):
        result.setdefault("path", result["match_dir"])
    return result
