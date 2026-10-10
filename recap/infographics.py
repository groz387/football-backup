"""Picture-first cards: 3D scenes and infographics built from the audit.

Shape, height, colour and position carry the read. Numbers stay on screen so a
viewer can check them, but they use ``draw.data_label`` and never the team
accent. Like ``graphs``, this module never imports ``scenes``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.patches import Circle, Polygon, Rectangle, Wedge

from . import depth, draw, i18n, theme
from .audit import display_surname
from .data import MatchBundle
from .draw import Layout, Timeline
from .theme import TEXT, TEXT_DIM, TEXT_FAINT

NEUTRAL = "#2f3833"
STAGE_FLOOR = 0.175


def _frame(bundle: MatchBundle, scene: dict[str, Any], progress: float, *, key_row: bool = True):
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    top = draw.scene_chrome(fig, scene, tl, headline_size=42.0)
    if key_row:
        key_y = top - 0.028
        draw.team_key_row(fig, design, bundle.home, bundle.away, key_y, tl.cue(0.06, 0.24))
        top = key_y - 0.036
    return design, fig, tl, top


def _empty(fig, tl: Timeline, path: Path, key: str) -> None:
    draw.empty_stage(fig, i18n.t(key), tl)
    draw.save_figure(fig, path)


def _identity(design: dict[str, Any], h_a: str) -> dict[str, str]:
    return design["home" if h_a == "h" else "away"]


def _caption(fig, text: str, y: float, alpha: float, *, size: float = 11.0, color: str = TEXT_FAINT) -> None:
    if alpha < draw.VISIBLE_ALPHA or not text:
        return
    draw.fit_text(
        fig, 0.5, y, str(text).upper(), fontsize=theme.label_size(size), max_width=Layout.CONTENT_W,
        max_lines=1, min_fontsize=8, ha="center", va="center", color=color,
        family=theme.LABEL_FONT, fontweight="bold", alpha=alpha, zorder=20,
    )


def _legend_top(fig, text: str, top: float, alpha: float) -> float:
    """One quiet key line between the team row and the stage. Returns the new stage top."""
    _caption(fig, text, top + 0.004, alpha, size=8.8)
    return top - 0.014


def _dual_meters(fig, design: dict[str, Any], y: float, home_value: float, away_value: float,
                 label: str, alpha: float, *, maximum: float = 100.0, suffix: str = "%") -> None:
    """Two independent rates, one bar each. Not a share: the two need not sum to 100."""
    if alpha < draw.VISIBLE_ALPHA:
        return
    _caption(fig, label, y + 0.032, alpha, size=10, color=TEXT_DIM)
    width, height = 0.30, 0.010
    for value, identity, x in ((home_value, design["home"], 0.5 - 0.035 - width),
                               (away_value, design["away"], 0.5 + 0.035)):
        draw.fig_rect(fig, x, y, width, height, "#171d19", 0.95 * alpha, zorder=12)
        draw.fig_rect(fig, x, y, width * max(0.0, min(1.0, value / maximum)) * alpha, height,
                      identity["chart"], 0.95, zorder=13)
        draw.data_label(fig, x + width / 2, y - 0.018, draw.number_text(value, suffix=suffix),
                        size=14, alpha=alpha)


def _share_strip(fig, design: dict[str, Any], y: float, home_value: float, away_value: float,
                 label: str, alpha: float, *, suffix: str = "") -> None:
    """Thin two-colour split with the label above and quiet numbers at the ends."""
    if alpha < draw.VISIBLE_ALPHA:
        return
    total = home_value + away_value
    share = 0.5 if total <= 0 else home_value / total
    left, width, height = 0.20, 0.60, 0.010
    draw.fig_rect(fig, left, y, width, height, "#171d19", 0.95 * alpha, zorder=12)
    draw.fig_rect(fig, left, y, width * share * alpha, height, design["home"]["chart"], 0.95, zorder=13)
    away_w = width * (1 - share) * alpha
    draw.fig_rect(fig, left + width - away_w, y, away_w, height, design["away"]["chart"], 0.95, zorder=13)
    _caption(fig, label, y + 0.021, alpha, size=8.5, color=TEXT_DIM)
    draw.data_label(fig, left - 0.018, y + height / 2, draw.number_text(home_value, suffix=suffix),
                    size=11.5, alpha=alpha, ha="right")
    draw.data_label(fig, left + width + 0.018, y + height / 2, draw.number_text(away_value, suffix=suffix),
                    size=11.5, alpha=alpha, ha="left")


def _coarsen(grid: np.ndarray, factor: int) -> np.ndarray:
    rows, cols = grid.shape
    rows -= rows % factor
    cols -= cols % factor
    trimmed = grid[:rows, :cols]
    return trimmed.reshape(rows // factor, factor, cols // factor, factor).sum(axis=(1, 3))


def _end_label(ax, cam: depth.Camera, x: float, text: str, colour: str, alpha: float,
               *, lift: float = 0.0) -> None:
    """Team label just past a goal line, outside the play area."""
    if alpha < draw.VISIBLE_ALPHA:
        return
    far = x > 50
    sx, sy = cam.point(x + (4.0 if far else -4.0), 34, lift)
    ax.text(sx, sy + (10 if far else -10), text, color=colour, fontsize=theme.label_size(9.5),
            family=theme.LABEL_FONT, fontweight="bold", ha="center", va="bottom" if far else "top",
            alpha=alpha, zorder=30, path_effects=draw.outline(alpha))


# ---------------------------------------------------------------------------
# 3D: territory skyline
# ---------------------------------------------------------------------------

def render_touch_skyline(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    """Every touch bin as a column on a 3D pitch. Height is volume, colour is owner."""
    design, fig, tl, top = _frame(bundle, scene, progress)
    heat = audit.get("touch_heatmap") or {}
    home = np.asarray(heat.get("home") or [], dtype=float)
    away = np.asarray(heat.get("away") or [], dtype=float)
    if home.size == 0 or home.shape != away.shape or (home.sum() + away.sum()) <= 0:
        _empty(fig, tl, path, "no_touch_coords")
        return
    factor = 2 if min(home.shape) >= 8 else 1
    home, away = _coarsen(home, factor), _coarsen(away, factor)
    total = home + away
    peak = float(total.max()) or 1.0
    nx, ny = total.shape
    cell_x, cell_y = depth.PITCH_X / nx, depth.PITCH_Y / ny
    max_h = 17.0
    cam = depth.fit_camera(
        depth.pitch_corners(height=max_h * 0.45),
        target=(52.5, 34.0, 0.0),
        azimuth=depth.ease_camera(tl.raw, 202.0, 172.0),
        elevation=depth.ease_camera(tl.raw, 54.0, 42.0),
        fov=30.0, rect=(0.03, STAGE_FLOOR + 0.045, 0.97, top - 0.01),
    )
    ax = depth.stage(fig, zorder=5)
    depth.draw_pitch(ax, cam, design, alpha=tl.cue(0.02, 0.22))

    painter = depth.Painter(cam)
    busiest = np.unravel_index(int(np.argmax(total)), total.shape)
    peak_height: float | None = None
    gap_x, gap_y = cell_x * 0.13, cell_y * 0.13
    for xi in range(nx):
        local = tl.stagger(xi, nx, start=0.10, span=0.40, duration=0.30, ease=draw.ease_out_back)
        if local <= 0.01:
            continue
        for yi in range(ny):
            count = float(total[xi, yi])
            if count <= 0:
                continue
            share = float(home[xi, yi]) / count
            identity = design["home"] if share >= 0.5 else design["away"]
            margin = abs(share - 0.5) * 2.0
            # Use the club/nation material, not the high-contrast chart ink.  This
            # keeps the city grounded and lets ownership emerge gradually.
            colour = theme.mix("#111612", identity["primary"], 0.14 + 0.56 * margin ** 0.75)
            height = max(0.15, max_h * (count / peak) ** 1.48 * min(1.12, local))
            x0, y0 = xi * cell_x + gap_x, yi * cell_y + gap_y
            is_peak = (xi, yi) == tuple(busiest)
            if is_peak:
                peak_height = height
            painter.box(x0, y0, x0 + cell_x - 2 * gap_x, y0 + cell_y - 2 * gap_y, 0.0, height, colour,
                        edge=theme.mix(colour, "#ffffff", 0.28) if is_peak else None,
                        lw=0.8 if is_peak else 0.0,
                        alpha=draw.opacity(min(1.0, local * 1.5)))
            if count / peak > 0.72:
                depth.ground_glow(ax, cam, x0 + cell_x / 2, y0 + cell_y / 2, identity["primary"],
                                  radius=cell_x * 0.55, alpha=0.09 * local, rings=3, zorder=6.7)
    painter.flush(ax, zorder=10)

    peak_alpha = tl.cue(0.52, 0.24)
    if peak_alpha > draw.VISIBLE_ALPHA and peak_height is not None:
        bx, by = busiest
        sx, sy = cam.point((bx + 0.5) * cell_x, (by + 0.5) * cell_y, peak_height)
        ax.plot([sx, sx], [sy + 5, sy + 23], color=TEXT, lw=0.8, alpha=peak_alpha * 0.7, zorder=31)
        ax.text(sx, sy + 27, i18n.t("busiest_zone"), color=TEXT_DIM, fontsize=theme.label_size(7.5),
                family=theme.LABEL_FONT, fontweight="bold", ha="center", va="bottom",
                alpha=peak_alpha, zorder=31, path_effects=draw.outline(peak_alpha))

    _share_strip(fig, design, STAGE_FLOOR - 0.005, float(home.sum()), float(away.sum()),
                 i18n.t("touches_label"), tl.cue(0.42, 0.26))
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# 3D: shot skyline
# ---------------------------------------------------------------------------

_SHOT_TIER = {"goal": 1.0, "saved": 0.62, "woodwork": 0.56, "off_target": 0.36, "blocked": 0.22}


def _shot_world(shot: dict[str, Any]) -> tuple[float, float]:
    x, y = float(shot.get("x") or 0), float(shot.get("y") or 0)
    if shot.get("h_a") == "a":
        x, y = 100.0 - x, 100.0 - y
    return depth.world_x(x), depth.world_y(y)


def render_shot_skyline(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    """Every shot as a tower where it was struck. Taller means closer to a goal."""
    design, fig, tl, top = _frame(bundle, scene, progress)
    shots = sorted(
        [shot for shot in audit.get("shots") or [] if shot.get("x") is not None],
        key=lambda shot: (shot.get("minute") or 0),
    )
    if len(shots) < 3:
        _empty(fig, tl, path, "too_few_shots_3d")
        return
    use_xg = bool((audit.get("data_health") or {}).get("has_vendor_xg")) and any(s.get("xg") for s in shots)
    max_h = 15.0
    cam = depth.fit_camera(
        depth.pitch_corners(height=max_h * 0.6),
        target=(52.5, 34.0, 0.0),
        azimuth=depth.ease_camera(tl.raw, 206.0, 182.0),
        elevation=depth.ease_camera(tl.raw, 36.0, 29.0),
        fov=28.0, rect=(0.02, STAGE_FLOOR + 0.045, 0.98, top - 0.01),
    )
    ax = depth.stage(fig, zorder=5)
    depth.draw_pitch(ax, cam, design, alpha=tl.cue(0.02, 0.22))

    painter = depth.Painter(cam)
    labels: list[tuple[float, float, float, str]] = []
    for index, shot in enumerate(shots):
        local = tl.stagger(index, len(shots), start=0.10, span=0.48, duration=0.22, ease=draw.ease_out_back)
        if local <= 0.01:
            continue
        outcome = str(shot.get("outcome") or "off_target")
        identity = _identity(design, str(shot.get("h_a")))
        tier = (0.18 + 0.82 * min(1.0, float(shot.get("xg") or 0) / 0.6)) if use_xg else _SHOT_TIER.get(outcome, 0.3)
        if shot.get("big_chance") and not use_xg:
            tier = min(1.0, tier + 0.10)
        height = max(0.2, max_h * tier * min(1.15, local))
        if outcome == "goal":
            colour = design["goal"]
        elif outcome in {"saved", "woodwork"}:
            colour = theme.mix("#18201b", identity["primary"], 0.82)
        else:
            colour = theme.mix("#0b0f0d", identity["primary"], 0.57 if outcome == "off_target" else 0.42)
        x, y = _shot_world(shot)
        half = 1.15 if outcome == "goal" else 0.85
        top_colour = theme.mix(colour, "#ffffff", 0.45) if shot.get("big_chance") or outcome == "goal" else None
        painter.box(x - half, y - half, x + half, y + half, 0.0, height, colour,
                    edge=None, lw=0.0, top=top_colour,
                    alpha=draw.opacity(min(1.0, local * 1.5)))
        if outcome == "goal":
            depth.ground_glow(ax, cam, x, y, design["goal"], radius=4.6, alpha=0.70 * min(1.0, local), zorder=7)
            surname = display_surname(str(shot.get("player") or ""))[:14]
            if surname and local > 0.6:
                labels.append((x, y, height, surname.upper()))
        else:
            depth.ground_glow(ax, cam, x, y, colour, radius=2.2, alpha=0.22 * min(1.0, local), rings=3,
                              zorder=6.8)
    painter.flush(ax, zorder=10)

    for x, y, height, text in labels:
        bx, by = cam.point(x, y, height + 1.1)
        ball = max(7.0, cam.pixels_per_metre(x, y, height) * 0.75)
        ax.add_patch(Circle((bx, by), ball * 1.9, facecolor=design["goal"], edgecolor="none", alpha=0.25, zorder=31))
        ax.add_patch(Circle((bx, by), ball, facecolor=TEXT, edgecolor="#050706", linewidth=1.2, zorder=32))
        ax.add_patch(Circle((bx, by), ball * 0.38, facecolor="#050706", edgecolor="none", zorder=33))
        ax.text(bx, by + ball * 1.6, text, color=TEXT, fontsize=10.5, family=theme.DISPLAY_FONT, fontweight="bold",
                ha="center", va="bottom", zorder=33, path_effects=draw.outline(1.0))

    stats = audit.get("team_stats") or {}
    _share_strip(fig, design, STAGE_FLOOR - 0.005,
                 float((stats.get(bundle.home) or {}).get("shots") or 0),
                 float((stats.get(bundle.away) or {}).get("shots") or 0),
                 i18n.t("shots_label"), tl.cue(0.42, 0.26))
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# 3D: shot trajectories into one goal
# ---------------------------------------------------------------------------

def render_shot_trajectories(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                             path: Path, progress: float = 1.0) -> None:
    """Every shot that reached the goal line, from boot to where it crossed it.

    Both sides are folded onto one goal. The end point is WhoScored's goal-mouth
    coordinate; the path between is a straight line, not a modelled flight.
    """
    design, fig, tl, top = _frame(bundle, scene, progress)
    candidates = sorted(
        [
            shot for shot in audit.get("shots") or []
            if shot.get("outcome") != "blocked"
            and shot.get("goal_mouth_y") is not None and shot.get("goal_mouth_z") is not None
            and shot.get("x") is not None
        ],
        key=lambda shot: (shot.get("minute") or 0),
    )
    if len(candidates) < 3:
        _empty(fig, tl, path, "too_few_shots_3d")
        return
    # A goal-mouth picture should read at phone scale.  Keep decisive paths and
    # a representative sample instead of turning a 24-shot match into neon yarn.
    outcome_priority = {"goal": 0, "saved": 1, "woodwork": 1, "off_target": 2}
    shots = sorted(
        sorted(candidates, key=lambda shot: (outcome_priority.get(str(shot.get("outcome")), 3),
                                               -(float(shot.get("xg") or 0)),
                                               int(shot.get("minute") or 0)))[:14],
        key=lambda shot: int(shot.get("minute") or 0),
    )

    origins = [(depth.world_x(s["x"]), depth.world_y(s["y"])) for s in shots]
    box_x = depth.PITCH_X - 16.5
    framing = [(box_x, 34 - 11.0, 0.0), (box_x, 34 + 11.0, 0.0), (box_x - 6.0, 34, 0.0),
               (depth.PITCH_X, 34 - 7.0, 0.0), (depth.PITCH_X, 34 + 7.0, 0.0),
               (depth.PITCH_X, 34, depth.GOAL_H + 1.6)]
    cam = depth.fit_camera(
        framing,
        target=(depth.PITCH_X - 7.0, 34.0, 1.0),
        azimuth=depth.ease_camera(tl.raw, 193.0, 178.0),
        elevation=depth.ease_camera(tl.raw, 22.0, 15.0),
        fov=40.0, rect=(0.04, STAGE_FLOOR + 0.07, 0.96, top - 0.04),
    )
    ax = depth.stage(fig, zorder=5)
    clip = Rectangle((0, (STAGE_FLOOR + 0.050) * theme.FRAME_H), theme.FRAME_W,
                     (top - STAGE_FLOOR - 0.050) * theme.FRAME_H, transform=ax.transData)
    depth.draw_pitch(ax, cam, design, alpha=tl.cue(0.02, 0.22),
                     x_range=(max(0.0, min(x for x, _ in origins) - 6.0), depth.PITCH_X), goals=False)
    for collection in ax.collections:
        collection.set_clip_path(clip)
    for line in ax.lines:
        line.set_clip_path(clip)
    depth.draw_goal(ax, cam, depth.PITCH_X, 1, alpha=tl.cue(0.04, 0.24), zorder=9)

    for index, shot in enumerate(shots):
        local = tl.stagger(index, len(shots), start=0.12, span=0.52, duration=0.16, ease=draw.ease_out_cubic)
        if local <= 0.01:
            continue
        ox, oy = origins[index]
        gy, gz = depth.goal_mouth_world(shot["goal_mouth_y"], shot["goal_mouth_z"])
        start = np.array([ox, oy, 0.11])
        end = np.array([depth.PITCH_X, gy, max(0.11, gz)])
        head = start + (end - start) * local
        outcome = str(shot.get("outcome"))
        identity = _identity(design, str(shot.get("h_a")))
        colour = design["goal"] if outcome == "goal" else theme.mix("#1b211d", identity["primary"], 0.84)
        faded = outcome == "off_target"
        sx, sy, _ = cam.project([start, head])
        for width, weight in ((6.0, 0.045), (3.0, 0.10)):
            line, = ax.plot(sx, sy, color=colour, lw=width, alpha=weight * (0.6 if faded else 1.0),
                            zorder=11, solid_capstyle="round")
            line.set_clip_path(clip)
        line, = ax.plot(sx, sy, color=colour, lw=1.6 if faded else 2.25,
                        alpha=0.42 if faded else 0.88, zorder=12, solid_capstyle="round")
        line.set_clip_path(clip)
        bx, by = cam.point(ox, oy, 0.02)
        origin = ax.scatter([bx], [by], s=26, color=colour, alpha=0.85, zorder=12, linewidths=0)
        origin.set_clip_path(clip)
        if local >= 0.999:
            hx, hy = cam.point(*end)
            if outcome == "goal":
                for radius, weight in ((26, 0.18), (15, 0.35)):
                    ax.add_patch(Circle((hx, hy), radius, facecolor=design["goal"], edgecolor="none",
                                        alpha=weight, zorder=13))
                ax.scatter([hx], [hy], s=70, color=design["goal"], edgecolor=TEXT, linewidth=1.4, zorder=14)
            elif outcome in {"saved", "woodwork"}:
                ring = theme.WARNING if outcome == "woodwork" else TEXT
                ax.scatter([hx], [hy], s=44, facecolor=colour, edgecolor=ring, linewidth=1.2, zorder=14)
            else:
                marker = ax.scatter([hx], [hy], s=34, facecolor="none", edgecolor=colour,
                                    linewidth=1.2, alpha=0.75, zorder=14)
                marker.set_clip_path(clip)
        else:
            hx, hy = cam.point(*head)
            ax.scatter([hx], [hy], s=36, color=TEXT, edgecolor=colour, linewidth=1.2, zorder=14)

    legend_alpha = tl.cue(0.56, 0.26)
    draw.legend_row(
        fig, STAGE_FLOOR + 0.024,
        [("dot", design["goal"], i18n.t("outcome_goal")),
         ("dot", TEXT_DIM, i18n.t("outcome_saved")),
         ("ring", TEXT_DIM, i18n.t("outcome_off_target"))],
        alpha=legend_alpha, fontsize=theme.label_size(9.5),
    )
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# 3D: player podium
# ---------------------------------------------------------------------------

def _icon_row(fig, x: float, y: float, count: int, colour: str, *, filled: bool, alpha: float,
              limit: int = 5, size: float = 0.0085) -> float:
    shown = min(limit, max(0, count))
    for index in range(shown):
        draw.fig_ellipse(fig, x + index * size * 2.6, y, size,
                         facecolor=colour if filled else "none", edgecolor=colour,
                         linewidth=1.6, alpha=alpha, zorder=24)
    return x + shown * size * 2.6


def render_player_podium(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    """The three best WhoScored ratings on a lit podium, with their rating curves."""
    design, fig, tl, top = _frame(bundle, scene, progress, key_row=False)
    ranked = list((audit.get("player_ratings") or {}).get("top") or [])
    if len(ranked) < 3:
        _empty(fig, tl, path, "empty_podium")
        return
    trio = ranked[:3]
    slots = ((trio[1], 34.0 + 3.3, 2), (trio[0], 34.0, 1), (trio[2], 34.0 - 3.3, 3))
    best, worst = trio[0]["rating"], trio[2]["rating"]
    spread = max(0.4, best - worst)

    def height_of(rating: float) -> float:
        return 1.3 + 1.9 * (rating - worst) / spread

    corners = []
    for _, centre_y, _ in slots:
        for dx in (-1.4, 1.4):
            for dy in (-1.45, 1.45):
                corners += [(50 + dx, centre_y + dy, 0.0), (50 + dx, centre_y + dy, height_of(best) + 2.4)]
    cam = depth.fit_camera(
        corners,
        target=(50.0, 34.0, 1.4),
        azimuth=depth.ease_camera(tl.raw, 200.0, 168.0),
        elevation=depth.ease_camera(tl.raw, 20.0, 14.0),
        fov=30.0, rect=(0.10, 0.40, 0.90, top - 0.04),
    )
    ax = depth.stage(fig, zorder=5)
    floor_alpha = tl.cue(0.02, 0.24)
    if floor_alpha > 0.02:
        sx, sy, _ = cam.project(depth.ground_circle(50, 34, 6.4, steps=72))
        ax.add_patch(Polygon(np.column_stack([sx, sy]), closed=True, facecolor="#0c110e",
                             edgecolor=theme.mix(TEXT, "#000000", 0.6), linewidth=1.0,
                             alpha=floor_alpha, zorder=4))
        for radius in (5.2, 3.9):
            depth.polyline(ax, cam, depth.ground_circle(50, 34, radius, z=0.01, steps=64),
                           theme.HAIRLINE, lw=1.0, alpha=floor_alpha, zorder=4.5)

    painter = depth.Painter(cam)
    tops: list[tuple[dict[str, Any], float, float, int, float]] = []
    for order, (player, centre_y, rank) in enumerate(slots):
        local = tl.stagger(rank - 1, 3, start=0.10, span=0.22, duration=0.34, ease=draw.ease_out_back)
        if local <= 0.01:
            continue
        identity = _identity(design, player["h_a"])
        height = height_of(player["rating"]) * min(1.1, local)
        colour = theme.mix("#151b17", identity["primary"], 0.86)
        painter.box(48.6, centre_y - 1.45, 51.4, centre_y + 1.45, 0.0, height, colour,
                    edge=None, lw=0.0,
                    top=theme.mix(colour, "#ffffff", 0.18), alpha=draw.opacity(min(1.0, local * 1.4)))
        depth.ground_glow(ax, cam, 50, centre_y, colour, radius=3.0, alpha=0.40 * local, zorder=4.8)
        tops.append((player, centre_y, height, rank, local))
    painter.flush(ax, zorder=8)

    for player, centre_y, height, rank, local in tops:
        identity = _identity(design, player["h_a"])
        fx, fy = cam.point(48.6, centre_y, height * 0.48)
        ax.text(fx, fy, str(rank), color=theme.ink_on(identity["chart"]), fontsize=60, fontweight="bold",
                family=theme.DISPLAY_FONT, ha="center", va="center", alpha=0.55 * local, zorder=12)
        ink = tl.cue(0.30 + 0.06 * rank, 0.24)
        if ink < draw.VISIBLE_ALPHA:
            continue
        sx, sy = cam.point(50, centre_y, height)
        fig_x, fig_y = sx / theme.FRAME_W, sy / theme.FRAME_H
        draw.team_badge(fig, player["team"], fig_x, fig_y + 0.040, 0.070,
                        identity=identity, alpha=ink, zorder=26)
        draw.data_label(fig, fig_x, fig_y + 0.082, f"{player['rating']:.2f}", size=14, alpha=ink,
                        color=TEXT_DIM)
        draw.fit_text(fig, fig_x, fig_y + 0.106, str(player["surname"]).upper(),
                      fontsize=24 if rank == 1 else 19, max_width=0.27, max_lines=1, min_fontsize=11,
                      ha="center", va="center", color=TEXT, family=theme.DISPLAY_FONT,
                      fontweight="bold", alpha=ink, zorder=26, path_effects=draw.soft_shadow(ink))

    _rating_strip(fig, design, [slot[0] for slot in slots], tl, top=0.375)
    draw.save_figure(fig, path)


def _rating_strip(fig, design: dict[str, Any], players: list[dict[str, Any]], tl: Timeline,
                  *, top: float) -> None:
    """Per-player rating curve and contribution pips, one column each."""
    alpha = tl.cue(0.46, 0.28)
    if alpha < draw.VISIBLE_ALPHA:
        return
    col_w = Layout.CONTENT_W / 3
    curves = [player.get("curve") or [] for player in players]
    lo = min([5.5] + [value for curve in curves for _, value in curve])
    hi = max([8.5] + [value for curve in curves for _, value in curve])
    last = max([90.0] + [minute for curve in curves for minute, _ in curve])
    _caption(fig, i18n.t("rating_through_match"), top + 0.006, alpha, size=9.5)
    for index, player in enumerate(players):
        identity = _identity(design, player["h_a"])
        x0 = Layout.MARGIN + col_w * index + col_w * 0.08
        width = col_w * 0.84
        box_top, box_h = top - 0.022, 0.085
        draw.fig_panel(fig, x0, box_top - box_h, width, box_h, color=design["surface"],
                       alpha=0.85 * alpha, edge=design["hairline"], radius=0.010, zorder=14)
        curve = curves[index]
        if len(curve) >= 2:
            ax = fig.add_axes([x0 + 0.012, box_top - box_h + 0.010, width - 0.024, box_h - 0.020], zorder=16)
            ax.set_xlim(0, last)
            ax.set_ylim(lo - 0.15, hi + 0.15)
            ax.set_axis_off()
            ax.patch.set_alpha(0.0)
            xs = [point[0] for point in curve] + [last]
            ys = [point[1] for point in curve] + [curve[-1][1]]
            reveal = tl.wipe(0.48, 0.30)
            cut = last * reveal
            keep = [i for i, x in enumerate(xs) if x <= cut] or [0]
            px = [xs[i] for i in keep] + ([cut] if cut > xs[keep[-1]] else [])
            py = [ys[i] for i in keep] + ([ys[keep[-1]]] if cut > xs[keep[-1]] else [])
            ax.axhline(6.0, color=design["hairline"], lw=0.8, alpha=alpha, zorder=1)
            ax.fill_between(px, lo - 0.15, py, step="post", color=identity["chart"], alpha=0.18 * alpha, lw=0)
            draw.glow_plot(ax, px, py, identity["chart"], lw=1.8, alpha=alpha, zorder=4)
            ax.lines[-1].set_drawstyle("steps-post")
        icon_y = box_top - box_h - 0.024
        cursor = x0 + 0.010
        cursor = _icon_row(fig, cursor, icon_y, int(player.get("goals") or 0), design["goal"], filled=True,
                           alpha=alpha)
        cursor = _icon_row(fig, cursor + 0.006, icon_y, int(player.get("assists") or 0), TEXT, filled=False,
                           alpha=alpha)
        draw.data_label(
            fig, x0 + width - 0.006, icon_y,
            i18n.t("podium_line", shots=int(player.get("shots") or 0), kp=int(player.get("key_passes") or 0)),
            size=10.5, alpha=alpha, ha="right", color=TEXT_FAINT,
        )
    if any(int(player.get("goals") or 0) or int(player.get("assists") or 0) for player in players):
        draw.legend_row(
            fig, top - 0.150,
            [("dot", design["goal"], i18n.t("goals")), ("ring", TEXT, i18n.t("assists_label"))],
            alpha=alpha, fontsize=theme.label_size(9),
        )


# ---------------------------------------------------------------------------
# lineup board
# ---------------------------------------------------------------------------

def _rating_tint(rating: float | None) -> str:
    if rating is None:
        return TEXT_FAINT
    if rating >= 8.0:
        return "#ffd166"
    if rating >= 7.0:
        return "#7ee0a1"
    if rating >= 6.3:
        return TEXT_DIM
    return "#ef6f6c"


def render_lineup_board(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    """Both starting shapes on one pitch. The ring around each shirt is the rating."""
    design, fig, tl, top = _frame(bundle, scene, progress, key_row=False)
    lineups = audit.get("lineups") or {}
    if not lineups.get("available"):
        _empty(fig, tl, path, "empty_lineup")
        return
    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=top - 0.062, bottom=STAGE_FLOOR + 0.062)
    pitch = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                                alpha=tl.cue(0.02, 0.24))
    stage = depth.stage(fig, zorder=8)
    ratings = audit.get("player_ratings") or {}
    motm = ((ratings.get("top") or [None])[0] or {}).get("player")
    scale = rect[2] * theme.FRAME_W / 100.0
    radius = 3.9 * scale

    label_alpha = tl.cue(0.08, 0.22)
    for key, h_a in (("home", "h"), ("away", "a")):
        lineup = lineups.get(key) or {}
        identity = _identity(design, h_a)
        flip = h_a == "a"
        y_row = rect[1] - 0.034 if not flip else rect[1] + rect[3] + 0.034
        draw.team_badge(fig, str(lineup.get("team") or ""), rect[0] + 0.030, y_row, 0.060,
                        identity=identity, alpha=label_alpha)
        draw.fit_text(
            fig, rect[0] + 0.074, y_row, str(lineup.get("team") or "").upper(),
            fontsize=22, max_width=rect[2] * 0.62, max_lines=1, min_fontsize=11, ha="left", va="center",
            color=identity["chart"], family=theme.DISPLAY_FONT, fontweight="bold", alpha=label_alpha, zorder=20,
        )
        draw.data_label(fig, rect[0] + rect[2], y_row, str(lineup.get("formation") or ""), size=18,
                        alpha=label_alpha, ha="right")
        players = sorted(lineup.get("players") or [], key=lambda p: p["vertical"])
        for index, player in enumerate(players):
            local = tl.stagger(index, len(players), start=0.14 + (0.06 if flip else 0.0), span=0.34,
                               duration=0.22, ease=draw.ease_out_back)
            if local <= 0.02:
                continue
            along = 5.0 + player["vertical"] / 10.0 * 40.5
            across = player["horizontal"] * 10.0
            px, py = draw.to_pitch(along, across, flip=flip)
            cx, cy = draw.pixel_of(pitch, px, py)
            r = radius * min(1.08, local)
            fill = identity.get("fill") or identity["primary"]
            tint = _rating_tint(player.get("rating"))
            fade = draw.opacity(min(1.0, local * 1.4))
            if player["player"] == motm:
                for glow_r, weight in ((r * 2.1, 0.12), (r * 1.6, 0.22)):
                    stage.add_patch(Circle((cx, cy), glow_r, facecolor="#ffd166", edgecolor="none",
                                           alpha=weight * fade, zorder=9))
            stage.add_patch(Circle((cx, cy), r * 1.22, facecolor="#060807", edgecolor="none",
                                   alpha=0.9 * fade, zorder=10))
            rating = player.get("rating")
            if rating is not None:
                sweep = 360.0 * max(0.0, min(1.0, (float(rating) - 4.0) / 6.0)) * tl.cue(0.36, 0.30)
                stage.add_patch(Wedge((cx, cy), r * 1.24, 90, 90 + 359.9, width=r * 0.20,
                                      facecolor="#1a211d", edgecolor="none", alpha=fade, zorder=11))
                if sweep > 1:
                    stage.add_patch(Wedge((cx, cy), r * 1.24, 90 - sweep, 90, width=r * 0.20,
                                          facecolor=tint, edgecolor="none", alpha=fade, zorder=12))
            stage.add_patch(Circle((cx, cy), r * 0.98, facecolor=fill, edgecolor=identity["chart"],
                                   linewidth=1.2, alpha=fade, zorder=13))
            shirt = player.get("shirt")
            if shirt not in (None, ""):
                stage.text(cx, cy, str(int(shirt)), color=theme.ink_on(fill), fontsize=13 if int(shirt) < 10 else 12,
                           fontweight="bold", family=theme.DISPLAY_FONT, ha="center", va="center",
                           alpha=fade, zorder=14)
            if local > 0.5:
                name_alpha = draw.opacity((local - 0.5) * 2)
                stage.text(cx, cy - r * 1.40, str(player.get("surname") or "")[:12].upper(), color=TEXT,
                           fontsize=8.6, family=theme.LABEL_FONT, fontweight="bold", ha="center", va="top",
                           alpha=name_alpha, zorder=15, path_effects=draw.outline(name_alpha))
                goals = int(player.get("goals") or 0)
                for g in range(min(3, goals)):
                    stage.add_patch(Circle((cx + r * (1.25 + 0.62 * g), cy + r * 0.95), r * 0.28,
                                           facecolor=design["goal"], edgecolor=TEXT, linewidth=0.8,
                                           alpha=name_alpha, zorder=16))
                for a in range(min(3, int(player.get("assists") or 0))):
                    stage.add_patch(Circle((cx - r * (1.25 + 0.62 * a), cy + r * 0.95), r * 0.26,
                                           facecolor="none", edgecolor=TEXT, linewidth=1.2,
                                           alpha=name_alpha, zorder=16))

    legend_alpha = tl.cue(0.52, 0.26)
    _caption(fig, i18n.t("legend_lineup"), top - 0.006, legend_alpha, size=8.8)
    draw.legend_row(
        fig, STAGE_FLOOR - 0.004,
        [("ring", "#ffd166", "8+"), ("ring", "#7ee0a1", "7+"), ("ring", TEXT_DIM, "6.3+"),
         ("ring", "#ef6f6c", i18n.t("below_label"))],
        alpha=legend_alpha, fontsize=theme.label_size(9),
    )
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# shot DNA: unit chart + how/with bars
# ---------------------------------------------------------------------------

_OUTCOME_ORDER = ("goal", "saved", "woodwork", "off_target", "blocked")
_SITUATION_KEYS = ("open_play", "counter", "corner", "set_piece", "free_kick", "penalty")
_BODY_KEYS = ("right_foot", "left_foot", "head", "other")


def _tile(fig, x: float, y: float, size: float, outcome: str, identity: dict[str, str],
          design: dict[str, Any], alpha: float) -> None:
    h = draw.y_of(size)
    chart = identity["chart"]
    if outcome == "goal":
        draw.fig_panel(fig, x, y, size, h, color=design["goal"], alpha=alpha, edge=TEXT, radius=0.008,
                       zorder=14, lw=1.4)
        draw.fig_ellipse(fig, x + size / 2, y + h / 2, size * 0.18, facecolor=TEXT, edgecolor="none",
                         alpha=alpha, zorder=15)
    elif outcome == "saved":
        draw.fig_panel(fig, x, y, size, h, color=chart, alpha=alpha, edge="none", radius=0.008, zorder=14)
    elif outcome == "woodwork":
        draw.fig_panel(fig, x, y, size, h, color=chart, alpha=alpha, edge=theme.WARNING, radius=0.008,
                       zorder=14, lw=2.0)
    elif outcome == "off_target":
        draw.fig_panel(fig, x, y, size, h, color="#0b0f0d", alpha=alpha, edge=chart, radius=0.008,
                       zorder=14, lw=1.6)
    else:
        draw.fig_panel(fig, x, y, size, h, color=theme.mix("#0b0f0d", chart, 0.28), alpha=alpha,
                       edge="none", radius=0.008, zorder=14)
        fig.lines.append(
            draw.plt.Line2D([x + size * 0.25, x + size * 0.75], [y + h * 0.25, y + h * 0.75],
                            transform=fig.transFigure, color=chart, linewidth=1.6, alpha=alpha, zorder=15)
        )


def _segment_bar(fig, y: float, values: dict[str, int], keys: tuple[str, ...], identity: dict[str, str],
                 label: str, alpha: float, *, label_prefix: str) -> None:
    total = sum(int(values.get(key) or 0) for key in keys)
    left, width, height = Layout.MARGIN, Layout.CONTENT_W, 0.022
    fig.text(left, y + height + 0.016, label.upper(), color=TEXT_FAINT, fontsize=theme.label_size(9),
             family=theme.LABEL_FONT, fontweight="bold", ha="left", va="center", alpha=alpha, zorder=16)
    if total <= 0:
        draw.fig_panel(fig, left, y, width, height, color="#141a17", alpha=alpha, edge="none",
                       radius=0.008, zorder=13)
        return
    present = [key for key in keys if int(values.get(key) or 0) > 0]
    cursor = left
    for rank, key in enumerate(present):
        count = int(values.get(key) or 0)
        seg_w = width * count / total * alpha
        shade = theme.mix(identity["chart"], "#0b0f0d", min(0.72, rank * 0.24))
        draw.fig_panel(fig, cursor, y, max(0.004, seg_w - 0.004), height, color=shade, alpha=0.95,
                       edge="none", radius=0.006, zorder=14)
        if seg_w >= 0.085:
            fig.text(cursor + seg_w / 2, y - 0.014, i18n.t(f"{label_prefix}{key}").upper(), color=TEXT_DIM,
                     fontsize=theme.label_size(7.6), family=theme.LABEL_FONT, fontweight="bold",
                     ha="center", va="center", alpha=alpha, zorder=16)
            draw.data_label(fig, cursor + seg_w / 2, y + height / 2, str(count), size=11,
                            color=theme.ink_on(shade), alpha=alpha)
        cursor += seg_w


def render_shot_dna(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                    path: Path, progress: float = 1.0) -> None:
    """One tile per shot, sorted by outcome, then how they came and what struck them."""
    design, fig, tl, top = _frame(bundle, scene, progress, key_row=False)
    profile = audit.get("shot_profile") or {}
    if not profile.get("available"):
        _empty(fig, tl, path, "too_few_shots_3d")
        return
    shots = audit.get("shots") or []
    panel_top = top - 0.012
    panel_h = (panel_top - STAGE_FLOOR) / 2
    for slot, (key, h_a, name) in enumerate((("home", "h", bundle.home), ("away", "a", bundle.away))):
        identity = _identity(design, h_a)
        side = profile.get(key) or {}
        y_top = panel_top - slot * panel_h
        local = tl.cue(0.06 + 0.10 * slot, 0.26)
        if local < draw.VISIBLE_ALPHA:
            continue
        draw.team_badge(fig, name, Layout.MARGIN + 0.040, y_top - 0.022, 0.070, identity=identity, alpha=local)
        draw.fit_text(fig, Layout.MARGIN + 0.092, y_top - 0.022, name.upper(), fontsize=24, max_width=0.56,
                      max_lines=1, min_fontsize=12, ha="left", va="center", color=identity["chart"],
                      family=theme.DISPLAY_FONT, fontweight="bold", alpha=local, zorder=20)
        draw.data_label(fig, 1 - Layout.MARGIN, y_top - 0.022,
                        i18n.t("n_shots_label", n=int(side.get("total") or 0)), size=14, alpha=local, ha="right")
        team_shots = sorted(
            [shot for shot in shots if shot.get("h_a") == h_a],
            key=lambda shot: (_OUTCOME_ORDER.index(shot.get("outcome")) if shot.get("outcome") in _OUTCOME_ORDER else 9,
                              shot.get("minute") or 0),
        )
        per_row = 12
        size = Layout.CONTENT_W / per_row * 0.82
        step = Layout.CONTENT_W / per_row
        grid_top = y_top - 0.062
        rows = max(1, math.ceil(len(team_shots) / per_row))
        row_h = draw.y_of(step)
        for index, shot in enumerate(team_shots):
            pop = tl.stagger(index, max(1, len(team_shots)), start=0.10 + 0.10 * slot, span=0.30,
                             duration=0.14, ease=draw.ease_out_back)
            if pop <= 0.02:
                continue
            row, col = divmod(index, per_row)
            grow = min(1.0, pop)
            tile = size * (0.6 + 0.4 * grow)
            x = Layout.MARGIN + col * step + (step - tile) / 2
            y = grid_top - row * row_h - draw.y_of(step) + (draw.y_of(step) - draw.y_of(tile)) / 2
            _tile(fig, x, y, tile, str(shot.get("outcome")), identity, design, draw.opacity(pop))
        bars_top = grid_top - rows * row_h - 0.034
        bars_alpha = tl.cue(0.40 + 0.08 * slot, 0.26)
        if bars_alpha > draw.VISIBLE_ALPHA:
            _segment_bar(fig, bars_top - 0.022, side.get("situation") or {}, _SITUATION_KEYS, identity,
                         i18n.t("shot_how"), bars_alpha, label_prefix="sit_")
            _segment_bar(fig, bars_top - 0.092, side.get("body") or {}, _BODY_KEYS, identity,
                         i18n.t("shot_with"), bars_alpha, label_prefix="body_")
    legend_alpha = tl.cue(0.56, 0.24)
    draw.legend_row(
        fig, STAGE_FLOOR - 0.010,
        [("dot", design["goal"], i18n.t("outcome_goal")), ("bar", TEXT_DIM, i18n.t("outcome_saved")),
         ("ring", TEXT_DIM, i18n.t("outcome_off_target")), ("cross", TEXT_DIM, i18n.t("outcome_blocked"))],
        alpha=legend_alpha, fontsize=theme.label_size(9),
    )
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# pass sonar
# ---------------------------------------------------------------------------

def _sonar(ax, cx: float, cy: float, radius: float, payload: dict[str, Any], sectors: int,
           peak: float, identity: dict[str, str], design: dict[str, Any], grown: float, ink: float) -> None:
    inner = radius * 0.22
    for ring in (0.25, 0.5, 0.75, 1.0):
        ax.add_patch(Circle((cx, cy), inner + (radius - inner) * ring, facecolor="none",
                            edgecolor=design["hairline"], linewidth=0.9, alpha=0.9 * ink, zorder=6))
    width = 360.0 / sectors
    counts = payload.get("counts") or [0] * sectors
    completed = payload.get("completed") or [0] * sectors
    for slot in range(sectors):
        count = float(counts[slot] or 0)
        if count <= 0:
            continue
        reach = inner + (radius - inner) * math.sqrt(count / peak) * grown
        rate = float(completed[slot] or 0) / count
        lift = max(0.0, min(1.0, (rate - 0.45) / 0.50))
        colour = theme.mix("#101512", identity["chart"], 0.22 + 0.78 * lift)
        centre = 90.0 + slot * width
        theta1, theta2 = centre - width * 0.43, centre + width * 0.43
        ax.add_patch(Wedge((cx, cy), reach + 3, theta1 - 1, theta2 + 1, width=reach - inner + 3,
                           facecolor=identity["chart"], edgecolor="none", alpha=0.10 * ink, zorder=7))
        ax.add_patch(Wedge((cx, cy), reach, theta1, theta2, width=reach - inner,
                           facecolor=colour, edgecolor=theme.mix(identity["chart"], "#ffffff", 0.25),
                           linewidth=0.8, alpha=0.95 * ink, zorder=8))
    ax.add_patch(Circle((cx, cy), inner * 0.92, facecolor="#060807", edgecolor=identity["chart"],
                        linewidth=1.4, alpha=ink, zorder=9))
    arrow_y = cy + radius + 16
    ax.add_patch(Polygon([(cx - 9, arrow_y), (cx + 9, arrow_y), (cx, arrow_y + 14)], closed=True,
                         facecolor=TEXT_FAINT, edgecolor="none", alpha=ink, zorder=9))


def _mini_meter(fig, x: float, y: float, width: float, value: float, maximum: float, colour: str,
                label: str, text: str, alpha: float) -> None:
    fig.text(x, y + 0.016, label.upper(), color=TEXT_FAINT, fontsize=theme.label_size(8),
             family=theme.LABEL_FONT, fontweight="bold", ha="left", va="center", alpha=alpha, zorder=16)
    draw.fig_rect(fig, x, y - 0.004, width, 0.008, "#171d19", alpha, zorder=14)
    draw.fig_rect(fig, x, y - 0.004, width * max(0.0, min(1.0, value / maximum)) * alpha, 0.008, colour,
                  0.95, zorder=15)
    draw.data_label(fig, x + width, y + 0.016, text, size=11, alpha=alpha, ha="right")


def render_pass_sonar(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Which way each side passed. Petal length is volume, brightness is completion."""
    design, fig, tl, top = _frame(bundle, scene, progress, key_row=False)
    sonar = audit.get("pass_sonar") or {}
    if not sonar.get("available"):
        _empty(fig, tl, path, "not_enough_passes")
        return
    sectors = int(sonar.get("sectors") or 16)
    peak = max(1.0, max(max(sonar["home"]["counts"]), max(sonar["away"]["counts"])))
    ax = depth.stage(fig, zorder=6)
    band_h = (top - STAGE_FLOOR) / 2
    radius = min(band_h * theme.FRAME_H * 0.36, theme.FRAME_W * 0.25)
    for slot, (key, h_a, name) in enumerate((("home", "h", bundle.home), ("away", "a", bundle.away))):
        identity = _identity(design, h_a)
        payload = sonar[key]
        mid = top - band_h * (slot + 0.5)
        cx, cy = theme.FRAME_W * 0.35, mid * theme.FRAME_H - 8
        ink = tl.cue(0.04 + 0.10 * slot, 0.26)
        if ink < draw.VISIBLE_ALPHA:
            continue
        grown = tl.cue(0.10 + 0.10 * slot, 0.42, ease=draw.ease_out_back)
        _sonar(ax, cx, cy, radius, payload, sectors, peak, identity, design, min(1.08, grown), ink)
        draw.team_badge(fig, name, cx / theme.FRAME_W, cy / theme.FRAME_H, 0.072, identity=identity,
                        alpha=ink, zorder=24)
        panel_x = 0.66
        draw.fit_text(fig, panel_x, mid + band_h * 0.30, name.upper(), fontsize=22, max_width=0.30,
                      max_lines=1, min_fontsize=11, ha="left", va="center", color=identity["chart"],
                      family=theme.DISPLAY_FONT, fontweight="bold", alpha=ink, zorder=20)
        meters = tl.cue(0.36 + 0.08 * slot, 0.28)
        rows = (
            (payload["forward_pct"], 100.0, i18n.t("forward_label"), f"{payload['forward_pct']:.0f}%"),
            (payload["backward_pct"], 100.0, i18n.t("backward_label"), f"{payload['backward_pct']:.0f}%"),
            (payload["avg_length_m"], 35.0, i18n.t("avg_length_label"), f"{payload['avg_length_m']:.0f} m"),
            (payload["long_pct"], 40.0, i18n.t("long_label"), f"{payload['long_pct']:.0f}%"),
        )
        for index, (value, maximum, label, text) in enumerate(rows):
            _mini_meter(fig, panel_x, mid + band_h * 0.14 - index * 0.050, 0.27, float(value), maximum,
                        identity["chart"], label, text, meters)
    _caption(fig, i18n.t("legend_sonar"), STAGE_FLOOR - 0.004, tl.cue(0.52, 0.26), size=8.5)
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# defensive block
# ---------------------------------------------------------------------------

_DEF_MARKERS = {"Tackle": "^", "Interception": "D", "BallRecovery": "o", "BlockedPass": "X", "Clearance": "s"}


def render_defensive_block(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                           path: Path, progress: float = 1.0) -> None:
    """Where each side won the ball back, its block, and how high its line sat."""
    design, fig, tl, top = _frame(bundle, scene, progress)
    shape = audit.get("defensive_shape") or {}
    if not shape.get("available"):
        _empty(fig, tl, path, "empty_block")
        return
    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=top - 0.020, bottom=STAGE_FLOOR + 0.075)
    rect[0] -= 0.035
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.02, 0.24))
    meter_x = rect[0] + rect[2] + 0.040
    for key, h_a in (("home", "h"), ("away", "a")):
        identity = _identity(design, h_a)
        payload = shape.get(key) or {}
        flip = h_a == "a"
        points = payload.get("points") or []
        visible = tl.reveal_count(len(points), start=0.08 + (0.05 if flip else 0.0), span=0.40)
        for kind, marker in _DEF_MARKERS.items():
            xs, ys = [], []
            for point in points[:visible]:
                if point.get("type") != kind:
                    continue
                px, py = draw.to_pitch(point["x"], point["y"], flip=flip)
                xs.append(px)
                ys.append(py)
            if xs:
                ax.scatter(xs, ys, s=30 if marker != "X" else 34, marker=marker, facecolor=identity["chart"],
                           edgecolor="#050706", linewidth=0.5, alpha=0.78, zorder=8)
        hull_alpha = tl.cue(0.40, 0.26)
        block = payload.get("block") or []
        if len(block) >= 3 and hull_alpha > draw.VISIBLE_ALPHA:
            verts = [draw.to_pitch(x, y, flip=flip) for x, y in block]
            ax.add_patch(Polygon(verts, closed=True, facecolor=identity["chart"], edgecolor="none",
                                 alpha=0.14 * hull_alpha, zorder=6))
            xs = [v[0] for v in verts] + [verts[0][0]]
            ys = [v[1] for v in verts] + [verts[0][1]]
            draw.glow_plot(ax, xs, ys, identity["chart"], lw=1.8, alpha=0.9 * hull_alpha, zorder=9)
        line_alpha = tl.cue(0.50, 0.26)
        height_m = float(payload.get("line_height_m") or 0)
        if line_alpha > draw.VISIBLE_ALPHA and height_m > 0:
            pct = height_m / depth.PITCH_X * 100.0
            line_y = 100.0 - pct if flip else pct
            reach = 100.0 * tl.wipe(0.50, 0.24)
            ax.plot([0, reach], [line_y, line_y], color=identity["chart"], lw=2.2, alpha=line_alpha,
                    zorder=10, ls=(0, (6, 4)))
            fy = rect[1] + rect[3] * line_y / 100.0
            draw.fig_rect(fig, meter_x - 0.010, fy - 0.0015, 0.020, 0.003, identity["chart"], line_alpha, zorder=16)
            draw.data_label(fig, meter_x + 0.016, fy, f"{height_m:.0f} m", size=12, alpha=line_alpha, ha="left")
    meter_alpha = tl.cue(0.44, 0.24)
    if meter_alpha > draw.VISIBLE_ALPHA:
        draw.fig_rect(fig, meter_x - 0.0015, rect[1], 0.003, rect[3], design["hairline"], meter_alpha, zorder=14)
    legend_alpha = tl.cue(0.56, 0.24)
    home, away = shape.get("home") or {}, shape.get("away") or {}
    _dual_meters(fig, design, STAGE_FLOOR + 0.024, float(home.get("high_pct") or 0),
                 float(away.get("high_pct") or 0), i18n.t("won_high_label"), legend_alpha)
    _caption(fig, i18n.t("legend_block"), STAGE_FLOOR - 0.016, legend_alpha, size=8.5)
    draw.save_figure(fig, path)


INFOGRAPHIC_RENDERERS = {
    "touch_skyline": render_touch_skyline,
    "shot_skyline": render_shot_skyline,
    "shot_trajectories": render_shot_trajectories,
    "player_podium": render_player_podium,
    "lineup_board": render_lineup_board,
    "shot_dna": render_shot_dna,
    "pass_sonar": render_pass_sonar,
    "defensive_block": render_defensive_block,
}
