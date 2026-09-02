"""Caption, hook and clip-smash placement for social canvases.

TikTok / Reels / Shorts / Stories chrome eats the top ~180px and the bottom
~250px. Mute-first captions live in the middle third so they stay readable
when the soundtrack is off (~80% of watches) and never sit on a face or the
ball during a live-clip smash.

Figure coordinates in this module use matplotlib's origin (y=0 at the bottom).
Pixel coordinates use video origin (y=0 at the top).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Default 9:16 social chrome. Pixel values on a 1080x1920 master.
DEFAULT_TOP_PX = 180
DEFAULT_BOTTOM_PX = 250
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920

# Typical face/ball box on a vertical clip, as a fraction of the frame.
CLIP_SMASH_KEEP_OUT = (0.28, 0.30, 0.44, 0.40)  # x, y, w, h in pixel space (top-origin)


@dataclass(frozen=True)
class PixelBox:
    """Axis-aligned box in top-origin pixel space."""

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x2 and self.y <= y < self.y2

    def intersects(self, other: "PixelBox") -> bool:
        return not (
            self.x2 <= other.x or other.x2 <= self.x
            or self.y2 <= other.y or other.y2 <= self.y
        )

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class SafeZones:
    """Derived bands for one canvas size."""

    width: int
    height: int
    top_px: int
    bottom_px: int

    @property
    def content_top(self) -> int:
        return self.top_px

    @property
    def content_bottom(self) -> int:
        return self.height - self.bottom_px

    @property
    def content_height(self) -> int:
        return max(1, self.content_bottom - self.content_top)

    @property
    def content(self) -> PixelBox:
        return PixelBox(0, self.content_top, self.width, self.content_height)

    @property
    def ui_top(self) -> PixelBox:
        return PixelBox(0, 0, self.width, self.top_px)

    @property
    def ui_bottom(self) -> PixelBox:
        return PixelBox(0, self.content_bottom, self.width, self.bottom_px)

    @property
    def middle_third(self) -> PixelBox:
        """Middle third of the full frame (mute-first caption home)."""
        y = self.height // 3
        return PixelBox(0, y, self.width, self.height // 3)

    @property
    def content_middle_third(self) -> PixelBox:
        y = self.content_top + self.content_height // 3
        return PixelBox(0, y, self.width, self.content_height // 3)

    @property
    def hook_band(self) -> PixelBox:
        """First readable hook: just under the top UI, upper content third."""
        h = max(160, int(self.content_height * 0.28))
        return PixelBox(0, self.content_top, self.width, h)

    @property
    def hero_band(self) -> PixelBox:
        """Giant number / score slam lives here."""
        start = self.hook_band.y2
        end = self.content_top + int(self.content_height * 0.72)
        return PixelBox(0, start, self.width, max(120, end - start))

    @property
    def graph_band(self) -> PixelBox:
        start = self.hero_band.y2
        return PixelBox(0, start, self.width, max(80, self.content_bottom - start))

    @property
    def clip_keep_out(self) -> PixelBox:
        x, y, w, h = CLIP_SMASH_KEEP_OUT
        return PixelBox(
            int(self.width * x),
            int(self.height * y),
            int(self.width * w),
            int(self.height * h),
        )

    def fig_y(self, pixel_y_from_top: float) -> float:
        """Convert a top-origin pixel y to matplotlib figure y (0 at bottom)."""
        return 1.0 - (pixel_y_from_top / max(1, self.height))

    def fig_box(self, box: PixelBox) -> tuple[float, float, float, float]:
        """Return (x, y, w, h) in figure coordinates (origin bottom-left)."""
        x = box.x / self.width
        w = box.w / self.width
        h = box.h / self.height
        y = 1.0 - (box.y2 / self.height)
        return (x, y, w, h)

    def in_safe_content(self, x: float, y: float) -> bool:
        return self.content.contains(x, y)

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "top_px": self.top_px,
            "bottom_px": self.bottom_px,
            "content": self.content.as_dict(),
            "middle_third": self.middle_third.as_dict(),
            "hook_band": self.hook_band.as_dict(),
            "hero_band": self.hero_band.as_dict(),
            "caption_band": caption_box(self).as_dict(),
            "clip_caption_band": caption_box(self, clip_smash=True).as_dict(),
            "clip_keep_out": self.clip_keep_out.as_dict(),
        }


def for_canvas(
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    *,
    top_px: int | None = None,
    bottom_px: int | None = None,
) -> SafeZones:
    """Safe zones scaled from the 1080x1920 social defaults."""
    if top_px is None:
        top_px = max(0, round(DEFAULT_TOP_PX * height / DEFAULT_HEIGHT))
    if bottom_px is None:
        bottom_px = max(0, round(DEFAULT_BOTTOM_PX * height / DEFAULT_HEIGHT))
    if height <= width:
        # Landscape / square: chrome is smaller; keep a modest inset.
        top_px = min(top_px, max(48, height // 12))
        bottom_px = min(bottom_px, max(64, height // 10))
    top_px = min(top_px, max(0, height // 5))
    bottom_px = min(bottom_px, max(0, height // 4))
    if top_px + bottom_px >= height:
        top_px = max(0, height // 10)
        bottom_px = max(0, height // 8)
    return SafeZones(width=int(width), height=int(height), top_px=int(top_px), bottom_px=int(bottom_px))


def caption_box(zones: SafeZones, *, clip_smash: bool = False) -> PixelBox:
    """Where burned captions go.

    Mute-first: the middle third of the frame. Clip smash: the lower slice of
    that third, shifted off the centre keep-out so it does not cover a face or
    the ball.
    """
    mid = zones.middle_third
    if not clip_smash:
        # Centre of the middle third — graphics cards, not footage.
        h = max(90, mid.h // 3)
        y = mid.y + (mid.h - h) // 2
        inset = max(24, zones.width // 18)
        return PixelBox(inset, y, zones.width - 2 * inset, h)

    keep = zones.clip_keep_out
    h = max(80, mid.h // 4)
    y = mid.y2 - h - 8
    if keep.intersects(PixelBox(0, y, zones.width, h)):
        y = min(y, keep.y - h - 8)
        if y < mid.y:
            y = mid.y2 - h
    # Sit in the lower-left of the middle third, clear of the keep-out.
    x = max(24, zones.width // 16)
    w = min(int(zones.width * 0.62), keep.x - x - 12) if keep.x > x + 80 else int(zones.width * 0.55)
    w = max(120, w)
    box = PixelBox(x, max(mid.y, y), w, h)
    if box.intersects(keep):
        # Fall back to the right of the keep-out, still inside the middle third.
        x = keep.x2 + 12
        w = max(120, zones.width - x - 24)
        box = PixelBox(x, max(mid.y, mid.y2 - h), w, h)
    return box


def caption_ass_style(
    zones: SafeZones | None = None,
    *,
    clip_smash: bool = False,
    fontname: str = "Bai Jamjuree",
    fontsize: int | None = None,
) -> str:
    """libass ``force_style`` string. High-contrast white fill, black stroke."""
    zones = zones or for_canvas()
    box = caption_box(zones, clip_smash=clip_smash)
    # Alignment 5 = middle-centre. MarginV is an offset from the centre;
    # positive values move the cue *up* in some builds and *down* in others,
    # so we pin with Alignment 8 (top-centre) plus a pixel MarginV from the
    # top of the play-res. PlayRes is the frame itself.
    fontsize = fontsize or (15 if zones.height >= 1600 else 13 if zones.height >= 1000 else 11)
    margin_v = box.y
    margin_l = box.x
    margin_r = max(0, zones.width - box.x2)
    align = 7 if clip_smash else 8  # top-left vs top-centre
    return (
        f"Fontname={fontname},Fontsize={fontsize},Bold=1,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,"
        "BorderStyle=1,Outline=3,Shadow=0,Alignment="
        f"{align},MarginL={margin_l},MarginR={margin_r},MarginV={margin_v}"
    )


def default_ass_style() -> str:
    return caption_ass_style(for_canvas(DEFAULT_WIDTH, DEFAULT_HEIGHT))


def ffmpeg_subtitles_filter(srt_path: str, zones: SafeZones, *, clip_smash: bool = False) -> str:
    """``subtitles=...`` filter fragment with a safe-zone force_style."""
    escaped = (
        str(srt_path).replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    )
    style = caption_ass_style(zones, clip_smash=clip_smash).replace("'", r"\'")
    return f"subtitles='{escaped}':force_style='{style}'"


def validate_zones(zones: SafeZones) -> list[str]:
    """Return human-readable problems. Empty means the layout is publishable."""
    problems: list[str] = []
    if zones.width < 2 or zones.height < 2:
        return [f"canvas {zones.width}x{zones.height} is too small"]
    if zones.top_px < 0 or zones.bottom_px < 0:
        problems.append("safe-zone insets cannot be negative")
    if zones.content_height < 200:
        problems.append(f"content band is only {zones.content_height}px high")
    cap = caption_box(zones)
    if cap.intersects(zones.ui_top) or cap.intersects(zones.ui_bottom):
        problems.append("captions overlap platform UI chrome")
    if not zones.middle_third.intersects(cap):
        problems.append("captions are not in the middle third")
    hook = zones.hook_band
    if hook.intersects(zones.ui_top):
        problems.append("hook band overlaps the top UI")
    smash = caption_box(zones, clip_smash=True)
    if smash.intersects(zones.clip_keep_out):
        problems.append("clip-smash captions cover the face/ball keep-out")
    if smash.intersects(zones.ui_top) or smash.intersects(zones.ui_bottom):
        problems.append("clip-smash captions overlap platform UI chrome")
    return problems


def dry_validate(
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    *,
    top_px: int | None = None,
    bottom_px: int | None = None,
) -> dict[str, Any]:
    """Dimension / safe-zone report. No match data, no encode."""
    zones = for_canvas(width, height, top_px=top_px, bottom_px=bottom_px)
    problems = validate_zones(zones)
    cap = caption_box(zones)
    smash = caption_box(zones, clip_smash=True)
    return {
        "ok": not problems,
        "problems": problems,
        "zones": zones.as_dict(),
        "caption_in_middle_third": zones.middle_third.intersects(cap),
        "caption_in_content": zones.content.contains(cap.cx, cap.cy),
        "clip_smash_clears_keep_out": not smash.intersects(zones.clip_keep_out),
        "ass_style": caption_ass_style(zones),
        "clip_smash_ass_style": caption_ass_style(zones, clip_smash=True),
    }
