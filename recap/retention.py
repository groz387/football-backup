"""Runtime packs that keep a recap inside a swipe.

Shorts die when the first graph overstays or a two-goal timeline eats the
middle. Packs target 21 / 35 / 45 seconds. Micro-hooks are 0.45s flashes
that never appear after the second analysis scene.
"""

from __future__ import annotations

from typing import Any

from .data import MatchBundle

PACKS: tuple[dict[str, Any], ...] = (
    {"id": "21", "target": 21.0, "viz": 2, "max_on_screen": 5.2, "words": 14},
    {"id": "35", "target": 35.0, "viz": 3, "max_on_screen": 6.4, "words": 18},
    {"id": "45", "target": 45.0, "viz": 5, "max_on_screen": 8.0, "words": 22},
)

MICRO_HOOK_SECONDS = 0.45
MAX_MICRO_HOOKS = 2
# Analysis scenes after this index must not be preceded by a micro-hook.
LAST_MICRO_ANALYSIS_INDEX = 1  # 0-based; never after the second analysis scene.


def pack_for(target_seconds: float | None) -> dict[str, Any]:
    """Nearest of the 21 / 35 / 45 second packs."""
    target = float(target_seconds or 35.0)
    return min(PACKS, key=lambda pack: abs(pack["target"] - target))


def recommended_viz(target_seconds: float | None, requested: int) -> int:
    """Cap the graph pack so a 21s cut cannot carry five cards."""
    pack = pack_for(target_seconds)
    requested = max(1, int(requested or pack["viz"]))
    if pack["id"] in {"21", "35"}:
        return min(requested, int(pack["viz"]))
    return requested


def micro_hook_indices(n_analysis: int, max_hooks: int = MAX_MICRO_HOOKS) -> list[int]:
    """Insert micros immediately before analysis scenes at these indices.

    Max two. Never after the second analysis scene has already played, so the
    legal window is indices ``0`` and ``1`` only. Index ``0`` is skipped so the
    first graph can prove the hook; that leaves index ``1`` (between the first
    and second analysis cards) as the default slot. A second micro is allowed
    at index ``0`` only when the pack is short enough that the open needs a
    second interrupt before the first graph.
    """
    n_analysis = int(n_analysis or 0)
    max_hooks = max(0, min(int(max_hooks), MAX_MICRO_HOOKS))
    if n_analysis <= 0 or max_hooks <= 0:
        return []
    legal = [index for index in range(n_analysis) if index <= LAST_MICRO_ANALYSIS_INDEX]
    if not legal:
        return []
    # Prefer the slot after the first analysis (index 1) when it exists.
    preferred: list[int] = []
    if 1 in legal:
        preferred.append(1)
    if 0 in legal and max_hooks >= 2:
        preferred.append(0)
    ordered = [index for index in preferred if index in legal]
    # Keep timeline order so the storyboard inserts them going forward.
    return sorted(ordered)[:max_hooks]


def first_frame_ok(scenes: list[dict[str, Any]]) -> bool:
    """True when the recap does not open on a crest/logo/clip."""
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "live_clip":
            return False
        language = str(scene.get("visual_language") or "")
        if viz in {"hook_claim", "hook_punch", "title"}:
            if language in {"number_slam", "split_smash", "stamp"}:
                return True
            if scene.get("hero_number") is not None:
                return True
            title = str(scene.get("title") or "")
            return bool(title.strip())
        return False
    return False


def apply_timeline_cap(candidates: list[dict[str, Any]], audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep goal_timeline from dominating a one- or two-goal match.

    The candidate already carries a −12 penalty for ≤2 goals. This pass makes
    sure it still cannot sit at the top of the ranked list in that case.
    """
    goals = len(audit.get("goal_timeline") or [])
    if goals > 2:
        return candidates
    patched = []
    for item in candidates:
        row = dict(item)
        if row.get("id") == "goal_timeline":
            row["score"] = min(float(row.get("score") or 0), 48.0)
        patched.append(row)
    return patched


def prevent_timeline_lead(chosen_ids: list[str], audit: dict[str, Any]) -> list[str]:
    """If a ≤2-goal pack still opens on the timeline, rotate it later."""
    goals = len(audit.get("goal_timeline") or [])
    if goals > 2 or not chosen_ids or chosen_ids[0] != "goal_timeline":
        return chosen_ids
    rest = [vid for vid in chosen_ids if vid != "goal_timeline"]
    return rest + ["goal_timeline"]


def scale_max_on_screen(viz_id: str, default: float, pack: dict[str, Any]) -> float:
    ceiling = float(pack.get("max_on_screen") or default)
    return min(default, ceiling)


def pack_word_budget(target_seconds: float | None, scene_count: int, fallback: int) -> int:
    pack = pack_for(target_seconds)
    budget = int(pack.get("words") or fallback)
    if scene_count <= 2:
        return budget
    return budget
