"""Find short match-action beats to put in front of the graphic package.

WhoScored event exports do not contain video. A recap can still open on a raw
clip when the editor (or an opt-in fetch) has put footage next to the scrape:

    output/<match>/clips/*.mp4
    output/<match>/highlights/*.mp4
    output/<match>/*.mp4

A file longer than about an hour is treated as a match tape and cut around
goal timestamps from the audit. Shorter files are treated as highlights and
sampled as 0.4–0.8s punches. Nothing is downloaded unless ``--fetch-clip``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .data import MatchBundle, safe_name
from .theme import FRAME_H, FRAME_W

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
FULL_MATCH_SECONDS = 70 * 60
HIGHLIGHT_SECONDS = 8.0
MICRO_CUT = 0.42
SINGLE_CUT = 0.70
MAX_BEATS = 2


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def duration_seconds(path: Path) -> float | None:
    probe = _ffprobe()
    if not probe or not path.exists():
        return None
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        value = float((result.stdout or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def discover_sources(match_dir: Path, extra: list[Path] | None = None) -> list[Path]:
    """Local video files that belong to this match, longest first."""
    root = Path(match_dir)
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not path.is_file():
            return
        if path.suffix.lower() not in VIDEO_EXTS:
            return
        seen.add(resolved)
        found.append(path)

    for path in extra or []:
        add(Path(path))
    for folder in (root / "clips", root / "highlights"):
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                add(path)
    if root.is_dir():
        for path in sorted(root.iterdir()):
            add(path)
    found.sort(key=lambda item: item.stat().st_size if item.exists() else 0, reverse=True)
    return found


def fetch_highlight(bundle: MatchBundle, dest_dir: Path) -> Path | None:
    """Opt-in YouTube search via yt-dlp. Off unless the caller asks."""
    ytdlp = shutil.which("yt-dlp") or shutil.which("yt_dlp")
    if not ytdlp:
        print("  [clips] yt-dlp is not on PATH; cannot fetch a highlight.")
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (bundle.kickoff or "")[:4]
    league = bundle.league or ""
    query = " ".join(part for part in (bundle.home, "vs", bundle.away, stamp, league, "highlights") if part)
    output = dest_dir / "highlight.%(ext)s"
    command = [
        ytdlp,
        "--no-playlist",
        "--no-warnings",
        "-f", "bv*[height<=720]+ba/b[height<=720]/b",
        "--max-downloads", "1",
        "-o", str(output),
        f"ytsearch1:{query}",
    ]
    print(f"  [clips] searching YouTube for {query!r}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode not in (0, 101):
        err = (result.stderr or result.stdout or "").strip()[:400]
        print(f"  [clips] fetch failed: {err}")
        return None
    matches = sorted(dest_dir.glob("highlight.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    video = next((path for path in matches if path.suffix.lower() in VIDEO_EXTS), None)
    if video:
        print(f"  [clips] saved {video.name}")
    return video


def _goal_offsets(audit: dict[str, Any], tape_seconds: float) -> list[float]:
    """Seek points on a full match tape, 1.2s before each goal."""
    offsets: list[float] = []
    for goal in audit.get("goal_timeline") or []:
        minute = int(goal.get("minute") or 0)
        second = int(goal.get("second") or 0)
        start = max(0.0, minute * 60 + second - 1.2)
        if start + SINGLE_CUT < tape_seconds - 1:
            offsets.append(start)
    return offsets[:MAX_BEATS] or [min(12.0, max(0.0, tape_seconds * 0.35))]


def _sample_offsets(tape_seconds: float, count: int) -> list[float]:
    if tape_seconds <= HIGHLIGHT_SECONDS:
        return [0.0]
    usable = max(0.4, tape_seconds - SINGLE_CUT)
    if count <= 1:
        return [min(usable * 0.35, usable)]
    return [usable * (index + 1) / (count + 1) for index in range(count)]


def plan_beats(
    bundle: MatchBundle,
    audit: dict[str, Any],
    sources: list[Path],
    *,
    max_beats: int = MAX_BEATS,
) -> list[dict[str, Any]]:
    """0.4–0.8s punches taken from whatever footage we actually have."""
    beats: list[dict[str, Any]] = []
    for source in sources:
        length = duration_seconds(source)
        if not length or length < 0.35:
            continue
        if length >= FULL_MATCH_SECONDS:
            offsets = _goal_offsets(audit, length)
            span = SINGLE_CUT
        elif length >= HIGHLIGHT_SECONDS:
            want = max_beats - len(beats)
            offsets = _sample_offsets(length, max(1, want))
            span = MICRO_CUT if want > 1 else SINGLE_CUT
        else:
            offsets = [0.0]
            span = min(SINGLE_CUT, length)
        for offset in offsets:
            duration = min(span, max(0.35, length - offset))
            if duration < 0.35:
                continue
            timeline = audit.get("goal_timeline") or []
            scorer = ""
            if length >= FULL_MATCH_SECONDS and len(timeline) > len(beats):
                scorer = str(timeline[len(beats)].get("scorer") or "")
            beats.append(
                {
                    "path": str(source),
                    "start": round(float(offset), 3),
                    "duration": round(float(duration), 3),
                    "label": scorer or f"{bundle.home} — {bundle.away}",
                }
            )
            if len(beats) >= max_beats:
                return beats
    return beats


def _scale_filter() -> str:
    return (
        f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=increase,"
        f"crop={FRAME_W}:{FRAME_H},setsar=1"
    )


def extract_frames(
    beat: dict[str, Any],
    dest_dir: Path,
    *,
    fps: int,
    frame_count: int,
    pattern: str = "frame_%05d.png",
) -> int:
    """Write ``frame_count`` 9:16 PNGs from *beat*. Returns how many exist."""
    ffmpeg = _ffmpeg()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not ffmpeg:
        return 0
    source = Path(beat["path"])
    if not source.exists():
        return 0
    target = dest_dir / pattern
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{float(beat.get('start') or 0):.3f}",
        "-i", str(source),
        "-t", f"{float(beat.get('duration') or 0.5):.3f}",
        "-vf", f"{_scale_filter()},fps={fps}",
        "-frames:v", str(max(2, frame_count)),
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    written = sorted(dest_dir.glob("frame_*.png"))
    if result.returncode != 0 or not written:
        return 0
    # ffmpeg fps rounding can undershoot; pad with the last frame.
    while len(written) < frame_count:
        clone = dest_dir / (pattern % (len(written) + 1))
        shutil.copyfile(written[-1], clone)
        written.append(clone)
    extra = written[frame_count:]
    for path in extra:
        path.unlink(missing_ok=True)
    return min(len(written), frame_count)


def extract_still(beat: dict[str, Any], dest: Path) -> bool:
    """One 9:16 still from the middle of the beat, for ``--still`` previews."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return False
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = float(beat.get("start") or 0) + max(0.05, float(beat.get("duration") or 0.5) * 0.4)
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(beat["path"]),
        "-frames:v", "1",
        "-vf", _scale_filter(),
        str(dest),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode == 0 and dest.exists()


def search_query(bundle: MatchBundle) -> str:
    return " ".join(
        part for part in (
            bundle.home, "vs", bundle.away,
            (bundle.kickoff or "")[:4],
            bundle.league or "",
            "highlights",
        ) if part
    )


def describe_beats(beats: list[dict[str, Any]]) -> str:
    if not beats:
        return "no local clip (drop mp4s in the match clips/ folder, or pass --fetch-clip)"
    bits = []
    for beat in beats:
        name = safe_name(Path(beat["path"]).stem)[:28]
        bits.append(f"{name} @{beat['start']:.1f}s ({beat['duration']:.2f}s)")
    return "; ".join(bits)
