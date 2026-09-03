"""New recap visualizations: slams, radar, heat, waves, gauges, funnels.

Imported by ``scenes`` and registered there. Does not import ``scenes``, so the
layering (draw → scenes) stays one-way.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.patches import Circle, Ellipse, Polygon

from . import draw, i18n, theme
from .audit import GOAL_Y_MAX, GOAL_Y_MIN, GOAL_Z_MAX, build_pass_network, dominant_team
from .data import MatchBundle
from .director import format_stat, pick_stat_rows, stat_label
from .draw import Layout, Timeline
from .theme import TEXT, TEXT_DIM, TEXT_FAINT


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

    grown = tl.cue(0.04, 0.40, ease=draw.ease_out_back)
    shown = tl.count_to(float(value), start=0.04, duration=0.42)
    text = format_stat(key, shown) if key.endswith("_pct") or key in {"xg", "xgot"} else str(int(round(shown)))
    draw.hero_number(fig, 0.5, 0.58, text, color=identity["chart"], alpha=grown, fontsize=188.0)
    draw.fit_text(
        fig, 0.5, 0.38, str(scene.get("hero_label") or stat_label(key)).upper(),
        fontsize=34, max_width=0.86, max_lines=1, min_fontsize=18,
        ha="center", va="center", color=TEXT,
        family=theme.DISPLAY_FONT, fontweight="bold", alpha=tl.cue(0.18, 0.28), zorder=22,
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
    grown = tl.cue(0.08, 0.52, ease=draw.ease_in_out)
    grid_alpha = tl.cue(0.04, 0.28, ease=draw.ease_in_out)

    count = len(keys)
    if grid_alpha > 0.02:
        for ring in (0.25, 0.5, 0.75, 1.0):
            xs, ys = [], []
            for index in range(count):
                angle = index * math.tau / count + math.pi / 2
                xs.append(0.5 + math.cos(angle) * 0.48 * ring)
                ys.append(0.5 + math.sin(angle) * 0.48 * ring)
            xs.append(xs[0])
            ys.append(ys[0])
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
    grown = tl.cue(0.06, 0.55, ease=draw.ease_in_out)
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
        _empty_note(fig, tl, "pressure_curve_empty")
        draw.save_figure(fig, path)
        return

    chart_top = content_top - 0.08
    rect = [Layout.MARGIN, 0.18, Layout.CONTENT_W, chart_top - 0.18]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#000000")
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
    _team_key_row(fig, design, bundle, content_top - 0.028, tl.cue(0.08, 0.24))
    grown = tl.cue(0.08, 0.52, ease=draw.ease_in_out)

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
        shown_on = tl.count_to(on, start=0.12, duration=0.50)
        shown_inner = tl.count_to(inner_value, start=0.12, duration=0.50)
        ax.text(0.5, 0.52, f"{int(round(shown_on))}" if not use_xg else f"{shown_inner:.1f}",
                color=TEXT, fontsize=36, fontweight="bold", family=theme.DISPLAY_FONT,
                ha="center", va="center", alpha=grown, zorder=12)
        ax.text(0.5, 0.18, name.upper(), color=identity["chart"], fontsize=13,
                family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
                alpha=tl.cue(0.28, 0.24), zorder=12)
        inner_shown = format_stat("xg", shown_inner) if use_xg else str(int(round(shown_inner)))
        fig.text(
            cx, 0.22,
            f"{int(round(shown_on))} {stat_label('shots_on_target').upper()}  ·  {str(inner_label).upper()} {inner_shown}",
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
        _empty_note(fig, tl, "too_few_shots_frame")
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
    ax.set_facecolor("#000000")
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
    fig.text(Layout.MARGIN + 0.02, content_top - 0.072, f"{shown_h:.2f}",
             color=design["home"]["chart"], fontsize=42, fontweight="bold",
             family=theme.DISPLAY_FONT, ha="left", va="center",
             alpha=tl.cue(0.14, 0.24), zorder=22, path_effects=draw.soft_shadow(tl.cue(0.14, 0.24)))
    fig.text(1 - Layout.MARGIN - 0.02, content_top - 0.072, f"{shown_a:.2f}",
             color=design["away"]["chart"], fontsize=42, fontweight="bold",
             family=theme.DISPLAY_FONT, ha="right", va="center",
             alpha=tl.cue(0.18, 0.24), zorder=22, path_effects=draw.soft_shadow(tl.cue(0.18, 0.24)))

    rect = [Layout.MARGIN, 0.20, Layout.CONTENT_W, content_top - 0.34]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#000000")
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
    draw.hero_number(fig, 0.5, 0.58, shown, color=identity["chart"],
                     alpha=tl.cue(0.08, 0.34, ease=draw.ease_out_back), fontsize=168.0)
    fig.text(
        0.5, 0.38, f"{str(spike.get('surname') or spike.get('player') or '').upper()}",
        color=TEXT, fontsize=36, family=theme.DISPLAY_FONT, fontweight="bold",
        ha="center", va="center", alpha=tl.cue(0.22, 0.24), zorder=22,
    )
    fig.text(
        0.5, 0.325, str(spike.get("action") or "").upper(),
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
    grown = draw.ease_in_out(draw.clamp01(progress))
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
    ink = min(1.0, grown * 2.0)
    if percent:
        home_text = f"{draw.hold_count(home_value, grown):.0f}%"
        away_text = f"{draw.hold_count(away_value, grown):.0f}%"
    else:
        home_text = draw.number_text(draw.hold_count(home_value, grown))
        away_text = draw.number_text(draw.hold_count(away_value, grown))
    fig.text(0.5, y + height + 0.014, str(label).upper(), color=TEXT_DIM,
             fontsize=theme.label_size(11), family=theme.LABEL_FONT, fontweight="bold",
             ha="center", va="center", alpha=ink, zorder=14)
    fig.text(left - 0.012, y + height / 2, home_text, color=home_chart, fontsize=26,
             fontweight="bold", family=theme.DISPLAY_FONT, ha="right", va="center",
             alpha=ink, zorder=14, path_effects=draw.soft_shadow(ink))
    fig.text(right + 0.012, y + height / 2, away_text, color=away_chart, fontsize=26,
             fontweight="bold", family=theme.DISPLAY_FONT, ha="left", va="center",
             alpha=ink, zorder=14, path_effects=draw.soft_shadow(ink))


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

    shown = int(round(tl.count_to(len(shots), start=0.08, duration=0.40)))
    draw.hero_number(fig, 0.5, 0.18, shown, color=TEXT, fontsize=72.0,
                     alpha=tl.cue(0.10, 0.28))
    fig.text(0.5, 0.125, i18n.t("sub_spiral").upper(), color=TEXT_DIM, fontsize=13,
             family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
             alpha=tl.cue(0.28, 0.22), zorder=22)

    rect = Layout.fitted_rect(1.0, top=content_top - 0.01, bottom=0.24, align="center")
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
        identity = design["home"] if trap.get("leader") == bundle.home else design["away"]
        draw.hero_number(fig, 0.5, 0.50, f"{shown:.1f}", color=identity["chart"],
                         fontsize=96.0, alpha=tl.cue(0.16, 0.32))
        fig.text(0.5, 0.40, i18n.t("vis_ppda_label"), color=TEXT_DIM, fontsize=22, family=theme.MONO_FONT,
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
    fig.text(rect[0], rect[1] + rect[3] + 0.016, i18n.t("vis_lanes_count", n=shown, team=focus.upper()),
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
    wipe = tl.wipe(0.08, 0.52)
    draw.hero_number(fig, 0.5, content_top - 0.10, shown, color=TEXT, fontsize=72.0,
                     alpha=tl.cue(0.10, 0.28, ease=draw.ease_in_out))
    fig.text(0.5, content_top - 0.155, i18n.t("bench_axis", n=int(last)), color=TEXT_DIM,
             fontsize=14, family=theme.MONO_FONT, fontweight="bold",
             ha="center", va="center", alpha=tl.cue(0.24, 0.22, ease=draw.ease_in_out), zorder=20)

    rect = [Layout.MARGIN, 0.22, Layout.CONTENT_W, 0.36]
    ax = fig.add_axes(rect, zorder=6)
    ax.set_xlim(0, last)
    ax.set_ylim(-1.35, 1.35)
    ax.set_axis_off()
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
    """Stacked cubes — tackles / aerials / take-ons. Not a bar chart."""
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
        ("tackles", i18n.t("vis_layer_tackles")),
        ("aerials", i18n.t("vis_layer_aerials")),
        ("take_ons", i18n.t("vis_layer_takeons")),
    )
    peak = max(
        1,
        max(int(home.get(key) or 0) for key, _ in layers),
        max(int(away.get(key) or 0) for key, _ in layers),
    )
    home_total = int(home.get("total") or 0)
    away_total = int(away.get("total") or 0)
    home_alpha = tl.cue(0.08, 0.28)
    away_alpha = tl.cue(0.12, 0.28)
    draw.hero_number(
        fig, 0.28, content_top - 0.10,
        int(round(tl.count_to(home_total, start=0.10, duration=0.40))),
        color=design["home"]["chart"], alpha=home_alpha, fontsize=64.0,
    )
    draw.hero_number(
        fig, 0.72, content_top - 0.10,
        int(round(tl.count_to(away_total, start=0.14, duration=0.40))),
        color=design["away"]["chart"], alpha=away_alpha, fontsize=64.0,
    )

    base_y = 0.20
    block_h = 0.12
    for index, (key, label) in enumerate(layers):
        local = tl.stagger(index, 3, start=0.16, span=0.40, duration=0.28, ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        y = base_y + index * (block_h + 0.028)
        fig.text(0.5, y + block_h + 0.006, label, color=TEXT_DIM, fontsize=12,
                 family=theme.MONO_FONT, fontweight="bold", ha="center", va="bottom",
                 alpha=local, zorder=16)
        for cx, payload, identity in (
            (0.28, home, design["home"]),
            (0.72, away, design["away"]),
        ):
            value = int(payload.get(key) or 0)
            width = 0.10 + 0.16 * (value / peak) * local
            # Trapezoid that narrows as it rises — a tower block, not a bar.
            inset = 0.018
            poly = Polygon(
                [
                    (cx - width / 2, y),
                    (cx + width / 2, y),
                    (cx + width / 2 - inset, y + block_h * local),
                    (cx - width / 2 + inset, y + block_h * local),
                ],
                closed=True, transform=fig.transFigure, facecolor=identity["fill"],
                edgecolor=identity["chart"], linewidth=1.4, alpha=0.92 * local, zorder=12,
            )
            fig.patches.append(poly)
            shown = int(round(draw.hold_count(value, local)))
            fig.text(cx, y + block_h * local / 2, str(shown), color=TEXT,
                     fontsize=28, fontweight="bold", family=theme.DISPLAY_FONT,
                     ha="center", va="center", alpha=local, zorder=14,
                     path_effects=draw.soft_shadow(local))
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

    draw.hero_number(
        fig, 0.28, 0.72,
        int(round(tl.count_to(home_won, start=0.10, duration=0.40))),
        color=design["home"]["chart"], alpha=tl.cue(0.08, 0.28), fontsize=72.0,
    )
    draw.hero_number(
        fig, 0.72, 0.72,
        int(round(tl.count_to(away_won, start=0.14, duration=0.40))),
        color=design["away"]["chart"], alpha=tl.cue(0.12, 0.28), fontsize=72.0,
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
    ax.set_facecolor("#000000")
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
    grown = tl.wipe(0.08, 0.42)
    # Diagonal slash through the frame, eased in like the momentum wave.
    fig.patches.append(
        Polygon(
            [(0.02, 0.18), (0.12, 0.18), (0.98, 0.78), (0.88, 0.78)],
            closed=True, transform=fig.transFigure, facecolor=TEXT,
            edgecolor="none", alpha=0.08 * grown, zorder=8,
        )
    )

    def stamp(x: float, payload: dict[str, Any], label: str, start: float) -> None:
        shots = int(payload.get("home_shots") or 0) + int(payload.get("away_shots") or 0)
        shown = int(round(tl.count_to(shots, start=start, duration=0.40)))
        ink = tl.cue(start, 0.28, ease=draw.ease_in_out)
        fig.text(x, 0.52, str(shown), color=TEXT, fontsize=120, fontweight="bold",
                 family=theme.DISPLAY_FONT, ha="center", va="center",
                 alpha=ink, zorder=16,
                 path_effects=draw.soft_shadow(ink))
        fig.text(x, 0.36, label, color=TEXT_DIM, fontsize=22, family=theme.MONO_FONT,
                 fontweight="bold", ha="center", va="center",
                 alpha=tl.cue(start + 0.08, 0.22, ease=draw.ease_in_out), zorder=16)
        fig.text(
            x, 0.28,
            i18n.t(
                "vis_half_shots",
                home=int(payload.get("home_shots") or 0),
                away=int(payload.get("away_shots") or 0),
            ),
            color=TEXT_FAINT, fontsize=13, family=theme.MONO_FONT, fontweight="bold",
            ha="center", va="center",
            alpha=tl.cue(start + 0.12, 0.22, ease=draw.ease_in_out), zorder=16,
        )

    stamp(0.28, first, "1H", 0.12)
    stamp(0.72, second, "2H", 0.22)
    fig.text(0.5, 0.20, i18n.t("halftime_stamp").upper(), color=TEXT_DIM, fontsize=16,
             family=theme.DISPLAY_FONT, fontweight="bold", ha="center", va="center",
             alpha=tl.cue(0.40, 0.24), zorder=16)
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
