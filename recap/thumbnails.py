"""Thumbnail JPGs for recap posting packs.

Huge 3–5 word overlays. Prefer a hook still (render assets, ``--still``
preview, or a local clip via ffmpeg); otherwise paint a split-colour card
with matplotlib. Numbers and names are passed in — this module never
invents them.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt

from . import theme

VERTICAL = (1080, 1920)
YOUTUBE = (1280, 720)
SQUARE = (1080, 1080)

SHAPE_FOR_PLATFORM = {
    "tiktok": "vertical",
    "reels": "vertical",
    "shorts": "vertical",
    "youtube": "youtube",
    "youtube_long": "youtube",
    "instagram_feed": "square",
}

SHAPE_SIZE = {
    "vertical": VERTICAL,
    "youtube": YOUTUBE,
    "square": SQUARE,
}


def word_count(text: str) -> int:
    return len([part for part in (text or "").split() if part])


def clip_words(text: str, lo: int = 3, hi: int = 5) -> str:
    """Keep overlay copy in the 3–5 word scream band when the facts allow it."""
    words = [part for part in (text or "").split() if part]
    if len(words) > hi:
        words = words[:hi]
    return " ".join(words)


def find_hook_still(
    match_dir: str | Path,
    package_dir: str | Path | None = None,
) -> Path | None:
    """Best available still: hook preview, first hook frame, then a clip grab."""
    roots: list[Path] = []
    if package_dir:
        roots.append(Path(package_dir))
    roots.append(Path(match_dir))

    named_globs = (
        "stills/*hook_claim*",
        "stills/*hook_punch*",
        "stills/*live_clip*",
        "assets/*hook_claim*/frame_00001.png",
        "assets/*hook_claim*/frame_00003.png",
        "assets/*live_clip*/frame_00001.png",
        "thumbs/*.jpg",
        "thumbs/*.png",
    )
    for root in roots:
        if not root.exists():
            continue
        for pattern in named_globs:
            hits = sorted(root.glob(pattern))
            for hit in hits:
                if hit.is_file() and hit.stat().st_size > 1024:
                    return hit

    clip_ext = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    for root in roots:
        clips_dir = root / "clips"
        if not clips_dir.is_dir():
            continue
        clips = sorted(
            path for path in clips_dir.iterdir()
            if path.suffix.lower() in clip_ext and path.stat().st_size > 8_000
        )
        if clips:
            grabbed = _ffmpeg_still(clips[0], root / "_growth_hook_still.jpg")
            if grabbed:
                return grabbed
    return None


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _ffmpeg_still(src: Path, dest: Path, start: float = 0.8) -> Path | None:
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", str(src),
        "-frames:v", "1", "-q:v", "3",
        str(dest),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0 and dest.exists() and dest.stat().st_size > 1024:
        return dest
    # Short clips: try the first frame.
    if start > 0:
        return _ffmpeg_still(src, dest, start=0.0)
    return None


def _font_name(language: str) -> str:
    theme.apply_language_fonts(language)
    return theme.DISPLAY_FONT


def _stroke() -> list:
    return [pe.withStroke(linewidth=14, foreground="#05070a")]


def _split_overlay(text: str) -> list[str]:
    words = [part for part in text.split() if part]
    if len(words) <= 2:
        return [" ".join(words)] if words else [""]
    mid = (len(words) + 1) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


def _draw_overlay(ax, text: str, language: str, *, y: float = 0.38, size: float = 92) -> None:
    font = _font_name(language)
    lines = _split_overlay(text.upper())
    n = max(1, len(lines))
    for index, line in enumerate(lines):
        yy = y + (n - 1) * 0.07 - index * 0.14
        ax.text(
            0.5, yy, line,
            transform=ax.transAxes,
            fontsize=size if len(line) < 14 else size * 0.78,
            fontname=font,
            color="#f6f3ea",
            ha="center", va="center", fontweight="bold",
            linespacing=0.92,
            path_effects=_stroke(),
            zorder=5,
        )


def render_overlay_jpg(
    dest: Path,
    text: str,
    *,
    still: Path | None = None,
    size: tuple[int, int] = VERTICAL,
    language: str = "en",
    home: str = "",
    away: str = "",
    kicker: str = "",
) -> Path:
    """Write one JPG. Overlay *text* (already 3–5 words) on a still or a card."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()

    painted = False
    if still and Path(still).exists():
        try:
            image = mpimg.imread(str(still))
            ax.imshow(image, aspect="auto")
            ax.set_xlim(0, max(1, image.shape[1] - 1))
            ax.set_ylim(max(1, image.shape[0] - 1), 0)
            painted = True
        except Exception:
            painted = False

    if not painted:
        home_id = theme.team_identity(home or "Home")
        away_id = theme.team_identity(away or "Away")
        ax.add_patch(plt.Rectangle((0, 0), 0.5, 1, color=home_id["primary"], transform=ax.transAxes, zorder=0))
        ax.add_patch(plt.Rectangle((0.5, 0), 0.5, 1, color=away_id["primary"], transform=ax.transAxes, zorder=0))
        ax.add_patch(plt.Rectangle((0, 0), 1, 0.28, color="#05070a", transform=ax.transAxes, zorder=1, alpha=0.55))

    ax.add_patch(plt.Rectangle((0, 0), 1, 0.22, color="#05070a", transform=ax.transAxes, zorder=2, alpha=0.72))
    ax.add_patch(plt.Rectangle((0, 0.78), 1, 0.22, color="#05070a", transform=ax.transAxes, zorder=2, alpha=0.45))

    overlay_size = 96 if size[1] >= 1400 else (72 if size[0] >= 1200 else 64)
    _draw_overlay(ax, text, language, y=0.42, size=overlay_size)

    if kicker:
        ax.text(
            0.5, 0.12, kicker.upper(),
            transform=ax.transAxes,
            fontsize=22 if size[1] >= 1400 else 16,
            fontname=_font_name(language),
            color="#c8c2b4",
            ha="center", va="center",
            zorder=5,
        )

    fig.savefig(dest, dpi=dpi, facecolor="#05070a")
    plt.close(fig)
    return dest


def spec_for(
    text: str,
    *,
    variant: str,
    language: str,
    alt: str,
    path: str | None = None,
    source: str = "card",
) -> dict[str, Any]:
    words = clip_words(text, 3, 5)
    return {
        "text": words,
        "words": word_count(words),
        "overlay": "huge",
        "variant": variant,
        "language": language,
        "alt": alt,
        "path": path,
        "source": source,
    }


def write_thumbnails(
    dest_dir: str | Path,
    *,
    language: str,
    slam_text: str,
    curiosity_text: str,
    home: str,
    away: str,
    kicker: str,
    alt_slam: str,
    alt_curiosity: str,
    still: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Write vertical / youtube / square JPGs for slam + curiosity variants."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    source = "hook_still" if still else "matplotlib_card"
    out: dict[str, dict[str, Any]] = {}
    jobs = (
        ("slam", "vertical", slam_text, alt_slam),
        ("slam", "youtube", slam_text, alt_slam),
        ("slam", "square", slam_text, alt_slam),
        ("curiosity", "vertical", curiosity_text, alt_curiosity),
        ("curiosity", "youtube", curiosity_text, alt_curiosity),
        ("curiosity", "square", curiosity_text, alt_curiosity),
    )
    for variant, shape, text, alt in jobs:
        words = clip_words(text, 3, 5)
        path = dest_dir / f"{language}_{variant}_{shape}.jpg"
        render_overlay_jpg(
            path, words,
            still=still, size=SHAPE_SIZE[shape], language=language,
            home=home, away=away, kicker=kicker,
        )
        out[f"{variant}_{shape}"] = spec_for(
            words, variant=variant, language=language, alt=alt,
            path=str(path), source=source,
        )
    return out
