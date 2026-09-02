"""Viral-quality gate for recap scripts.

Scores a storyboard 0-100 and remembers punch lines so two similar upsets do
not open on the same slam. Failures are fed back into the next Gemini pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import hooks
from .data import MatchBundle, write_json
from .director import SHAPE_FAMILY, _SCORELINE, _is_polite_title

MEMORY_NAME = "_hook_memory.json"
MEMORY_KEEP = 40
_BUT = re.compile(r"\bbut\b", re.IGNORECASE)
_DIGIT = re.compile(r"\d")


def memory_path(output_root: Path) -> Path:
    return Path(output_root) / MEMORY_NAME


def load_memory(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def remember_punch(output_root: Path, punch: str, match_id: str, kind: str) -> None:
    if not punch:
        return
    path = memory_path(output_root)
    rows = load_memory(path)
    fingerprint = _fingerprint(punch)
    rows = [row for row in rows if _fingerprint(str(row.get("punch") or "")) != fingerprint]
    rows.append({"punch": punch, "match_id": match_id, "kind": kind})
    write_json(path, rows[-MEMORY_KEEP:])


def score_plan(
    scenes: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    output_root: Path | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    failures: list[str] = []
    score = 100

    def warn(message: str, *, fail: bool = False, penalty: int = 8) -> None:
        nonlocal score
        warnings.append(message)
        score -= penalty
        if fail:
            failures.append(message)

    punch = ""
    hook_kind = ""
    for scene in scenes:
        if scene.get("visualization") == "hook_punch":
            punch = str(scene.get("title") or "")
            hook_kind = str(scene.get("hook_kind") or "")
            break

    if output_root is not None and punch:
        for row in load_memory(memory_path(output_root)):
            if _fingerprint(str(row.get("punch") or "")) == _fingerprint(punch):
                warn(f"punch line reused from {row.get('match_id')}", fail=True, penalty=18)
                break

    families = []
    for item in selected:
        families.append(item.get("shape") or SHAPE_FAMILY.get(item.get("id", ""), "other"))
    unique = {family for family in families if family}
    from collections import Counter
    family_counts = Counter(family for family in families if family)
    dupes = [family for family, n in family_counts.items() if n > 1]
    if dupes:
        warn(f"two selected viz share shape family {dupes[0]}", fail=True, penalty=18)
    if len(unique) < 3:
        warn(f"pack geometry diversity is {len(unique)} families (need 3+)", fail=True, penalty=16)
    if unique == {"bars"} or (families and all(family == "bars" for family in families)):
        warn("all-bar pack", fail=True, penalty=20)

    buts = 0
    for scene in scenes:
        if scene.get("hook"):
            continue
        if _BUT.search(str(scene.get("narration") or "")):
            buts += 1
    if buts > 1:
        warn(f"narration uses 'but' on {buts} scenes", fail=True, penalty=12)

    for scene in scenes:
        if scene.get("hook"):
            for field in ("title", "subtitle", "insight", "narration"):
                text = str(scene.get(field) or "")
                if _SCORELINE.search(text):
                    warn(f"{scene.get('id')} spoils the score in the hook", fail=True, penalty=20)
        if scene.get("visualization") in {"close", "micro_hook", "live_clip"} or scene.get("hook"):
            continue
        title = str(scene.get("title") or "")
        pack = scene.get("fact_pack") or {}
        surnames = [str(name) for name in (pack.get("surnames") or []) if name]
        numbers = pack.get("numbers") or []
        if numbers and surnames and not _DIGIT.search(title) and not any(name.lower() in title.lower() for name in surnames):
            warn(f"{scene.get('id')} title has no digit and no surname", penalty=6)
        if _is_polite_title(title, bundle):
            warn(f"{scene.get('id')} uses a polite title: {title[:40]!r}", fail=True, penalty=10)
        if not str(scene.get("insight") or "").strip():
            warn(f"{scene.get('id')} insight is empty", penalty=5)

    qualified = []
    try:
        qualified = hooks.qualifying_kinds(bundle, audit)
    except Exception:
        qualified = []
    stronger = [kind for kind in qualified if kind not in {"one_moment", "level", "stalemate"}]
    if hook_kind == "one_moment" and stronger:
        warn(f"hook kind is one_moment but {stronger[0]} also qualified", fail=True, penalty=14)

    return {
        "score": max(0, min(100, score)),
        "warnings": warnings,
        "failures": failures,
        "families": sorted(unique),
        "hook_kind": hook_kind,
        "punch": punch,
    }


def redo_instruction(base: str, report: dict[str, Any]) -> str:
    notes = report.get("failures") or report.get("warnings") or []
    if not notes:
        return f"{base} Sharpen the hook and vary the sentence rhythm.".strip()
    joined = " ".join(f"- {note}" for note in notes[:8])
    return f"{base} Fix these viral-audit failures: {joined}".strip()


def _fingerprint(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())
