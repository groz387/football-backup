"""Export one recap master to every requested social format.

The matplotlib recap is already a 1080x1920 portrait master. This module
ffmpeg-exports TikTok / Reels / Shorts / Stories / square / YouTube 16:9 from
that file without stripping the baked wiperight cuts, and without letterboxing
a landscape frame into 9:16.

Cover frames are drawn from the audited hook NUMBER (never a random frame,
never an invented xG). Optional 0.8s end card uses an i18n comment-bait line.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from . import platforms, safe_zones, theme
from .data import write_json

MASTER_W, MASTER_H = 1080, 1920
INK = "#000000"


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def probe_size(path: Path) -> tuple[int, int] | None:
    probe = _ffprobe()
    if not probe or not Path(path).exists():
        return None
    result = subprocess.run(
        [
            probe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    line = (result.stdout or "").strip().split(",")
    if len(line) != 2:
        return None
    try:
        return int(line[0]), int(line[1])
    except ValueError:
        return None


def probe_duration(path: Path) -> float | None:
    probe = _ffprobe()
    if not probe or not Path(path).exists():
        return None
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float((result.stdout or "").strip())
    except ValueError:
        return None


def probe_has_audio(path: Path) -> bool:
    probe = _ffprobe()
    if not probe or not Path(path).exists():
        return False
    result = subprocess.run(
        [probe, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool((result.stdout or "").strip())


# ---------------------------------------------------------------------------
# restack — portrait master, never letterbox
# ---------------------------------------------------------------------------

def composition_kind(src_w: int, src_h: int, dst_w: int, dst_h: int) -> str:
    src_a = src_w / max(1, src_h)
    dst_a = dst_w / max(1, dst_h)
    if abs(src_a - dst_a) < 0.03:
        return "fill_crop"
    if dst_a < src_a:
        return "landscape_to_portrait"
    if abs(dst_a - 1.0) < 0.03:
        return "portrait_to_square"
    return "portrait_to_landscape"


def is_letterbox_filter(filter_graph: str) -> bool:
    """True when the graph pads with bars instead of restacking content."""
    lowered = filter_graph.lower()
    if "force_original_aspect_ratio=decrease" in lowered and "pad=" in lowered:
        return True
    if "pad=" in lowered and "vstack" not in lowered and "hstack" not in lowered and "overlay" not in lowered:
        return True
    return False


def restack_filter(src_w: int, src_h: int, dst_w: int, dst_h: int) -> str:
    """ffmpeg ``-vf`` / filter_complex body. Fills the destination; no black bars."""
    kind = composition_kind(src_w, src_h, dst_w, dst_h)
    if kind == "fill_crop":
        return (
            f"scale={dst_w}:{dst_h}:force_original_aspect_ratio=increase,"
            f"crop={dst_w}:{dst_h},setsar=1,format=yuv420p"
        )
    if kind == "landscape_to_portrait":
        return _landscape_to_portrait(src_w, src_h, dst_w, dst_h)
    if kind == "portrait_to_square":
        return _portrait_to_square(src_w, src_h, dst_w, dst_h)
    return _portrait_to_landscape(src_w, src_h, dst_w, dst_h)


def _even(value: int) -> int:
    return value - (value % 2)


def _landscape_to_portrait(sw: int, sh: int, dw: int, dh: int) -> str:
    """Stack title / hero / caption bands from a 16:9 recap onto 9:16."""
    top_src = _even(max(2, int(sh * 0.28)))
    bot_src = _even(max(2, int(sh * 0.22)))
    mid_src = _even(max(2, sh - top_src - bot_src))
    top_h = _even(max(2, int(round(top_src * dw / sw))))
    bot_h = _even(max(2, int(round(bot_src * dw / sw))))
    mid_h = _even(max(2, dh - top_h - bot_h))
    top_off = 0
    mid_off = top_src
    bot_off = top_src + mid_src
    return (
        f"split=3[t][m][b];"
        f"[t]crop={sw}:{top_src}:0:{top_off},scale={dw}:{top_h}[top];"
        f"[m]crop={sw}:{mid_src}:0:{mid_off},scale={dw}:{mid_h}[mid];"
        f"[b]crop={sw}:{bot_src}:0:{bot_off},scale={dw}:{bot_h}[bot];"
        f"[top][mid][bot]vstack=inputs=3,setsar=1,format=yuv420p"
    )


def _portrait_to_landscape(sw: int, sh: int, dw: int, dh: int) -> str:
    """Hook left, hero/graph right — restack, not pillarbox."""
    zones = safe_zones.for_canvas(sw, sh)
    hook = zones.hook_band
    hero = zones.hero_band
    left_h = _even(max(2, hook.h + int(hero.h * 0.45)))
    left_y = hook.y
    right_y = _even(max(0, hero.y))
    right_h = _even(max(2, min(sh - right_y, zones.content_bottom - right_y)))
    left_w = _even(dw // 2)
    right_w = _even(dw - left_w)
    return (
        f"split=2[l][r];"
        f"[l]crop={sw}:{left_h}:0:{left_y},scale={left_w}:{dh}[left];"
        f"[r]crop={sw}:{right_h}:0:{right_y},scale={right_w}:{dh}[right];"
        f"[left][right]hstack=inputs=2,setsar=1,format=yuv420p"
    )


def _portrait_to_square(sw: int, sh: int, dw: int, dh: int) -> str:
    """Smart crop on the hook/hero band, then restack a caption strip underneath."""
    zones = safe_zones.for_canvas(sw, sh)
    cap_h = _even(max(2, int(dh * 0.22)))
    main_h = _even(dh - cap_h)
    crop_y = zones.hook_band.y
    crop_h = _even(min(sw, zones.content_bottom - crop_y))
    cap_y = _even(max(crop_y, zones.middle_third.y))
    cap_src_h = _even(min(zones.middle_third.h, sh - cap_y))
    return (
        f"split=2[m][c];"
        f"[m]crop={sw}:{crop_h}:0:{crop_y},scale={dw}:{main_h}[main];"
        f"[c]crop={sw}:{cap_src_h}:0:{cap_y},scale={dw}:{cap_h}[cap];"
        f"[main][cap]vstack=inputs=2,setsar=1,format=yuv420p"
    )


def restack_method_description() -> str:
    return (
        "9:16 is produced as the portrait master (matplotlib 1080x1920, fill-crop "
        "if the source already matches). Landscape sources are restacked into "
        "title/hero/caption bands with vstack — not pad/letterbox. 16:9 and 1:1 "
        "are hstack/vstack restacks of those same bands from the portrait master."
    )


# ---------------------------------------------------------------------------
# hook peak / audited hero number
# ---------------------------------------------------------------------------

def _vendor_xg_ok(audit: dict[str, Any] | None) -> bool:
    if not audit:
        return False
    health = audit.get("data_health") or {}
    if not health.get("has_vendor_xg"):
        return False
    blocked = list(health.get("blocked_claims") or []) + list(health.get("unsupported_claims") or [])
    blocked_l = {str(item).lower() for item in blocked}
    return "xg" not in blocked_l and "vendor_xg" not in blocked_l


def _is_xg_label(label: Any) -> bool:
    return "xg" in str(label or "").lower()


def hook_peak_seconds(scenes: list[dict[str, Any]], fps: int = 24) -> float:
    """Timestamp of the NUMBER slam, not a random frame."""
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz == "hook_claim" or scene.get("hero_number") is not None:
            start = float(scene.get("visible_start") or scene.get("clip_start") or 0.0)
            length = float(scene.get("on_screen") or scene.get("seconds") or scene.get("clip") or 0.8)
            # Number is on screen from the first frames; land past the 2-frame colour slam.
            return round(start + min(0.35, max(2 / max(1, fps), length * 0.45)), 3)
    for scene in scenes:
        if str(scene.get("visualization") or "") == "hook_punch":
            return round(float(scene.get("visible_start") or 0.0) + 0.12, 3)
    return 0.4


def pick_cover_stat(
    audit: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    *,
    spoiler: str = "show",
) -> dict[str, Any]:
    """Giant cover number. Only audited stats. Never invent xG."""
    audit = audit or {}
    plan = plan or {}
    match = audit.get("match") or plan.get("match") or {}
    home = str(match.get("home") or "HOME")
    away = str(match.get("away") or "AWAY")
    score = str(match.get("score_display") or "")
    if not score and isinstance(match.get("score"), dict):
        raw = match["score"]
        score = str(raw.get("display") or f"{raw.get('home', '')} : {raw.get('away', '')}").strip()
    if not score:
        score = str(match.get("score") or "")

    def accept(number: Any, label: str, source: str) -> dict[str, Any] | None:
        if number is None or str(number) == "":
            return None
        if _is_xg_label(label) and not _vendor_xg_ok(audit):
            return None
        if spoiler == "hide" and platforms.looks_like_score(number):
            return None
        return {
            "number": number,
            "label": str(label or "").upper(),
            "source": source,
            "home": home,
            "away": away,
            "score": score,
        }

    scenes = list(plan.get("scenes") or [])
    for scene in scenes:
        if str(scene.get("visualization") or "") != "hook_claim":
            continue
        hit = accept(scene.get("hero_number"), str(scene.get("hero_label") or ""), "hook_claim")
        if hit:
            return hit
        split = scene.get("split") or {}
        if split.get("home") is not None:
            hit = accept(split.get("home"), str(split.get("label") or "SHOTS"), "hook_split")
            if hit:
                hit["away_number"] = split.get("away")
                return hit

    viral = plan.get("viral_audit") or {}
    if viral.get("punch") and spoiler == "hide":
        # Punch lines are copy, not a number. Keep looking for a stat.
        pass

    stats = audit.get("team_stats") or {}
    home_stats = stats.get(home) or {}
    away_stats = stats.get(away) or {}

    def pair(key: str) -> tuple[Any, Any]:
        return home_stats.get(key), away_stats.get(key)

    shots_h, shots_a = pair("shots")
    if shots_h is not None and shots_a is not None:
        leader = shots_h if shots_h >= shots_a else shots_a
        hit = accept(int(leader), "SHOTS", "team_stats.shots")
        if hit:
            return hit
    saves_h, saves_a = pair("saves")
    if saves_h or saves_a:
        leader = max(int(saves_h or 0), int(saves_a or 0))
        hit = accept(leader, "SAVES", "team_stats.saves")
        if hit:
            return hit

    if spoiler == "show" and score:
        return {
            "number": score.replace(" ", ""),
            "label": "FULL TIME",
            "source": "match.score_display",
            "home": home,
            "away": away,
            "score": score,
        }
    # Curiosity fallback: total shots, still audited.
    total = int(shots_h or 0) + int(shots_a or 0)
    return {
        "number": total,
        "label": "SHOTS",
        "source": "team_stats.shots_total",
        "home": home,
        "away": away,
        "score": score,
    }


def _team_colors(audit: dict[str, Any] | None, plan: dict[str, Any] | None) -> tuple[str, str]:
    plan = plan or {}
    gen = (plan.get("generation") or {}).get("colors") or {}
    if gen.get("home") and gen.get("away"):
        return str(gen["home"]), str(gen["away"])
    try:
        override = theme.get_team_colors()
        if override[0] and override[1]:
            return override[0], override[1]
    except Exception:
        pass
    match = (audit or {}).get("match") or plan.get("match") or {}
    design = theme.match_design(str(match.get("home") or "Home"), str(match.get("away") or "Away"))
    home = design["home"].get("fill") or design["home"]["primary"]
    away = design["away"].get("fill") or design["away"]["primary"]
    return str(home), str(away)


def _stroke(width: float = 7.0) -> list[Any]:
    return [pe.withStroke(linewidth=width, foreground="#050608", alpha=0.92)]


def render_thumbnail(
    dest: Path,
    *,
    width: int,
    height: int,
    cover: dict[str, Any],
    home_color: str,
    away_color: str,
    spoiler: str = "show",
) -> Path:
    """Poster next to the mp4: giant audited number + two team colours."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dpi = 120
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=INK)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 0.5, 1, transform=fig.transFigure, color=home_color, zorder=1))
    ax.add_patch(Rectangle((0.5, 0), 0.5, 1, transform=fig.transFigure, color=away_color, zorder=1))
    ink_home = theme.ink_on(home_color)
    ink_away = theme.ink_on(away_color)
    # Centre panel so the number reads on any shirt colour.
    ax.add_patch(Rectangle(
        (0.06, 0.22), 0.88, 0.56, transform=fig.transFigure,
        color="#07090c", alpha=0.72, zorder=2,
    ))
    number = str(cover.get("number") if spoiler == "show" or not platforms.looks_like_score(cover.get("number")) else cover.get("number"))
    if spoiler == "hide" and platforms.looks_like_score(number):
        number = str(cover.get("number") or "")
        # pick_cover_stat already avoided the score; keep the robbery number.
    label = str(cover.get("label") or "")
    home = str(cover.get("home") or "")
    away = str(cover.get("away") or "")
    fig.text(
        0.5, 0.58, number,
        ha="center", va="center", fontsize=min(210, int(height * 0.13)),
        fontweight="bold", color="#f5f8f3", family=theme.DISPLAY_FONT,
        zorder=5, path_effects=_stroke(14),
    )
    if label:
        fig.text(
            0.5, 0.36, label,
            ha="center", va="center", fontsize=min(36, int(height * 0.028)),
            fontweight="bold", color="#f5f8f3", family=theme.DISPLAY_FONT,
            zorder=5, path_effects=_stroke(5),
        )
    fig.text(
        0.25, 0.14, home.upper(),
        ha="center", va="center", fontsize=min(22, int(height * 0.018)),
        fontweight="bold", color=ink_home, family=theme.DISPLAY_FONT, zorder=5,
        path_effects=_stroke(4),
    )
    fig.text(
        0.75, 0.14, away.upper(),
        ha="center", va="center", fontsize=min(22, int(height * 0.018)),
        fontweight="bold", color=ink_away, family=theme.DISPLAY_FONT, zorder=5,
        path_effects=_stroke(4),
    )
    fig.savefig(dest, dpi=dpi, facecolor=fig.get_facecolor(), pad_inches=0)
    plt.close(fig)
    return dest


def render_end_card(
    dest: Path,
    *,
    width: int,
    height: int,
    bait: str,
    home_color: str,
    away_color: str,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dpi = 120
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=INK)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 0.5, 1, transform=fig.transFigure, color=home_color, zorder=1))
    ax.add_patch(Rectangle((0.5, 0), 0.5, 1, transform=fig.transFigure, color=away_color, zorder=1))
    ax.add_patch(Rectangle(
        (0.07, 0.32), 0.86, 0.36, transform=fig.transFigure,
        color="#07090c", alpha=0.78, zorder=2,
    ))
    fig.text(
        0.5, 0.52, bait,
        ha="center", va="center", fontsize=min(42, int(height * 0.032)),
        fontweight="bold", color="#f5f8f3", family=theme.DISPLAY_FONT,
        zorder=5, wrap=True, path_effects=_stroke(6),
    )
    fig.savefig(dest, dpi=dpi, facecolor=fig.get_facecolor(), pad_inches=0)
    plt.close(fig)
    return dest


def thumbnail_array(
    *,
    width: int,
    height: int,
    cover: dict[str, Any],
    home_color: str,
    away_color: str,
    spoiler: str = "show",
) -> np.ndarray:
    """In-memory RGBA poster for dry-run dimension checks."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cover.png"
        render_thumbnail(
            path, width=width, height=height, cover=cover,
            home_color=home_color, away_color=away_color, spoiler=spoiler,
        )
        image = plt.imread(path)
    return np.asarray(image)


# ---------------------------------------------------------------------------
# encode
# ---------------------------------------------------------------------------

def _run_ffmpeg(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def _encode_still_clip(
    image: Path,
    dest: Path,
    *,
    seconds: float,
    fps: int,
    has_audio_ref: Path | None = None,
) -> Path | None:
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image),
        "-t", f"{seconds:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-an",
        str(dest),
    ]
    result = _run_ffmpeg(command)
    if result.returncode != 0 or not dest.exists():
        return None
    return dest


def _append_end_card(
    video: Path,
    card: Path,
    dest: Path,
    *,
    fps: int,
) -> Path | None:
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(card),
    ]
    if probe_has_audio(video):
        command += [
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v];[0:a]apad=pad_dur=2[a]",
            "-map", "[v]", "-map", "[a]", "-shortest",
        ]
    else:
        command += [
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-an",
        ]
    command += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
        str(dest),
    ]
    result = _run_ffmpeg(command)
    if result.returncode != 0 or not dest.exists():
        return None
    return dest


def _loop_tail(video: Path, dest: Path, *, seconds: float, mode: str, fps: int) -> Path | None:
    ffmpeg = _ffmpeg()
    if not ffmpeg or seconds <= 0:
        return None
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video)]
    if mode == "snapback":
        duration = probe_duration(video) or 0.0
        start = max(0.0, duration - seconds)
        graph = (
            f"[0:v]split=2[main][tail];"
            f"[tail]trim=start={start:.3f},setpts=PTS-STARTPTS,reverse[rev];"
            f"[main][rev]concat=n=2:v=1:a=0[v]"
        )
        if probe_has_audio(video):
            command += [
                "-filter_complex", graph + ";[0:a]apad=pad_dur=2[a]",
                "-map", "[v]", "-map", "[a]", "-shortest",
            ]
        else:
            command += ["-filter_complex", graph, "-map", "[v]", "-an"]
    else:
        command += ["-vf", f"tpad=stop_mode=clone:stop_duration={seconds:.3f}"]
        if probe_has_audio(video):
            command += ["-af", f"apad=pad_dur={seconds:.3f}", "-shortest"]
        else:
            command += ["-an"]
    command += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
        str(dest),
    ]
    result = _run_ffmpeg(command)
    if result.returncode != 0 or not dest.exists():
        if mode == "snapback":
            return _loop_tail(video, dest, seconds=seconds, mode="freeze", fps=fps)
        return None
    return dest


def _burn_captions(video: Path, dest: Path, srt: Path, profile: platforms.PlatformProfile, fps: int) -> Path | None:
    ffmpeg = _ffmpeg()
    if not ffmpeg or not srt.exists() or srt.stat().st_size <= 0:
        return None
    zones = profile.safe()
    filt = safe_zones.ffmpeg_subtitles_filter(str(srt.resolve()), zones)
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-vf", filt,
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
    ]
    if probe_has_audio(video):
        command += ["-c:a", "copy"]
    else:
        command += ["-an"]
    command.append(str(dest))
    result = _run_ffmpeg(command)
    if result.returncode != 0 or not dest.exists():
        return None
    return dest


def export_one(
    master: Path,
    profile: platforms.PlatformProfile,
    dest_dir: Path,
    *,
    fps: int = 24,
    spoiler: str = "show",
    end_card: bool = True,
    language: str = "en",
    audit: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    srt_path: Path | None = None,
    cover: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export one platform file + sibling poster jpg. Does not rewrite the master."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()
    mp4 = dest_dir / (profile.filename or f"{profile.id}.mp4")
    jpg = mp4.with_suffix(".jpg")
    home_color, away_color = _team_colors(audit, plan)
    cover = cover or pick_cover_stat(audit, plan, spoiler=spoiler)
    render_thumbnail(
        jpg, width=profile.width, height=profile.height, cover=cover,
        home_color=home_color, away_color=away_color, spoiler=spoiler,
    )
    info: dict[str, Any] = {
        "id": profile.id,
        "mp4": str(mp4),
        "jpg": str(jpg),
        "width": profile.width,
        "height": profile.height,
        "method": composition_kind(
            *(probe_size(master) or (MASTER_W, MASTER_H)),
            profile.width, profile.height,
        ),
        "ok": False,
    }
    if not ffmpeg:
        info["error"] = "ffmpeg is not on PATH"
        return info
    if not Path(master).exists():
        info["error"] = f"master {master} is missing"
        return info

    src_w, src_h = probe_size(master) or (MASTER_W, MASTER_H)
    filt = restack_filter(src_w, src_h, profile.width, profile.height)
    if is_letterbox_filter(filt):
        info["error"] = "refusing letterbox filter"
        info["filter"] = filt
        return info

    work = dest_dir / f"_{profile.id}_work.mp4"
    if "split=" in filt:
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(master),
            "-filter_complex", f"{filt}[vout]",
            "-map", "[vout]",
        ]
    else:
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(master), "-vf", filt, "-map", "0:v:0",
        ]
    if probe_has_audio(master):
        command += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    else:
        command += ["-an"]
    command += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
        str(work),
    ]
    result = _run_ffmpeg(command)
    current = work if result.returncode == 0 and work.exists() else None
    if current is None:
        info["error"] = (result.stderr or "ffmpeg restack failed")[:400]
        info["filter"] = filt
        return info

    # Re-burn captions on restacked canvases (the 9:16 master already has them
    # in the middle third). Skip when the filter was identity fill-crop so we
    # do not double-burn.
    srt = Path(srt_path) if srt_path else None
    if (
        profile.burn_captions and srt and srt.exists()
        and composition_kind(src_w, src_h, profile.width, profile.height) != "fill_crop"
    ):
        captioned = dest_dir / f"_{profile.id}_cap.mp4"
        burned = _burn_captions(current, captioned, srt, profile, fps)
        if burned:
            current = burned

    if profile.loop_tail_seconds > 0:
        looped = dest_dir / f"_{profile.id}_loop.mp4"
        tailed = _loop_tail(
            current, looped, seconds=profile.loop_tail_seconds,
            mode=profile.loop_mode, fps=fps,
        )
        if tailed:
            current = tailed

    if end_card:
        bait_key, bait = platforms.comment_bait(
            language=language,
            hook_kind=str(((plan or {}).get("viral_audit") or {}).get("hook_kind") or ""),
            player=str((((audit or {}).get("player_leaders") or {}).get("spike") or {}).get("player") or ""),
        )
        card_png = dest_dir / f"_{profile.id}_end.png"
        render_end_card(
            card_png, width=profile.width, height=profile.height,
            bait=bait, home_color=home_color, away_color=away_color,
        )
        card_mp4 = dest_dir / f"_{profile.id}_end.mp4"
        still = _encode_still_clip(card_png, card_mp4, seconds=profile.end_card_seconds, fps=fps)
        if still:
            ended = dest_dir / f"_{profile.id}_ended.mp4"
            appended = _append_end_card(current, still, ended, fps=fps)
            if appended:
                current = appended
                info["end_card"] = bait
                info["end_card_key"] = bait_key

    shutil.copyfile(current, mp4)
    info["ok"] = mp4.exists()
    info["size"] = probe_size(mp4)
    info["duration"] = probe_duration(mp4)
    info["filter"] = filt
    info["letterbox"] = is_letterbox_filter(filt)
    if profile.chapters:
        chapters = platforms.chapters_from_scenes(list((plan or {}).get("scenes") or []))
        txt = dest_dir / f"{profile.id}.chapters.txt"
        txt.write_text(platforms.render_youtube_chapters(chapters), encoding="utf-8")
        info["chapters"] = str(txt)
    # Leave intermediates for debugging only if encode failed; otherwise tidy.
    for leftover in dest_dir.glob(f"_{profile.id}_*"):
        try:
            leftover.unlink()
        except OSError:
            pass
    return info


def export_pack(
    out_dir: Path,
    master: Path | None,
    *,
    platforms_flag: str = "tiktok,shorts",
    aspect: str = "all",
    spoiler: str = "show",
    end_card: bool = True,
    language: str = "en",
    audit: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    srt_path: Path | None = None,
    fps: int = 24,
) -> dict[str, Any]:
    """Write ``pack/<platform>.mp4`` + ``.jpg`` beside the recap master."""
    out_dir = Path(out_dir)
    pack_dir = out_dir / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    profiles = platforms.resolve_exports(platforms_flag, aspect)
    cover = pick_cover_stat(audit, plan, spoiler=spoiler)
    home_color, away_color = _team_colors(audit, plan)
    # Canonical cover at hook peak, next to the master as well as in pack/.
    cover_jpg = out_dir / "cover.jpg"
    render_thumbnail(
        cover_jpg, width=MASTER_W, height=MASTER_H, cover=cover,
        home_color=home_color, away_color=away_color, spoiler=spoiler,
    )
    exports = []
    for profile in profiles:
        if master and Path(master).exists():
            row = export_one(
                Path(master), profile, pack_dir, fps=fps, spoiler=spoiler,
                end_card=end_card, language=language, audit=audit, plan=plan,
                srt_path=srt_path or out_dir / "subtitles.srt", cover=cover,
            )
        else:
            jpg = pack_dir / Path(profile.filename).with_suffix(".jpg")
            render_thumbnail(
                jpg, width=profile.width, height=profile.height, cover=cover,
                home_color=home_color, away_color=away_color, spoiler=spoiler,
            )
            row = {
                "id": profile.id, "mp4": None, "jpg": str(jpg),
                "ok": False, "error": "no master mp4; poster only",
            }
        exports.append(row)
    manifest = {
        "platforms": [p.id for p in profiles],
        "aspect": aspect,
        "spoiler": spoiler,
        "end_card": end_card,
        "language": language,
        "cover": {"path": str(cover_jpg), **{k: cover.get(k) for k in ("number", "label", "source")}},
        "portrait_method": restack_method_description(),
        "exports": exports,
    }
    write_json(pack_dir / "manifest.json", manifest)
    return manifest


def dry_run(
    *,
    platforms_flag: str = "tiktok,shorts",
    aspect: str = "all",
    spoiler: str = "hide",
    language: str = "en",
    end_card: bool = True,
) -> dict[str, Any]:
    """Validate canvases, safe zones, restack filters and a poster — no match."""
    profile_report = platforms.dry_validate_profiles(platforms_flag, aspect)
    fake_audit = {
        "match": {"home": "Scotland", "away": "Morocco", "score_display": "0 : 1"},
        "data_health": {"has_vendor_xg": False, "blocked_claims": ["xG"], "unsupported_claims": ["vendor_xg"]},
        "team_stats": {
            "Scotland": {"shots": 6, "saves": 5, "goals": 0},
            "Morocco": {"shots": 12, "saves": 3, "goals": 1},
        },
        "player_leaders": {},
    }
    fake_plan = {
        "match": fake_audit["match"],
        "scenes": [
            {
                "visualization": "hook_claim", "hero_number": 12, "hero_label": "SHOTS",
                "title": "MOROCCO HAD 12 SHOTS.", "seconds": 0.85, "visible_start": 0.4,
                "on_screen": 0.85,
            },
            {
                "visualization": "shot_map", "title": "SHOT MAP",
                "narration": "Twelve shots. One finish.", "seconds": 5.0,
                "visible_start": 1.3, "on_screen": 5.0,
            },
        ],
        "viral_audit": {"hook_kind": "volume_upset", "punch": "THEY STILL LOST."},
    }
    cover = pick_cover_stat(fake_audit, fake_plan, spoiler=spoiler)
    if _is_xg_label(cover.get("label")) and not _vendor_xg_ok(fake_audit):
        xg_ok = False
    else:
        xg_ok = True
    posters = []
    for profile in platforms.resolve_exports(platforms_flag, aspect):
        arr = thumbnail_array(
            width=profile.width, height=profile.height, cover=cover,
            home_color="#005eb8", away_color="#c1272d", spoiler=spoiler,
        )
        posters.append({
            "id": profile.id,
            "shape": list(arr.shape),
            "expected": [profile.height, profile.width],
            "ok": abs(arr.shape[0] - profile.height) <= 2 and abs(arr.shape[1] - profile.width) <= 2,
        })
        filt = restack_filter(MASTER_W, MASTER_H, profile.width, profile.height)
        if is_letterbox_filter(filt):
            posters[-1]["ok"] = False
            posters[-1]["letterbox"] = True
        posters[-1]["filter_kind"] = composition_kind(MASTER_W, MASTER_H, profile.width, profile.height)
        posters[-1]["letterbox"] = is_letterbox_filter(filt)
    bait_key, bait = platforms.comment_bait(language=language, hook_kind="volume_upset")
    scenes = platforms.apply_hook_deadline([
        {"visualization": "live_clip", "seconds": 0.7, "hook": True, "title": "clip"},
        {"visualization": "hook_claim", "seconds": 0.85, "hero_number": 12, "title": "12 SHOTS"},
    ])
    readable = platforms.first_readable_at(scenes)
    return {
        "ok": profile_report["ok"] and all(p["ok"] for p in posters) and xg_ok and readable <= 0.5
              and (spoiler != "hide" or not platforms.looks_like_score(cover.get("number"))),
        "profiles": profile_report,
        "cover": cover,
        "cover_is_score": platforms.looks_like_score(cover.get("number")),
        "xg_invented": not xg_ok,
        "posters": posters,
        "end_card_key": bait_key,
        "end_card_text": bait,
        "hook_deadline_seconds": readable,
        "portrait_method": restack_method_description(),
        "end_card": end_card,
        "spoiler": spoiler,
        "language": language,
    }


def _maybe_ffmpeg_restack_smoke() -> dict[str, Any] | None:
    """One-frame lavfi restack. Skipped when ffmpeg is missing."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "portrait.png"
        filt = restack_filter(1920, 1080, 1080, 1920)
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=1920x1080:d=0.05",
            "-filter_complex" if "split=" in filt else "-vf",
        ]
        if "split=" in filt:
            command = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=1920x1080:d=0.05",
                "-filter_complex", f"{filt}[vout]", "-map", "[vout]",
                "-frames:v", "1", str(dest),
            ]
        else:
            command += [filt, "-frames:v", "1", str(dest)]
        result = _run_ffmpeg(command)
        size = None
        if dest.exists():
            image = plt.imread(dest)
            size = (int(image.shape[1]), int(image.shape[0]))
        return {
            "ok": result.returncode == 0 and size == (1080, 1920),
            "size": size,
            "letterbox_filter": is_letterbox_filter(filt),
            "method": composition_kind(1920, 1080, 1080, 1920),
            "error": (result.stderr or "")[:240] if result.returncode else "",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run or export a recap platform pack")
    platforms.add_cli_arguments(parser)
    parser.add_argument("--dry-run", action="store_true", help="Validate canvases without a match")
    parser.add_argument("--out-dir", default="", help="Existing video_output/<match> package")
    parser.add_argument("--master", default="", help="Path to match_video.mp4")
    parser.add_argument("--language", default="en")
    args = parser.parse_args(argv)
    if args.dry_run or not args.out_dir:
        report = dry_run(
            platforms_flag=args.platforms, aspect=args.aspect,
            spoiler=args.spoiler, language=args.language, end_card=args.end_card,
        )
        smoke = _maybe_ffmpeg_restack_smoke()
        if smoke is not None:
            report["ffmpeg_restack_smoke"] = smoke
            report["ok"] = bool(report["ok"] and smoke["ok"])
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    out_dir = Path(args.out_dir)
    master = Path(args.master) if args.master else out_dir / "match_video.mp4"
    audit = {}
    plan = {}
    audit_path = out_dir / "data_audit.json"
    plan_path = out_dir / "video_plan.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = export_pack(
        out_dir, master if master.exists() else None,
        platforms_flag=args.platforms, aspect=args.aspect, spoiler=args.spoiler,
        end_card=args.end_card, language=args.language, audit=audit, plan=plan,
    )
    print(json.dumps(manifest, indent=2))
    return 0 if any(row.get("ok") for row in manifest.get("exports") or []) else 1


if __name__ == "__main__":
    raise SystemExit(main())
