"""YouTube long-form recap: more viz, chapters, slower punch, no silent padding.

Short-form stays the farm default (~40s, five cards). Long-form aims at 3–8
minutes of *distinct* visualizations. If the match cannot fill three minutes
without repeating a card, the cut is shorter. Nothing is padded with black
or silence, and the hook still has to be on screen in the first three seconds.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import timing
from .data import write_json

FORMATS = ("short", "long", "both")
SHORT = "short"
LONG = "long"

HOOK_WINDOW = 3.0
SHORT_TARGET_SECONDS = 40.0
SHORT_VIZ_COUNT = 5
LONG_TARGET_MIN = 180.0
LONG_TARGET_MAX = 480.0
LONG_WORD_TARGET = 240.0
LONG_WORDS_PER_SECOND = 2.15
LONG_LEAD_IN = 0.70
LONG_TAIL = 1.00
LONG_ANALYSIS_FLOOR = 7.5
LONG_ANALYSIS_CEILING = 26.0
LONG_CLAIM_SECONDS = 1.15
LONG_PUNCH_SECONDS = 1.55

CHAPTER_TITLES = {
    "hook_claim": "Hook",
    "hook_punch": "Hook",
    "live_clip": "Hook",
    "micro_hook": None,
    "goal_timeline": "Goals",
    "shot_map": "Shot map",
    "momentum": "Momentum",
    "zone_control": "Territory",
    "goal_chain": "Build-up",
    "goalmouth": "The frame",
    "pass_network": "Pass network",
    "sterile_domination": "Control vs threat",
    "stat_slam": "The number",
    "match_radar": "Match radar",
    "touch_heatmap": "Touch heat",
    "field_tilt_wave": "Field tilt",
    "conversion_gauges": "Chances vs goals",
    "chance_funnel": "Chance funnel",
    "keeper_frame": "The keeper",
    "xg_race": "xG race",
    "time_zones": "The thirds",
    "player_spike": "The spike",
    "standard_stats": "The numbers",
    "close": "Full time",
}


def formats_from(flag: str | None) -> list[str]:
    value = (flag or SHORT).strip().lower()
    if value == "both":
        return [SHORT, LONG]
    if value in (SHORT, LONG):
        return [value]
    raise ValueError(f"Unknown --format {flag!r}. Choose short, long, or both.")


def viz_count_for(fmt: str, explicit: int | None, available: int) -> int:
    """How many distinct tactical cards to pick. Never asks for more than exist."""
    n = max(0, int(available))
    if fmt == LONG:
        if explicit is not None:
            return max(1, min(int(explicit), n or 1))
        return max(1, n)
    if explicit is not None:
        return max(1, int(explicit))
    return SHORT_VIZ_COUNT


def target_seconds_for(fmt: str, explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    return LONG_WORD_TARGET if fmt == LONG else SHORT_TARGET_SECONDS


def pace_scenes(scenes: list[dict[str, Any]], fmt: str) -> list[dict[str, Any]]:
    """Assign on_screen / clip lengths. Long form never inserts filler scenes."""
    if fmt != LONG:
        return timing.plan_durations(scenes)

    prepared: list[dict[str, Any]] = []
    for scene in scenes:
        if scene.get("visualization") == "micro_hook":
            continue
        prepared.append(dict(scene))

    for scene in prepared:
        viz = scene.get("visualization", "")
        if scene.get("hook") or viz in {"hook_claim", "hook_punch", "live_clip"}:
            if viz == "live_clip":
                on_screen = min(0.55, float(scene.get("seconds") or scene.get("on_screen") or 0.5))
            elif viz == "hook_punch":
                on_screen = float(scene.get("seconds") or LONG_PUNCH_SECONDS)
            else:
                on_screen = float(scene.get("seconds") or LONG_CLAIM_SECONDS)
            scene["on_screen"] = round(on_screen, 3)
            continue
        needed = LONG_LEAD_IN + (timing.word_count(scene.get("narration", "")) / LONG_WORDS_PER_SECOND) + LONG_TAIL
        floor = max(LONG_ANALYSIS_FLOOR, timing.MINIMUM_ON_SCREEN.get(viz, timing.DEFAULT_MINIMUM) * 0.9)
        scene["on_screen"] = round(min(LONG_ANALYSIS_CEILING, max(floor, needed)), 3)

    prepared = _fit_hook_window(prepared)
    prepared = _with_clip_lengths(prepared)
    prepared = _cap_runtime(prepared)
    return prepared


def scale_to_audio(scenes: list[dict[str, Any]], audio_seconds: float | None) -> list[dict[str, Any]]:
    """Fit analysis cards to a recorded VO. Never stretches past LONG_TARGET_MAX."""
    if not audio_seconds or audio_seconds <= 0 or not scenes:
        return scenes
    rest = [scene for scene in scenes if not scene.get("hook")]
    hook_time = sum(float(scene["on_screen"]) for scene in scenes if scene.get("hook"))
    if not rest:
        return scenes
    target = min(LONG_TARGET_MAX - hook_time, max(1.0, audio_seconds - hook_time))
    current = sum(float(scene["on_screen"]) for scene in rest)
    if current <= 0:
        return scenes
    factor = target / current
    scaled = []
    for scene in scenes:
        if scene.get("hook"):
            scaled.append(scene)
            continue
        viz = scene.get("visualization", "")
        speech = LONG_LEAD_IN + (timing.word_count(scene.get("narration", "")) / LONG_WORDS_PER_SECOND) + LONG_TAIL
        floor = max(speech * 0.9, timing.MINIMUM_ON_SCREEN.get(viz, timing.DEFAULT_MINIMUM) * 0.85)
        on_screen = min(LONG_ANALYSIS_CEILING, max(floor, float(scene["on_screen"]) * factor))
        scaled.append({**scene, "on_screen": round(on_screen, 3)})
    return _cap_runtime(_with_clip_lengths(scaled))


def chapter_markers(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """YouTube chapters. First marker is always 0:00."""
    placed = timing.timeline(scenes)
    chapters: list[dict[str, Any]] = []
    for scene in placed:
        viz = str(scene.get("visualization") or "")
        title = CHAPTER_TITLES.get(viz, viz.replace("_", " ").title())
        if title is None:
            continue
        start = float(scene.get("visible_start") or scene.get("clip_start") or 0.0)
        if scene.get("hook") or viz in {"hook_claim", "hook_punch", "live_clip"}:
            if chapters and chapters[0]["title"] == "Hook":
                continue
            chapters.append({
                "start": 0.0,
                "title": "Hook",
                "visualization": "hook",
            })
            continue
        if chapters and abs(chapters[-1]["start"] - start) < 0.05:
            continue
        chapters.append({
            "start": round(start, 3),
            "title": str(title),
            "visualization": viz,
        })
    if not chapters:
        chapters.append({"start": 0.0, "title": "Hook", "visualization": "hook"})
    elif chapters[0]["start"] != 0.0:
        chapters[0] = {**chapters[0], "start": 0.0}
    return chapters


def youtube_chapters_text(chapters: list[dict[str, Any]]) -> str:
    return "\n".join(f"{_timestamp(ch['start'])} {ch['title']}" for ch in chapters)


def runtime_note(total_seconds: float, viz_ids: list[str]) -> str:
    if total_seconds + 0.05 >= LONG_TARGET_MIN:
        if total_seconds > LONG_TARGET_MAX + 0.05:
            return f"capped at {format_runtime(LONG_TARGET_MAX)} — dropped padding, not cards"
        return ""
    n = len([v for v in viz_ids if v not in {"close"}])
    return (
        f"cut short of 3:00 ({format_runtime(total_seconds)}, {n} distinct viz) "
        "— not enough unique cards to fill without repeating"
    )


def format_runtime(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(round(seconds))
    if whole >= 3600:
        return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}"
    return f"{whole // 60}:{whole % 60:02d}"


def write_youtube_sidecars(
    out_dir: Path,
    chapters: list[dict[str, Any]],
    audit: dict[str, Any],
    *,
    series_id: str = "",
    total_seconds: float = 0.0,
) -> dict[str, Path]:
    """Description + chapter list for the YouTube upload box. series_id is never on frame."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    match = audit.get("match") or {}
    home = match.get("home") or "Home"
    away = match.get("away") or "Away"
    score = match.get("score_display") or ""
    league = " ".join(part for part in (match.get("league"), match.get("stage")) if part)
    lines = [
        f"{home} {score} {away}".strip(),
        league,
        "",
        youtube_chapters_text(chapters),
        "",
    ]
    if series_id:
        lines += [f"Series: {series_id}", ""]
    description = out_dir / "youtube_description.md"
    chapters_path = out_dir / "youtube_chapters.txt"
    description.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    chapters_path.write_text(youtube_chapters_text(chapters) + "\n", encoding="utf-8")
    meta = out_dir / "ffmetadata_chapters.txt"
    meta.write_text(_ffmetadata(chapters, total_seconds), encoding="utf-8")
    write_json(out_dir / "chapters.json", {
        "chapters": chapters,
        "series_id": series_id or None,
        "burned_in_video": False,
        "total_seconds": total_seconds,
    })
    return {
        "description": description,
        "chapters": chapters_path,
        "ffmetadata": meta,
    }


def mux_chapters(mp4: Path, chapters: list[dict[str, Any]], total_seconds: float) -> Path | None:
    """Best-effort chapter atoms on the mp4. Sidecars remain the source of truth."""
    ffmpeg = shutil.which("ffmpeg")
    mp4 = Path(mp4)
    if not ffmpeg or not mp4.exists() or not chapters:
        return None
    meta = mp4.parent / "ffmetadata_chapters.txt"
    if not meta.exists():
        meta.write_text(_ffmetadata(chapters, total_seconds), encoding="utf-8")
    staged = mp4.with_name(mp4.stem + ".chapters.mp4")
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(mp4),
        "-i", str(meta),
        "-map_metadata", "1",
        "-codec", "copy",
        str(staged),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not staged.exists():
        staged.unlink(missing_ok=True)
        return None
    staged.replace(mp4)
    return mp4


def hook_lands_in_window(scenes: list[dict[str, Any]], window: float = HOOK_WINDOW) -> bool:
    for scene in timing.timeline(scenes):
        if scene.get("hook") or scene.get("visualization") in {"hook_claim", "hook_punch"}:
            start = float(scene.get("visible_start") or scene.get("clip_start") or 0.0)
            return start < window
    return False


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _timestamp(seconds: float) -> str:
    whole = int(max(0.0, float(seconds)))
    if whole >= 3600:
        return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}"
    return f"{whole // 60}:{whole % 60:02d}"


def _hard_cut_after(scenes: list[dict[str, Any]], index: int) -> bool:
    if index >= len(scenes) - 1:
        return True
    return scenes[index + 1].get("cut") == "hard"


def _with_clip_lengths(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for index, scene in enumerate(scenes):
        on_screen = float(scene["on_screen"])
        extra = 0.0 if _hard_cut_after(scenes, index) else timing.TRANSITION
        out.append({**scene, "clip": round(on_screen + extra, 3)})
    return out


def _fit_hook_window(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the opening slam inside HOOK_WINDOW. Live clips stay short; punch slows first."""
    hook_idx = [i for i, scene in enumerate(scenes) if scene.get("hook")]
    if not hook_idx:
        return scenes
    total = sum(float(scenes[i]["on_screen"]) for i in hook_idx)
    if total <= HOOK_WINDOW:
        return scenes
    graphics = [
        i for i in hook_idx
        if scenes[i].get("visualization") in {"hook_claim", "hook_punch"}
    ]
    clips = [i for i in hook_idx if i not in graphics]
    clip_time = sum(float(scenes[i]["on_screen"]) for i in clips)
    remain = max(1.2, HOOK_WINDOW - clip_time)
    graphic_time = sum(float(scenes[i]["on_screen"]) for i in graphics) or remain
    factor = remain / graphic_time
    for i in graphics:
        floor = 0.65 if scenes[i].get("visualization") == "hook_punch" else 0.55
        scenes[i]["on_screen"] = round(max(floor, float(scenes[i]["on_screen"]) * factor), 3)
    return scenes


def _cap_runtime(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """If the cut would exceed 8 minutes, shrink analysis — never duplicate, never pad."""
    total = timing.total_seconds(scenes) if scenes and "clip" in scenes[0] else sum(
        float(s.get("clip") or s.get("on_screen") or 0) for s in scenes
    )
    if total <= LONG_TARGET_MAX or not scenes:
        return scenes
    rest = [s for s in scenes if not s.get("hook")]
    hook_time = total - sum(float(s.get("clip") or s.get("on_screen") or 0) for s in rest)
    budget = max(30.0, LONG_TARGET_MAX - hook_time)
    current = sum(float(s.get("on_screen") or 0) for s in rest) or 1.0
    factor = budget / current
    out = []
    for scene in scenes:
        if scene.get("hook"):
            out.append(scene)
            continue
        viz = scene.get("visualization", "")
        speech = LONG_LEAD_IN + (timing.word_count(scene.get("narration", "")) / LONG_WORDS_PER_SECOND) + LONG_TAIL
        floor = min(speech, timing.MINIMUM_ON_SCREEN.get(viz, 5.0) * 0.85)
        on_screen = max(floor, float(scene["on_screen"]) * factor)
        out.append({**scene, "on_screen": round(on_screen, 3)})
    return _with_clip_lengths(out)


def _ffmetadata(chapters: list[dict[str, Any]], total_seconds: float) -> str:
    ends = [int(round(ch["start"] * 1000)) for ch in chapters[1:]]
    ends.append(int(round(max(total_seconds, chapters[-1]["start"] + 0.4) * 1000)))
    lines = [";FFMETADATA1", "title=match recap"]
    for chapter, end in zip(chapters, ends):
        start = int(round(float(chapter["start"]) * 1000))
        if end <= start:
            end = start + 400
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={chapter['title']}",
        ]
    return "\n".join(lines) + "\n"
