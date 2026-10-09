"""Locate the live WhoScored export selected for integration tests."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"


def sample_match_dir() -> Path | None:
    env = (os.getenv("RECAP_TEST_MATCH") or "").strip()
    if env:
        path = Path(env)
        if not path.is_absolute():
            path = OUTPUT / env
        if path.exists() and path.is_dir():
            return path

    pointer = OUTPUT / ".test_match"
    if pointer.exists():
        name = pointer.read_text(encoding="utf-8").strip()
        path = OUTPUT / name
        if path.exists() and path.is_dir():
            return path

    candidates: list[Path] = []
    if not OUTPUT.exists():
        return None
    for path in OUTPUT.iterdir():
        if not path.is_dir():
            continue
        if (path / "match_summary.json").exists() or (path / "all_events.csv").exists():
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)
