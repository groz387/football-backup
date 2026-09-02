"""Scene timing and subtitles.

The previous pipeline gave every scene a fixed length between two and five
seconds regardless of how much narration it carried, which meant a fifty-word
line had to be read in two seconds. Here the narration decides the length, and
the subtitles are derived from the same numbers so they cannot drift.
"""

from __future__ import annotations

import re
from typing import Any

# A brisk but intelligible sports-VO pace, in words per second.
WORDS_PER_SECOND = 2.55

# Breathing room around the spoken line so scenes do not cut on the last word.
LEAD_IN = 0.45
TAIL = 0.65

# Cross-dissolve between consecutive scenes. 12 frames at 24fps is a wipe, not a dissolve.
TRANSITION = 0.50

# Time each visualization needs to finish animating and still be readable.
MINIMUM_ON_SCREEN = {
    "hook_claim": 0.85,
    "hook_punch": 0.70,
    "micro_hook": 0.45,
    "live_clip": 0.40,
    "title": 3.2,
    "standard_stats": 5.2,
    "goal_timeline": 5.4,
    "shot_map": 5.2,
    "momentum": 5.2,
    "zone_control": 5.0,
    "goal_chain": 5.6,
    "goalmouth": 5.0,
    "pass_network": 5.2,
    "sterile_domination": 5.0,
    "stat_slam": 4.4,
    "match_radar": 5.0,
    "touch_heatmap": 5.0,
    "field_tilt_wave": 5.2,
    "conversion_gauges": 5.0,
    "chance_funnel": 5.2,
    "keeper_frame": 5.0,
    "xg_race": 5.2,
    "time_zones": 5.4,
    "player_spike": 5.0,
    "close": 4.4,
}
DEFAULT_MINIMUM = 5.0
# Analysis cards die if they sit as a finished slide. Keep them inside one swipe.
MAXIMUM_ON_SCREEN = 8.0

# Subtitle readability limits.
SUBTITLE_MAX_CHARS = 84
SUBTITLE_LINE_CHARS = 40
SUBTITLE_MIN_SECONDS = 1.1


def word_count(text: str) -> int:
    return len([token for token in re.split(r"\s+", str(text).strip()) if token])


def speech_seconds(text: str) -> float:
    return word_count(text) / WORDS_PER_SECOND


def word_budget(target_seconds: float, scene_count: int) -> int:
    """Words per scene that would fill *target_seconds* of finished video."""
    if scene_count <= 0:
        return 30
    speakable = max(1.0, target_seconds - scene_count * (LEAD_IN + TAIL) - TRANSITION)
    return max(14, int(speakable * WORDS_PER_SECOND / scene_count))


def _hard_cut_after(scenes: list[dict[str, Any]], index: int) -> bool:
    """True when the boundary after *index* is a cut, not a dissolve."""
    if index >= len(scenes) - 1:
        return True
    return scenes[index + 1].get("cut") == "hard"


def _with_clip_lengths(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for index, scene in enumerate(scenes):
        on_screen = float(scene["on_screen"])
        extra = 0.0 if _hard_cut_after(scenes, index) else TRANSITION
        out.append({**scene, "clip": round(on_screen + extra, 3)})
    return out


def plan_durations(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every scene an ``on_screen`` (visible) and ``clip`` (encoded) length.

    Analysis scenes are longer than ``on_screen`` by one transition, because
    adjacent clips overlap when the cross-dissolve is applied. Hook scenes
    hard-cut, so their clip length equals the time they occupy.
    """
    planned = []
    for scene in scenes:
        viz = scene.get("visualization", "")
        if scene.get("hook"):
            on_screen = float(scene.get("seconds") or MINIMUM_ON_SCREEN.get(viz, 0.7))
        else:
            needed = LEAD_IN + speech_seconds(scene.get("narration", "")) + TAIL
            floor = MINIMUM_ON_SCREEN.get(viz, DEFAULT_MINIMUM)
            on_screen = min(MAXIMUM_ON_SCREEN, max(floor, needed))
        planned.append({**scene, "on_screen": round(on_screen, 3)})
    return _with_clip_lengths(planned)


def scale_to_audio(scenes: list[dict[str, Any]], audio_seconds: float | None) -> list[dict[str, Any]]:
    """Stretch or squeeze analysis scenes so the video ends when the narration does.

    Hook beats stay at their slam lengths. Only the package after them flexes.
    """
    if not audio_seconds or audio_seconds <= 0 or not scenes:
        return scenes

    rest = [scene for scene in scenes if not scene.get("hook")]
    hook_time = sum(float(scene["on_screen"]) for scene in scenes if scene.get("hook"))
    if not rest:
        return scenes

    target = max(1.0, audio_seconds - hook_time)
    current = sum(float(scene["on_screen"]) for scene in rest)
    if current <= 0:
        return scenes
    factor = target / current
    scaled = []
    for scene in scenes:
        if scene.get("hook"):
            scaled.append(scene)
            continue
        floor = MINIMUM_ON_SCREEN.get(scene.get("visualization", ""), DEFAULT_MINIMUM)
        on_screen = round(
            min(MAXIMUM_ON_SCREEN, max(floor * 0.85, float(scene["on_screen"]) * factor)),
            2,
        )
        scaled.append({**scene, "on_screen": on_screen})
    return _with_clip_lengths(scaled)


def timeline(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Absolute start/end times once cuts and dissolves are accounted for."""
    placed = []
    cursor = 0.0
    for index, scene in enumerate(scenes):
        start = cursor
        clip = float(scene["clip"])
        hard_in = index == 0 or scene.get("cut") == "hard"
        hard_out = _hard_cut_after(scenes, index)
        pad_in = 0.0 if hard_in else TRANSITION / 2
        pad_out = 0.0 if hard_out else TRANSITION / 2
        placed.append(
            {
                **scene,
                "clip_start": round(start, 3),
                "clip_end": round(start + clip, 3),
                "visible_start": round(start + pad_in, 3),
                "visible_end": round(start + clip - pad_out, 3),
            }
        )
        cursor += clip if hard_out else clip - TRANSITION
    return placed


def total_seconds(scenes: list[dict[str, Any]]) -> float:
    if not scenes:
        return 0.0
    return round(float(timeline(scenes)[-1]["clip_end"]), 3)


# ---------------------------------------------------------------------------
# subtitles
# ---------------------------------------------------------------------------

def _split_for_subtitles(text: str) -> list[str]:
    """Break narration into cue-sized chunks on sentence then clause boundaries."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text).strip()) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        if len(sentence) <= SUBTITLE_MAX_CHARS:
            chunks.append(sentence)
            continue
        buffer = ""
        for piece in re.split(r"(?<=[,;:])\s+", sentence):
            candidate = f"{buffer} {piece}".strip()
            if len(candidate) <= SUBTITLE_MAX_CHARS or not buffer:
                buffer = candidate
            else:
                chunks.append(buffer)
                buffer = piece
        if buffer:
            chunks.append(buffer)

    # Anything still too long gets broken on word boundaries.
    final: list[str] = []
    for chunk in chunks:
        while len(chunk) > SUBTITLE_MAX_CHARS:
            cut = chunk.rfind(" ", 0, SUBTITLE_MAX_CHARS)
            cut = cut if cut > 0 else SUBTITLE_MAX_CHARS
            final.append(chunk[:cut].strip())
            chunk = chunk[cut:].strip()
        if chunk:
            final.append(chunk)
    return final


def _wrap_two_lines(text: str) -> str:
    if len(text) <= SUBTITLE_LINE_CHARS:
        return text
    cut = text.rfind(" ", 0, len(text) // 2 + 8)
    if cut <= 0:
        return text
    return f"{text[:cut].strip()}\n{text[cut:].strip()}"


def build_subtitles(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cues that sit inside each scene's own visible window."""
    cues: list[dict[str, Any]] = []
    for scene in scenes:
        if scene.get("hook") or scene.get("visualization") in {
            "hook_claim", "hook_punch", "micro_hook", "live_clip",
        }:
            continue
        narration = str(scene.get("narration", "")).strip()
        if not narration:
            continue
        start = float(scene["visible_start"])
        end = float(scene["visible_end"])
        span = max(0.4, end - start)
        chunks = _split_for_subtitles(narration) or [narration]
        weights = [max(1, len(chunk)) for chunk in chunks]
        total_weight = sum(weights)

        cursor = start
        for chunk, weight in zip(chunks, weights):
            length = max(SUBTITLE_MIN_SECONDS, span * weight / total_weight)
            cue_end = min(end, cursor + length)
            if cue_end - cursor < 0.25:
                continue
            cues.append({"start": round(cursor, 3), "end": round(cue_end, 3), "text": _wrap_two_lines(chunk)})
            cursor = cue_end
        if cues and cursor < end:
            cues[-1]["end"] = round(end, 3)
    return cues


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds == 1000:
        seconds, milliseconds = seconds + 1, 0
    whole = int(seconds)
    return f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d},{milliseconds:03d}"


def render_srt(cues: list[dict[str, Any]]) -> str:
    blocks = [
        f"{index}\n{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}\n{cue['text']}\n"
        for index, cue in enumerate(cues, 1)
    ]
    return "\n".join(blocks)
