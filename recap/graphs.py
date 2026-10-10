"""New recap visualizations: slams, radar, heat, waves, gauges, funnels.

Imported by ``scenes`` and registered there. Does not import ``scenes``, so the
layering (draw → scenes) stays one-way.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.patches import Circle, Polygon

from . import depth, draw, i18n, theme
from .audit import build_pass_network, dominant_team
from .data import MatchBundle
from .director import format_stat, pick_stat_rows, stat_label
from .draw import Layout, Timeline
from .theme import TEXT, TEXT_DIM, TEXT_FAINT


def _short_team(name: str) -> str:
    skip = {"fc", "cf", "afc", "the", "de", "club", "sd", "ud", "cd", "sc"}
    parts = [part for part in str(name or "").split() if part.lower() not in skip]
    return (parts[-1] if parts else name).upper()


def _chrome(fig, scene: dict[str, Any], tl: Timeline, *, headline_size: float = 50.0) -> float:
    return draw.scene_chrome(fig, scene, tl, headline_size=headline_size)


def _empty_note(fig, tl: Timeline, message_key: str, y: float = 0.5) -> None:
    draw.empty_stage(fig, i18n.t(message_key), tl, y=y)


def _empty_card(bundle: MatchBundle, scene: dict[str, Any], path: Path, message_key: str,
                progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.06, 0.24))
    _empty_note(fig, tl, message_key)
    draw.save_figure(fig, path)


def _stats_pair(bundle: MatchBundle, audit: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    stats = audit.get("team_stats") or {}
    return stats.get(bundle.home, {}) or {}, stats.get(bundle.away, {}) or {}


def _team_key_row(fig, design: dict[str, Any], bundle: MatchBundle, y: float, alpha: float) -> None:
    home, away = design["home"], design["away"]
    draw.team_badge(fig, bundle.home, Layout.MARGIN + 0.052, y, 0.098, identity=home, alpha=alpha)
    draw.fit_text(
        fig, Layout.MARGIN + 0.118, y, bundle.home.upper(), fontsize=27,
        max_width=0.30, max_lines=1, min_fontsize=13, ha="left", va="center",
        color=home["chart"], family=theme.DISPLAY_FONT, fontweight="bold", alpha=alpha, zorder=20,
    )
    draw.team_badge(fig, bundle.away, 1 - Layout.MARGIN - 0.052, y, 0.098, identity=away, alpha=alpha)
    draw.fit_text(
        fig, 1 - Layout.MARGIN - 0.118, y, bundle.away.upper(), fontsize=27,
        max_width=0.30, max_lines=1, min_fontsize=13, ha="right", va="center",
        color=away["chart"], family=theme.DISPLAY_FONT, fontweight="bold", alpha=alpha, zorder=20,
    )


def _radar_axes() -> list[str]:
    return [
        "shots", "shots_on_target", "big_chances", "possession_pct",
        "pass_share_pct", "penalty_box_touches", "xg", "tackles_won", "saves", "goals",
    ]


def render_stat_slam(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                     path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    key = (scene.get("stat_keys") or pick_stat_rows(bundle, audit, limit=1) or ["shots"])[0]
    leader = scene.get("hero_team") or dominant_team(bundle, audit, key) or bundle.home
    identity = design["home"] if leader == bundle.home else design["away"]
    value = stats.get(leader, {}).get(key, scene.get("hero_number") or 0)
    other = bundle.away if leader == bundle.home else bundle.home
    other_value = stats.get(other, {}).get(key, 0)
    other_identity = design["away"] if leader == bundle.home else design["home"]

    content_top = _chrome(fig, scene, tl)
    if key.endswith("_pct"):
        _slam_waffle(fig, design, bundle, key, stats, tl, top=content_top - 0.04)
    elif float(max(value or 0, other_value or 0)) <= 0 or key in {"xg", "xgot"}:
        _slam_bars(fig, key, (leader, identity, float(value or 0)), (other, other_identity, float(other_value or 0)),
                   tl, top=content_top - 0.06)
    else:
        _slam_units(fig, key, (leader, identity, float(value or 0)), (other, other_identity, float(other_value or 0)),
                    tl, top=content_top - 0.03)
    draw.save_figure(fig, path)


def _slam_units(fig, key: str, lead: tuple[str, dict[str, str], float], trail: tuple[str, dict[str, str], float],
                tl: Timeline, *, top: float) -> None:
    """One dot per unit. The longer block is the story; the count sits beside it, quietly."""
    peak = max(lead[2], trail[2], 1.0)
    unit = 1 if peak <= 40 else int(math.ceil(peak / 40.0))
    units_peak = int(math.ceil(peak / unit))
    cols = 10 if units_peak > 10 else max(4, units_peak)
    step = min(0.17, Layout.CONTENT_W * 0.86 / cols)
    floor = Layout.STAGE_BOTTOM + 0.11
    rows_needed = [max(1, int(math.ceil(math.ceil(v / unit) / cols))) for _, _, v in (lead, trail)]
    block_gap = 0.075
    needed = sum(draw.y_of(step) * rows for rows in rows_needed) + 2 * 0.068 + block_gap
    if needed > top - floor:
        step *= (top - floor) / needed
        needed = sum(draw.y_of(step) * rows for rows in rows_needed) + 2 * 0.068 + block_gap
    radius = step * 0.36
    y = top - max(0.0, (top - floor - needed) / 2)
    for slot, ((name, identity, value), rows) in enumerate(zip((lead, trail), rows_needed)):
        ink = tl.cue(0.06 + 0.10 * slot, 0.24)
        draw.team_badge(fig, name, Layout.MARGIN + 0.036, y - 0.024, 0.062, identity=identity, alpha=ink)
        draw.fit_text(fig, Layout.MARGIN + 0.082, y - 0.024, name.upper(), fontsize=24, max_width=0.56,
                      max_lines=1, min_fontsize=12, ha="left", va="center", color=identity["chart"],
                      family=theme.DISPLAY_FONT, fontweight="bold", alpha=ink, zorder=20)
        shown = draw.hold_count(value, tl.cue(0.10 + 0.10 * slot, 0.46, ease=draw.ease_out_quint))
        draw.data_label(fig, 1 - Layout.MARGIN, y - 0.024, format_stat(key, shown), size=26, alpha=ink, ha="right")
        dots = int(math.ceil(value / unit)) if value > 0 else 0
        grid_top = y - 0.068
        x0 = 0.5 - step * cols / 2 + step / 2
        if dots == 0 and ink > draw.VISIBLE_ALPHA:
            draw.fig_ellipse(fig, x0, grid_top - draw.y_of(step) / 2, radius, facecolor="none",
                             edgecolor=TEXT_FAINT, linewidth=1.4, alpha=ink, zorder=14)
        for index in range(dots):
            pop = tl.stagger(index, max(1, dots), start=0.12 + 0.12 * slot, span=0.34, duration=0.14,
                             ease=draw.ease_out_back)
            if pop <= 0.02:
                continue
            row, col = divmod(index, cols)
            cx = x0 + col * step
            cy = grid_top - draw.y_of(step) * (row + 0.5)
            glow = identity["chart"]
            draw.fig_ellipse(fig, cx, cy, radius * 1.45 * min(1.0, pop), facecolor=glow, edgecolor="none",
                             alpha=0.12 * draw.opacity(pop), zorder=13)
            draw.fig_ellipse(fig, cx, cy, radius * min(1.12, pop), facecolor=identity["chart"],
                             edgecolor=theme.mix(identity["chart"], "#ffffff", 0.4), linewidth=1.0,
                             alpha=draw.opacity(pop), zorder=14)
        y = grid_top - draw.y_of(step) * rows - block_gap
    if unit > 1:
        _unit_note(fig, i18n.t("dot_equals", n=unit, stat=stat_label(key).lower()), tl)


def _slam_waffle(fig, design: dict[str, Any], bundle: MatchBundle, key: str, stats: dict[str, Any],
                 tl: Timeline, *, top: float) -> None:
    """Ten by ten: every square is one percent."""
    home_pct = float((stats.get(bundle.home) or {}).get(key) or 0)
    away_pct = float((stats.get(bundle.away) or {}).get(key) or 0)
    total = home_pct + away_pct
    home_cells = int(round(100 * home_pct / total)) if total > 0 else 50
    size = Layout.CONTENT_W * 0.72
    step = size / 10
    x0 = 0.5 - size / 2
    grid_top = top - 0.09
    ink = tl.cue(0.06, 0.24)
    draw.team_key_row(fig, design, bundle.home, bundle.away, top - 0.030, ink)
    for index in range(100):
        pop = tl.stagger(index, 100, start=0.10, span=0.40, duration=0.10, ease=draw.ease_out_back)
        if pop <= 0.02:
            continue
        row, col = divmod(index, 10)
        identity = design["home"] if index < home_cells else design["away"]
        cell = step * 0.84 * min(1.0, pop)
        cx = x0 + col * step + step / 2
        cy = grid_top - draw.y_of(step) * (row + 0.5)
        draw.fig_panel(fig, cx - cell / 2, cy - draw.y_of(cell) / 2, cell, draw.y_of(cell),
                       color=identity["chart"], alpha=draw.opacity(pop), edge="none", radius=cell * 0.22, zorder=14)
    label_y = grid_top - draw.y_of(size) - 0.040
    ink = tl.cue(0.46, 0.24)
    draw.data_label(fig, x0, label_y, format_stat(key, home_pct), size=26, alpha=ink, ha="left")
    draw.data_label(fig, x0 + size, label_y, format_stat(key, away_pct), size=26, alpha=ink, ha="right")
    _unit_note(fig, i18n.t("square_equals"), tl)


def _slam_bars(fig, key: str, lead: tuple[str, dict[str, str], float], trail: tuple[str, dict[str, str], float],
               tl: Timeline, *, top: float) -> None:
    peak = max(lead[2], trail[2], 1e-6)
    for slot, (name, identity, value) in enumerate((lead, trail)):
        y = top - 0.06 - slot * 0.20
        ink = tl.cue(0.06 + 0.10 * slot, 0.24)
        draw.team_badge(fig, name, Layout.MARGIN + 0.036, y + 0.050, 0.062, identity=identity, alpha=ink)
        draw.fit_text(fig, Layout.MARGIN + 0.082, y + 0.050, name.upper(), fontsize=24, max_width=0.56,
                      max_lines=1, min_fontsize=12, ha="left", va="center", color=identity["chart"],
                      family=theme.DISPLAY_FONT, fontweight="bold", alpha=ink, zorder=20)
        grown = tl.cue(0.12 + 0.10 * slot, 0.44, ease=draw.ease_in_out)
        width = Layout.CONTENT_W * (value / peak) * grown
        draw.fig_panel(fig, Layout.MARGIN, y - 0.022, Layout.CONTENT_W, 0.044, color="#141a17",
                       alpha=ink, edge="none", radius=0.018, zorder=12)
        if width > 0.004:
            draw.fig_panel(fig, Layout.MARGIN, y - 0.022, width, 0.044, color=identity["chart"],
                           alpha=0.96, edge="none", radius=min(0.018, width / 2), zorder=13)
        draw.data_label(fig, 1 - Layout.MARGIN, y + 0.050, format_stat(key, draw.hold_count(value, grown)),
                        size=26, alpha=ink, ha="right")


def _unit_note(fig, text: str, tl: Timeline) -> None:
    alpha = tl.cue(0.50, 0.24)
    if alpha < draw.VISIBLE_ALPHA:
        return
    fig.text(0.5, Layout.STAGE_BOTTOM + 0.098, text.upper(), color=TEXT_FAINT, fontsize=theme.label_size(9),
             family=theme.LABEL_FONT, fontweight="bold", ha="center", va="center", alpha=alpha, zorder=20)


def render_match_radar(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                       path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    source_supported = set(audit.get("source_supported_stats") or [])
    keys = [
        key for key in _radar_axes()
        if key in home and key in away
        and (not source_supported or key in source_supported or key == "goals")
    ]
    if len(keys) < 3:
        keys = [key for key in _radar_axes() if key in home and key in away][:4]

    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))

    rect = [0.17, 0.23, 0.66, 0.50]
    ax = fig.add_axes(rect, zorder=6)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_aspect("equal")

    maxima = [max(float(home.get(key) or 0), float(away.get(key) or 0), 1.0) for key in keys]
    home_vals = [float(home.get(key) or 0) / peak for key, peak in zip(keys, maxima)]
    away_vals = [float(away.get(key) or 0) / peak for key, peak in zip(keys, maxima)]
    grown = tl.cue(0.08, 0.52, ease=draw.ease_in_out)
    grid_alpha = tl.cue(0.04, 0.28, ease=draw.ease_in_out)

    count = len(keys)
    if grid_alpha > 0.02:
        for band, ring in enumerate((1.0, 0.75, 0.5, 0.25)):
            xs, ys = [], []
            for index in range(count):
                angle = index * math.tau / count + math.pi / 2
                xs.append(0.5 + math.cos(angle) * 0.48 * ring)
                ys.append(0.5 + math.sin(angle) * 0.48 * ring)
            xs.append(xs[0])
            ys.append(ys[0])
            ax.fill(xs, ys, color="#0d100f" if band % 2 == 0 else "#080a09", alpha=grid_alpha,
                    zorder=3, linewidth=0)
            ax.plot(xs, ys, color=design["hairline"], lw=0.8, alpha=0.7 * grid_alpha, zorder=4)
            ax.plot([0.5, xs[0]], [0.5, ys[0]], color=design["hairline"], lw=0.6,
                    alpha=0.35 * grid_alpha, zorder=4)
        for index in range(count):
            angle = index * math.tau / count + math.pi / 2
            ax.plot([0.5, 0.5 + math.cos(angle) * 0.48], [0.5, 0.5 + math.sin(angle) * 0.48],
                    color=design["hairline"], lw=0.7, alpha=0.45 * grid_alpha, zorder=4)

    draw.radar_polygon(ax, home_vals, design["home"]["chart"], progress=grown, fill_alpha=0.32, lw=2.4)
    draw.radar_polygon(ax, away_vals, design["away"]["chart"], progress=grown, fill_alpha=0.28, lw=2.4)

    label_alpha = tl.cue(0.28, 0.30)
    if label_alpha > draw.VISIBLE_ALPHA:
        for index, key in enumerate(keys):
            angle = index * math.tau / count + math.pi / 2
            lx = 0.5 + math.cos(angle) * 0.60
            ly = 0.5 + math.sin(angle) * 0.60
            ax.text(lx, ly + 0.012, "\n".join(_wrap_label(stat_label(key).upper(), 10)), color=TEXT_DIM,
                    fontsize=theme.label_size(8.6), family=theme.LABEL_FONT, fontweight="bold",
                    ha="center", va="bottom", alpha=label_alpha, zorder=12, linespacing=0.95)
            ax.text(lx, ly - 0.004, f"{format_stat(key, home.get(key) or 0)}  ·  {format_stat(key, away.get(key) or 0)}",
                    color=theme.NUMBER_INK, fontsize=10.5, family=theme.LABEL_FONT, fontweight="bold",
                    ha="center", va="top", alpha=label_alpha, zorder=12)
    draw.save_figure(fig, path)


def _wrap_label(text: str, width: int = 12) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines[:2] or [text]


def render_touch_heatmap(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    """Crisp touch-territory mosaic.

    The old blurred red/blue wash hid the pitch and looked like compression
    noise. Hex cells show the dominant side and volume at each real touch bin;
    no interpolation invents activity between coordinates.
    """
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    heat = audit.get("touch_heatmap") or {}
    content_top = _chrome(fig, scene, tl)
    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.02, bottom=0.16)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))
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
    cells = cells[:110]
    maximum = max((cell[0] for cell in cells), default=1.0)
    shown = tl.reveal_count(len(cells), start=0.08, span=0.62)
    x_bins = max(1, int(heat.get("x_bins") or len(home_grid) or 1))
    y_bins = max(1, int(heat.get("y_bins") or (len(home_grid[0]) if home_grid else 1)))
    draw.pitch_grid_fade(ax, alpha=0.035 * tl.cue(0.08, 0.24))
    for index, (total, xi, yi, home_value, away_value) in enumerate(cells[:shown]):
        local = tl.stagger(index, max(1, len(cells)), start=0.08, span=0.60, duration=0.18)
        share = home_value / total if total else 0.5
        identity = design["home"] if share >= 0.5 else design["away"]
        dominance = abs(share - 0.5) * 2.0
        px = draw.pitch_column(yi, y_bins)
        py = (xi + 0.5) * 100.0 / x_bins
        size = (34.0 + 250.0 * (total / maximum) ** 0.72) * local
        ax.scatter(
            [px], [py], s=size, marker="h",
            facecolor=identity["fill"], edgecolor=identity["chart"],
            linewidth=0.7 + 0.8 * dominance,
            alpha=draw.opacity((0.22 + 0.60 * dominance) * local),
            zorder=6 + index * 0.001,
        )
    draw.legend_row(
        fig, 0.118,
        [("bar", design["home"]["fill"], bundle.home), ("bar", design["away"]["fill"], bundle.away)],
        alpha=tl.cue(0.40, 0.26), fontsize=theme.label_size(10),
    )
    draw.save_figure(fig, path)


def render_field_tilt_wave(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                           path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    rows = audit.get("field_tilt") or []
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if len(rows) < 2:
        _empty_note(fig, tl, "pressure_curve_empty")
        draw.save_figure(fig, path)
        return

    chart_top = content_top - 0.08
    rect = [Layout.MARGIN, 0.18, Layout.CONTENT_W, chart_top - 0.18]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#0b0f0d")
    for spine in ax.spines.values():
        spine.set_visible(False)
    starts = np.array([row["start"] for row in rows], dtype=float)
    home = np.array([row["home_tilt_pct"] for row in rows], dtype=float)
    away = np.array([row["away_tilt_pct"] for row in rows], dtype=float)
    span = max(1.0, float(starts[-1] + (rows[-1]["end"] - rows[-1]["start"])))
    ax.set_xlim(0, span)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75])
    ax.set_yticklabels(["25", "50", "75"], color=TEXT_FAINT, fontsize=9, family=theme.MONO_FONT)
    ax.tick_params(axis="x", length=0)
    ax.set_xticks(starts[:: max(1, len(starts) // 6)])
    ax.set_xticklabels(
        [row["minute_block"] for row in rows][:: max(1, len(rows) // 6)],
        color=TEXT_FAINT, fontsize=9, family=theme.MONO_FONT,
    )

    reveal = tl.wipe(0.02, 0.58)
    cutoff = span * reveal
    dense_x, home_y = _smooth_series(starts, home, cutoff)
    _, away_y = _smooth_series(starts, away, cutoff)
    tick_alpha = min(1.0, reveal * 2.0)
    ax.tick_params(axis="x", length=0, colors=TEXT_FAINT)
    for label in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        label.set_alpha(tick_alpha)
    ax.axhline(50, color=design["pitch_line"], lw=1.2, alpha=0.8 * tick_alpha, zorder=5)
    if len(dense_x) > 1:
        ax.fill_between(dense_x, 50, home_y, color=design["home"]["fill"], alpha=0.55, linewidth=0, zorder=4)
        ax.fill_between(dense_x, 50, away_y, color=design["away"]["fill"], alpha=0.50, linewidth=0, zorder=4)
        ax.plot(dense_x, home_y, color=design["home"]["chart"], lw=2.4, zorder=8)
        ax.plot(dense_x, away_y, color=design["away"]["chart"], lw=2.4, zorder=8)

    peak = max(rows, key=lambda row: max(row["home_tilt_pct"], row["away_tilt_pct"]))
    peak_alpha = tl.cue(0.50, 0.28)
    if peak_alpha > 0.02:
        at = (peak["start"] + peak["end"]) / 2
        pct = max(peak["home_tilt_pct"], peak["away_tilt_pct"])
        colour = design["home"]["chart"] if peak["home_tilt_pct"] >= peak["away_tilt_pct"] else design["away"]["chart"]
        ax.axvline(at, color=colour, lw=1.6, alpha=0.7 * peak_alpha, zorder=9)
        ax.scatter([at], [pct], s=90, color=colour, edgecolor=TEXT, linewidth=1.1, zorder=10, alpha=peak_alpha)
        ax.text(at, min(96, pct + 6), f"{int(pct)}%", color=colour, fontsize=12,
                family=theme.MONO_FONT, fontweight="bold", ha="center", va="bottom",
                path_effects=draw.outline(peak_alpha), alpha=peak_alpha, zorder=12)
    draw.save_figure(fig, path)


def render_conversion_gauges(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                             path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    content_top = _chrome(fig, scene, tl)
    grown = tl.cue(0.08, 0.52, ease=draw.ease_in_out)

    pairs = (
        (0.28, bundle.home, home, design["home"]),
        (0.72, bundle.away, away, design["away"]),
    )
    health = audit.get("data_health") or {}
    source_supported = set(audit.get("source_supported_stats") or [])
    use_xg = bool(health.get("has_vendor_xg"))
    for cx, name, team, identity in pairs:
        ax = fig.add_axes([cx - 0.16, 0.38, 0.32, 0.32], zorder=6)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_axis_off()
        ax.set_aspect("equal")
        shots = float(team.get("shots") or 0)
        outer_key = (
            "shots_on_target"
            if not source_supported or "shots_on_target" in source_supported
            else "big_chances"
            if "big_chances" in source_supported
            else "shots"
        )
        on = float(team.get(outer_key) or 0)
        goals = float(team.get("goals") or 0)
        if use_xg and team.get("xg") is not None:
            inner_value, inner_max, inner_label = float(team.get("xg") or 0), max(shots / 4, 1.5), "xG"
        else:
            inner_value, inner_max, inner_label = goals, max(on, 1.0), i18n.t("goals")
        draw.ring_gauge(ax, 0.5, 0.52, on, max(shots, 1.0), identity["chart"],
                        progress=grown, radius=0.38, width=0.07, zorder=8)
        draw.ring_gauge(ax, 0.5, 0.52, inner_value, inner_max, identity.get("fill") or identity["primary"],
                        progress=grown, radius=0.28, width=0.06, zorder=9)
        shown_on = tl.count_to(on, start=0.12, duration=0.50)
        shown_inner = tl.count_to(inner_value, start=0.12, duration=0.50)
        ax.text(0.5, 0.52, f"{int(round(shown_on))}" if not use_xg else f"{shown_inner:.1f}",
                color=TEXT, fontsize=36, fontweight="bold", family=theme.DISPLAY_FONT,
                ha="center", va="center", alpha=grown, zorder=12)
        inner_shown = format_stat("xg", shown_inner) if use_xg else str(int(round(shown_inner)))
        fig.text(
            cx, 0.30,
            name.upper(),
            color=identity["chart"], fontsize=14, family=theme.MONO_FONT, fontweight="bold",
            ha="center", va="center", alpha=tl.cue(0.28, 0.24), zorder=20,
        )
        fig.text(
            cx, 0.24,
            f"{int(round(shown_on))} {stat_label(outer_key).upper()}  ·  {str(inner_label).upper()} {inner_shown}",
            color=TEXT_DIM, fontsize=theme.label_size(11), family=theme.LABEL_FONT,
            fontweight="bold", ha="center", va="center", alpha=tl.cue(0.36, 0.24), zorder=20,
        )
    draw.save_figure(fig, path)


def render_chance_funnel(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))

    source_supported = set(audit.get("source_supported_stats") or [])
    if source_supported:
        candidates = [
            ("possession_pct", stat_label("possession_pct"), True),
            ("penalty_box_touches", stat_label("penalty_box_touches"), False),
            ("shots", stat_label("shots"), False),
            ("big_chances", stat_label("big_chances"), False),
            ("goals", stat_label("goals"), False),
        ]
        funnel = [
            row for row in candidates
            if row[0] == "goals" or row[0] in source_supported
        ]
    else:
        funnel = [
            ("pass_share_pct", i18n.t("pass_share"), True),
            ("final_third_passes", i18n.t("final_third_short"), False),
            ("box_entry_passes", i18n.t("into_box_short"), False),
            ("shots", stat_label("shots"), False),
            ("shots_on_target", stat_label("shots_on_target"), False),
            ("goals", stat_label("goals"), False),
        ]
    top = content_top - 0.078
    bottom = Layout.STAGE_BOTTOM + 0.050
    step = (top - bottom) / len(funnel)
    for index, (key, label, percent) in enumerate(funnel):
        local = tl.stagger(index, len(funnel), start=0.10, span=0.52, duration=0.28)
        if local <= 0.01:
            continue
        home_v = float(home.get(key) or 0)
        away_v = float(away.get(key) or 0)
        total = home_v + away_v
        share = 0.5 if total <= 0 else home_v / total
        taper = index / max(1, len(funnel) - 1)
        total_w = (0.70 - 0.18 * taper) * (0.55 + 0.45 * local)
        height = step * 0.50
        y = top - step * (index + 1) + 0.010
        ink = min(1.0, local * 2.0)
        fig.text(
            0.5, y + height + 0.015, str(label).upper(),
            color=TEXT_DIM, fontsize=theme.label_size(11), family=theme.LABEL_FONT,
            fontweight="bold", ha="center", va="center", alpha=ink, zorder=14,
        )
        gap = 0.008
        home_w = max(0.11, (total_w - gap) * share) if home_v > 0 else 0.0
        away_w = max(0.11, (total_w - gap) * (1.0 - share)) if away_v > 0 else 0.0
        if home_v > 0 and away_v > 0 and home_w + away_w + gap > total_w:
            scale = (total_w - gap) / (home_w + away_w)
            home_w *= scale
            away_w *= scale
        used = (home_w + away_w + (gap if home_w and away_w else 0.0))
        x = 0.5 - used / 2
        suffix = "%" if percent else ""
        if home_w:
            draw.fig_panel(
                fig, x, y, home_w, height,
                color=design["home"]["chart"], alpha=0.94 * draw.opacity(local),
                edge="none", radius=0.014, zorder=12,
            )
            fig.text(
                x + home_w / 2, y + height / 2,
                draw.number_text(draw.hold_count(home_v, local), suffix=suffix),
                color=theme.ink_on(design["home"]["chart"]), fontsize=26,
                fontweight="bold", family=theme.DISPLAY_FONT,
                ha="center", va="center", alpha=ink, zorder=14,
            )
            x += home_w + gap
        else:
            fig.text(
                0.5 - total_w / 2 - 0.018, y + height / 2,
                draw.number_text(0, suffix=suffix),
                color=design["home"]["chart"], fontsize=22, fontweight="bold",
                family=theme.DISPLAY_FONT, ha="right", va="center", alpha=ink, zorder=14,
            )
        if away_w:
            draw.fig_panel(
                fig, x, y, away_w, height,
                color=design["away"]["chart"], alpha=0.94 * draw.opacity(local),
                edge="none", radius=0.014, zorder=12,
            )
            fig.text(
                x + away_w / 2, y + height / 2,
                draw.number_text(draw.hold_count(away_v, local), suffix=suffix),
                color=theme.ink_on(design["away"]["chart"]), fontsize=26,
                fontweight="bold", family=theme.DISPLAY_FONT,
                ha="center", va="center", alpha=ink, zorder=14,
            )
        else:
            fig.text(
                0.5 + total_w / 2 + 0.018, y + height / 2,
                draw.number_text(0, suffix=suffix),
                color=design["away"]["chart"], fontsize=22, fontweight="bold",
                family=theme.DISPLAY_FONT, ha="left", va="center", alpha=ink, zorder=14,
            )
    draw.save_figure(fig, path)


def render_keeper_frame(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    content_top = _chrome(fig, scene, tl)
    on_target = [
        shot for shot in audit.get("shots") or []
        if shot.get("outcome") in {"goal", "saved"}
        and shot.get("goal_mouth_y") is not None
        and shot.get("goal_mouth_z") is not None
    ]
    if len(on_target) < 2:
        _empty_note(fig, tl, "too_few_shots_frame")
        draw.save_figure(fig, path)
        return

    key_row_y = content_top - 0.028
    _team_key_row(fig, design, bundle, key_row_y, tl.cue(0.08, 0.24))
    rect = draw.goal_frame_rect(key_row_y - 0.046, 0.210)
    ax = draw.goal_frame_axes(fig, rect)
    frame_alpha = tl.cue(0.06, 0.26)
    draw.paint_goal_frame(ax, design, alpha=frame_alpha)

    visible = tl.reveal_count(len(on_target), start=0.14, span=0.52)
    dots: dict[str, dict[str, list]] = {
        "save": {"x": [], "y": [], "s": [], "c": [], "a": []},
        "goal": {"x": [], "y": [], "s": [], "c": [], "a": []},
    }
    for index, shot in enumerate(on_target):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(on_target)), start=0.14, span=0.52, duration=0.18,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        mx, mz = draw.goal_mouth_metres(shot["goal_mouth_y"], shot["goal_mouth_z"])
        is_goal = shot["outcome"] == "goal"
        colour = design["goal"] if is_goal else theme.side_color(design, shot["h_a"])
        size = (250 if is_goal else 145) * (0.70 + 0.30 * local)
        if shot.get("big_chance"):
            size *= 1.12
        batch = dots["goal" if is_goal else "save"]
        batch["x"].append(mx)
        batch["y"].append(mz)
        batch["s"].append(size)
        batch["c"].append(colour)
        batch["a"].append(draw.opacity(0.88 * local))
        if is_goal and local > 0.45:
            draw.glow_ring(ax, mx, mz, design["goal"], radius=0.22,
                           alpha=0.36 * local, zorder=11)

    draw.scatter_batch(ax, dots["save"]["x"], dots["save"]["y"],
                       sizes=dots["save"]["s"], colors=dots["save"]["c"],
                       alphas=dots["save"]["a"], linewidth=0.8, zorder=15)
    draw.scatter_batch(ax, dots["goal"]["x"], dots["goal"]["y"],
                       sizes=dots["goal"]["s"], colors=dots["goal"]["c"],
                       alphas=dots["goal"]["a"], linewidth=1.6, edgecolor=TEXT, zorder=16)

    legend_y = rect[1] - 0.030
    draw.legend_row(
        fig, legend_y,
        [("dot", design["goal"], i18n.t("outcome_goal")),
         ("dot", design["home"]["chart"], _short_team(bundle.home)),
         ("dot", design["away"]["chart"], _short_team(bundle.away))],
        alpha=tl.cue(0.48, 0.26), fontsize=theme.label_size(10),
    )
    stats = audit.get("team_stats") or {}
    keys = ["shots_on_target", "saves", "goals"]
    top = legend_y - 0.048
    floor = Layout.STAGE_BOTTOM + 0.034
    step = (top - floor) / len(keys)
    for index, key in enumerate(keys):
        local = tl.stagger(index, len(keys), start=0.18, span=0.36, duration=0.28,
                           ease=draw.ease_in_out)
        if local <= 0.01:
            continue
        y = top - step * (index + 1) + step * 0.30
        draw.comparison_bar(
            fig, y, stat_label(key),
            float((stats.get(bundle.home) or {}).get(key) or 0),
            float((stats.get(bundle.away) or {}).get(key) or 0),
            design["home"]["chart"], design["away"]["chart"], progress=local,
        )
    draw.save_figure(fig, path)


def render_xg_race(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                   path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    health = audit.get("data_health") or {}
    shots = sorted(
        [shot for shot in (audit.get("shots") or []) if shot.get("xg") is not None and shot.get("minute") is not None],
        key=lambda shot: float(shot["minute"]),
    )
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if not health.get("has_vendor_xg") or len(shots) < 2:
        _empty_note(fig, tl, "empty_xg_race", y=0.48)
        draw.save_figure(fig, path)
        return

    home_x, home_y, away_x, away_y = [0.0], [0.0], [0.0], [0.0]
    h_sum = a_sum = 0.0
    for shot in shots:
        if shot["h_a"] == "h":
            h_sum += float(shot["xg"] or 0)
            home_x.append(float(shot["minute"]))
            home_y.append(h_sum)
        else:
            a_sum += float(shot["xg"] or 0)
            away_x.append(float(shot["minute"]))
            away_y.append(a_sum)
    last = max(home_x[-1], away_x[-1], 90.0)
    home_x.append(last)
    home_y.append(home_y[-1])
    away_x.append(last)
    away_y.append(away_y[-1])

    shown_h = tl.count_to(home_y[-1], start=0.12, duration=0.50)
    shown_a = tl.count_to(away_y[-1], start=0.16, duration=0.50)
    draw.data_label(fig, Layout.MARGIN + 0.02, content_top - 0.072, f"{shown_h:.2f}", size=28,
                    alpha=tl.cue(0.14, 0.24), ha="left")
    draw.data_label(fig, 1 - Layout.MARGIN - 0.02, content_top - 0.072, f"{shown_a:.2f}", size=28,
                    alpha=tl.cue(0.18, 0.24), ha="right")

    rect = [Layout.MARGIN, 0.20, Layout.CONTENT_W, content_top - 0.34]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#0b0f0d")
    for spine in ax.spines.values():
        spine.set_visible(False)
    peak = max(home_y[-1], away_y[-1], 0.6) * 1.18
    ax.set_xlim(0, last)
    ax.set_ylim(0, peak)
    ax.tick_params(colors=TEXT_FAINT, labelsize=9)
    reveal = tl.wipe(0.02, 0.58)
    cut = last * reveal
    hx = np.array(home_x)
    hy = np.array(home_y)
    ax_ = np.array(away_x)
    ay = np.array(away_y)
    ax.fill_between(hx[hx <= cut + 0.01], 0, hy[: len(hx[hx <= cut + 0.01])],
                    color=design["home"]["fill"], alpha=0.35, step="post", zorder=4)
    ax.fill_between(ax_[ax_ <= cut + 0.01], 0, ay[: len(ax_[ax_ <= cut + 0.01])],
                    color=design["away"]["fill"], alpha=0.32, step="post", zorder=4)
    ax.step(hx[hx <= cut + 0.01], hy[: len(hx[hx <= cut + 0.01])],
            where="post", color=design["home"]["chart"], lw=3.2, zorder=8)
    ax.step(ax_[ax_ <= cut + 0.01], ay[: len(ax_[ax_ <= cut + 0.01])],
            where="post", color=design["away"]["chart"], lw=3.2, zorder=8)
    goals = [goal for goal in (audit.get("goal_timeline") or []) if float(goal.get("minute") or 0) <= cut + 1]
    for index, goal in enumerate(goals):
        minute = float(goal.get("minute") or 0)
        colour = theme.side_color(design, goal["h_a"])
        ax.axvline(minute, color=colour, lw=1.3, alpha=0.45 * tl.cue(0.40, 0.24), zorder=7)
        local = tl.stagger(index, max(1, len(goals)), start=0.40, span=0.28, duration=0.16)
        draw.freeze_frame_badge(
            ax, minute, peak * 0.08, index + 1, colour,
            alpha=local, radius=max(1.6, last * 0.018), latest=index == len(goals) - 1,
        )
    draw.save_figure(fig, path)


def render_time_zones(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    slices = audit.get("time_zones") or []
    content_top = _chrome(fig, scene, tl)
    if len(slices) < 3:
        _empty_note(fig, tl, "no_touch_coords")
        draw.save_figure(fig, path)
        return

    band_top = content_top - 0.02
    band_bottom = 0.16
    slot_h = (band_top - band_bottom) / 3
    home_c, away_c = design["home"]["fill"], design["away"]["fill"]
    for index, slice_ in enumerate(slices[:3]):
        local = tl.stagger(index, 3, start=0.08, span=0.42, duration=0.32)
        if local <= 0.01:
            continue
        top = band_top - slot_h * index
        bottom = top - slot_h + 0.018
        fig.text(Layout.MARGIN, top - 0.012, slice_.get("label", ""), color=TEXT_DIM,
                 fontsize=theme.label_size(12), family=theme.MONO_FONT, fontweight="bold",
                 ha="left", va="center", alpha=local, zorder=20)
        rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=top - 0.028, bottom=bottom, align="center")
        # Shrink height to the slot.
        rect[1] = bottom
        rect[3] = max(0.08, top - 0.028 - bottom)
        ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                                 alpha=0.35 * local, lw=0.9)
        zones = slice_.get("zones") or []
        if not zones:
            continue
        x_bins = max(z["xbin"] for z in zones) + 1
        y_bins = max(z["ybin"] for z in zones) + 1
        grid = np.zeros((x_bins, y_bins, 4))
        busiest = max((z["total_touches"] for z in zones), default=1) or 1
        for zone in zones:
            share = zone["home_share_pct"] / 100.0
            base = home_c if share >= 0.5 else away_c
            r, g, b = theme.hex_to_rgb(base)
            weight = 0.15 + 0.75 * (zone["total_touches"] / busiest)
            grid[zone["xbin"], zone["ybin"], 0] = r
            grid[zone["xbin"], zone["ybin"], 1] = g
            grid[zone["xbin"], zone["ybin"], 2] = b
            grid[zone["xbin"], zone["ybin"], 3] = weight * local
        ax.imshow(grid[:, ::-1], origin="lower", extent=(0, 100, 0, 100), interpolation="bilinear",
                  aspect="auto", zorder=5)
        leader = bundle.home if slice_.get("home_touches", 0) >= slice_.get("away_touches", 0) else bundle.away
        fig.text(1 - Layout.MARGIN, top - 0.012, leader.upper(),
                 color=design["home"]["chart"] if leader == bundle.home else design["away"]["chart"],
                 fontsize=theme.label_size(11), family=theme.DISPLAY_FONT, fontweight="bold",
                 ha="right", va="center", alpha=local, zorder=20)
    draw.save_figure(fig, path)


def render_player_spike(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    """One player vs the rest of their team — giant jersey, not a pitch clone."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    spike = (audit.get("player_leaders") or {}).get("spike") or {}
    content_top = _chrome(fig, scene, tl)
    if not spike:
        _empty_note(fig, tl, "empty_spike")
        draw.save_figure(fig, path)
        return

    identity = design["home"] if spike.get("h_a") == "h" else design["away"]
    shirt = spike.get("shirt")
    shirt_label = str(int(shirt)) if shirt not in (None, "") else ""
    if shirt_label:
        # Poster background: huge jersey, readable on a phone but behind the hero count.
        fig.text(
            0.5, 0.54, shirt_label,
            color=identity["chart"], fontsize=292, fontweight="bold",
            family=theme.DISPLAY_FONT, ha="center", va="center",
            alpha=0.22 * tl.cue(0.06, 0.28), zorder=6,
        )
        fig.text(
            0.5, 0.445, f"#{shirt_label}",
            color=identity["chart"], fontsize=22, fontweight="bold",
            family=theme.MONO_FONT, ha="center", va="center",
            alpha=0.85 * tl.cue(0.18, 0.24), zorder=20,
        )

    count = int(spike.get("count") or 0)
    rest = int(spike.get("rest") or 0)
    shown = int(round(tl.count_to(count, start=0.08, duration=0.42)))
    draw.hero_number(fig, 0.5, 0.58, shown, color=TEXT,
                     alpha=tl.cue(0.08, 0.34, ease=draw.ease_out_back), fontsize=132.0)
    fig.text(
        0.5, 0.38, f"{str(spike.get('surname') or spike.get('player') or '').upper()}",
        color=TEXT, fontsize=36, family=theme.DISPLAY_FONT, fontweight="bold",
        ha="center", va="center", alpha=tl.cue(0.22, 0.24), zorder=22,
    )
    fig.text(
        0.5, 0.325, i18n.spike_action_label(str(spike.get("action") or "")).upper(),
        color=TEXT_DIM, fontsize=18, family=theme.MONO_FONT, fontweight="bold",
        ha="center", va="center", alpha=tl.cue(0.26, 0.24), zorder=22,
    )

    vs_alpha = tl.cue(0.36, 0.28)
    total = max(1, count + rest)
    bar_w = 0.62
    left = 0.5 - bar_w / 2
    fig_y = 0.22
    draw.fig_rect(fig, left, fig_y, bar_w, 0.018, "#171d19", 0.95 * vs_alpha, zorder=10)
    spike_w = bar_w * (count / total) * vs_alpha
    rest_w = bar_w * (rest / total) * vs_alpha
    draw.fig_rect(fig, left, fig_y, spike_w, 0.018, identity["fill"], 0.95, zorder=12)
    draw.fig_rect(fig, left + spike_w, fig_y, rest_w, 0.010, TEXT_FAINT, 0.55 * vs_alpha, zorder=11)
    fig.text(
        0.5, 0.18,
        i18n.t("vs_the_rest", n=count, rest=rest),
        color=TEXT_DIM, fontsize=16, family=theme.LABEL_FONT, fontweight="bold",
        ha="center", va="center", alpha=vs_alpha, zorder=22,
    )

    points = spike.get("points") or []
    visible = tl.reveal_count(min(12, len(points)), start=0.28, span=0.36)
    if visible:
        strip = fig.add_axes([0.18, 0.255, 0.64, 0.05], zorder=8)
        strip.set_xlim(0, 1)
        strip.set_ylim(0, 1)
        strip.set_axis_off()
        xs, ys, sizes, alphas = [], [], [], []
        for index, point in enumerate(points[:visible]):
            local = tl.stagger(index, max(1, visible), start=0.28, span=0.36, duration=0.12)
            xs.append(0.06 + 0.88 * (index / max(1, visible - 1)))
            ys.append(0.5)
            sizes.append(40 + 50 * local)
            alphas.append(draw.opacity(local))
        draw.scatter_batch(strip, xs, ys, sizes=sizes, colors=[identity["fill"]] * len(xs),
                           alphas=alphas, linewidth=0.6, zorder=10)
    draw.save_figure(fig, path)


def _stamp_insight(fig, scene: dict[str, Any], tl: Timeline) -> None:
    draw.stamp_insight(fig, scene, tl)


def _smooth_series(x: np.ndarray, y: np.ndarray, cutoff: float) -> tuple[np.ndarray, np.ndarray]:
    keep = x <= max(float(x[0]), cutoff)
    if not keep.any():
        return np.array([0.0]), np.array([float(y[0]) if len(y) else 50.0])
    xs = np.append(x[keep], cutoff)
    ys = np.append(y[keep], y[keep][-1])
    if len(xs) < 3:
        return xs, ys
    dense = np.linspace(xs[0], xs[-1], 160)
    interp = np.interp(dense, xs, ys)
    kernel = np.hanning(9)
    kernel /= kernel.sum()
    pad = 4
    padded = np.pad(interp, pad, mode="edge")
    smooth = np.convolve(padded, kernel, mode="same")[pad:-pad]
    return dense, smooth


def render_shot_clock_spiral(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                             path: Path, progress: float = 1.0) -> None:
    """Shots on a match clock. Angle is minute; radius is how close to goal."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    shots = sorted(
        [shot for shot in (audit.get("shots") or []) if shot.get("minute") is not None],
        key=lambda shot: (float(shot["minute"]), float(shot.get("x") or 0)),
    )
    content_top = _chrome(fig, scene, tl)
    if len(shots) < 2:
        _empty_note(fig, tl, "empty_spiral")
        draw.save_figure(fig, path)
        return

    rect = Layout.fitted_rect(1.0, top=content_top - 0.02, bottom=0.18, align="center")
    ax = fig.add_axes(rect, zorder=6)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_aspect("equal")

    last_minute = max(90.0, max(float(s["minute"]) for s in shots))
    ring_alpha = tl.cue(0.06, 0.24)
    for ring in (0.22, 0.36, 0.50):
        ax.add_patch(Circle((0.5, 0.5), ring, fill=False, ec=design["hairline"],
                            lw=0.8, alpha=0.55 * ring_alpha, zorder=4))
    for mark, label in ((0, "0'"), (15, "15'"), (45, "45'"), (90, "90'")):
        angle = mark / last_minute * math.tau - math.pi / 2
        ax.text(
            0.5 + math.cos(angle) * 0.56, 0.5 + math.sin(angle) * 0.56, label,
            color=TEXT_FAINT, fontsize=9, family=theme.MONO_FONT, ha="center", va="center",
            alpha=ring_alpha, zorder=8,
        )

    visible = tl.reveal_count(len(shots), start=0.12, span=0.55)
    for index, shot in enumerate(shots):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(shots)), start=0.12, span=0.55, duration=0.14,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        angle = float(shot["minute"]) / last_minute * math.tau - math.pi / 2
        closeness = 1.0 - min(1.0, max(0.0, float(shot.get("x") or 50) / 100.0))
        radius = 0.20 + 0.30 * closeness
        px = 0.5 + math.cos(angle) * radius
        py = 0.5 + math.sin(angle) * radius
        colour = design["goal"] if shot.get("outcome") == "goal" else theme.side_color(design, shot.get("h_a"))
        latest = index == visible - 1
        draw.freeze_frame_badge(
            ax, px, py, index + 1, colour, alpha=local, radius=0.022, latest=latest,
        )
        if shot.get("outcome") == "goal" and local > 0.55:
            draw.glow_ring(ax, px, py, design.get("goal") or colour, radius=0.038,
                           alpha=0.28 * local, zorder=9)
    draw.save_figure(fig, path)


def render_press_trap(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Closing jaws sized by audited PPDA. Skip when the number was not audited."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    trap = audit.get("press_trap") or {}
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if not trap.get("audited"):
        _empty_note(fig, tl, "empty_trap")
        draw.save_figure(fig, path)
        return

    home = trap.get("home") or {}
    away = trap.get("away") or {}
    grown = tl.cue(0.10, 0.48, ease=draw.ease_in_out)

    def jaw(side: str, identity: dict[str, str], payload: dict[str, Any], inward: float) -> None:
        if not payload.get("audited"):
            return
        ppda = float(payload.get("ppda") or 12)
        # Lower PPDA = tighter jaws (stronger press).
        open_gap = 0.06 + 0.22 * min(1.0, ppda / 18.0)
        reach = (0.50 - open_gap) * grown
        y0, y1 = 0.22, 0.72
        if side == "home":
            points = [(0.08, y0), (0.08 + reach, 0.47), (0.08, y1)]
        else:
            points = [(0.92, y0), (0.92 - reach, 0.47), (0.92, y1)]
        fig.patches.append(
            Polygon(points, closed=True, transform=fig.transFigure,
                    facecolor=identity["fill"], edgecolor=identity["chart"],
                    linewidth=1.6, alpha=0.88 * grown, zorder=10)
        )
        actions = int(payload.get("press_actions") or 0)
        cx = 0.18 if side == "home" else 0.82
        fig.text(cx, 0.28, i18n.t("ppda_actions", n=actions), color=identity["chart"],
                 fontsize=13, family=theme.MONO_FONT, fontweight="bold",
                 ha="center", va="center", alpha=tl.cue(0.32, 0.24), zorder=16)

    jaw("home", design["home"], home, grown)
    jaw("away", design["away"], away, grown)

    leader_ppda = trap.get("leader_ppda")
    if leader_ppda is not None:
        shown = tl.count_to(float(leader_ppda), start=0.18, duration=0.40)
        draw.hero_number(fig, 0.5, 0.50, f"{shown:.1f}", color=theme.NUMBER_INK,
                         fontsize=68.0, alpha=tl.cue(0.16, 0.32))
        fig.text(0.5, 0.40, "PPDA", color=TEXT_DIM, fontsize=22, family=theme.MONO_FONT,
                 fontweight="bold", ha="center", va="center", alpha=tl.cue(0.28, 0.22), zorder=22)
    draw.save_figure(fig, path)


def render_pass_lanes(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Strongest passing lanes only — weak edges dropped, sequential reveal."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    content_top = _chrome(fig, scene, tl)
    stats = (audit.get("team_stats") or {}).get(bundle.home) or {}
    away_stats = (audit.get("team_stats") or {}).get(bundle.away) or {}
    home_passes = int(stats.get("pass_attempts") or 0)
    away_passes = int(away_stats.get("pass_attempts") or 0)
    focus = bundle.home if home_passes >= away_passes else bundle.away
    h_a = "h" if focus == bundle.home else "a"
    identity = design["home" if h_a == "h" else "away"]
    network = build_pass_network(bundle, h_a, max_edges=10)
    nodes = network.get("nodes") or {}
    max_edge = max(1, int(network.get("max_edge") or 1))
    edges = [edge for edge in (network.get("edges") or []) if int(edge.get("count") or 0) >= max(3, max_edge * 0.40)]
    if not edges:
        edges = list((network.get("edges") or [])[:4])
    if not nodes or not edges:
        _empty_note(fig, tl, "empty_lanes")
        draw.save_figure(fig, path)
        return

    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.02, bottom=0.18)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))
    strongest = max(int(e.get("count") or 0) for e in edges)
    shown = int(round(tl.count_to(strongest, start=0.10, duration=0.36)))
    fig.text(rect[0], rect[1] + rect[3] + 0.016, i18n.t("lanes_label", n=shown, team=focus.upper()),
             color=identity["chart"], fontsize=16, family=theme.DISPLAY_FONT, fontweight="bold",
             ha="left", va="center", alpha=tl.cue(0.12, 0.22), zorder=20)

    visible = tl.reveal_count(len(edges), start=0.12, span=0.48)
    used = set()
    for index, edge in enumerate(edges):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(edges)), start=0.12, span=0.48, duration=0.18)
        source, target = nodes.get(edge["source"]), nodes.get(edge["target"])
        if not source or not target:
            continue
        start = draw.to_pitch(source["x"], source["y"])
        finish = draw.to_pitch(target["x"], target["y"])
        width = 1.6 + edge["count"] / max_edge * 7.0
        ax.plot(
            [start[0], start[0] + (finish[0] - start[0]) * local],
            [start[1], start[1] + (finish[1] - start[1]) * local],
            color=identity["chart"], lw=width, alpha=0.55 * local, zorder=7,
            solid_capstyle="round",
        )
        used.add(edge["source"])
        used.add(edge["target"])
        if local > 0.7 and index == 0:
            draw.freeze_frame_badge(ax, (start[0] + finish[0]) / 2, (start[1] + finish[1]) / 2,
                                    int(edge["count"]), identity["chart"], alpha=local, radius=2.4)

    node_x, node_y, node_s, node_a = [], [], [], []
    for name in used:
        node = nodes.get(name)
        if not node:
            continue
        point = draw.to_pitch(node["x"], node["y"])
        node_x.append(point[0])
        node_y.append(point[1])
        node_s.append(140 + node["count"] * 4)
        node_a.append(tl.cue(0.28, 0.24))
    draw.scatter_batch(ax, node_x, node_y, sizes=node_s, colors=[identity["fill"]] * len(node_x),
                       alphas=node_a, linewidth=1.2, zorder=10)
    draw.save_figure(fig, path)


def render_bench_impact(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    """Sub ticks on a two-lane tape, with shots that followed each arrival."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    bench = audit.get("bench_impact") or {}
    subs = list(bench.get("subs") or [])
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if len(subs) < 1:
        _empty_note(fig, tl, "empty_bench")
        draw.save_figure(fig, path)
        return

    last = max(90.0, max(float(sub.get("minute") or 0) for sub in subs))
    shown = int(round(tl.count_to(len(subs), start=0.10, duration=0.36)))
    draw.hero_number(fig, 0.5, content_top - 0.10, shown, color=theme.NUMBER_INK, fontsize=50.0,
                     alpha=tl.cue(0.10, 0.28))
    fig.text(0.5, content_top - 0.155, i18n.t("bench_axis", n=int(last)), color=TEXT_DIM,
             fontsize=14, family=theme.MONO_FONT, fontweight="bold",
             ha="center", va="center", alpha=tl.cue(0.24, 0.22), zorder=20)

    rect = [Layout.MARGIN, 0.22, Layout.CONTENT_W, 0.36]
    ax = fig.add_axes(rect, zorder=6)
    ax.set_xlim(0, last)
    ax.set_ylim(-1.35, 1.35)
    ax.set_axis_off()
    wipe = tl.wipe(0.08, 0.56)
    ax.set_facecolor("#000000")
    tape_end = last * max(0.08, wipe)
    ax.axhline(0.55, xmin=0, xmax=max(0.02, tape_end / last), color=design["home"]["chart"],
               lw=2.0, alpha=0.55 * wipe, zorder=4)
    ax.axhline(-0.55, xmin=0, xmax=max(0.02, tape_end / last), color=design["away"]["chart"],
               lw=2.0, alpha=0.55 * wipe, zorder=4)
    lane_alpha = tl.cue(0.12, 0.22, ease=draw.ease_in_out)
    ax.text(0, 1.15, bundle.home.upper(), color=design["home"]["chart"], fontsize=11,
            family=theme.MONO_FONT, fontweight="bold", ha="left", va="center", alpha=lane_alpha)
    ax.text(0, -1.15, bundle.away.upper(), color=design["away"]["chart"], fontsize=11,
            family=theme.MONO_FONT, fontweight="bold", ha="left", va="center", alpha=lane_alpha)

    visible = tl.reveal_count(len(subs), start=0.16, span=0.50)
    last_label_at: dict[str, float] = {"h": -99.0, "a": -99.0}
    for index, sub in enumerate(subs):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(subs)), start=0.16, span=0.50, duration=0.16)
        minute = float(sub.get("minute") or 0)
        up = sub.get("h_a") == "h"
        colour = design["home"]["chart"] if up else design["away"]["chart"]
        y = 0.55 if up else -0.55
        ax.plot([minute, minute], [y, y + (0.42 if up else -0.42) * local],
                color=colour, lw=2.2, alpha=local, zorder=8, solid_capstyle="round")
        shirt = sub.get("shirt")
        label = str(int(shirt)) if shirt not in (None, "") else (sub.get("surname") or "")[:8]
        side_key = "h" if up else "a"
        crowded = abs(minute - last_label_at[side_key]) < 7
        label_x = minute + (2.8 if crowded else 0.0)
        extra = 0.16 if (index % 2) else 0.0
        label_y = y + ((0.58 + extra) if up else -(0.58 + extra))
        ax.text(label_x, label_y, label, color=colour, fontsize=11,
                family=theme.DISPLAY_FONT, fontweight="bold", ha="center",
                va="bottom" if up else "top", alpha=local, zorder=10)
        last_label_at[side_key] = minute
        after = int(sub.get("shots_after") or 0)
        if after and local > 0.6:
            ax.text(minute, y + (0.22 if up else -0.22), f"+{after}", color=TEXT,
                    fontsize=8, family=theme.MONO_FONT, ha="center", va="center",
                    alpha=local * 0.9, zorder=11)
    for tick in (0, 45, 90):
        if tick <= last:
            ax.text(tick, 0.0, f"{tick}'", color=TEXT_FAINT, fontsize=9,
                    family=theme.MONO_FONT, ha="center", va="center", alpha=tl.cue(0.20, 0.22))
    draw.save_figure(fig, path)


def render_duel_tower(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Two columns of stacked slabs — tackles, aerials, take-ons."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    duels = audit.get("duels") or {}
    home = duels.get("home") or {}
    away = duels.get("away") or {}
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if int(duels.get("total") or 0) < 4:
        _empty_note(fig, tl, "empty_duel")
        draw.save_figure(fig, path)
        return

    layers = (
        ("tackles", i18n.t("layer_tackles")),
        ("aerials", i18n.t("layer_aerials")),
        ("take_ons", i18n.t("layer_take_ons")),
    )
    tallest = max(1, int(home.get("total") or 0), int(away.get("total") or 0))
    unit = 6.5 / tallest
    towers = ((home, design["home"], 34.0 + 2.6, 0.00, -1), (away, design["away"], 34.0 - 2.6, 0.06, 1))
    corners = [(50 + dx, cy + dy, z) for _, _, cy, _, _ in towers
               for dx in (-1.3, 1.3) for dy in (-1.3, 1.3) for z in (0.0, tallest * unit + 1.6)]
    cam = depth.fit_camera(
        corners, target=(50.0, 34.0, 2.6),
        azimuth=depth.ease_camera(tl.raw, 202.0, 170.0),
        elevation=depth.ease_camera(tl.raw, 22.0, 15.0),
        fov=30.0, rect=(0.16, Layout.STAGE_BOTTOM + 0.13, 0.84, content_top - 0.11),
    )
    stage = depth.stage(fig, zorder=6)
    floor = tl.cue(0.04, 0.24)
    if floor > draw.VISIBLE_ALPHA:
        sx, sy, _ = cam.project(depth.ground_circle(50, 34, 6.0, steps=72))
        stage.add_patch(Polygon(np.column_stack([sx, sy]), closed=True, facecolor="#0c110e",
                                edgecolor=design["hairline"], linewidth=1.0, alpha=floor, zorder=4))
    painter = depth.Painter(cam)
    labels: list[tuple[float, float, float, str, int, int, float]] = []
    tops: list[tuple[dict[str, Any], float, float, float, int]] = []
    for payload, identity, centre_y, delay, side in towers:
        z = 0.0
        depth.ground_glow(stage, cam, 50, centre_y, identity["chart"], radius=2.6, alpha=0.35 * floor, zorder=4.5)
        for index, (key, label) in enumerate(layers):
            local = tl.stagger(index, 3, start=0.14 + delay, span=0.30, duration=0.28, ease=draw.ease_out_back)
            if local <= 0.02:
                continue
            value = int(payload.get(key) or 0)
            height = max(0.12, value * unit) * min(1.1, local)
            colour = theme.mix(identity["chart"], "#05070a", 0.20 * index) if value else "#1a211d"
            painter.box(48.7, centre_y - 1.3, 51.3, centre_y + 1.3, z, z + height, colour,
                        edge=theme.mix(colour, "#ffffff", 0.32), lw=0.7,
                        alpha=draw.opacity(min(1.0, local * 1.5)), depth_bias=-index * 0.01)
            labels.append((centre_y, z, height, str(label).upper(), value, side, local))
            z += height + 0.10
        tops.append((identity, centre_y, z, float(payload.get("total") or 0), side))
    painter.flush(stage, zorder=10)

    for centre_y, z, height, label, value, side, local in labels:
        ink = draw.opacity((local - 0.4) * 1.8)
        if ink < draw.VISIBLE_ALPHA:
            continue
        sx, sy = cam.point(50, centre_y + (-1.3 if side > 0 else 1.3), z + height / 2)
        offset = 18 if side > 0 else -18
        stage.text(sx + offset, sy + 9, label, color=TEXT_DIM, fontsize=theme.label_size(8.5),
                   family=theme.LABEL_FONT, fontweight="bold", ha="left" if side > 0 else "right",
                   va="center", alpha=ink, zorder=20)
        draw.data_label(stage, sx + offset, sy - 13, str(value), size=15, alpha=ink,
                        ha="left" if side > 0 else "right")
    for identity, centre_y, z, total, side in tops:
        ink = tl.cue(0.46, 0.24)
        sx, sy = cam.point(50, centre_y, z + 0.4)
        draw.data_label(stage, sx, sy + 12, str(int(total)), size=24, alpha=ink, va="bottom")
    draw.save_figure(fig, path)


def render_aerial_war(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Rising chevrons for headers won. Home climbs, away drops."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    aerials = audit.get("aerials") or {}
    home_won = int(aerials.get("home_won") or 0)
    away_won = int(aerials.get("away_won") or 0)
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if int(aerials.get("total") or 0) < 3:
        _empty_note(fig, tl, "empty_aerial")
        draw.save_figure(fig, path)
        return

    draw.data_label(
        fig, 0.28, 0.72, str(int(round(tl.count_to(home_won, start=0.10, duration=0.40)))),
        size=46, alpha=tl.cue(0.08, 0.28),
    )
    draw.data_label(
        fig, 0.72, 0.72, str(int(round(tl.count_to(away_won, start=0.14, duration=0.40)))),
        size=46, alpha=tl.cue(0.12, 0.28),
    )
    fig.text(0.5, 0.64, i18n.t("aerials_won").upper(), color=TEXT_DIM, fontsize=16,
             family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
             alpha=tl.cue(0.22, 0.22), zorder=16)

    draw.fig_rect(fig, 0.12, 0.455, 0.76, 0.004, design["hairline"], tl.cue(0.10, 0.20), zorder=8)

    def chevron(cx: float, cy: float, colour: str, scale: float, up: bool, alpha: float) -> None:
        h = 0.028 * scale
        w = 0.055 * scale
        if up:
            pts = [(cx, cy + h), (cx - w, cy - h * 0.4), (cx, cy - h * 0.05), (cx + w, cy - h * 0.4)]
        else:
            pts = [(cx, cy - h), (cx - w, cy + h * 0.4), (cx, cy + h * 0.05), (cx + w, cy + h * 0.4)]
        fig.patches.append(
            Polygon(pts, closed=True, transform=fig.transFigure, facecolor=colour,
                    edgecolor="none", alpha=0.92 * alpha, zorder=12)
        )

    n_home = min(10, home_won)
    n_away = min(10, away_won)
    for index in range(n_home):
        local = tl.stagger(index, max(1, n_home), start=0.18, span=0.44, duration=0.16,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        chevron(0.28, 0.48 + 0.028 * index * local, design["home"]["fill"], 0.7 + 0.5 * local, True, local)
    for index in range(n_away):
        local = tl.stagger(index, max(1, n_away), start=0.22, span=0.44, duration=0.16,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        chevron(0.72, 0.44 - 0.028 * index * local, design["away"]["fill"], 0.7 + 0.5 * local, False, local)
    draw.save_figure(fig, path)


def render_momentum_wave(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    """Mirrored sound-wave lobes from per-bucket pressure. Smoother than the fill chart."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    rows = audit.get("momentum") or []
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if len(rows) < 2:
        _empty_note(fig, tl, "pressure_curve_empty")
        draw.save_figure(fig, path)
        return

    rect = [Layout.MARGIN, 0.20, Layout.CONTENT_W, content_top - 0.28]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#0b0f0d")
    for spine in ax.spines.values():
        spine.set_visible(False)
    axis = audit.get("clock_axis") or {}
    span = max(1.0, float((axis or {}).get("end") or rows[-1]["end"]))
    starts = np.array([row["start"] for row in rows], dtype=float)
    home_p = np.array([row.get("home_pressure") or 0 for row in rows], dtype=float)
    away_p = np.array([row.get("away_pressure") or 0 for row in rows], dtype=float)
    ax.set_xlim(0, span)
    peak = max(6.0, float(max(home_p.max(initial=0), away_p.max(initial=0))) * 1.25)
    ax.set_ylim(-peak, peak)
    ax.set_yticks([])
    ticks = (axis or {}).get("ticks") or []
    if ticks:
        ax.set_xticks([tick["at"] for tick in ticks])
        ax.set_xticklabels([tick["label"] for tick in ticks], color=TEXT_FAINT,
                           fontsize=10, family=theme.MONO_FONT)
    ax.tick_params(axis="x", length=0, pad=6)
    reveal = tl.wipe(0.02, 0.58)
    tick_alpha = min(1.0, reveal * 2.0)
    for label in ax.get_xticklabels():
        label.set_alpha(tick_alpha)
    ax.axhline(0, color=design["pitch_line"], lw=1.4, alpha=0.9 * tick_alpha, zorder=6)

    cutoff = span * reveal
    hx, hy = _smooth_series(starts, home_p, cutoff)
    ax_, ay = _smooth_series(starts, away_p, cutoff)
    if len(hx) > 1:
        ax.fill_between(hx, hy, -hy, color=design["home"]["fill"], alpha=0.42, linewidth=0, zorder=4)
        ax.plot(hx, hy, color=design["home"]["chart"], lw=2.0, zorder=8)
        ax.plot(hx, -hy, color=design["home"]["chart"], lw=1.1, alpha=0.55, zorder=8)
    if len(ax_) > 1:
        ax.fill_between(ax_, ay, -ay, color=design["away"]["fill"], alpha=0.38, linewidth=0, zorder=5)
        ax.plot(ax_, ay, color=design["away"]["chart"], lw=2.0, zorder=9)
        ax.plot(ax_, -ay, color=design["away"]["chart"], lw=1.1, alpha=0.55, zorder=9)

    for boundary in (axis or {}).get("boundaries") or []:
        ax.axvline(boundary["at"], color=design["hairline"], lw=1.0,
                   alpha=0.8 * tick_alpha, ls=(0, (3, 4)), zorder=3)
        ax.text(boundary["at"], peak * 0.92, i18n.period_label(boundary["label"]), color=TEXT_FAINT,
                fontsize=9.5, family=theme.MONO_FONT, ha="center", va="top",
                alpha=tl.cue(0.20, 0.24), zorder=7)

    peak_row = max(rows, key=lambda row: abs(row.get("swing") or 0))
    peak_alpha = tl.cue(0.52, 0.26)
    if peak_alpha > 0.02:
        at = (peak_row["start"] + peak_row["end"]) / 2
        colour = design["home"]["chart"] if peak_row.get("swing", 0) >= 0 else design["away"]["chart"]
        ax.axvline(at, color=colour, lw=1.6, alpha=0.7 * peak_alpha, zorder=10)
        ax.text(at, peak * 0.72, i18n.t("peak", block=str(peak_row.get("minute_block") or "")),
                color=colour, fontsize=11, family=theme.MONO_FONT, fontweight="bold",
                ha="center", va="center", path_effects=draw.outline(peak_alpha), alpha=peak_alpha, zorder=12)
    draw.save_figure(fig, path)


def render_halftime_split(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                          path: Path, progress: float = 1.0) -> None:
    """Giant 1H / 2H stamp. One idea: the match changed character."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    split = audit.get("halftime_split") or {}
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if not split.get("ready"):
        _empty_note(fig, tl, "empty_split")
        draw.save_figure(fig, path)
        return

    first, second = split.get("first") or {}, split.get("second") or {}
    grown = tl.cue(0.10, 0.36)
    divider = 0.5
    draw.fig_rect(fig, divider - 0.0012, Layout.STAGE_BOTTOM + 0.12, 0.0024,
                  (content_top - 0.10) - (Layout.STAGE_BOTTOM + 0.12), design["hairline"], grown, zorder=8)

    peak = max(
        int(first.get("home_shots") or 0), int(first.get("away_shots") or 0),
        int(second.get("home_shots") or 0), int(second.get("away_shots") or 0), 1,
    )
    cols = 5
    step = 0.072
    rows_each = int(math.ceil(peak / cols))
    block_h = draw.y_of(step) * rows_each
    available = (content_top - 0.19) - (Layout.STAGE_BOTTOM + 0.16)
    if 2 * block_h + 0.06 > available:
        step *= available / (2 * block_h + 0.06)
        block_h = draw.y_of(step) * rows_each
    blocks_top = content_top - 0.19 - max(0.0, (available - (2 * block_h + 0.06)) / 2)

    def column(x: float, payload: dict[str, Any], label: str, start: float) -> None:
        ink = tl.cue(start, 0.26, ease=draw.ease_in_out)
        fig.text(x, content_top - 0.105, label, color=TEXT, fontsize=58, fontweight="bold",
                 family=theme.DISPLAY_FONT, ha="center", va="center", alpha=ink, zorder=16)
        y = blocks_top
        for side, identity in (("home", design["home"]), ("away", design["away"])):
            shots = int(payload.get(f"{side}_shots") or 0)
            goals = min(shots, int(payload.get(f"{side}_goals") or 0))
            x0 = x - step * cols / 2 + step / 2
            for index in range(shots):
                pop = tl.stagger(index, max(1, shots), start=start + 0.06, span=0.30, duration=0.14,
                                 ease=draw.ease_out_back)
                if pop <= 0.02:
                    continue
                row, col = divmod(index, cols)
                cx, cy = x0 + col * step, y - draw.y_of(step) * (row + 0.5)
                is_goal = index < goals
                colour = design["goal"] if is_goal else identity["chart"]
                radius = step * 0.34 * min(1.12, pop)
                draw.fig_ellipse(fig, cx, cy, radius * 1.5, facecolor=colour, edgecolor="none",
                                 alpha=0.12 * draw.opacity(pop), zorder=13)
                draw.fig_ellipse(fig, cx, cy, radius, facecolor=colour,
                                 edgecolor=TEXT if is_goal else theme.mix(colour, "#ffffff", 0.35),
                                 linewidth=1.6 if is_goal else 0.9, alpha=draw.opacity(pop), zorder=14)
            y -= block_h + 0.06
        draw.data_label(
            fig, x, Layout.STAGE_BOTTOM + 0.135,
            f"{int(payload.get('home_shots') or 0)} – {int(payload.get('away_shots') or 0)}  {stat_label('shots').upper()}",
            size=17, alpha=tl.cue(start + 0.30, 0.22),
        )

    column(0.27, first, "1H", 0.10)
    column(0.73, second, "2H", 0.20)
    draw.legend_row(
        fig, Layout.STAGE_BOTTOM + 0.098,
        [("dot", design["home"]["chart"], _short_team(bundle.home)),
         ("dot", design["away"]["chart"], _short_team(bundle.away)),
         ("dot", design["goal"], i18n.t("outcome_goal"))],
        alpha=tl.cue(0.46, 0.24), fontsize=theme.label_size(9.5),
    )
    draw.save_figure(fig, path)


# New graphs plus the polished existing ones. scenes.py registers these.
GRAPH_RENDERERS = {
    "stat_slam": render_stat_slam,
    "match_radar": render_match_radar,
    "touch_heatmap": render_touch_heatmap,
    "field_tilt_wave": render_field_tilt_wave,
    "conversion_gauges": render_conversion_gauges,
    "chance_funnel": render_chance_funnel,
    "keeper_frame": render_keeper_frame,
    "xg_race": render_xg_race,
    "time_zones": render_time_zones,
    "player_spike": render_player_spike,
    "shot_clock_spiral": render_shot_clock_spiral,
    "press_trap": render_press_trap,
    "pass_lanes": render_pass_lanes,
    "bench_impact": render_bench_impact,
    "duel_tower": render_duel_tower,
    "aerial_war": render_aerial_war,
    "momentum": render_momentum_wave,
    "halftime_split": render_halftime_split,
}
