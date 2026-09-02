"""Frame rendering and mp4 assembly.

Frame counts are the source of truth for duration. Each scene is rendered to a
whole number of frames, the scene's duration is snapped to that frame count,
and only then are the timeline and the subtitles computed. That is what keeps
the narration, the captions and the picture from drifting apart.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import clips as clip_mod
from . import scenes as scene_renderers
from . import timing
from . import audio as audio_mod
from .data import MatchBundle, safe_name
from .draw import HOLD_AT

DEFAULT_FPS = 24
FRAME_PATTERN = "frame_%05d.png"


def quantize_to_frames(scene_list: list[dict[str, Any]], fps: int) -> list[dict[str, Any]]:
    """Snap every scene to a whole number of frames."""
    quantized = []
    for index, scene in enumerate(scene_list):
        frames = max(2, int(round(float(scene["clip"]) * fps)))
        clip = frames / fps
        hard_out = index >= len(scene_list) - 1 or scene_list[index + 1].get("cut") == "hard"
        on_screen = clip if hard_out else max(0.2, clip - timing.TRANSITION)
        quantized.append(
            {
                **scene,
                "frames": frames,
                "clip": round(clip, 6),
                "on_screen": round(on_screen, 6),
            }
        )
    return quantized


def render_frames(
    bundle: MatchBundle,
    audit: dict[str, Any],
    scene_list: list[dict[str, Any]],
    assets_dir: Path,
    *,
    fps: int = DEFAULT_FPS,
    on_progress: Any = None,
) -> list[dict[str, Any]]:
    """Render every scene to its own numbered frame sequence."""
    assets_dir = Path(assets_dir)
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    total = sum(scene["frames"] for scene in scene_list)
    done = 0
    started = time.perf_counter()
    rendered = []

    for index, scene in enumerate(scene_list, 1):
        renderer = scene_renderers.renderer_for(scene["visualization"])
        scene_dir = assets_dir / f"{index:02d}_{safe_name(scene['visualization'])}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        frames = int(scene["frames"])
        if scene.get("visualization") == "live_clip":
            beat = {
                "path": scene.get("clip_path", ""),
                "start": scene.get("clip_offset", 0),
                "duration": scene.get("seconds") or scene.get("clip"),
            }
            written = clip_mod.extract_frames(
                beat, scene_dir, fps=fps, frame_count=frames, pattern=FRAME_PATTERN,
            )
            if written < frames:
                renderer = scene_renderers.renderer_for("hook_claim")
                for number in range(written, frames):
                    renderer(bundle, audit, scene, scene_dir / (FRAME_PATTERN % (number + 1)), 1.0)
            done += frames
            if on_progress and done % 12 == 0:
                on_progress(done, total, time.perf_counter() - started)
            rendered.append({**scene, "frame_dir": str(scene_dir)})
            continue

        # Everything is still after HOLD_AT, so that tail is rendered once and
        # copied. On a typical scene that is a quarter of the frames.
        hold_frame: Path | None = None
        full_motion = bool(scene.get("hook"))
        for number in range(frames):
            position = number / max(1, frames - 1)
            target = scene_dir / (FRAME_PATTERN % (number + 1))
            if hold_frame is not None and not full_motion and position >= HOLD_AT:
                shutil.copyfile(hold_frame, target)
            else:
                renderer(bundle, audit, scene, target, position)
                if position >= HOLD_AT:
                    hold_frame = target
            done += 1
            if on_progress and done % 12 == 0:
                on_progress(done, total, time.perf_counter() - started)

        rendered.append({**scene, "frame_dir": str(scene_dir)})

    if on_progress:
        on_progress(total, total, time.perf_counter() - started)
    return rendered


def render_stills(
    bundle: MatchBundle,
    audit: dict[str, Any],
    scene_list: list[dict[str, Any]],
    assets_dir: Path,
    *,
    positions: tuple[float, ...] = (1.0,),
) -> list[Path]:
    """One image per scene per position. Used for quick visual review."""
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for index, scene in enumerate(scene_list, 1):
        stem = safe_name(scene["visualization"])
        if scene.get("visualization") == "live_clip" and scene.get("clip_path"):
            beat = {
                "path": scene.get("clip_path", ""),
                "start": scene.get("clip_offset", 0),
                "duration": scene.get("seconds") or 0.6,
            }
            for position in positions:
                suffix = "" if position == 1.0 else f"_p{int(position * 100):03d}"
                path = assets_dir / f"{index:02d}_{stem}{suffix}.png"
                if not clip_mod.extract_still(beat, path):
                    scene_renderers.renderer_for("hook_claim")(bundle, audit, scene, path, position)
                written.append(path)
            continue
        renderer = scene_renderers.renderer_for(scene["visualization"])
        for position in positions:
            suffix = "" if position == 1.0 else f"_p{int(position * 100):03d}"
            path = assets_dir / f"{index:02d}_{safe_name(scene['visualization'])}{suffix}.png"
            renderer(bundle, audit, scene, path, position)
            written.append(path)
    return written


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _assembly_filter(scene_list: list[dict[str, Any]], fps: int) -> tuple[str, str]:
    """Hard-cuts on hook beats, xfade on the analysis package."""
    tb = f"1/{fps}"
    parts = [
        f"[{index}:v]fps={fps},settb={tb},setpts=N/{fps}/TB,format=yuv420p[v{index}]"
        for index in range(len(scene_list))
    ]
    if len(scene_list) == 1:
        return ";".join(parts), "v0"

    current = "v0"
    elapsed = float(scene_list[0]["clip"])
    for index in range(1, len(scene_list)):
        raw = f"r{index}"
        label = f"x{index}"
        incoming = scene_list[index]
        if incoming.get("cut") == "hard":
            parts.append(f"[{current}][v{index}]concat=n=2:v=1:a=0[{raw}]")
            elapsed += float(incoming["clip"])
        else:
            offset = max(0.0, elapsed - timing.TRANSITION)
            parts.append(
                f"[{current}][v{index}]xfade=transition=wiperight"
                f":duration={timing.TRANSITION:.3f}:offset={offset:.3f}[{raw}]"
            )
            elapsed += float(incoming["clip"]) - timing.TRANSITION
        parts.append(f"[{raw}]fps={fps},settb={tb},setpts=N/{fps}/TB[{label}]")
        current = label
    return ";".join(parts), current


def assemble(
    out_dir: Path,
    scene_list: list[dict[str, Any]],
    audio_path: Path | None,
    *,
    fps: int = DEFAULT_FPS,
    crossfade: bool = True,
    sfx: bool = True,
    burn_captions: bool = True,
    music_file: str | Path | None = None,
    srt_path: Path | None = None,
    loudnorm: str = "tiktok",
    skip_audio: bool = False,
) -> Path | None:
    """Encode the frame sequences into ``match_video.mp4``."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        print("  [video] ffmpeg is not on PATH; cannot assemble the mp4.")
        return None
    if not scene_list:
        return None

    output = Path(out_dir) / "match_video.mp4"
    command: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for scene in scene_list:
        command += ["-framerate", str(fps), "-i", str(Path(scene["frame_dir"]).resolve() / FRAME_PATTERN)]

    duration = timing.total_seconds(scene_list)
    mixed = None
    voice = Path(audio_path) if audio_path and Path(audio_path).exists() else None
    # --skip-audio must produce a valid silent mp4. Never run loudnorm on it.
    if not skip_audio and (sfx or music_file or voice):
        mixed = audio_mod.mix(
            Path(out_dir), scene_list, voice,
            sfx=sfx, music_file=music_file, ffmpeg=ffmpeg, duration=duration,
            loudnorm=loudnorm, skip_audio=False,
        )
    audio_input = None if skip_audio else (mixed or voice)
    has_audio = bool(audio_input)

    if has_audio:
        command += ["-i", str(Path(audio_input).resolve())]

    if crossfade and len(scene_list) > 1:
        graph, label = _assembly_filter(scene_list, fps)
    else:
        graph = ";".join(
            f"[{index}:v]fps={fps},settb=1/{fps},setpts=N/{fps}/TB,format=yuv420p[v{index}]"
            for index in range(len(scene_list))
        )
        graph += ";" + "".join(f"[v{i}]" for i in range(len(scene_list)))
        graph += f"concat=n={len(scene_list)}:v=1:a=0[vout]"
        label = "vout"

    mapped_video = f"[{label}]"
    srt = Path(srt_path) if srt_path else Path(out_dir) / "subtitles.srt"
    if burn_captions and srt.exists() and srt.stat().st_size > 0:
        from . import i18n, locale_meta

        escaped = _escape_subtitles_path(srt)
        lang = i18n.get_language()
        style = locale_meta.ffmpeg_subtitle_style(lang).replace("'", r"\'")
        extra = f"force_style='{style}'"
        fontfile = locale_meta.find_fontfile(lang)
        if fontfile:
            fontdir = Path(fontfile).parent.as_posix().replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
            extra = f"fontsdir={fontdir}:{extra}"
        graph += f";{mapped_video}subtitles={escaped}:{extra}[vcapt]"
        mapped_video = "[vcapt]"

    command += ["-filter_complex", graph, "-map", mapped_video]
    if has_audio:
        # apad + shortest extends a short SFX bed to the picture instead of
        # chopping the video when the mix was written to on-screen time.
        command += [
            "-map", f"{len(scene_list)}:a:0",
            "-c:a", "aac", "-b:a", "192k",
            "-af", "apad", "-shortest",
        ]
    else:
        command += ["-an"]
    command += [
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-r", str(fps),
        str(output),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [video] ffmpeg failed: {result.stderr.strip()[:500]}")
        retry = dict(
            fps=fps, sfx=sfx, music_file=music_file, srt_path=srt_path,
            loudnorm=loudnorm, skip_audio=skip_audio,
        )
        if burn_captions:
            print("  [video] retrying without burned captions")
            return assemble(
                out_dir, scene_list, audio_path, crossfade=crossfade,
                burn_captions=False, **retry,
            )
        if crossfade:
            print("  [video] retrying without cross-dissolves")
            return assemble(
                out_dir, scene_list, audio_path, crossfade=False,
                burn_captions=False, **retry,
            )
        return None
    return output if output.exists() else None


def _escape_subtitles_path(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    return f"'{raw}'"


def probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not Path(path).exists():
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None
