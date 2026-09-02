"""Viral-quality gate for recap scripts.

A ruthless 0–100 for "will this get views": weighted pillars, not vibes.
Failures feed the next Gemini pass. Punch / claim phrases are remembered in
``video_output/_hook_memory.json`` so a team series does not open on the same slam.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import hooks, i18n
from .data import MatchBundle, write_json
from .director import SHAPE_FAMILY, _SCORELINE, _is_polite_title

MEMORY_NAME = "_hook_memory.json"
MEMORY_KEEP = 80
MEMORY_VERSION = 2

HOOK_DEADLINE = 0.8
LENGTH_BAND = (21.0, 45.0)
BAR_CLONE_RATIO = 0.15

# Short-form virality. Sum is 100. Missing modules drop a pillar and renormalize.
PILLAR_WEIGHTS: dict[str, int] = {
    "hook_speed": 14,     # readable number or stamp inside 0.8s
    "mute_first": 10,     # % of beats with on-screen text
    "viz_mix": 10,        # unique shape families; 3 bar clones die
    "spoiler": 8,         # hide/show strategy actually held
    "length": 10,         # 21–45s shorts sweet spot
    "insight": 8,         # claim on the card, not only in VO
    "language": 8,        # AZ/ES/RU recap must not leak English UI
    "live_clip": 6,       # smash present, or explicitly skipped
    "thumbnail": 8,       # first + last frame fitness
    "number_lock": 8,     # no invented digits, no score on the hook
    "comment_bait": 6,    # closer asks for a comment
    "safe_zones": 4,      # recap.platforms insets; skipped if module missing
}

# Platform rescores of the same ratios (hook deadline + length band change).
TIKTOK_WEIGHTS: dict[str, int] = {
    "hook_speed": 18,
    "mute_first": 14,
    "viz_mix": 8,
    "spoiler": 6,
    "length": 12,
    "insight": 6,
    "language": 6,
    "live_clip": 8,
    "thumbnail": 8,
    "number_lock": 6,
    "comment_bait": 8,
    "safe_zones": 4,
}
SHORTS_WEIGHTS: dict[str, int] = {
    "hook_speed": 16,
    "mute_first": 12,
    "viz_mix": 8,
    "spoiler": 6,
    "length": 10,
    "insight": 8,
    "language": 6,
    "live_clip": 6,
    "thumbnail": 10,
    "number_lock": 8,
    "comment_bait": 6,
    "safe_zones": 4,
}
YOUTUBE_WEIGHTS: dict[str, int] = {
    "hook_speed": 8,
    "mute_first": 8,
    "viz_mix": 10,
    "spoiler": 8,
    "length": 6,
    "insight": 14,
    "language": 8,
    "live_clip": 4,
    "thumbnail": 10,
    "number_lock": 10,
    "comment_bait": 4,
    "safe_zones": 4,
}

TIKTOK_DEADLINE = 0.5
SHORTS_DEADLINE = 0.8
YOUTUBE_DEADLINE = 3.0
TIKTOK_LENGTH = (21.0, 45.0)
SHORTS_LENGTH = (21.0, 60.0)
YOUTUBE_LENGTH = (21.0, 480.0)

CRITICAL_PILLARS = {"hook_speed", "spoiler", "number_lock", "language"}
CLIP_SKIP_MODES = {
    "skipped", "none", "graphics", "graphics_only", "no-fetch",
    "disabled", "explicit", "no-clip",
}
STAMP_LANGUAGES = {"number_slam", "split_smash", "stamp"}
READABLE_VIZ = {"hook_claim", "hook_punch", "stat_slam"}
ANALYSIS_SKIP = {"hook_claim", "hook_punch", "micro_hook", "live_clip", "close", "title"}
_BUT = re.compile(r"\bbut\b", re.IGNORECASE)
_DIGIT = re.compile(r"\d")
_BAIT = re.compile(
    r"(\?|comment|vote|motm|robbery|yes or no|tell us|"
    r"şərh|ses ver|səs ver|comenta|vota|пиши|голосуй)",
    re.IGNORECASE,
)
_EN_CHROME = re.compile(
    r"\b(shot map|full time|match recap|match result|pass share|"
    r"on target|big chances|touch map|keeper saves|field tilt)\b",
    re.IGNORECASE,
)


def memory_path(output_root: Path) -> Path:
    return Path(output_root) / MEMORY_NAME


def fingerprint(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_fingerprint = fingerprint


def hook_fingerprint(punch: str, claim: str = "") -> str:
    """Series memory keys off the scream line. Claim is a fallback only."""
    return fingerprint(punch) or fingerprint(claim)


def load_memory(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        rows = data.get("entries") or data.get("punches") or []
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def save_memory(path: Path, rows: list[dict[str, Any]]) -> None:
    write_json(path, {"version": MEMORY_VERSION, "entries": rows[-MEMORY_KEEP:]})


def _entry_fp(row: dict[str, Any]) -> str:
    return str(row.get("fingerprint") or hook_fingerprint(
        str(row.get("punch") or ""), str(row.get("claim") or ""),
    ))


def series_used_fingerprints(
    rows: list[dict[str, Any]],
    teams: list[str] | None = None,
    series_id: str | None = None,
) -> set[str]:
    """Phrases this team series must not open on again."""
    wanted_teams = {str(name).strip().lower() for name in (teams or []) if str(name).strip()}
    series = str(series_id or "").strip()
    used: set[str] = set()
    for row in rows:
        fp = _entry_fp(row)
        if not fp:
            continue
        row_series = str(row.get("series_id") or "").strip()
        row_teams = {str(name).strip().lower() for name in (row.get("teams") or []) if str(name).strip()}
        if series and row_series and row_series == series:
            used.add(fp)
        elif wanted_teams and row_teams and wanted_teams & row_teams:
            used.add(fp)
    return used


def remember_punch(output_root: Path, punch: str, match_id: str, kind: str) -> None:
    remember_round(
        output_root,
        winner={"punch": punch, "claim": "", "kind": kind, "score": None},
        losers=[],
        match_id=match_id,
        teams=[],
        series_id="",
    )


def remember_round(
    output_root: Path,
    *,
    winner: dict[str, Any],
    losers: list[dict[str, Any]] | None = None,
    match_id: str,
    teams: list[str] | None = None,
    series_id: str | None = None,
) -> None:
    """Persist the shipped punch and the A/B losers for the next match in the series."""
    path = memory_path(output_root)
    rows = load_memory(path)
    team_list = [str(name) for name in (teams or []) if str(name).strip()]
    series = str(series_id or "").strip()

    def upsert(payload: dict[str, Any], role: str) -> None:
        punch = str(payload.get("punch") or "").strip()
        claim = str(payload.get("claim") or "").strip()
        if not punch and not claim:
            return
        fp = hook_fingerprint(punch, claim)
        rows[:] = [row for row in rows if _entry_fp(row) != fp]
        rows.append({
            "punch": punch,
            "claim": claim,
            "fingerprint": fp,
            "match_id": match_id,
            "kind": str(payload.get("kind") or ""),
            "role": role,
            "score": payload.get("score"),
            "variant": payload.get("variant"),
            "teams": team_list,
            "series_id": series or None,
        })

    upsert(winner, "winner")
    for loser in losers or []:
        upsert(loser, "loser")
    save_memory(path, rows)


def scene_seconds(scene: dict[str, Any]) -> float:
    return float(scene.get("on_screen") or scene.get("clip") or scene.get("seconds") or 0.0)


def total_seconds(scenes: list[dict[str, Any]]) -> float:
    return sum(scene_seconds(scene) for scene in scenes)


def _has_duration(scene: dict[str, Any]) -> bool:
    return scene.get("on_screen") is not None or scene.get("clip") is not None or scene.get("seconds") is not None


def timed_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill on_screen via the timing planner when the script stage has not yet."""
    if not scenes or all(_has_duration(scene) for scene in scenes):
        return scenes
    try:
        from . import timing
        return timing.plan_durations(scenes)
    except Exception:
        return scenes


def planned_runtime(scenes: list[dict[str, Any]]) -> float:
    planned = timed_scenes(scenes)
    if planned and any(scene.get("clip") is not None for scene in planned):
        return sum(float(scene.get("clip") or scene_seconds(scene)) for scene in planned)
    return total_seconds(planned)


def scene_has_text(scene: dict[str, Any]) -> bool:
    if scene.get("hero_number") is not None:
        return True
    if any(str(item).strip() for item in (scene.get("lines") or []) if item is not None):
        return True
    for field in ("title", "subtitle", "insight", "narration", "kicker", "comment_bait"):
        if str(scene.get(field) or "").strip():
            return True
    return False


def has_number_or_stamp(scene: dict[str, Any]) -> bool:
    if scene.get("hero_number") is not None:
        return True
    language = str(scene.get("visual_language") or "")
    if language in STAMP_LANGUAGES:
        return True
    viz = str(scene.get("visualization") or "")
    title = str(scene.get("title") or "")
    if viz in READABLE_VIZ and _DIGIT.search(title):
        return True
    return False


def first_readable_at(scenes: list[dict[str, Any]]) -> tuple[float, dict[str, Any] | None]:
    elapsed = 0.0
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "live_clip" and not has_number_or_stamp(scene):
            elapsed += scene_seconds(scene)
            continue
        if has_number_or_stamp(scene) or viz in READABLE_VIZ:
            return elapsed, scene
        elapsed += scene_seconds(scene)
    return elapsed, None


def hook_speed_ratio(
    elapsed: float,
    *,
    stamped: bool,
    deadline: float = HOOK_DEADLINE,
) -> float:
    stamp_factor = 1.0 if stamped else 0.4
    if elapsed <= deadline:
        time_factor = 1.0
    elif elapsed >= deadline + 1.2:
        time_factor = 0.0
    else:
        time_factor = 1.0 - (elapsed - deadline) / 1.2
    return max(0.0, min(1.0, time_factor * stamp_factor))


def length_ratio(seconds: float, band: tuple[float, float] = LENGTH_BAND) -> float:
    lo, hi = band
    value = float(seconds or 0.0)
    if lo <= value <= hi:
        return 1.0
    if value < lo:
        floor = lo - 12.0
        if value <= floor:
            return 0.0
        return (value - floor) / 12.0
    extra = value - hi
    if extra >= 20.0:
        return 0.0
    return 1.0 - extra / 20.0


def combine_score(
    ratios: dict[str, float],
    *,
    weights: dict[str, int] | None = None,
    skip: set[str] | None = None,
) -> int:
    table = dict(weights or PILLAR_WEIGHTS)
    ignored = skip or set()
    used = {key: weight for key, weight in table.items() if key not in ignored}
    total_w = float(sum(used.values()) or 1)
    raw = sum(max(0.0, min(1.0, float(ratios.get(key, 0.0)))) * weight for key, weight in used.items())
    return int(round(100.0 * raw / total_w))


def _platforms():
    try:
        from . import platforms
    except ImportError:
        return None
    return platforms


def _families(selected: list[dict[str, Any]], scenes: list[dict[str, Any]]) -> list[str]:
    families: list[str] = []
    if selected:
        for item in selected:
            families.append(str(item.get("shape") or SHAPE_FAMILY.get(item.get("id", ""), "other")))
        return [family for family in families if family]
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz in SHAPE_FAMILY:
            families.append(SHAPE_FAMILY[viz])
    return families


def _analysis_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if scene.get("hook") or viz in ANALYSIS_SKIP:
            continue
        out.append(scene)
    return out


def _clip_skipped(clip_report: dict[str, Any] | None) -> bool:
    if not clip_report:
        return False
    if clip_report.get("skipped") is True:
        return True
    mode = str(clip_report.get("mode") or "").strip().lower()
    reason = str(clip_report.get("reason") or "").strip().lower()
    return mode in CLIP_SKIP_MODES or reason in CLIP_SKIP_MODES


def _looks_english_ui(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    try:
        if i18n.looks_english(raw):
            return True
    except Exception:
        pass
    return bool(_EN_CHROME.search(raw))


def score_pillars(
    scenes: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    language: str | None = None,
    spoiler: str | None = None,
    clip_report: dict[str, Any] | None = None,
    output_root: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str], list[str], set[str]]:
    """Return (pillars, warnings, failures, skipped). Each pillar has ratio 0–1."""
    warnings: list[str] = []
    failures: list[str] = []
    skipped: set[str] = set()
    notes: dict[str, list[str]] = {key: [] for key in PILLAR_WEIGHTS}
    ratios: dict[str, float] = {key: 1.0 for key in PILLAR_WEIGHTS}

    def fail(pillar: str, message: str, *, ratio: float | None = None) -> None:
        warnings.append(message)
        failures.append(message)
        notes[pillar].append(message)
        if ratio is not None:
            ratios[pillar] = min(ratios[pillar], ratio)

    def warn(pillar: str, message: str, *, ratio: float | None = None) -> None:
        warnings.append(message)
        notes[pillar].append(message)
        if ratio is not None:
            ratios[pillar] = min(ratios[pillar], ratio)

    lang = language or i18n.get_language()
    spoiler_mode = str(spoiler or "show").strip().lower() or "show"

    elapsed, readable = first_readable_at(scenes)
    stamped = bool(readable and has_number_or_stamp(readable))
    ratios["hook_speed"] = hook_speed_ratio(elapsed, stamped=stamped, deadline=HOOK_DEADLINE)
    if elapsed > HOOK_DEADLINE:
        fail(
            "hook_speed",
            f"first readable hook at {elapsed:.2f}s (need <{HOOK_DEADLINE}s)",
            ratio=ratios["hook_speed"],
        )
    elif not stamped:
        fail("hook_speed", "opening has no readable number or stamp", ratio=ratios["hook_speed"])

    punch = ""
    hook_kind = ""
    claim = ""
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "hook_punch" and not punch:
            punch = str(scene.get("title") or "")
            hook_kind = str(scene.get("hook_kind") or "")
        if viz == "hook_claim" and not claim:
            claim = str(scene.get("title") or "")
            hook_kind = hook_kind or str(scene.get("hook_kind") or "")

    if output_root is not None and punch:
        for row in load_memory(memory_path(output_root)):
            if fingerprint(str(row.get("punch") or "")) == fingerprint(punch):
                fail(
                    "hook_speed",
                    f"punch line reused from {row.get('match_id')}",
                    ratio=min(ratios["hook_speed"], 0.2),
                )
                break

    qualified: list[str] = []
    try:
        qualified = hooks.qualifying_kinds(bundle, audit)
    except Exception:
        qualified = []
    stronger = [kind for kind in qualified if kind not in {"one_moment", "level", "stalemate"}]
    if hook_kind == "one_moment" and stronger:
        fail(
            "hook_speed",
            f"hook kind is one_moment but {stronger[0]} also qualified",
            ratio=min(ratios["hook_speed"], 0.35),
        )

    n_scenes = max(1, len(scenes))
    covered = sum(1 for scene in scenes if scene_has_text(scene))
    ratios["mute_first"] = covered / n_scenes
    if ratios["mute_first"] < 1.0:
        gaps = [
            str(scene.get("visualization") or scene.get("id") or "scene")
            for scene in scenes if not scene_has_text(scene)
        ]
        warn(
            "mute_first",
            f"mute-first coverage {int(round(ratios['mute_first'] * 100))}% "
            f"(no text on {', '.join(gaps[:6])})",
            ratio=ratios["mute_first"],
        )
        if ratios["mute_first"] < 0.7:
            failures.append(notes["mute_first"][-1])

    families = _families(selected, scenes)
    unique = {family for family in families if family}
    bar_count = sum(1 for family in families if family == "bars")
    if bar_count >= 3 or (families and unique == {"bars"}):
        ratios["viz_mix"] = BAR_CLONE_RATIO
        fail("viz_mix", f"{bar_count or len(families)} bar clones in the pack", ratio=BAR_CLONE_RATIO)
    elif len(unique) >= 3 and bar_count <= 1:
        ratios["viz_mix"] = 1.0
    elif len(unique) >= 3:
        ratios["viz_mix"] = 0.75
        warn("viz_mix", "shape mix is 3+ families but still repeats bars")
    elif len(unique) == 2:
        ratios["viz_mix"] = 0.45
        fail("viz_mix", f"pack geometry diversity is {len(unique)} families (need 3+)", ratio=0.45)
    else:
        ratios["viz_mix"] = 0.2
        fail("viz_mix", f"pack geometry diversity is {len(unique)} families (need 3+)", ratio=0.2)

    spoiled = False
    close_has_score = False
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        blob = " ".join(
            str(scene.get(field) or "")
            for field in ("title", "subtitle", "kicker", "insight", "narration", "hook_stat")
        )
        if viz == "close" and _SCORELINE.search(blob):
            close_has_score = True
        if scene.get("hook") or viz in {"hook_claim", "hook_punch", "micro_hook"}:
            if _SCORELINE.search(blob):
                spoiled = True
                fail("spoiler", f"{scene.get('id')} spoils the score in the hook", ratio=0.0)
    opening_score = False
    cursor = 0.0
    for scene in scenes:
        if cursor >= 3.0:
            break
        blob = " ".join(str(scene.get(field) or "") for field in ("title", "subtitle", "kicker", "insight", "narration"))
        if _SCORELINE.search(blob):
            opening_score = True
            break
        cursor += scene_seconds(scene)
    if spoiler_mode == "hide":
        if opening_score or spoiled:
            ratios["spoiler"] = 0.0
            fail("spoiler", "spoiler=hide but a score appears in the first 3s / hook", ratio=0.0)
        else:
            ratios["spoiler"] = 1.0
    else:
        if spoiled:
            ratios["spoiler"] = 0.0
        elif close_has_score:
            ratios["spoiler"] = 1.0
        else:
            ratios["spoiler"] = 0.55
            warn("spoiler", "spoiler=show but the close never puts the score on screen", ratio=0.55)

    runtime = planned_runtime(scenes)
    ratios["length"] = length_ratio(runtime, LENGTH_BAND)
    if not (LENGTH_BAND[0] <= runtime <= LENGTH_BAND[1]):
        warn(
            "length",
            f"runtime {runtime:.1f}s is outside the {LENGTH_BAND[0]:.0f}–{LENGTH_BAND[1]:.0f}s shorts band",
            ratio=ratios["length"],
        )
        if ratios["length"] < 0.5:
            failures.append(notes["length"][-1])

    analysis = _analysis_scenes(scenes)
    if not analysis:
        ratios["insight"] = 0.0
        fail("insight", "no analysis cards to put an on-screen insight on", ratio=0.0)
    else:
        shown = 0
        for scene in analysis:
            insight = str(scene.get("insight") or "").strip()
            narration = str(scene.get("narration") or "").strip()
            title = str(scene.get("title") or "")
            if _is_polite_title(title, bundle):
                fail(
                    "insight",
                    f"{scene.get('id')} uses a polite title: {title[:40]!r}",
                    ratio=0.4,
                )
            if insight and insight.lower() != narration.lower():
                shown += 1
            elif not insight:
                warn("insight", f"{scene.get('id')} insight is empty", ratio=None)
        ratios["insight"] = min(ratios["insight"], shown / max(1, len(analysis)))
        if notes["insight"] and ratios["insight"] < 0.7:
            # empty insights already warned; promote if coverage is poor
            if ratios["insight"] < 0.5:
                failures.extend(note for note in notes["insight"] if note not in failures)

    buts = 0
    for scene in scenes:
        if scene.get("hook"):
            continue
        if _BUT.search(str(scene.get("narration") or "")):
            buts += 1
    if buts > 1:
        fail("insight", f"narration uses 'but' on {buts} scenes", ratio=min(ratios["insight"], 0.45))

    if lang == "en":
        ratios["language"] = 1.0
    else:
        fields = ("kicker", "title", "subtitle", "insight", "narration", "hook_stat")
        checked = 0
        dirty = 0
        for scene in scenes:
            viz = str(scene.get("visualization") or "")
            for field in fields:
                text = str(scene.get(field) or "").strip()
                if not text:
                    continue
                # Proper nouns / scores are fine; leftover English chrome is not.
                checked += 1
                if _looks_english_ui(text):
                    dirty += 1
                    warn(
                        "language",
                        f"{lang} recap leaks English UI on {scene.get('id')}.{field}: {text[:48]!r}",
                    )
        ratios["language"] = 1.0 if not checked else max(0.0, 1.0 - dirty / checked)
        if dirty:
            fail("language", f"{lang} recap still has {dirty} English UI leftover(s)", ratio=ratios["language"])

    has_clip = any(str(scene.get("visualization") or "") == "live_clip" for scene in scenes)
    if has_clip:
        ratios["live_clip"] = 1.0
    elif _clip_skipped(clip_report):
        ratios["live_clip"] = 1.0
        notes["live_clip"].append("live clip smash explicitly skipped")
    else:
        ratios["live_clip"] = 0.0
        fail("live_clip", "live clip smash missing (not marked skipped)", ratio=0.0)

    first = scenes[0] if scenes else None
    last = scenes[-1] if scenes else None
    first_ok = bool(
        first
        and str(first.get("visualization") or "") != "live_clip"
        and has_number_or_stamp(first)
    )
    last_ok = bool(
        last
        and str(last.get("visualization") or "") == "close"
        and (
            _SCORELINE.search(str(last.get("title") or ""))
            or _BAIT.search(" ".join(str(last.get(field) or "") for field in ("title", "insight", "narration", "comment_bait")))
        )
    )
    ratios["thumbnail"] = (1.0 if first_ok else 0.0) * 0.5 + (1.0 if last_ok else 0.0) * 0.5
    if not first_ok:
        warn("thumbnail", "first frame is not a number/stamp hook (thumbnail dead on arrival)", ratio=None)
    if not last_ok:
        warn("thumbnail", "last frame is not a close with score or bait", ratio=None)
    if ratios["thumbnail"] < 0.5:
        failures.append(notes["thumbnail"][-1] if notes["thumbnail"] else "thumbnail unfit")

    lock_checked = 0
    lock_passed = 0
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        pack = scene.get("fact_pack") or {
            "numbers": scene.get("allowed_numbers") or [],
            "never_say": [],
        }
        if scene.get("hook") or viz in {"hook_claim", "hook_punch", "micro_hook"}:
            for field in ("title", "subtitle", "insight", "narration"):
                text = str(scene.get(field) or "")
                if not text.strip():
                    continue
                lock_checked += 1
                if hooks.hook_passes_lock(text, pack):
                    lock_passed += 1
                else:
                    fail("number_lock", f"{scene.get('id')}.{field} fails the number lock", ratio=None)
        elif pack.get("numbers"):
            for field in ("title", "insight", "narration"):
                text = str(scene.get(field) or "")
                if not text.strip():
                    continue
                lock_checked += 1
                extras = hooks.extra_numbers(text, hooks.allowed_number_tokens(pack.get("numbers") or []))
                if extras:
                    fail("number_lock", f"{scene.get('id')}.{field} invents {sorted(extras)}", ratio=None)
                else:
                    lock_passed += 1
            title = str(scene.get("title") or "")
            surnames = [str(name) for name in (pack.get("surnames") or []) if name]
            numbers = pack.get("numbers") or []
            if numbers and surnames and not _DIGIT.search(title) and not any(name.lower() in title.lower() for name in surnames):
                warn("number_lock", f"{scene.get('id')} title has no digit and no surname")
    ratios["number_lock"] = 1.0 if not lock_checked else lock_passed / lock_checked
    if ratios["number_lock"] < 1.0:
        ratios["number_lock"] = min(ratios["number_lock"], 0.4 if ratios["number_lock"] < 0.8 else ratios["number_lock"])

    bait_blob = ""
    if last:
        bait_blob = " ".join(
            str(last.get(field) or "")
            for field in ("title", "insight", "narration", "comment_bait", "subtitle")
        )
        if last.get("comment_bait"):
            bait_blob += " " + str(last.get("comment_bait"))
    has_bait = bool(_BAIT.search(bait_blob))
    ratios["comment_bait"] = 1.0 if has_bait else 0.0
    if not has_bait:
        fail("comment_bait", "comment-bait closer missing", ratio=0.0)

    platforms = _platforms()
    if platforms is None or not hasattr(platforms, "validate_plan"):
        skipped.add("safe_zones")
        ratios["safe_zones"] = 1.0
    else:
        problems: list[str] = []
        try:
            profiles = []
            table = getattr(platforms, "PROFILES", {}) or {}
            for key in ("tiktok", "shorts", "youtube_long", "youtube"):
                profile = table.get(key)
                if profile is not None:
                    profiles.append(profile)
            if not profiles and hasattr(platforms, "resolve_exports"):
                profiles = list(platforms.resolve_exports(None, "all") or [])
            for profile in profiles[:3]:
                problems.extend(platforms.validate_plan(scenes, profile, spoiler=spoiler_mode) or [])
        except Exception as exc:
            problems.append(str(exc))
        if not problems:
            ratios["safe_zones"] = 1.0
        else:
            ratios["safe_zones"] = max(0.0, 1.0 - min(1.0, len(problems) / 6.0))
            warn("safe_zones", f"platform safe-zones: {problems[0]}", ratio=ratios["safe_zones"])
            if ratios["safe_zones"] < 0.5:
                failures.append(notes["safe_zones"][-1])

    for key in CRITICAL_PILLARS:
        if key in skipped:
            continue
        if ratios[key] < 0.5:
            message = notes[key][-1] if notes[key] else f"{key} scored {ratios[key]:.2f}"
            if message not in failures:
                failures.append(message)

    pillars = {}
    for key, weight in PILLAR_WEIGHTS.items():
        pillars[key] = {
            "ratio": round(float(ratios[key]), 4),
            "weight": weight,
            "notes": notes[key],
            "skipped": key in skipped,
        }
    return pillars, warnings, failures, skipped


def platform_scores(
    scenes: list[dict[str, Any]],
    ratios: dict[str, float],
    *,
    skip: set[str] | None = None,
) -> dict[str, int]:
    elapsed, readable = first_readable_at(scenes)
    stamped = bool(readable and has_number_or_stamp(readable))
    runtime = planned_runtime(scenes)
    ignored = set(skip or set())

    def rescore(deadline: float, band: tuple[float, float], weights: dict[str, int]) -> int:
        mixed = dict(ratios)
        mixed["hook_speed"] = hook_speed_ratio(elapsed, stamped=stamped, deadline=deadline)
        mixed["length"] = length_ratio(runtime, band)
        return combine_score(mixed, weights=weights, skip=ignored)

    return {
        "tiktok_score": rescore(TIKTOK_DEADLINE, TIKTOK_LENGTH, TIKTOK_WEIGHTS),
        "shorts_score": rescore(SHORTS_DEADLINE, SHORTS_LENGTH, SHORTS_WEIGHTS),
        "youtube_score": rescore(YOUTUBE_DEADLINE, YOUTUBE_LENGTH, YOUTUBE_WEIGHTS),
    }


def score_plan(
    scenes: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any],
    *,
    output_root: Path | None = None,
    language: str | None = None,
    spoiler: str | None = None,
    clip_report: dict[str, Any] | None = None,
    series_id: str | None = None,
) -> dict[str, Any]:
    pillars, warnings, failures, skipped = score_pillars(
        scenes, selected, bundle, audit,
        language=language, spoiler=spoiler, clip_report=clip_report,
        output_root=output_root,
    )
    ratios = {key: float(row["ratio"]) for key, row in pillars.items()}
    score = combine_score(ratios, skip=skipped)
    platforms = platform_scores(scenes, ratios, skip=skipped)

    punch = ""
    hook_kind = ""
    claim = ""
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "hook_punch" and not punch:
            punch = str(scene.get("title") or "")
            hook_kind = str(scene.get("hook_kind") or "")
        if viz == "hook_claim" and not claim:
            claim = str(scene.get("title") or "")
            hook_kind = hook_kind or str(scene.get("hook_kind") or "")

    families = sorted({family for family in _families(selected, scenes) if family})
    return {
        "score": max(0, min(100, score)),
        "tiktok_score": platforms["tiktok_score"],
        "shorts_score": platforms["shorts_score"],
        "youtube_score": platforms["youtube_score"],
        "pillars": pillars,
        "warnings": warnings,
        "failures": failures,
        "families": families,
        "hook_kind": hook_kind,
        "punch": punch,
        "claim": claim,
        "skipped_pillars": sorted(skipped),
        "safe_zones_scored": "safe_zones" not in skipped,
        "runtime_seconds": round(planned_runtime(scenes), 3),
        "series_id": series_id or None,
        "language": language or i18n.get_language(),
        "spoiler": str(spoiler or "show"),
    }


def redo_instruction(base: str, report: dict[str, Any]) -> str:
    notes = list(report.get("failures") or []) or list(report.get("warnings") or [])
    pillars = report.get("pillars") or {}
    weak = [
        f"{name}={row.get('ratio', 0):.2f}"
        for name, row in pillars.items()
        if not row.get("skipped") and float(row.get("ratio") or 0) < 0.6
    ]
    if not notes and not weak:
        return f"{base} Sharpen the hook and vary the sentence rhythm.".strip()
    joined = " ".join(f"- {note}" for note in notes[:8])
    extra = f" Weak pillars: {', '.join(weak)}." if weak else ""
    platforms = (
        f" tiktok={report.get('tiktok_score')} shorts={report.get('shorts_score')} "
        f"youtube={report.get('youtube_score')}."
    )
    return f"{base} Fix these viral-audit failures: {joined}.{extra}{platforms}".strip()
