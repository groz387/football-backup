"""A/B picker for recap hooks.

Three variants: the deterministic hash open plus two pool alternates.
Each is applied to the storyboard, scored by ``viral_audit``, and the winner
ships. Losers go into ``_hook_memory.json`` so the next match in a team series
does not repeat the same phrase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import hooks, viral_audit
from .data import MatchBundle
from .director import lock_hook_cards

DEFAULT_VARIANTS = 3


def generate_hooks(
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    count: int = DEFAULT_VARIANTS,
    storyboard_hook: dict[str, Any] | None = None,
    language: str | None = None,
    spoiler: str | None = None,
) -> list[dict[str, Any]]:
    """Deterministic hash (variant 0) plus ``count-1`` alternate pool picks."""
    want = max(1, int(count or DEFAULT_VARIANTS))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(hook: dict[str, Any], source: str, variant: int) -> None:
        row = dict(hook)
        row["variant"] = variant
        row["source"] = source
        fp = viral_audit.hook_fingerprint(str(row.get("punch") or ""), _claim_line(row))
        row["fingerprint"] = fp
        if fp and fp in seen:
            return
        if fp:
            seen.add(fp)
        out.append(row)

    if storyboard_hook:
        take(storyboard_hook, "storyboard", 0)
    salt = 0
    while len(out) < want and salt < want + 16:
        hook = hooks.build_hook(
            bundle, audit, language=language, spoiler=spoiler, variant=salt,
        )
        source = "hash" if salt == 0 else "alternate"
        # If the storyboard already filled slot 0, skip the raw hash duplicate.
        if salt == 0 and storyboard_hook:
            salt += 1
            continue
        take(hook, source, salt)
        salt += 1
    if not out:
        take(
            hooks.build_hook(bundle, audit, language=language, spoiler=spoiler, variant=0),
            "hash", 0,
        )
    return out[:want]


def _claim_line(hook: dict[str, Any]) -> str:
    lines = hook.get("lines") or []
    if lines:
        return str(lines[0] or "")
    return str(hook.get("narration_claim") or "")


def hook_from_scenes(
    scenes: list[dict[str, Any]],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild a hook dict from the current storyboard (post-Gemini wording)."""
    base = dict(fallback or {})
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "hook_claim":
            lines = list(scene.get("lines") or [])
            title = str(scene.get("title") or "")
            if title and (not lines or str(lines[0]) != title):
                lines = [title] + [str(item) for item in lines[1:]]
            if lines:
                base["lines"] = lines
                base["narration_claim"] = str(scene.get("narration") or " ".join(lines))
            if scene.get("hero_number") is not None:
                base["hero_number"] = scene.get("hero_number")
            if scene.get("hero_label"):
                base["hero_label"] = scene.get("hero_label")
            if scene.get("visual_language"):
                base["visual_language"] = scene.get("visual_language")
            if scene.get("hook_kind"):
                base["kind"] = scene.get("hook_kind")
            pack = scene.get("fact_pack") or {}
            if pack.get("numbers"):
                base["numbers"] = pack.get("numbers")
            if pack.get("never_say"):
                base["never_say"] = pack.get("never_say")
        elif viz == "hook_punch":
            punch = str(scene.get("title") or "")
            if punch:
                base["punch"] = punch
                base["narration_punch"] = str(scene.get("narration") or punch.rstrip("."))
            if scene.get("hook_kind"):
                base["kind"] = scene.get("hook_kind")
    base.setdefault("variant", 0)
    base.setdefault("source", "storyboard")
    base["fingerprint"] = viral_audit.hook_fingerprint(
        str(base.get("punch") or ""), _claim_line(base),
    )
    return base


def apply_hook(scenes: list[dict[str, Any]], hook: dict[str, Any]) -> list[dict[str, Any]]:
    """Overwrite claim / punch cards with one hook variant. Other beats stay."""
    lines = [str(item) for item in (hook.get("lines") or []) if str(item).strip()]
    punch = str(hook.get("punch") or "")
    out: list[dict[str, Any]] = []
    for scene in scenes:
        row = dict(scene)
        viz = str(row.get("visualization") or "")
        if viz == "hook_claim" and lines:
            row["title"] = lines[0]
            row["subtitle"] = lines[1] if len(lines) > 1 else ""
            row["insight"] = lines[2] if len(lines) > 2 else ""
            row["lines"] = lines
            row["narration"] = str(hook.get("narration_claim") or " ".join(lines))
            _stamp_hook_fields(row, hook)
        elif viz == "hook_punch" and punch:
            row["title"] = punch
            row["subtitle"] = ""
            row["insight"] = ""
            row["lines"] = [punch]
            row["narration"] = str(hook.get("narration_punch") or punch.rstrip("."))
            _stamp_hook_fields(row, hook)
        out.append(row)
    return out


def _stamp_hook_fields(row: dict[str, Any], hook: dict[str, Any]) -> None:
    row["hook_kind"] = hook.get("kind") or row.get("hook_kind")
    if hook.get("visual_language"):
        row["visual_language"] = hook.get("visual_language")
    if hook.get("hero_number") is not None:
        row["hero_number"] = hook.get("hero_number")
    if hook.get("hero_label"):
        row["hero_label"] = hook.get("hero_label")
    if hook.get("team"):
        row["hero_team"] = hook.get("team")
    if hook.get("split"):
        row["split"] = hook.get("split")
    pack = dict(row.get("fact_pack") or {})
    pack["kind"] = hook.get("kind") or pack.get("kind")
    pack["numbers"] = hook.get("numbers") or pack.get("numbers") or []
    pack["never_say"] = hook.get("never_say") or pack.get("never_say") or []
    pack["qualified"] = hook.get("qualified") or pack.get("qualified") or []
    row["fact_pack"] = pack
    row["allowed_numbers"] = pack.get("numbers") or []


def _payload(hook: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "punch": str(hook.get("punch") or report.get("punch") or ""),
        "claim": _claim_line(hook) or str(report.get("claim") or ""),
        "kind": str(hook.get("kind") or report.get("hook_kind") or ""),
        "score": report.get("score"),
        "variant": hook.get("variant"),
        "fingerprint": hook.get("fingerprint") or viral_audit.hook_fingerprint(
            str(hook.get("punch") or ""), _claim_line(hook),
        ),
        "source": hook.get("source"),
        "tiktok_score": report.get("tiktok_score"),
        "shorts_score": report.get("shorts_score"),
        "youtube_score": report.get("youtube_score"),
    }


def pick_winner(
    scenes: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    count: int = DEFAULT_VARIANTS,
    output_root: Path | None = None,
    language: str | None = None,
    spoiler: str | None = None,
    clip_report: dict[str, Any] | None = None,
    series_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Score ``count`` hook variants and return (winning scenes, A/B report)."""
    fallback = hooks.build_hook(bundle, audit, language=language, spoiler=spoiler, variant=0)
    current = hook_from_scenes(scenes, fallback)
    variants = generate_hooks(
        bundle, audit, count=count, storyboard_hook=current,
        language=language, spoiler=spoiler,
    )
    memory_rows = viral_audit.load_memory(viral_audit.memory_path(output_root)) if output_root else []
    used = viral_audit.series_used_fingerprints(
        memory_rows,
        teams=[bundle.home, bundle.away],
        series_id=series_id,
    )

    scored: list[dict[str, Any]] = []
    for hook in variants:
        applied = apply_hook(scenes, hook)
        try:
            applied = lock_hook_cards(
                applied, bundle, audit, hook=hook, language=language, spoiler=spoiler,
            )
        except TypeError:
            applied = lock_hook_cards(applied, bundle, audit)
        report = viral_audit.score_plan(
            applied, selected, bundle, audit,
            output_root=output_root,
            language=language,
            spoiler=spoiler,
            clip_report=clip_report,
            series_id=series_id,
        )
        fp = str(hook.get("fingerprint") or "")
        repeat = bool(fp and fp in used)
        scored.append({
            "hook": hook,
            "scenes": applied,
            "report": report,
            "repeat": repeat,
            "payload": _payload(hook, report),
        })

    fresh = [row for row in scored if not row["repeat"]]
    pool = fresh or scored
    winner = max(
        pool,
        key=lambda row: (
            int((row["report"] or {}).get("score") or 0),
            int((row["report"] or {}).get("tiktok_score") or 0),
            -int(row["hook"].get("variant") or 0),
        ),
    )
    losers = [row for row in scored if row is not winner]
    ab = {
        "enabled": True,
        "picked_variant": winner["hook"].get("variant"),
        "picked_source": winner["hook"].get("source"),
        "winner": winner["payload"],
        "winner_hook": {
            key: winner["hook"].get(key)
            for key in (
                "kind", "lines", "punch", "narration_claim", "narration_punch",
                "visual_language", "hero_number", "hero_label", "split", "team",
                "numbers", "never_say", "qualified", "matchup", "variant",
                "fingerprint", "source", "seconds_claim", "seconds_punch",
            )
            if key in winner["hook"]
        },
        "losers": [row["payload"] for row in losers],
        "candidates": [
            {
                **row["payload"],
                "repeat": row["repeat"],
                "score": (row["report"] or {}).get("score"),
            }
            for row in scored
        ],
        "series_id": series_id or None,
        "report": winner["report"],
    }
    return winner["scenes"], ab
