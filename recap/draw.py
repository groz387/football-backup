"""Drawing primitives and the layout grid every scene shares.

Two ideas keep the output consistent:

``Layout``
    Named horizontal bands in figure coordinates. Scenes place content into
    bands rather than picking y values by hand, which is what previously left
    a quarter of the frame empty on some cards and overlapping text on others.

``Timeline``
    Scenes receive a linear 0-1 position through their own duration and ask for
    element cues. All easing lives here, so the pipeline never pre-eases the
    value and animations no longer finish in the first third of a scene.
"""

from __future__ import annotations

import math
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

from . import theme
from .theme import (
    GOAL,
    HAIRLINE,
    INK,
    PITCH,
    PITCH_LINE,
    SURFACE,
    SURFACE_HI,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
)

theme.configure_matplotlib()

FIG_DPI = 120
# Default portrait box; ``figure_size()`` follows ``theme.FRAME_W/H``.
FIG_SIZE = (9.0, 16.0)

# Animation finishes here and the frame holds, so the viewer can read it.
HOLD_AT = 0.80
# Hero numerals stay on one integer for this many frames at 24fps.
HOLD_FRAMES = 8
COUNT_FPS = 24
COUNT_ANIM_SECONDS = 1.5
# Below this, ink is not drawn. Matplotlib path-effects keep a 0.55 stroke
# even when the glyph alpha is 0, which is the ghost-type flicker on frame 1.
VISIBLE_ALPHA = 0.08
EFFECT_ALPHA = 0.28


# ---------------------------------------------------------------------------
# easing and cues
# ---------------------------------------------------------------------------

def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def opacity(value: float) -> float:
    """Clamp a computed alpha into the range matplotlib accepts.

    Easing curves that overshoot (``ease_out_back``) and expressions that scale
    a cue up to make an element appear faster can both leave the 0-1 range, and
    matplotlib raises rather than clipping.
    """
    return clamp01(value)


def linear(t: float) -> float:
    return clamp01(t)


def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - clamp01(t)) ** 3


def ease_out_quint(t: float) -> float:
    return 1.0 - (1.0 - clamp01(t)) ** 5


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float) -> float:
    """Slight overshoot, for elements that should feel like they land."""
    t = clamp01(t)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


class Timeline:
    """Turns a scene-wide 0-1 position into per-element progress."""

    def __init__(self, progress: float) -> None:
        self.raw = clamp01(progress)
        # Compress the scene so every cue has completed by HOLD_AT.
        self.t = clamp01(self.raw / HOLD_AT)

    def cue(self, start: float, duration: float = 0.34, ease=ease_out_cubic) -> float:
        """Progress of an element that animates from *start* for *duration*."""
        if duration <= 0:
            return 1.0 if self.t >= start else 0.0
        return ease(clamp01((self.t - start) / duration))

    def stagger(self, index: int, count: int, start: float = 0.06, span: float = 0.52,
                duration: float = 0.30, ease=ease_out_cubic) -> float:
        """Cue for item *index* of *count* in a staggered sequence."""
        if count <= 1:
            return self.cue(start, duration, ease)
        step = span / (count - 1)
        return self.cue(start + index * step, duration, ease)

    def reveal_count(self, count: int, start: float = 0.08, span: float = 0.62) -> int:
        """How many of *count* items should be on screen yet."""
        if count <= 0:
            return 0
        local = clamp01((self.t - start) / max(1e-6, span))
        return max(0, min(count, int(math.ceil(ease_out_cubic(local) * count))))

    def count_to(self, value: float, start: float = 0.06, duration: float = 0.45) -> float:
        """A number ticking up to *value*, holding each glyph ~HOLD_FRAMES."""
        return hold_count(value, self.cue(start, duration, ease_out_quint))

    def wipe(self, start: float = 0.02, duration: float = 0.58) -> float:
        """0-1 ease-in-out reveal used by waves, tapes and split stamps."""
        return ease_in_out(clamp01((self.t - start) / max(1e-6, duration)))

    def stamp(self, start: float = 0.70, duration: float = 0.28) -> float:
        """Late insight cue that still finishes before HOLD_AT (t=1)."""
        return self.cue(start, duration, ease_in_out)

def hold_count(
    value: float,
    progress: float,
    *,
    hold_frames: int = HOLD_FRAMES,
    fps: int = COUNT_FPS,
) -> float:
    """Quantize a ticking number so each glyph stays readable (~8 frames).

    Integers hold on whole numbers. xG-style decimals hold on tenths so the
    readout does not chatter every frame, then snap at the end.
    """
    progress = clamp01(progress)
    target = float(value)
    mag = abs(target)
    if mag < 1e-9:
        return 0.0
    if progress >= 0.995:
        return target
    fractional = abs(target - round(target)) >= 0.05
    unit = 0.1 if fractional and mag < 20 else 1.0
    if mag < 0.5 and not fractional:
        return target * progress
    steps_max = max(1, int(math.ceil(mag / unit)))
    anim_frames = max(hold_frames, int(COUNT_ANIM_SECONDS * fps))
    n_steps = max(1, min(steps_max, anim_frames // max(1, hold_frames)))
    step_index = min(n_steps, int(math.floor(progress * n_steps + 1e-9)))
    shown = mag * step_index / n_steps
    if unit >= 1.0:
        shown = round(shown)
    else:
        shown = round(shown / unit) * unit
    return math.copysign(shown, target)


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------

class Layout:
    """Named bands in figure coordinates, top to bottom.

    ``stage`` is the region a visualization may draw into. Everything else is
    reserved chrome so that headers and footers never sit on top of the data.
    """

    MARGIN = 0.062
    CONTENT_W = 1.0 - 2 * MARGIN

    KICKER_Y = 0.938
    TITLE_TOP = 0.938
    SUBTITLE_GAP = 0.026

    STAGE_TOP = 0.830
    STAGE_BOTTOM = 0.072

    INSIGHT_Y = 0.128
    FOOTER_Y = 0.052

    @classmethod
    def stage_rect(cls, top: float | None = None, bottom: float | None = None) -> list[float]:
        """An ``add_axes`` rect covering the stage."""
        top = cls.STAGE_TOP if top is None else top
        bottom = cls.STAGE_BOTTOM if bottom is None else bottom
        return [cls.MARGIN, bottom, cls.CONTENT_W, top - bottom]

    @classmethod
    def fitted_rect(cls, aspect: float, top: float | None = None, bottom: float | None = None,
                    align: str = "center") -> list[float]:
        """Largest rect of a given width/height *aspect* that fits the stage.

        *aspect* is measured in output pixels, so a vertical pitch passes
        68/105 and gets a box with true proportions instead of a stretched one.
        """
        top = cls.STAGE_TOP if top is None else top
        bottom = cls.STAGE_BOTTOM if bottom is None else bottom
        avail_w_px = cls.CONTENT_W * theme.FRAME_W
        avail_h_px = (top - bottom) * theme.FRAME_H

        width_px = min(avail_w_px, avail_h_px * aspect)
        height_px = width_px / aspect

        width = width_px / theme.FRAME_W
        height = height_px / theme.FRAME_H
        x = cls.MARGIN + (cls.CONTENT_W - width) / 2
        if align == "top":
            y = top - height
        elif align == "bottom":
            y = bottom
        else:
            y = bottom + ((top - bottom) - height) / 2
        return [x, y, width, height]


# ---------------------------------------------------------------------------
# figure and background
# ---------------------------------------------------------------------------

def figure_size(dpi: float | None = None) -> tuple[float, float]:
    """Matplotlib figsize (inches) that matches the active frame size."""
    dpi = float(dpi or FIG_DPI)
    return (theme.FRAME_W / dpi, theme.FRAME_H / dpi)


def new_figure(
    design: dict[str, Any],
    figsize: tuple[float, float] | None = None,
    dpi: float | None = None,
) -> plt.Figure:
    dpi = float(dpi or FIG_DPI)
    figsize = figsize or figure_size(dpi)
    fig = plt.figure(figsize=figsize, dpi=dpi, facecolor=design["ink"])
    _paint_background(fig, design)
    return fig


def y_of(x_length: float) -> float:
    """Figure-y length that occupies the same number of pixels as *x_length*.

    Uses the live frame aspect so landscape 1920x1080 stays round, not oval.
    """
    return x_length * theme.ASPECT


@lru_cache(maxsize=8)
def _background_pixels(ink: str, home: str, away: str, width: int, height: int) -> np.ndarray:
    """The full-frame background as raw pixels.

    Drawn straight into the canvas buffer with ``figimage``, which skips both
    resampling and an extra axes. Stacking rectangles or resampling a small
    gradient both cost more per frame than the rest of a scene combined.
    """
    base = np.array(theme.hex_to_rgb(ink))
    top = np.array(theme.hex_to_rgb(home))
    bottom = np.array(theme.hex_to_rgb(away))

    # figimage rows run bottom-to-top, so fraction 0 is the bottom of the frame.
    fraction = np.linspace(0.0, 1.0, height)[:, None]
    tint = bottom * (1.0 - fraction) + top * fraction
    wash = 0.14 * (1.0 - np.abs(fraction - 0.5) * 0.55)
    colour = base * (1.0 - wash) + tint * wash

    # Vignette so the chrome bands always have a darker base to sit on.
    from_top = 1.0 - fraction
    darken = np.where(from_top < 0.17, 0.26 * (1.0 - from_top / 0.17), 0.0)
    darken = np.where(from_top > 0.76, 0.32 * ((from_top - 0.76) / 0.24), darken)
    colour = colour * (1.0 - darken)

    column = np.clip(colour * 255.0, 0, 255).astype(np.uint8)
    return np.repeat(column[:, None, :], width, axis=1)


def _paint_background(fig: plt.Figure, design: dict[str, Any]) -> None:
    fig.figimage(
        _background_pixels(
            design["ink"],
            design["home"]["primary"],
            design["away"]["primary"],
            int(theme.FRAME_W),
            int(theme.FRAME_H),
        ),
        xo=0, yo=0, zorder=0,
    )


def fig_rect(fig: plt.Figure, x: float, y: float, w: float, h: float, color: str,
             alpha: float = 1.0, zorder: int = 2) -> None:
    alpha = opacity(alpha)
    if alpha < 0.02:
        return
    fig.patches.append(
        Rectangle((x, y), w, h, transform=fig.transFigure, facecolor=color,
                  edgecolor="none", alpha=alpha, zorder=zorder)
    )


def fig_panel(fig: plt.Figure, x: float, y: float, w: float, h: float, *,
              color: str = SURFACE, alpha: float = 1.0, edge: str | None = HAIRLINE,
              radius: float = 0.014, zorder: int = 2, lw: float = 1.1) -> None:
    """A rounded surface covering exactly (x, y, w, h) in figure coordinates.

    ``mutation_aspect`` is set so the padding and the corner radius come out
    square in pixels rather than stretched by the 9:16 frame.
    """
    alpha = opacity(alpha)
    if alpha < 0.02:
        return
    pad_x = min(radius, w / 2 - 1e-4, 0.06)
    pad_y = y_of(pad_x)
    fig.patches.append(
        FancyBboxPatch(
            (x + pad_x, y + pad_y),
            max(1e-4, w - 2 * pad_x),
            max(1e-4, h - 2 * pad_y),
            boxstyle=f"round,pad={pad_x},rounding_size={pad_x}",
            transform=fig.transFigure, facecolor=color,
            edgecolor=edge or "none", linewidth=lw if edge else 0.0,
            alpha=alpha, zorder=zorder, mutation_aspect=theme.ASPECT,
        )
    )


def fig_ellipse(fig: plt.Figure, cx: float, cy: float, radius: float, **kwargs: Any) -> Ellipse:
    """A true circle in output pixels, placed in figure coordinates."""
    if "alpha" in kwargs:
        kwargs["alpha"] = opacity(kwargs["alpha"])
        if kwargs["alpha"] < 0.02:
            return None
    patch = Ellipse((cx, cy), radius * 2, y_of(radius * 2), transform=fig.transFigure, **kwargs)
    fig.patches.append(patch)
    return patch


def score_badge(
    fig: plt.Figure,
    cx: float,
    cy: float,
    label: str,
    *,
    edge: str,
    alpha: float = 1.0,
    max_height: float = 0.052,
) -> None:
    """Running score inside a true circle (or a pill if the score is wide).

    The old fixed 0.052×0.052 panel was taller than it was wide on a 9:16
    frame, so ``1-0`` overflowed the sides. Size is measured from the glyphs.
    """
    text = str(label or "")
    if not text or opacity(alpha) < VISIBLE_ALPHA:
        return
    size = min(16.0, max(11.0, max_height * 72.0 * (theme.FRAME_H / FIG_DPI) * 0.42))
    artist = fig.text(
        cx, cy, text,
        fontsize=size, fontweight="bold", family=theme.DISPLAY_FONT,
        ha="center", va="center", color=TEXT, alpha=opacity(alpha), zorder=14,
    )
    pad = 0.016
    width, height = _extent_fractions(fig, artist)
    # Bold caps measure short of their ink; leave extra air inside the stroke.
    width *= 1.08
    height *= 1.22
    need_w = width + 2 * pad
    need_h = height + 2 * y_of(pad)
    diameter = max(need_w, need_h / theme.ASPECT, 0.046)
    max_diameter = max(0.040, max_height / theme.ASPECT)
    if diameter > max_diameter + 1e-6:
        scale = max_diameter / diameter
        size = max(10.0, size * scale * 0.90)
        artist.set_fontsize(size)
        width, height = _extent_fractions(fig, artist)
        width *= 1.08
        height *= 1.22
        need_w = width + 2 * pad
        need_h = height + 2 * y_of(pad)
        diameter = min(max_diameter, max(need_w, need_h / theme.ASPECT, 0.038))

    if need_w <= diameter * 1.04:
        fig_ellipse(
            fig, cx, cy, diameter / 2,
            facecolor="#080b09", edgecolor=edge, linewidth=1.8,
            alpha=alpha, zorder=12,
        )
        return
    pill_w = max(need_w, diameter)
    pill_h = min(max_height, max(need_h, y_of(diameter * 0.92)))
    fig_panel(
        fig, cx - pill_w / 2, cy - pill_h / 2, pill_w, pill_h,
        color="#080b09", alpha=alpha, edge=edge, radius=pill_w,
        zorder=12, lw=1.8,
    )


def outline(alpha: float = 1.0) -> list[Any]:
    """Halo around type. Empty at low alpha so the stroke cannot ghost."""
    alpha = opacity(alpha)
    if alpha < EFFECT_ALPHA:
        return []
    return [pe.withStroke(linewidth=3.0, foreground="#040605", alpha=opacity(0.85 * alpha))]


def soft_shadow(alpha: float = 1.0) -> list[Any]:
    """Soft display-type shadow. Empty at low alpha so frame 1 is not a ghost."""
    alpha = opacity(alpha)
    if alpha < EFFECT_ALPHA:
        return []
    return [pe.withStroke(linewidth=5.0, foreground="#040605", alpha=opacity(0.55 * alpha))]


def fade_effects(effects: list[Any] | None, alpha: float) -> list[Any]:
    """Re-scale stroke alpha with the glyph. Drops the effect while ink is faint."""
    alpha = opacity(alpha)
    if not effects or alpha < EFFECT_ALPHA:
        return []
    faded: list[Any] = []
    for effect in effects:
        gc = getattr(effect, "_gc", None) or {}
        stroke_alpha = opacity(float(gc.get("alpha", 0.55)) * alpha)
        if stroke_alpha < 0.05:
            continue
        faded.append(
            pe.withStroke(
                linewidth=gc.get("linewidth", 3.0),
                foreground=gc.get("foreground", "#040605"),
                alpha=stroke_alpha,
            )
        )
    return faded


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

def _renderer(fig: plt.Figure) -> Any:
    canvas = fig.canvas
    if not hasattr(canvas, "get_renderer"):
        fig.canvas.draw()
    return canvas.get_renderer()


def _extent_fractions(fig: plt.Figure, artist: Any) -> tuple[float, float]:
    """Rendered (width, height) of an artist as fractions of the figure."""
    try:
        extent = artist.get_window_extent(_renderer(fig))
    except Exception:
        return 0.0, 0.0
    return (
        extent.width / (fig.get_figwidth() * fig.dpi),
        extent.height / (fig.get_figheight() * fig.dpi),
    )


# Mean glyph advance as a fraction of the point size. Used only to pick a
# starting wrap width; the result is then verified by measurement.
_DEFAULT_ADVANCE = 0.52
def _points_to_fig_x() -> float:
    return 1.0 / 72.0 / max(1e-6, theme.FRAME_W / FIG_DPI)


def _chars_per_line(size: float, max_width: float, family: str) -> int:
    char_width = size * _points_to_fig_x() * _DEFAULT_ADVANCE
    return max(4, int(max_width / max(1e-6, char_width)))


def fit_text(
    fig: plt.Figure,
    x: float,
    y: float,
    text: str,
    *,
    fontsize: float,
    max_width: float,
    max_lines: int = 2,
    min_fontsize: float = 9.0,
    ha: str = "left",
    va: str = "top",
    family: str | None = None,
    **kwargs: Any,
) -> tuple[Any, int]:
    """Draw *text* so that it fits *max_width* in at most *max_lines* lines.

    The font size is reduced until the measured width fits. If it still will
    not fit at ``min_fontsize``, one extra wrap line is allowed rather than
    clipping glyphs at the edge of the card.
    """
    text = " ".join(str(text).split())
    if not text:
        return None, 0
    alpha = opacity(kwargs.get("alpha", 1.0))
    if alpha < VISIBLE_ALPHA:
        return None, 0
    kwargs["alpha"] = alpha
    if "path_effects" in kwargs:
        kwargs["path_effects"] = fade_effects(kwargs.get("path_effects"), alpha)
    if family is None:
        family = theme.BODY_FONT

    size = float(fontsize)
    artist = None
    extra_line = False
    while True:
        if max_lines <= 1:
            lines = [text]
        else:
            lines = textwrap.wrap(
                text, _chars_per_line(size, max_width, family), break_long_words=False
            ) or [text]

        if artist is not None:
            artist.remove()
        artist = fig.text(x, y, "\n".join(lines), fontsize=size, ha=ha, va=va,
                          family=family, **kwargs)
        width, _ = _extent_fractions(fig, artist)
        fits = width <= max_width and len(lines) <= max_lines
        if fits:
            return artist, len(lines)
        if size > min_fontsize + 0.05:
            size = max(min_fontsize, size * 0.93)
            continue
        if not extra_line and max_lines >= 1:
            extra_line = True
            max_lines += 1
            continue
        return artist, len(lines)


def kicker(fig: plt.Figure, text: str, *, alpha: float = 1.0, color: str = TEXT_DIM) -> None:
    if not text:
        return
    fit_text(
        fig, Layout.MARGIN, Layout.KICKER_Y, str(text).upper(),
        fontsize=13.5, max_width=Layout.CONTENT_W, max_lines=1, min_fontsize=9.0,
        va="center", color=color, family=theme.MONO_FONT, alpha=alpha, zorder=20,
    )


def headline(fig: plt.Figure, text: str, subtitle: str = "", *, alpha: float = 1.0,
             fontsize: float = 52.0, color: str = TEXT) -> float:
    """Title (and optional subtitle). Returns the y the block ends at.

    The returned value is measured, not estimated, so callers can place content
    directly beneath a title whether it wrapped to one line or two.
    """
    y = Layout.TITLE_TOP
    alpha = opacity(alpha)
    if alpha < VISIBLE_ALPHA:
        return y
    if text:
        artist, _ = fit_text(
            fig, Layout.MARGIN, y, str(text).upper(),
            fontsize=fontsize, max_width=Layout.CONTENT_W, max_lines=2, min_fontsize=22.0,
            va="top", color=color, family=theme.DISPLAY_FONT, fontweight="bold",
            linespacing=1.05, alpha=alpha, zorder=20, path_effects=soft_shadow(alpha),
        )
        if artist is not None:
            _, height = _extent_fractions(fig, artist)
            y -= height + 0.014
    if subtitle:
        artist, _ = fit_text(
            fig, Layout.MARGIN + 0.003, y, str(subtitle).upper(),
            fontsize=13.0, max_width=Layout.CONTENT_W, max_lines=1, min_fontsize=9.0,
            va="top", color=TEXT_DIM, family=theme.MONO_FONT, alpha=alpha, zorder=20,
        )
        if artist is not None:
            _, height = _extent_fractions(fig, artist)
            y -= height + 0.010
    return y


def insight(fig: plt.Figure, text: str, *, alpha: float = 1.0, color: str = TEXT) -> None:
    """The single conclusion line in the footer band."""
    if not text or opacity(alpha) < VISIBLE_ALPHA:
        return
    fig_rect(fig, 0.0, Layout.FOOTER_Y + 0.030, 1.0, Layout.INSIGHT_Y - Layout.FOOTER_Y + 0.010,
             "#040605", 0.30 * alpha, zorder=17)
    fit_text(
        fig, 0.5, Layout.INSIGHT_Y, str(text),
        fontsize=25.0, max_width=Layout.CONTENT_W - 0.02, max_lines=2, min_fontsize=15.0,
        ha="center", va="center", color=color, family=theme.DISPLAY_FONT, fontweight="bold",
        linespacing=1.05, alpha=alpha, zorder=20, path_effects=soft_shadow(),
    )


def footer(fig: plt.Figure, right_text: str = "", *, alpha: float = 1.0) -> None:
    from . import i18n

    alpha = opacity(alpha)
    if alpha < VISIBLE_ALPHA:
        return
    fig.text(Layout.MARGIN, Layout.FOOTER_Y, i18n.t("watermark"), color=TEXT_FAINT, fontsize=8.0,
             family=theme.MONO_FONT, ha="left", va="center", alpha=alpha * 0.45, zorder=20)
    fit_text(
        fig, 1 - Layout.MARGIN, Layout.FOOTER_Y, (right_text or theme.DATA_SOURCE).upper(),
        fontsize=9.0, max_width=0.52, max_lines=1, min_fontsize=6.5,
        ha="right", va="center", color=TEXT_FAINT, family=theme.MONO_FONT, alpha=alpha, zorder=20,
    )


def legend_row(fig: plt.Figure, y: float, entries: Iterable[tuple[str, str, str]], *,
               alpha: float = 1.0, fontsize: float = 11.0) -> None:
    """A centred key. Each entry is (marker, colour, label).

    Marker is one of ``dot``, ``ring``, ``cross`` or ``bar``.
    """
    entries = list(entries)
    if not entries or opacity(alpha) < VISIBLE_ALPHA:
        return
    slot = (Layout.CONTENT_W) / len(entries)
    for index, (marker, colour, label) in enumerate(entries):
        cx = Layout.MARGIN + slot * (index + 0.5)
        swatch_x = cx - slot * 0.40
        if marker == "dot":
            fig_ellipse(fig, swatch_x, y, 0.0085, facecolor=colour, edgecolor="none",
                        alpha=alpha, zorder=20)
        elif marker == "ring":
            fig_ellipse(fig, swatch_x, y, 0.0085, facecolor="none", edgecolor=colour,
                        linewidth=2.0, alpha=alpha, zorder=20)
        elif marker == "cross":
            arm = 0.007
            for direction in (1, -1):
                fig.lines.append(
                    plt.Line2D(
                        [swatch_x - arm, swatch_x + arm],
                        [y - y_of(arm) * direction, y + y_of(arm) * direction],
                        transform=fig.transFigure, color=colour, linewidth=2.0,
                        alpha=alpha, zorder=20,
                    )
                )
        else:
            fig_rect(fig, swatch_x - 0.010, y - 0.004, 0.020, 0.008, colour, alpha, zorder=20)
        fig.text(swatch_x + 0.017, y, label.upper(), color=TEXT_DIM,
                 fontsize=theme.label_size(fontsize), family=theme.LABEL_FONT, fontweight="bold",
                 ha="left", va="center", alpha=alpha, zorder=20)


def number_text(value: float, *, decimals: int = 0, suffix: str = "") -> str:
    if decimals <= 0:
        return f"{int(round(value))}{suffix}"
    return f"{value:.{decimals}f}{suffix}"


# ---------------------------------------------------------------------------
# vertical pitch
# ---------------------------------------------------------------------------
# WhoScored coordinates: x runs 0-100 from a team's own goal to the goal it is
# attacking, y runs 0-100 across the width. Vertical framing suits a 9:16 video,
# so x maps to the figure's vertical axis.

PITCH_LENGTH_M, PITCH_WIDTH_M = 105.0, 68.0
PITCH_ASPECT = PITCH_WIDTH_M / PITCH_LENGTH_M

_BOX_DEPTH = 16.5 / PITCH_LENGTH_M * 100
_BOX_HALF_W = 40.32 / PITCH_WIDTH_M * 100 / 2
_SIX_DEPTH = 5.5 / PITCH_LENGTH_M * 100
_SIX_HALF_W = 18.32 / PITCH_WIDTH_M * 100 / 2
_SPOT_DEPTH = 11.0 / PITCH_LENGTH_M * 100
_GOAL_HALF_W = 7.32 / PITCH_WIDTH_M * 100 / 2
_CIRCLE_RX = 9.15 / PITCH_WIDTH_M * 100
_CIRCLE_RY = 9.15 / PITCH_LENGTH_M * 100


def to_pitch(x: float, y: float, flip: bool = False) -> tuple[float, float]:
    """Map WhoScored (x, y) into vertical pitch axes coordinates.

    With ``flip=False`` the team attacks the top of the frame; with
    ``flip=True`` it attacks the bottom, which is how two teams are shown on
    one pitch without pretending they shot at the same goal.
    """
    if flip:
        return 100.0 - y, 100.0 - x
    return y, x


def vertical_pitch(fig: plt.Figure, rect: list[float], *, face: str = PITCH,
                   line: str = PITCH_LINE, alpha: float = 1.0, lw: float = 1.6,
                   zorder: int = 3) -> plt.Axes:
    ax = fig.add_axes(rect, zorder=zorder)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_facecolor(face)
    ax.patch.set_alpha(opacity(alpha))
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    draw_pitch_markings(ax, line=line, alpha=alpha, lw=lw)
    return ax


def draw_pitch_markings(ax: plt.Axes, *, line: str = PITCH_LINE, alpha: float = 1.0,
                        lw: float = 1.6, zorder: int = 4) -> None:
    alpha = opacity(alpha)
    style = dict(color=line, lw=lw, alpha=alpha, zorder=zorder, solid_capstyle="butt")

    add_shape(ax, Rectangle((0, 0), 100, 100, fill=False, ec=line, lw=lw, alpha=alpha, zorder=zorder))
    ax.plot([0, 100], [50, 50], **style)
    add_shape(
        ax,
        Ellipse((50, 50), _CIRCLE_RX * 2, _CIRCLE_RY * 2, fill=False, ec=line, lw=lw,
                alpha=alpha, zorder=zorder),
    )
    ax.plot([50], [50], marker="o", ms=2.4, color=line, alpha=alpha, zorder=zorder)

    for near in (True, False):
        base = 0.0 if near else 100.0
        sign = 1 if near else -1

        add_shape(
            ax,
            Rectangle((50 - _BOX_HALF_W, base if near else base - _BOX_DEPTH),
                      _BOX_HALF_W * 2, _BOX_DEPTH, fill=False, ec=line, lw=lw,
                      alpha=alpha, zorder=zorder),
        )
        add_shape(
            ax,
            Rectangle((50 - _SIX_HALF_W, base if near else base - _SIX_DEPTH),
                      _SIX_HALF_W * 2, _SIX_DEPTH, fill=False, ec=line, lw=lw,
                      alpha=alpha, zorder=zorder),
        )
        spot_y = base + sign * _SPOT_DEPTH
        ax.plot([50], [spot_y], marker="o", ms=2.4, color=line, alpha=alpha, zorder=zorder)

        # Arc of the D, clipped to the part outside the penalty area.
        arc_x, arc_y = [], []
        for step in range(61):
            angle = math.pi * step / 60
            px = 50 + _CIRCLE_RX * math.cos(angle)
            py = spot_y + sign * _CIRCLE_RY * math.sin(angle)
            if (py - base) * sign >= _BOX_DEPTH:
                arc_x.append(px)
                arc_y.append(py)
        if arc_x:
            ax.plot(arc_x, arc_y, **style)

        # Goal, drawn slightly outside the line so it reads as a frame.
        ax.plot([50 - _GOAL_HALF_W, 50 + _GOAL_HALF_W], [base, base],
                color=line, lw=lw * 2.6, alpha=min(1.0, alpha * 1.1),
                zorder=zorder + 1, solid_capstyle="butt")


def pitch_grid_fade(ax: plt.Axes, alpha: float = 0.05) -> None:
    for value in (100 / 3, 200 / 3):
        ax.plot([0, 100], [value, value], color=TEXT, lw=0.8, alpha=alpha, zorder=2, ls=(0, (4, 6)))


# ---------------------------------------------------------------------------
# team badges
# ---------------------------------------------------------------------------

def _flag_painter(key: str):
    return _FLAGS.get(key)


def team_badge(fig: plt.Figure, team: str, cx: float, cy: float, width: float, *,
               identity: dict[str, str] | None = None, alpha: float = 1.0,
               zorder: int = 12) -> None:
    """National: rectangular flag tile. Club: circular crest with logo/initials.

    ``width`` is the tile width in figure-x units. National height follows the
    3:2 flag ratio; club badges are circular so height matches width in pixels.
    """
    identity = identity or theme.team_identity(team)
    alpha = opacity(alpha)
    if alpha < VISIBLE_ALPHA:
        return
    shape = identity.get("shape") or theme.badge_shape()
    if shape == "circle":
        _club_badge(fig, team, cx, cy, width, identity=identity, alpha=alpha, zorder=zorder)
        return

    height = y_of(width * 2 / 3)
    x0, y0 = cx - width / 2, cy - height / 2

    pad = 0.005
    fig_panel(fig, x0 - pad, y0 - y_of(pad), width + 2 * pad, height + 2 * y_of(pad),
              color="#0c100e", alpha=0.92 * alpha, edge=identity["chart"], radius=0.006,
              zorder=zorder - 1, lw=1.4)

    painter = _flag_painter(identity["key"])
    if painter is not None:
        painter(fig, x0, y0, width, height, alpha, zorder)
    else:
        _crest_fallback(fig, identity, x0, y0, width, height, alpha, zorder)

    # Border on top of the flag, so the tile stays crisp against the panel.
    fig.patches.append(
        Rectangle((x0, y0), width, height, transform=fig.transFigure, facecolor="none",
                  edgecolor="#050706", linewidth=1.2, alpha=alpha, zorder=zorder + 5)
    )


def _club_badge(fig: plt.Figure, team: str, cx: float, cy: float, width: float, *,
                identity: dict[str, str], alpha: float, zorder: int) -> None:
    """Circular club crest: real logo when cached, otherwise a colour disc + abbr."""
    height = y_of(width)
    x0, y0 = cx - width / 2, cy - height / 2
    radius = width / 2

    # Soft ring behind the crest in the club's chart colour.
    fig_ellipse(fig, cx, cy, radius + 0.007, facecolor="#0c100e",
                edgecolor=identity["chart"], linewidth=2.0, alpha=0.95 * alpha,
                zorder=zorder - 1)

    logo_path = None
    try:
        from . import logos

        logo_path = logos.resolve_logo(team)
    except Exception:
        logo_path = None

    drawn = False
    if logo_path:
        drawn = _draw_logo_circle(fig, logo_path, x0, y0, width, height, alpha, zorder)

    if not drawn:
        fig_ellipse(fig, cx, cy, radius * 0.96, facecolor=identity["primary"],
                    edgecolor="none", alpha=alpha, zorder=zorder)
        # Secondary crescent for a bit of kit colour without muddying the abbr.
        fig_ellipse(fig, cx, cy - height * 0.18, radius * 0.96,
                    facecolor=identity["secondary"], edgecolor="none",
                    alpha=0.55 * alpha, zorder=zorder + 1)
        tile_h_px = height * theme.FRAME_H
        fontsize = max(8.0, tile_h_px * 0.34)
        fig.text(
            cx, cy + height * 0.04, identity["abbr"],
            color=theme.ink_on(identity["primary"]), fontsize=fontsize, fontweight="bold",
            family=theme.DISPLAY_FONT, ha="center", va="center", alpha=alpha, zorder=zorder + 2,
        )

    fig_ellipse(fig, cx, cy, radius, facecolor="none", edgecolor="#050706",
                linewidth=1.4, alpha=alpha, zorder=zorder + 5)


def _draw_logo_circle(fig: plt.Figure, path: str, x0: float, y0: float,
                      width: float, height: float, alpha: float, zorder: int) -> bool:
    """Paint a crest into a circular clip. Returns False if the image cannot load."""
    try:
        image = plt.imread(path)
    except Exception:
        return False
    if image is None or getattr(image, "size", 0) == 0:
        return False

    # Slight inset so the ring border stays clean around the artwork.
    inset = 0.04
    ax = fig.add_axes(
        [x0 + width * inset, y0 + height * inset, width * (1 - 2 * inset), height * (1 - 2 * inset)],
        anchor="C",
    )
    ax.set_zorder(zorder + 1)
    ax.set_facecolor("none")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.patch.set_alpha(0.0)

    # White disc behind transparent PNGs so crests stay readable on dark ink.
    ax.add_patch(Circle((0.5, 0.5), 0.5, transform=ax.transAxes,
                        facecolor="#ffffff", edgecolor="none", alpha=alpha, zorder=0))
    artist = ax.imshow(image, extent=(0, 1, 0, 1), origin="upper",
                       interpolation="bilinear", alpha=alpha, zorder=1, aspect="auto")
    clip = Circle((0.5, 0.5), 0.5, transform=ax.transAxes)
    artist.set_clip_path(clip)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_clip_path(clip)
    return True


def _band(fig: plt.Figure, x0: float, y0: float, w: float, h: float,
          fx: float, fy: float, fw: float, fh: float, color: str,
          alpha: float, zorder: int) -> None:
    fig_rect(fig, x0 + fx * w, y0 + fy * h, fw * w, fh * h, color, alpha, zorder)


def _crest_fallback(fig: plt.Figure, identity: dict[str, str], x0: float, y0: float,
                    w: float, h: float, alpha: float, zorder: int) -> None:
    """Two-tone tile with the team's three letters, sized to the tile."""
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, identity["primary"], alpha, zorder)
    _band(fig, x0, y0, w, h, 0, 0, 1, 0.30, identity["secondary"], alpha * 0.95, zorder + 1)

    # Font size derived from the tile's pixel height, not a magic constant.
    tile_h_px = h * theme.FRAME_H
    fontsize = max(7.0, tile_h_px * 0.40)
    fig.text(
        x0 + w / 2, y0 + h * 0.60, identity["abbr"],
        color=theme.ink_on(identity["primary"]), fontsize=fontsize, fontweight="bold",
        family=theme.DISPLAY_FONT, ha="center", va="center", alpha=alpha, zorder=zorder + 2,
    )


def _star_points(cx: float, cy: float, outer: float, inner: float) -> list[tuple[float, float]]:
    """A five-pointed star in figure coordinates, round in pixels."""
    points = []
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.pi / 2 + index * math.pi / 5
        points.append((cx + math.cos(angle) * radius, cy + y_of(math.sin(angle) * radius)))
    return points


def _tricolour_v(colors: tuple[str, str, str]):
    def painter(fig, x0, y0, w, h, alpha, zorder):
        for index, color in enumerate(colors):
            _band(fig, x0, y0, w, h, index / 3, 0, 1 / 3, 1, color, alpha, zorder)
    return painter


def _tricolour_h(colors: tuple[str, str, str]):
    """Three horizontal bands, given top to bottom."""
    def painter(fig, x0, y0, w, h, alpha, zorder):
        for index, color in enumerate(colors):
            _band(fig, x0, y0, w, h, 0, (2 - index) / 3, 1, 1 / 3, color, alpha, zorder)
    return painter


def _bicolour_h(top: str, bottom: str):
    def painter(fig, x0, y0, w, h, alpha, zorder):
        _band(fig, x0, y0, w, h, 0, 0.5, 1, 0.5, top, alpha, zorder)
        _band(fig, x0, y0, w, h, 0, 0, 1, 0.5, bottom, alpha, zorder)
    return painter


def _solid_with_disc(base: str, disc: str, radius: float = 0.28):
    def painter(fig, x0, y0, w, h, alpha, zorder):
        _band(fig, x0, y0, w, h, 0, 0, 1, 1, base, alpha, zorder)
        fig_ellipse(fig, x0 + w / 2, y0 + h / 2, w * radius, facecolor=disc,
                    edgecolor="none", alpha=alpha, zorder=zorder + 1)
    return painter


def _nordic_cross(base: str, cross: str, offset: float = 0.5):
    def painter(fig, x0, y0, w, h, alpha, zorder):
        _band(fig, x0, y0, w, h, 0, 0, 1, 1, base, alpha, zorder)
        _band(fig, x0, y0, w, h, 0, 0.40, 1, 0.20, cross, alpha, zorder + 1)
        _band(fig, x0, y0, w, h, offset - 0.07, 0, 0.14, 1, cross, alpha, zorder + 1)
    return painter


def _swiss(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, "#d52b1e", alpha, zorder)
    _band(fig, x0, y0, w, h, 0.42, 0.20, 0.16, 0.60, "#ffffff", alpha, zorder + 1)
    _band(fig, x0, y0, w, h, 0.26, 0.40, 0.48, 0.20, "#ffffff", alpha, zorder + 1)


def _usa(fig, x0, y0, w, h, alpha, zorder):
    for index in range(13):
        _band(fig, x0, y0, w, h, 0, index / 13, 1, 1 / 13,
              "#b31942" if index % 2 == 0 else "#ffffff", alpha, zorder)
    _band(fig, x0, y0, w, h, 0, 6 / 13, 0.42, 7 / 13, "#0a3161", alpha, zorder + 1)


def _saltire(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, "#005eb8", alpha, zorder)
    for direction in (1, -1):
        fig.patches.append(
            Polygon(
                [
                    (x0 if direction > 0 else x0 + w, y0 + h * 0.86),
                    (x0 + w * 0.14 if direction > 0 else x0 + w * 0.86, y0 + h),
                    (x0 + w if direction > 0 else x0, y0 + h * 0.14),
                    (x0 + w * 0.86 if direction > 0 else x0 + w * 0.14, y0),
                ],
                closed=True, transform=fig.transFigure, facecolor="#ffffff",
                edgecolor="none", alpha=alpha, zorder=zorder + 1,
            )
        )


def _morocco(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, "#c1272d", alpha, zorder)
    fig.patches.append(
        Polygon(_star_points(x0 + w / 2, y0 + h / 2, w * 0.26, w * 0.10),
                closed=True, transform=fig.transFigure, facecolor="none",
                edgecolor="#006233", linewidth=1.8, alpha=alpha, zorder=zorder + 1)
    )


def _brazil(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, "#009c3b", alpha, zorder)
    fig.patches.append(
        Polygon(
            [(x0 + w * 0.06, y0 + h * 0.5), (x0 + w * 0.5, y0 + h * 0.92),
             (x0 + w * 0.94, y0 + h * 0.5), (x0 + w * 0.5, y0 + h * 0.08)],
            closed=True, transform=fig.transFigure, facecolor="#ffdf00",
            edgecolor="none", alpha=alpha, zorder=zorder + 1,
        )
    )
    fig_ellipse(fig, x0 + w / 2, y0 + h / 2, w * 0.17, facecolor="#002776",
                edgecolor="none", alpha=alpha, zorder=zorder + 2)


def _argentina(fig, x0, y0, w, h, alpha, zorder):
    for index, color in enumerate(("#74acdf", "#ffffff", "#74acdf")):
        _band(fig, x0, y0, w, h, 0, index / 3, 1, 1 / 3, color, alpha, zorder)
    fig_ellipse(fig, x0 + w / 2, y0 + h / 2, w * 0.095, facecolor="#f6b40e",
                edgecolor="#c8951a", linewidth=0.6, alpha=alpha, zorder=zorder + 1)


def _england(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, "#ffffff", alpha, zorder)
    _band(fig, x0, y0, w, h, 0.42, 0, 0.16, 1, "#ce1124", alpha, zorder + 1)
    _band(fig, x0, y0, w, h, 0, 0.40, 1, 0.20, "#ce1124", alpha, zorder + 1)


def _portugal(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 0.40, 1, "#006600", alpha, zorder)
    _band(fig, x0, y0, w, h, 0.40, 0, 0.60, 1, "#ff0000", alpha, zorder)
    fig_ellipse(fig, x0 + w * 0.40, y0 + h * 0.5, w * 0.13, facecolor="#ffcc00",
                edgecolor="#c8951a", linewidth=0.6, alpha=alpha, zorder=zorder + 1)


def _spain(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 0.25, "#c60b1e", alpha, zorder)
    _band(fig, x0, y0, w, h, 0, 0.25, 1, 0.50, "#ffc400", alpha, zorder)
    _band(fig, x0, y0, w, h, 0, 0.75, 1, 0.25, "#c60b1e", alpha, zorder)


def _croatia(fig, x0, y0, w, h, alpha, zorder):
    for index, color in enumerate(("#171796", "#ffffff", "#ff0000")):
        _band(fig, x0, y0, w, h, 0, index / 3, 1, 1 / 3, color, alpha, zorder)
    for row in range(4):
        for col in range(5):
            shade = "#ff0000" if (row + col) % 2 == 0 else "#ffffff"
            _band(fig, x0, y0, w, h, 0.40 + col * 0.04, 0.34 + row * 0.08, 0.04, 0.08,
                  shade, alpha, zorder + 1)


def _south_korea(fig, x0, y0, w, h, alpha, zorder):
    _band(fig, x0, y0, w, h, 0, 0, 1, 1, "#ffffff", alpha, zorder)
    fig_ellipse(fig, x0 + w / 2, y0 + h / 2, w * 0.17, facecolor="#c60c30",
                edgecolor="none", alpha=alpha, zorder=zorder + 1)
    fig_ellipse(fig, x0 + w / 2, y0 + h * 0.42, w * 0.085, facecolor="#003478",
                edgecolor="none", alpha=alpha, zorder=zorder + 2)


def _mexico(fig, x0, y0, w, h, alpha, zorder):
    _tricolour_v(("#006847", "#ffffff", "#ce1126"))(fig, x0, y0, w, h, alpha, zorder)
    fig_ellipse(fig, x0 + w / 2, y0 + h / 2, w * 0.085, facecolor="#8d6b3a",
                edgecolor="none", alpha=alpha, zorder=zorder + 1)


def _egypt(fig, x0, y0, w, h, alpha, zorder):
    for index, color in enumerate(("#000000", "#ffffff", "#ce1126")):
        _band(fig, x0, y0, w, h, 0, index / 3, 1, 1 / 3, color, alpha, zorder)
    fig_ellipse(fig, x0 + w / 2, y0 + h / 2, w * 0.085, facecolor="#c09300",
                edgecolor="none", alpha=alpha, zorder=zorder + 1)


def _germany(fig, x0, y0, w, h, alpha, zorder):
    for index, color in enumerate(("#ffcc00", "#dd0000", "#000000")):
        _band(fig, x0, y0, w, h, 0, index / 3, 1, 1 / 3, color, alpha, zorder)


def _belgium(fig, x0, y0, w, h, alpha, zorder):
    _tricolour_v(("#000000", "#fdda24", "#ef3340"))(fig, x0, y0, w, h, alpha, zorder)


_FLAGS: dict[str, Any] = {
    "argentina": _argentina,
    "belgium": _belgium,
    "brazil": _brazil,
    "croatia": _croatia,
    "denmark": _nordic_cross("#c8102e", "#ffffff", 0.36),
    "egypt": _egypt,
    "england": _england,
    "france": _tricolour_v(("#2b4eb8", "#ffffff", "#ed2939")),
    "germany": _germany,
    "italy": _tricolour_v(("#009246", "#ffffff", "#ce2b37")),
    "ivory coast": _tricolour_v(("#ff8200", "#ffffff", "#009a44")),
    "japan": _solid_with_disc("#ffffff", "#bc002d", 0.22),
    "mexico": _mexico,
    "morocco": _morocco,
    "netherlands": _tricolour_h(("#ae1c28", "#ffffff", "#21468b")),
    "nigeria": _tricolour_v(("#008751", "#ffffff", "#008751")),
    "norway": _nordic_cross("#ba0c2f", "#ffffff", 0.36),
    "peru": _tricolour_v(("#d91023", "#ffffff", "#d91023")),
    "poland": _bicolour_h("#ffffff", "#dc143c"),
    "portugal": _portugal,
    "scotland": _saltire,
    "south korea": _south_korea,
    "spain": _spain,
    "sweden": _nordic_cross("#006aa7", "#fecc02", 0.36),
    "switzerland": _swiss,
    "united states": _usa,
}


# ---------------------------------------------------------------------------
# comparison bars
# ---------------------------------------------------------------------------

def comparison_bar(
    fig: plt.Figure,
    y: float,
    label: str,
    home_value: float,
    away_value: float,
    home_color: str,
    away_color: str,
    *,
    progress: float = 1.0,
    height: float = 0.0165,
    left: float = 0.215,
    right: float = 0.785,
    decimals: int = 0,
    suffix: str = "",
    zorder: int = 12,
) -> None:
    """One diverging bar: the split point is the two teams' share of the total."""
    total = home_value + away_value
    home_share = 0.5 if total <= 0 else home_value / total
    width = right - left
    grown = ease_in_out(clamp01(progress))
    if grown < VISIBLE_ALPHA:
        return
    ink = min(1.0, grown * 2.4)

    fig.text(0.5, y + height + 0.019, str(label).upper(), color=TEXT_DIM,
             fontsize=theme.label_size(13), family=theme.LABEL_FONT, fontweight="bold",
             ha="center", va="center", alpha=ink,
             zorder=zorder)

    fig_rect(fig, left, y, width, height, "#171d19", 0.95 * min(1.0, grown * 3), zorder=zorder - 2)

    split = left + width * home_share
    grown_home = (split - left) * grown
    grown_away = (right - split) * grown
    fig_rect(fig, split - grown_home, y, grown_home, height, home_color, 0.95, zorder=zorder)
    fig_rect(fig, split, y, grown_away, height, away_color, 0.95, zorder=zorder)

    shown_home = hold_count(home_value, grown)
    shown_away = hold_count(away_value, grown)
    fig.text(left - 0.022, y + height / 2, number_text(shown_home, decimals=decimals, suffix=suffix),
             color=home_color, fontsize=38, fontweight="bold", family=theme.DISPLAY_FONT,
             ha="right", va="center", alpha=ink, zorder=zorder,
             path_effects=soft_shadow(ink))
    fig.text(right + 0.022, y + height / 2, number_text(shown_away, decimals=decimals, suffix=suffix),
             color=away_color, fontsize=38, fontweight="bold", family=theme.DISPLAY_FONT,
             ha="left", va="center", alpha=ink, zorder=zorder,
             path_effects=soft_shadow(ink))


def impact_burst(ax: plt.Axes, x: float, y: float, color: str, progress: float,
                 base_radius: float = 2.4, zorder: int = 20, size: float = 190.0) -> None:
    """A goal marker: rings that expand and fade, over a marker that stays put."""
    if progress <= 0:
        return
    fade = opacity(progress)
    for index, (scale, weight) in enumerate(((1.0, 2.8), (2.1, 2.0), (3.4, 1.3))):
        local = clamp01(progress * 1.4 - index * 0.18)
        if local <= 0:
            continue
        add_shape(
            ax,
            Circle((x, y), base_radius * scale * (0.35 + 0.65 * local), fill=False,
                   ec=color, lw=weight, alpha=opacity((1.0 - local) * 0.9), zorder=zorder),
        )
    # The expanding rings are transient, so a halo and a filled dot are what
    # remain visible once the scene settles.
    add_shape(
        ax,
        Circle((x, y), base_radius * 1.5, fill=False, ec=color, lw=1.6,
               alpha=fade * 0.55, zorder=zorder),
    )
    ax.scatter([x], [y], s=size * progress, color=color, edgecolor=TEXT, linewidth=2.0,
               zorder=zorder + 1, alpha=fade)


def add_shape(ax: plt.Axes, patch: Any) -> Any:
    """Add a patch without recomputing the data limits.

    Every axes here has explicit limits, so ``add_patch``'s bezier extrema
    calculation is wasted work; on a shot map it was the single biggest cost
    per frame.
    """
    ax.add_artist(patch)
    return patch


def scatter_batch(
    ax: plt.Axes,
    xs: list[float],
    ys: list[float],
    *,
    sizes: list[float],
    colors: list[str],
    alphas: list[float],
    marker: str = "o",
    filled: bool = True,
    linewidth: float = 1.0,
    edgecolor: str = "#050706",
    zorder: int = 10,
) -> None:
    """One collection for many markers.

    Drawing each marker as its own ``scatter`` call is the slowest thing a scene
    can do; per-point size, colour and alpha arrays give the same picture from a
    single collection.
    """
    if not xs:
        return
    count = len(xs)
    kwargs: dict[str, Any] = {
        "s": sizes,
        "marker": marker,
        "linewidths": linewidth,
        # Matplotlib requires the colour and alpha sequences to be the same
        # length, so colours are expanded rather than passed as a scalar.
        "alpha": [opacity(value) for value in alphas],
        "zorder": zorder,
    }
    # Stroke-only markers such as "x" take their colour from facecolors, and
    # passing edgecolors at all makes matplotlib warn.
    if marker in {"x", "+", "|", "_", "1", "2", "3", "4"}:
        kwargs["facecolors"] = list(colors)
    elif filled:
        kwargs["facecolors"] = list(colors)
        kwargs["edgecolors"] = [edgecolor] * count
    else:
        kwargs["facecolors"] = ["none"] * count
        kwargs["edgecolors"] = list(colors)
    ax.scatter(xs, ys, **kwargs)


def hero_number(fig: plt.Figure, x: float, y: float, value: Any, *,
                color: str = TEXT, alpha: float = 1.0, fontsize: float = 160.0,
                ha: str = "center", va: str = "center") -> None:
    """A phone-stopping numeral. Labels stay small; this does not."""
    alpha = opacity(alpha)
    if alpha < VISIBLE_ALPHA:
        return
    fig.text(
        x, y, str(value), color=color, fontsize=fontsize, fontweight="bold",
        family=theme.DISPLAY_FONT, ha=ha, va=va, alpha=alpha, zorder=22,
        path_effects=soft_shadow(alpha),
    )


def caption_bar(fig: plt.Figure, text: str, *, y: float | None = None, alpha: float = 1.0,
                progress: float = 1.0) -> None:
    """On-screen insight, stamped late so the graph can speak first."""
    if not text or opacity(alpha * progress) < VISIBLE_ALPHA:
        return
    if y is None:
        insight(fig, text, alpha=opacity(alpha * progress))
        return
    slide = (1.0 - ease_out_cubic(progress)) * 0.04
    fit_text(
        fig, 0.5, y + slide, str(text),
        fontsize=22.0, max_width=Layout.CONTENT_W - 0.02, max_lines=2, min_fontsize=13.0,
        ha="center", va="center", color=TEXT, family=theme.DISPLAY_FONT, fontweight="bold",
        linespacing=1.05, alpha=opacity(alpha * progress), zorder=21, path_effects=soft_shadow(),
    )


def stamp_insight(fig: plt.Figure, scene: dict[str, Any], tl: Timeline,
                  *, y: float | None = None) -> None:
    """Insight that completes on the compressed timeline, before HOLD_AT.

    ``y`` is only for cards that already have their own footer band. The
    default stays on ``insight()`` / ``Layout.INSIGHT_Y`` — do not invent a
    second stamp position.
    """
    text = str(scene.get("insight") or "").strip()
    stamp = tl.stamp()
    if not text or stamp < VISIBLE_ALPHA:
        return
    caption_bar(fig, text, y=y, progress=stamp)


def scene_chrome(fig: plt.Figure, scene: dict[str, Any], tl: Timeline,
                 *, headline_size: float = 50.0) -> float:
    """Headline plus a late insight stamp. Shared by scenes and graphs."""
    header_bottom = headline(
        fig, scene.get("title", ""), "",
        alpha=tl.cue(0.0, 0.28, ease=ease_out_cubic),
        fontsize=headline_size,
    )
    stamp_insight(fig, scene, tl)
    return header_bottom - 0.016


def empty_stage(fig: plt.Figure, message: str, tl: Timeline, *, y: float = 0.50) -> None:
    """Fallback copy that fades in — never a finished empty card on frame 1."""
    alpha = tl.cue(0.10, 0.36, ease=ease_in_out)
    if not message or alpha < VISIBLE_ALPHA:
        return
    fig.text(
        0.5, y, str(message), color=TEXT_DIM, fontsize=22,
        family=theme.DISPLAY_FONT, ha="center", va="center",
        alpha=alpha, zorder=14,
    )


def color_flash(fig: plt.Figure, color: str, *, alpha: float = 1.0, zorder: int = 5) -> None:
    fig_rect(fig, 0.0, 0.0, 1.0, 1.0, color, opacity(alpha), zorder=zorder)


def particle_burst(ax, x: float, y: float, color: str, progress: float,
                   count: int = 8, radius: float = 4.0, zorder: int = 21) -> None:
    """Cheap expanding dots around a goal / slam."""
    if progress <= 0:
        return
    fade = opacity(1.0 - progress)
    for index in range(count):
        angle = (index / count) * math.tau
        reach = radius * (0.35 + 0.65 * progress)
        add_shape(
            ax,
            Circle((x + math.cos(angle) * reach, y + math.sin(angle) * reach),
                   0.35 + 0.25 * (1.0 - progress), facecolor=color, edgecolor="none",
                   alpha=fade * 0.85, zorder=zorder),
        )


def radar_polygon(ax, values: list[float], color: str, *, progress: float = 1.0,
                  fill_alpha: float = 0.28, lw: float = 2.2, zorder: int = 8) -> None:
    """Regular polygon radar. *values* are 0-1 scores, one per axis."""
    count = len(values)
    progress = opacity(progress)
    if count < 3 or progress < VISIBLE_ALPHA:
        return
    grown = [max(0.0, min(1.0, float(value) * progress)) for value in values]
    angles = [index * math.tau / count + math.pi / 2 for index in range(count)]
    xs = [0.5 + math.cos(angle) * value * 0.48 for angle, value in zip(angles, grown)]
    ys = [0.5 + math.sin(angle) * value * 0.48 for angle, value in zip(angles, grown)]
    xs.append(xs[0])
    ys.append(ys[0])
    ax.fill(xs, ys, color=color, alpha=opacity(fill_alpha * progress), zorder=zorder, linewidth=0)
    ax.plot(xs, ys, color=color, lw=lw, alpha=opacity(0.95 * progress), zorder=zorder + 1)


def ring_gauge(ax, cx: float, cy: float, value: float, maximum: float, color: str, *,
               progress: float = 1.0, radius: float = 0.32, width: float = 0.07,
               zorder: int = 8) -> None:
    """Arc gauge from 12 o'clock clockwise. *value* / *maximum* fills the ring."""
    from matplotlib.patches import Wedge

    progress = opacity(progress)
    if progress < VISIBLE_ALPHA:
        return
    frac = 0.0 if maximum <= 0 else min(1.0, max(0.0, value / maximum))
    frac *= progress
    add_shape(
        ax,
        Wedge((cx, cy), radius, 90, 90 - 359.9, width=width,
              facecolor="#2a332f", edgecolor="none",
              alpha=opacity(0.95 * min(1.0, progress * 2.2)), zorder=zorder),
    )
    if frac > 0.002:
        add_shape(
            ax,
            Wedge((cx, cy), radius, 90, 90 - 359.9 * frac, width=width,
                  facecolor=color, edgecolor="none", alpha=0.95, zorder=zorder + 1),
        )


def heat_pitch(ax, grid: list[list[float]], color: str, *, progress: float = 1.0,
               flip: bool = False, zorder: int = 6) -> None:
    """Smooth heatmap on a 0-100 pitch."""
    array = np.array(grid, dtype=float)
    if array.size == 0:
        return
    if flip:
        array = np.flipud(np.fliplr(array))
    peak = float(array.max()) or 1.0
    array = array / peak * progress
    x_bins, y_bins = array.shape
    rgba = np.zeros((x_bins, y_bins, 4))
    r, g, b = theme.hex_to_rgb(color)
    rgba[..., 0] = r
    rgba[..., 1] = g
    rgba[..., 2] = b
    rgba[..., 3] = np.clip(array, 0, 1) * 0.85
    ax.imshow(
        rgba, origin="lower", extent=(0, 100, 0, 100), interpolation="bilinear",
        aspect="auto", zorder=zorder,
    )


def funnel_stage(fig: plt.Figure, y: float, label: str, home_value: float, away_value: float,
                 home_color: str, away_color: str, *, progress: float = 1.0,
                 inset: float = 0.0, height: float = 0.055) -> None:
    """A trapezoid row that narrows toward the goal. Not a comparison bar."""
    left = 0.18 + inset
    right = 0.82 - inset
    width = right - left
    total = home_value + away_value
    home_share = 0.5 if total <= 0 else home_value / total
    grown = ease_in_out(clamp01(progress))
    if grown < VISIBLE_ALPHA:
        return
    split = left + width * home_share
    fig_rect(fig, left, y, (split - left) * grown, height, home_color, 0.92, zorder=12)
    fig_rect(fig, split, y, (right - split) * grown, height, away_color, 0.92, zorder=12)
    ink = min(1.0, grown * 2.2)
    fig.text(0.5, y + height + 0.016, str(label).upper(), color=TEXT_DIM,
             fontsize=theme.label_size(12), family=theme.LABEL_FONT, fontweight="bold",
             ha="center", va="center", alpha=ink, zorder=14)
    fig.text(left - 0.018, y + height / 2, number_text(hold_count(home_value, grown)),
             color=home_color, fontsize=28, fontweight="bold", family=theme.DISPLAY_FONT,
             ha="right", va="center", alpha=ink, zorder=14,
             path_effects=soft_shadow(ink))
    fig.text(right + 0.018, y + height / 2, number_text(hold_count(away_value, grown)),
             color=away_color, fontsize=28, fontweight="bold", family=theme.DISPLAY_FONT,
             ha="left", va="center", alpha=ink, zorder=14,
             path_effects=soft_shadow(ink))


def glow_ring(
    ax: plt.Axes,
    x: float,
    y: float,
    color: str,
    *,
    radius: float = 3.0,
    alpha: float = 0.28,
    zorder: int = 7,
) -> None:
    """One restrained halo. Not a particle storm."""
    if alpha <= 0:
        return
    add_shape(
        ax,
        Circle((x, y), radius, fill=False, ec=color, lw=2.0,
               alpha=opacity(alpha), zorder=zorder),
    )


def freeze_frame_badge(
    ax: plt.Axes,
    x: float,
    y: float,
    n: int,
    color: str,
    *,
    alpha: float = 1.0,
    radius: float = 2.15,
    zorder: int = 18,
    latest: bool = False,
) -> None:
    """Numbered freeze-frame disc. Default radius is pitch 0-100 units.

    Polar / 0-1 axes should pass ``radius=0.022``.
    """
    if alpha <= 0:
        return
    r = radius * (1.18 if latest else 1.0)
    add_shape(
        ax,
        Circle(
            (x, y), r, facecolor=color, edgecolor=TEXT, linewidth=1.3,
            alpha=opacity(alpha), zorder=zorder,
        ),
    )
    ax.text(
        x, y, str(n),
        color=theme.ink_on(color), fontsize=12.0 if latest else 10.5,
        fontweight="bold", family=theme.DISPLAY_FONT,
        ha="center", va="center", alpha=opacity(alpha), zorder=zorder + 1,
    )


def save_figure(fig: plt.Figure, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Intermediate frames are read once by ffmpeg, so trade file size for speed.
    fig.savefig(path, facecolor=fig.get_facecolor(), dpi=fig.dpi, pad_inches=0,
                pil_kwargs={"compress_level": 1})
    plt.close(fig)
