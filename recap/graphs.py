"""Crisp touch-territory mosaic — the heatmap replacement.

Viral slam/radar/spiral cards lived here and drifted from the backup recap
core. Studio now selects backup pitch/time/territory cards from ``scenes.py``.
This module keeps one extra renderer: rectangular tiles from real touch bins,
with no interpolation that invents activity between coordinates.

Does not import ``scenes``, so draw → graphs/scenes stays one-way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from matplotlib.patches import Rectangle

from . import draw, theme
from .data import MatchBundle
from .draw import Layout, Timeline


def render_touch_heatmap(
    bundle: MatchBundle,
    audit: dict[str, Any],
    scene: dict[str, Any],
    path: Path,
    progress: float = 1.0,
) -> None:
    """Crisp touch-territory mosaic.

    Occupied bins become rectangular tiles with a small gap. Volume is inset
    plus alpha, not marker size, so a 9:16 still reads as a map of cells.
    """
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    heat = audit.get("touch_heatmap") or {}
    content_top = draw.scene_chrome(fig, scene, tl, headline_size=50.0)
    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.02, bottom=0.16)
    ax = draw.vertical_pitch(
        fig, rect, face=design["pitch"], line=design["pitch_line"],
        alpha=tl.cue(0.06, 0.26),
    )
    home_grid = heat.get("home") or []
    away_grid = heat.get("away") or []
    cells: list[tuple[float, int, int, float, float]] = []
    if home_grid and away_grid:
        for xi, home_row in enumerate(home_grid):
            away_row = away_grid[xi] if xi < len(away_grid) else []
            for yi, home_value in enumerate(home_row):
                away_value = away_row[yi] if yi < len(away_row) else 0
                total = float(home_value or 0) + float(away_value or 0)
                if total > 0:
                    cells.append((total, xi, yi, float(home_value or 0), float(away_value or 0)))
    cells.sort(reverse=True)
    maximum = max((cell[0] for cell in cells), default=1.0)
    shown = tl.reveal_count(len(cells), start=0.08, span=0.62)
    x_bins = max(1, int(heat.get("x_bins") or len(home_grid) or 1))
    y_bins = max(1, int(heat.get("y_bins") or (len(home_grid[0]) if home_grid else 1)))
    cell_w = 100.0 / y_bins
    cell_h = 100.0 / x_bins
    gap = min(cell_w, cell_h) * 0.08
    for index, (total, xi, yi, home_value, away_value) in enumerate(cells[:shown]):
        local = tl.stagger(index, max(1, len(cells)), start=0.08, span=0.60, duration=0.18)
        if local <= 0:
            continue
        share = home_value / total if total else 0.5
        identity = design["home"] if share >= 0.5 else design["away"]
        dominance = abs(share - 0.5) * 2.0
        volume = total / maximum
        extra = (0.20 * (1.0 - volume ** 0.65)) * min(cell_w, cell_h)
        inset = gap + extra
        x0 = yi * cell_w + inset
        y0 = xi * cell_h + inset
        width = max(0.55, cell_w - 2 * inset)
        height = max(0.55, cell_h - 2 * inset)
        draw.add_shape(
            ax,
            Rectangle(
                (x0, y0), width, height,
                facecolor=identity["fill"],
                edgecolor=identity["chart"],
                linewidth=0.6 + 0.7 * dominance,
                alpha=draw.opacity((0.26 + 0.50 * volume + 0.18 * dominance) * local),
                zorder=6 + index * 0.001,
            ),
        )
    grid_alpha = 0.55 * tl.cue(0.10, 0.26)
    if grid_alpha > 0:
        for index in range(1, y_bins):
            ax.plot(
                [index * cell_w] * 2, [0, 100], color="#0a0d0b", lw=1.6,
                alpha=grid_alpha, zorder=12, solid_capstyle="butt",
            )
        for index in range(1, x_bins):
            ax.plot(
                [0, 100], [index * cell_h] * 2, color="#0a0d0b", lw=1.6,
                alpha=grid_alpha, zorder=12, solid_capstyle="butt",
            )
    draw.legend_row(
        fig, 0.118,
        [("bar", design["home"]["fill"], bundle.home), ("bar", design["away"]["fill"], bundle.away)],
        alpha=tl.cue(0.40, 0.26), fontsize=theme.label_size(10),
    )
    draw.save_figure(fig, path)


GRAPH_RENDERERS = {
    "touch_heatmap": render_touch_heatmap,
}
