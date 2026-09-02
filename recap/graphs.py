"""New recap visualizations: slams, radar, heat, waves, gauges, funnels.

Imported by ``scenes`` and registered there. Does not import ``scenes``, so the
layering (draw → scenes) stays one-way.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.patches import Ellipse, Polygon

from . import draw, i18n, theme
from .audit import GOAL_Y_MAX, GOAL_Y_MIN, GOAL_Z_MAX, dominant_team
from .data import MatchBundle
from .director import format_stat, pick_stat_rows, stat_label
from .draw import Layout, Timeline
from .theme import TEXT, TEXT_DIM, TEXT_FAINT


def _chrome(fig, scene: dict[str, Any], tl: Timeline, *, headline_size: float = 50.0) -> float:
    header_bottom = draw.headline(
        fig, scene.get("title", ""), "",
        alpha=tl.cue(0.04, 0.26), fontsize=headline_size,
    )
    insight = str(scene.get("insight") or "").strip()
    if insight and tl.raw >= 0.72:
        stamp = draw.ease_out_cubic(min(1.0, (tl.raw - 0.72) / 0.14))
        draw.caption_bar(fig, insight, y=Layout.STAGE_BOTTOM + 0.024, progress=stamp)
    return header_bottom - 0.016


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
    return ["shots", "shots_on_target", "pass_share_pct", "penalty_box_touches", "tackles_won", "saves"]


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

    flash = tl.raw < 0.08
    if flash:
        draw.color_flash(fig, identity.get("fill") or identity["primary"], alpha=0.92, zorder=5)

    grown = tl.cue(0.06, 0.38, ease=draw.ease_out_back)
    shown = tl.count_to(float(value), start=0.08, duration=0.42)
    text = format_stat(key, shown) if key.endswith("_pct") or key in {"xg", "xgot"} else str(int(round(shown)))
    color = "#120e08" if flash else identity["chart"]
    draw.hero_number(fig, 0.5, 0.58, text, color=color, alpha=max(0.4, grown), fontsize=188.0)
    draw.fit_text(
        fig, 0.5, 0.38, str(scene.get("hero_label") or stat_label(key)).upper(),
        fontsize=34, max_width=0.86, max_lines=1, min_fontsize=18,
        ha="center", va="center", color=TEXT if not flash else "#120e08",
        family=theme.DISPLAY_FONT, fontweight="bold", alpha=tl.cue(0.22, 0.28), zorder=22,
    )
    draw.fit_text(
        fig, 0.5, 0.30, f"{other.upper()}  {format_stat(key, other_value)}",
        fontsize=22, max_width=0.86, max_lines=1, min_fontsize=13,
        ha="center", va="center", color=TEXT_DIM, family=theme.LABEL_FONT, fontweight="bold",
        alpha=tl.cue(0.34, 0.28), zorder=22,
    )
    draw.team_badge(fig, leader, 0.5, 0.20, 0.14, identity=identity, alpha=tl.cue(0.28, 0.30), zorder=22)
    _stamp_insight(fig, scene, tl)
    draw.save_figure(fig, path)


def render_match_radar(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                       path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    keys = [key for key in _radar_axes() if key in home and key in away]
    if len(keys) < 3:
        keys = ["shots", "shots_on_target", "pass_share_pct"]

    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))

    rect = [0.12, 0.22, 0.76, 0.52]
    ax = fig.add_axes(rect, zorder=6)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_aspect("equal")

    maxima = [max(float(home.get(key) or 0), float(away.get(key) or 0), 1.0) for key in keys]
    home_vals = [float(home.get(key) or 0) / peak for key, peak in zip(keys, maxima)]
    away_vals = [float(away.get(key) or 0) / peak for key, peak in zip(keys, maxima)]
    grown = tl.cue(0.12, 0.50)

    count = len(keys)
    for ring in (0.25, 0.5, 0.75, 1.0):
        xs, ys = [], []
        for index in range(count):
            angle = index * math.tau / count + math.pi / 2
            xs.append(0.5 + math.cos(angle) * 0.48 * ring)
            ys.append(0.5 + math.sin(angle) * 0.48 * ring)
        xs.append(xs[0])
        ys.append(ys[0])
        ax.plot(xs, ys, color=design["hairline"], lw=0.8, alpha=0.7, zorder=4)
        ax.plot([0.5, xs[0]], [0.5, ys[0]], color=design["hairline"], lw=0.6, alpha=0.35, zorder=4)
    for index in range(count):
        angle = index * math.tau / count + math.pi / 2
        ax.plot([0.5, 0.5 + math.cos(angle) * 0.48], [0.5, 0.5 + math.sin(angle) * 0.48],
                color=design["hairline"], lw=0.7, alpha=0.45, zorder=4)

    draw.radar_polygon(ax, home_vals, design["home"]["chart"], progress=grown, fill_alpha=0.32, lw=2.4)
    draw.radar_polygon(ax, away_vals, design["away"]["chart"], progress=grown, fill_alpha=0.28, lw=2.4)

    label_alpha = tl.cue(0.28, 0.30)
    for index, key in enumerate(keys):
        angle = index * math.tau / count + math.pi / 2
        lx = 0.5 + math.cos(angle) * 0.58
        ly = 0.5 + math.sin(angle) * 0.58
        ax.text(lx, ly, stat_label(key).upper(), color=TEXT_DIM, fontsize=9,
                family=theme.MONO_FONT, ha="center", va="center", alpha=label_alpha, zorder=12)
    draw.save_figure(fig, path)


def render_touch_heatmap(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    heat = audit.get("touch_heatmap") or {}
    content_top = _chrome(fig, scene, tl)
    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.02, bottom=0.16)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))
    grown = tl.cue(0.10, 0.55)
    home_grid = heat.get("home") or []
    away_grid = heat.get("away") or []
    if home_grid:
        draw.heat_pitch(ax, home_grid, design["home"]["fill"], progress=grown, zorder=6)
    if away_grid:
        draw.heat_pitch(ax, away_grid, design["away"]["fill"], progress=grown * 0.92, zorder=7)
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
        fig.text(0.5, 0.5, i18n.t("pressure_curve_empty"), color=TEXT_DIM,
                 fontsize=22, family=theme.DISPLAY_FONT, ha="center", zorder=14)
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

    reveal = draw.ease_in_out(draw.clamp01((tl.t - 0.10) / 0.55))
    cutoff = span * reveal
    dense_x, home_y = _smooth_series(starts, home, cutoff)
    _, away_y = _smooth_series(starts, away, cutoff)
    ax.axhline(50, color=design["pitch_line"], lw=1.2, alpha=0.8, zorder=5)
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
                path_effects=draw.outline(), alpha=peak_alpha, zorder=12)
    draw.save_figure(fig, path)


def render_conversion_gauges(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                             path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    grown = tl.cue(0.12, 0.50)

    pairs = (
        (0.28, bundle.home, home, design["home"]),
        (0.72, bundle.away, away, design["away"]),
    )
    health = audit.get("data_health") or {}
    use_xg = bool(health.get("has_vendor_xg"))
    for cx, name, team, identity in pairs:
        ax = fig.add_axes([cx - 0.18, 0.32, 0.36, 0.36], zorder=6)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_axis_off()
        ax.set_aspect("equal")
        shots = float(team.get("shots") or 0)
        on = float(team.get("shots_on_target") or 0)
        goals = float(team.get("goals") or 0)
        if use_xg and team.get("xg") is not None:
            inner_value, inner_max, inner_label = float(team.get("xg") or 0), max(shots / 4, 1.5), "xG"
        else:
            inner_value, inner_max, inner_label = goals, max(on, 1.0), i18n.t("goals")
        draw.ring_gauge(ax, 0.5, 0.52, on, max(shots, 1.0), identity["chart"],
                        progress=grown, radius=0.38, width=0.07, zorder=8)
        draw.ring_gauge(ax, 0.5, 0.52, inner_value, inner_max, identity.get("fill") or identity["primary"],
                        progress=grown, radius=0.28, width=0.06, zorder=9)
        ax.text(0.5, 0.52, f"{int(on)}" if not use_xg else f"{inner_value:.1f}",
                color=TEXT, fontsize=36, fontweight="bold", family=theme.DISPLAY_FONT,
                ha="center", va="center", alpha=grown, zorder=12)
        ax.text(0.5, 0.18, name.upper(), color=identity["chart"], fontsize=13,
                family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
                alpha=tl.cue(0.28, 0.24), zorder=12)
        inner_shown = format_stat("xg", inner_value) if use_xg else str(int(inner_value))
        fig.text(
            cx, 0.22,
            f"{int(on)} ON TARGET  ·  {str(inner_label).upper()} {inner_shown}",
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

    funnel = [
        ("pass_share_pct", i18n.t("pass_share"), True),
        ("final_third_passes", i18n.t("final_third_short"), False),
        ("box_entry_passes", i18n.t("into_box_short"), False),
        ("shots", stat_label("shots"), False),
        ("shots_on_target", stat_label("shots_on_target"), False),
        ("goals", stat_label("goals"), False),
    ]
    top = content_top - 0.08
    bottom = Layout.STAGE_BOTTOM + 0.055
    step = (top - bottom) / len(funnel)
    for index, (key, label, percent) in enumerate(funnel):
        local = tl.stagger(index, len(funnel), start=0.10, span=0.52, duration=0.28)
        if local <= 0.01:
            continue
        inset = 0.04 + 0.055 * (index / max(1, len(funnel) - 1))
        next_inset = 0.04 + 0.055 * ((index + 1) / max(1, len(funnel) - 1))
        y = top - step * (index + 1) + step * 0.18
        _funnel_trap(
            fig, y, step * 0.62, inset, next_inset,
            float(home.get(key) or 0), float(away.get(key) or 0),
            design["home"]["fill"], design["away"]["fill"],
            label, local, percent=percent,
            home_chart=design["home"]["chart"], away_chart=design["away"]["chart"],
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
        fig.text(0.5, 0.5, i18n.t("too_few_shots_frame"), color=TEXT_DIM, fontsize=22,
                 family=theme.DISPLAY_FONT, ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    view_y_min, view_y_max = GOAL_Y_MIN - 1.4, GOAL_Y_MAX + 1.4
    view_z_max = GOAL_Z_MAX * 1.18
    metres_wide = (view_y_max - view_y_min) / (GOAL_Y_MAX - GOAL_Y_MIN) * 7.32
    metres_tall = view_z_max / GOAL_Z_MAX * 2.44
    rect = Layout.fitted_rect(metres_wide / metres_tall, top=content_top - 0.04, bottom=0.22, align="top")
    ax = fig.add_axes(rect, zorder=4)
    ax.set_xlim(view_y_min, view_y_max)
    ax.set_ylim(0, view_z_max)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor("#070a09")
    for spine in ax.spines.values():
        spine.set_visible(False)

    frame_alpha = tl.cue(0.06, 0.26)
    ax.plot([GOAL_Y_MIN, GOAL_Y_MIN, GOAL_Y_MAX, GOAL_Y_MAX],
            [0, GOAL_Z_MAX, GOAL_Z_MAX, 0], color=TEXT, lw=4.2, alpha=frame_alpha, zorder=8)
    ax.plot([view_y_min, view_y_max], [0, 0], color=design["pitch_line"], lw=2.0, alpha=frame_alpha, zorder=6)

    visible = tl.reveal_count(len(on_target), start=0.14, span=0.52)
    for index, shot in enumerate(on_target):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(on_target)), start=0.14, span=0.52, duration=0.18,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        colour = design["goal"] if shot["outcome"] == "goal" else theme.side_color(design, shot["h_a"], "fill")
        threat = 1.15 if shot.get("big_chance") else 0.85
        if shot.get("xg"):
            threat = 0.7 + min(1.4, float(shot["xg"]) * 2.2)
        rx, ry = 0.28 * threat * local, 0.18 * threat * local
        draw.add_shape(
            ax,
            Ellipse((shot["goal_mouth_y"], shot["goal_mouth_z"]), rx * 2, ry * 2,
                    facecolor=colour, edgecolor=TEXT if shot["outcome"] == "goal" else "none",
                    linewidth=1.2, alpha=draw.opacity(0.55 + 0.4 * local), zorder=12),
        )
        if shot["outcome"] == "goal" and local > 0.45:
            draw.particle_burst(ax, shot["goal_mouth_y"], shot["goal_mouth_z"], design["goal"],
                                min(1.0, (local - 0.45) * 2), count=7, radius=0.55, zorder=14)
    draw.legend_row(
        fig, 0.155,
        [("dot", design["goal"], i18n.t("outcome_goal")),
         ("dot", design["home"]["chart"], bundle.home),
         ("dot", design["away"]["chart"], bundle.away)],
        alpha=tl.cue(0.48, 0.26), fontsize=theme.label_size(10),
    )
    draw.save_figure(fig, path)


def render_xg_race(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                   path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    shots = sorted(
        [shot for shot in (audit.get("shots") or []) if shot.get("xg") is not None and shot.get("minute") is not None],
        key=lambda shot: float(shot["minute"]),
    )
    content_top = _chrome(fig, scene, tl)
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    if len(shots) < 2:
        fig.text(0.5, 0.5, "NO VENDOR xG", color=TEXT_DIM, fontsize=22,
                 family=theme.DISPLAY_FONT, ha="center", zorder=14)
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

    rect = [Layout.MARGIN, 0.20, Layout.CONTENT_W, content_top - 0.28]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#0b0f0d")
    for spine in ax.spines.values():
        spine.set_visible(False)
    peak = max(home_y[-1], away_y[-1], 0.6) * 1.18
    ax.set_xlim(0, last)
    ax.set_ylim(0, peak)
    ax.tick_params(colors=TEXT_FAINT, labelsize=9)
    reveal = draw.ease_in_out(draw.clamp01((tl.t - 0.10) / 0.55))
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
            where="post", color=design["home"]["chart"], lw=2.6, zorder=8)
    ax.step(ax_[ax_ <= cut + 0.01], ay[: len(ax_[ax_ <= cut + 0.01])],
            where="post", color=design["away"]["chart"], lw=2.6, zorder=8)
    for goal in audit.get("goal_timeline") or []:
        minute = float(goal.get("minute") or 0)
        if minute > cut + 1:
            continue
        colour = theme.side_color(design, goal["h_a"])
        ax.axvline(minute, color=colour, lw=1.3, alpha=0.55 * tl.cue(0.40, 0.24), zorder=7)
        ax.scatter([minute], [peak * 0.06], s=70, color=colour, edgecolor=TEXT, zorder=10,
                   alpha=tl.cue(0.40, 0.24))
    draw.save_figure(fig, path)


def render_time_zones(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    slices = audit.get("time_zones") or []
    content_top = _chrome(fig, scene, tl)
    if len(slices) < 3:
        fig.text(0.5, 0.5, i18n.t("no_touch_coords"), color=TEXT_DIM, fontsize=20,
                 family=theme.DISPLAY_FONT, ha="center", zorder=14)
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
        ax.imshow(grid, origin="lower", extent=(0, 100, 0, 100), interpolation="bilinear",
                  aspect="auto", zorder=5)
        leader = bundle.home if slice_.get("home_touches", 0) >= slice_.get("away_touches", 0) else bundle.away
        fig.text(1 - Layout.MARGIN, top - 0.012, leader.upper(),
                 color=design["home"]["chart"] if leader == bundle.home else design["away"]["chart"],
                 fontsize=theme.label_size(11), family=theme.DISPLAY_FONT, fontweight="bold",
                 ha="right", va="center", alpha=local, zorder=20)
    draw.save_figure(fig, path)


def render_player_spike(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    spike = (audit.get("player_leaders") or {}).get("spike") or {}
    content_top = _chrome(fig, scene, tl)
    if not spike:
        fig.text(0.5, 0.5, "NO SPIKE", color=TEXT_DIM, fontsize=22,
                 family=theme.DISPLAY_FONT, ha="center", zorder=14)
        draw.save_figure(fig, path)
        return

    identity = design["home"] if spike.get("h_a") == "h" else design["away"]
    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.02, bottom=0.22)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))
    points = spike.get("points") or []
    visible = tl.reveal_count(len(points), start=0.12, span=0.50)
    xs, ys, sizes, alphas = [], [], [], []
    for index, point in enumerate(points):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(points)), start=0.12, span=0.50, duration=0.16,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        px, py = draw.to_pitch(point["x"], point["y"], flip=spike.get("h_a") == "a")
        xs.append(px)
        ys.append(py)
        sizes.append(90 + 80 * local)
        alphas.append(draw.opacity(local))
    draw.scatter_batch(ax, xs, ys, sizes=sizes, colors=[identity["fill"]] * len(xs),
                       alphas=alphas, linewidth=1.0, zorder=12)
    grown = tl.cue(0.10, 0.40, ease=draw.ease_out_back)
    draw.hero_number(
        fig, 0.5, 0.18, int(spike.get("count") or 0),
        color=identity["chart"], alpha=grown, fontsize=92.0,
    )
    fig.text(0.5, 0.125, f"{str(spike.get('surname') or spike.get('player') or '').upper()}  ·  {str(spike.get('action') or '').upper()}",
             color=TEXT_DIM, fontsize=16, family=theme.MONO_FONT, fontweight="bold",
             ha="center", va="center", alpha=tl.cue(0.28, 0.24), zorder=22)
    draw.save_figure(fig, path)


def _stamp_insight(fig, scene: dict[str, Any], tl: Timeline) -> None:
    insight = str(scene.get("insight") or "").strip()
    if insight and tl.raw >= 0.72:
        stamp = draw.ease_out_cubic(min(1.0, (tl.raw - 0.72) / 0.14))
        draw.caption_bar(fig, insight, y=Layout.STAGE_BOTTOM + 0.024, progress=stamp)


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


def _funnel_trap(
    fig, y: float, height: float, inset: float, next_inset: float,
    home_value: float, away_value: float, home_fill: str, away_fill: str,
    label: str, progress: float, *, percent: bool, home_chart: str, away_chart: str,
) -> None:
    left = 0.16 + inset
    right = 0.84 - inset
    inner_left = 0.16 + next_inset
    inner_right = 0.84 - next_inset
    total = home_value + away_value
    share = 0.5 if total <= 0 else home_value / max(total, 1e-6)
    grown = draw.clamp01(progress)
    mid_top = left + (right - left) * share
    mid_bot = inner_left + (inner_right - inner_left) * share
    home_poly = Polygon(
        [(left, y + height), (mid_top, y + height), (mid_bot, y), (inner_left, y)],
        closed=True, transform=fig.transFigure, facecolor=home_fill, edgecolor="none",
        alpha=0.92 * grown, zorder=12,
    )
    away_poly = Polygon(
        [(mid_top, y + height), (right, y + height), (inner_right, y), (mid_bot, y)],
        closed=True, transform=fig.transFigure, facecolor=away_fill, edgecolor="none",
        alpha=0.92 * grown, zorder=12,
    )
    fig.patches.append(home_poly)
    fig.patches.append(away_poly)
    home_text = f"{home_value:.0f}%" if percent else draw.number_text(home_value * grown)
    away_text = f"{away_value:.0f}%" if percent else draw.number_text(away_value * grown)
    if percent:
        home_text = f"{home_value:.0f}%"
        away_text = f"{away_value:.0f}%"
    fig.text(0.5, y + height + 0.014, str(label).upper(), color=TEXT_DIM,
             fontsize=theme.label_size(11), family=theme.LABEL_FONT, fontweight="bold",
             ha="center", va="center", alpha=min(1.0, progress * 2.0), zorder=14)
    fig.text(left - 0.012, y + height / 2, home_text, color=home_chart, fontsize=26,
             fontweight="bold", family=theme.DISPLAY_FONT, ha="right", va="center",
             alpha=min(1.0, progress * 2.0), zorder=14, path_effects=draw.soft_shadow())
    fig.text(right + 0.012, y + height / 2, away_text, color=away_chart, fontsize=26,
             fontweight="bold", family=theme.DISPLAY_FONT, ha="left", va="center",
             alpha=min(1.0, progress * 2.0), zorder=14, path_effects=draw.soft_shadow())
