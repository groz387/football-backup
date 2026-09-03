"""Studio probe shim.

``recap.studio_api`` looks for ``recap.livescore.resolve_url``. Parsing,
WhoScored health, and fallback adapters live in ``recap.ingest`` /
``recap.resolve_match``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from recap.ingest import parse_livescore_url, resolve
from recap.resolve_match import resolve_from_livescore

__all__ = ["parse_livescore_url", "resolve_url", "resolve_from_livescore"]


def resolve_url(url: str, output_root: Path | str | None = None, **_: Any) -> dict[str, Any]:
    """Return the ingest dict (``match_dir`` / ``path``) studio already accepts."""
    result = resolve(livescore_url=url, output_root=output_root or "output")
    if result.get("match_dir"):
        result.setdefault("path", result["match_dir"])
    return result
