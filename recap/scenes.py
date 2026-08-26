"""One renderer per visualization.

Every renderer has the same signature and is a pure function of
``(bundle, audit, scene, progress)``. ``progress`` is a linear 0-1 position
through the scene's own duration; all easing happens inside via ``Timeline``.

Shared rules, so that scenes look like they belong to the same product:

* Chrome is the headline only. Kickers, subtitles, insight captions and
  corner watermarks are left off so the card stays one idea.
* Pitches are vertical, and a team that attacks the bottom of the frame is
  drawn mirrored rather than sharing a goal with its opponent.
* Nothing is drawn outside the stage band, so text cannot land on data.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle

from . import draw, i18n, theme
from .audit import GOAL_Y_MAX, GOAL_Y_MIN, GOAL_Z_MAX, best_goal_chain, build_pass_network, dominant_team
from .data import MatchBundle
from .director import format_stat, stat_label
from .draw import Layout, Timeline
from .theme import TEXT, TEXT_DIM, TEXT_FAINT

Renderer = Callable[[MatchBundle, dict[str, Any], dict[str, Any], Path, float], None]

# Shot outcome styling, shared by the shot map and its legend.
OUTCOME_STYLE = {
    "goal": {"label_key": "outcome_goal", "marker": "dot", "size": 240},
    "saved": {"label_key": "outcome_saved", "marker": "dot", "size": 120},
    "off_target": {"label_key": "outcome_off_target", "marker": "ring", "size": 110},
    "blocked": {"label_key": "outcome_blocked", "marker": "cross", "size": 105},
    "woodwork": {"label_key": "outcome_woodwork", "marker": "ring", "size": 140},
}


# ---------------------------------------------------------------------------
# shared blocks
# ---------------------------------------------------------------------------

def _chrome(fig, bundle: MatchBundle, scene: dict[str, Any], tl: Timeline, *,
            headline_size: float = 50.0) -> float:
    """Draw the headline and return the y where scene content may start."""
    header_bottom = draw.headline(
        fig,
        scene.get("title", ""),
        "",
        alpha=tl.cue(0.04, 0.26),
        fontsize=headline_size,
    )
    return header_bottom - 0.016


KEY_ROW_HEIGHT = 0.062
STAGE_FLOOR = Layout.STAGE_BOTTOM


def _team_key_row(fig, design: dict[str, Any], bundle: MatchBundle, y: float, alpha: float) -> None:
    """Home badge and name on the left, away on the right."""
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


def _scoreboard(fig, bundle: MatchBundle, design: dict[str, Any], tl: Timeline, *,
                top: float, row_height: float = 0.104, gap: float = 0.013,
                show_qualifier: bool = True, instant: bool = False) -> float:
    """Two stacked rows: flag, team name, goals. Returns the y it ends at.

    Laying the score out as one row per team means the goal numerals get their
    own column and cannot collide with a long country name.
    """
    score = bundle.score
    rows = (
        (bundle.home, design["home"], score.home),
        (bundle.away, design["away"], score.away),
    )
    y = top
    for index, (name, identity, goals) in enumerate(rows):
        if instant:
            local = 1.0
            slide = 0.0
            alpha = 1.0
            goal_count = int(goals)
        else:
            local = tl.stagger(index, 2, start=0.10, span=0.16, duration=0.30, ease=draw.ease_out_back)
            if local <= 0.001:
                y -= row_height + gap
                continue
            slide = (1.0 - local) * 0.06
            alpha = min(1.0, local * 1.6)
            goal_count = int(round(tl.count_to(goals, start=0.18, duration=0.42)))
        row_y = y - row_height

        draw.fig_panel(fig, Layout.MARGIN - slide, row_y, Layout.CONTENT_W, row_height,
                       color=design["surface"], alpha=0.90 * alpha,
                       edge=identity["chart"], radius=0.012, zorder=8, lw=1.2)
        draw.fig_rect(fig, Layout.MARGIN - slide, row_y, 0.008, row_height,
                      identity["chart"], alpha, zorder=10)

        centre = row_y + row_height / 2
        draw.team_badge(fig, name, Layout.MARGIN + 0.088 - slide, centre, 0.108,
                        identity=identity, alpha=alpha, zorder=12)
        draw.fit_text(
            fig, Layout.MARGIN + 0.162 - slide, centre, name.upper(), fontsize=40,
            max_width=0.50, max_lines=1, min_fontsize=17, ha="left", va="center",
            color=TEXT, family=theme.DISPLAY_FONT, fontweight="bold", alpha=alpha, zorder=14,
        )
        fig.text(
            1 - Layout.MARGIN - 0.045 - slide, centre, str(goal_count), color=identity["chart"],
            fontsize=92, fontweight="bold", family=theme.DISPLAY_FONT, ha="center", va="center",
            alpha=alpha, zorder=14, path_effects=draw.soft_shadow(),
        )
        y -= row_height + gap

    if score.qualifier and show_qualifier:
        chip_alpha = 1.0 if instant else tl.cue(0.34, 0.24)
        if chip_alpha > 0.01:
            label = score.qualifier
            width = 0.028 + len(label) * 0.0125
            draw.fig_panel(fig, 0.5 - width / 2, y - 0.030, width, 0.034,
                           color="#1b1410", alpha=0.95 * chip_alpha, edge=theme.WARNING,
                           radius=0.014, zorder=12, lw=1.1)
            fig.text(0.5, y - 0.0135, label, color=theme.WARNING, fontsize=13,
                     family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
                     alpha=chip_alpha, zorder=14)
        y -= 0.046
    return y


def _goal_list(fig, bundle: MatchBundle, audit: dict[str, Any], design: dict[str, Any],
               tl: Timeline, *, top: float, bottom: float, start_cue: float = 0.40,
               instant: bool = False) -> None:
    """A compact list of goals filling the band between *top* and *bottom*."""
    timeline = audit["goal_timeline"]
    if not timeline:
        stats = audit["team_stats"]
        total_shots = sum(team.get("shots", 0) for team in stats.values())
        alpha = 1.0 if instant else tl.cue(start_cue, 0.30)
        fig.text(0.5, (top + bottom) / 2, i18n.t("no_goals"), color=TEXT_DIM, fontsize=40,
                 fontweight="bold", family=theme.DISPLAY_FONT, ha="center", va="center",
                 alpha=alpha, zorder=14)
        fig.text(0.5, (top + bottom) / 2 - 0.036, i18n.t("shots_none_counted", shots=total_shots),
                 color=TEXT_FAINT, fontsize=theme.label_size(12), family=theme.LABEL_FONT, fontweight="bold",
                 ha="center", va="center",
                 alpha=alpha, zorder=14)
        return

    band_top = top - 0.026
    available = band_top - bottom
    row_h = min(0.058, available / max(1, len(timeline)))
    # Centre the rows in the band so a two-goal match does not leave a hole.
    list_top = band_top - (available - row_h * len(timeline)) / 2
    fig.text(Layout.MARGIN, list_top + 0.020, i18n.t("goals"), color=TEXT_FAINT,
             fontsize=theme.label_size(11), family=theme.LABEL_FONT, fontweight="bold",
             ha="left", va="center",
             alpha=1.0 if instant else tl.cue(start_cue - 0.04, 0.20), zorder=14)

    for index, goal in enumerate(timeline):
        local = 1.0 if instant else tl.stagger(index, len(timeline), start=start_cue, span=0.26, duration=0.22)
        if local <= 0.01:
            continue
        alpha = min(1.0, local * 1.6)
        y = list_top - row_h * (index + 0.5)
        colour = theme.side_color(design, goal["h_a"])
        slide = (1.0 - local) * 0.04

        fig.text(Layout.MARGIN + 0.006 - slide, y, f"{goal['minute']}'", color=TEXT_DIM,
                 fontsize=15, family=theme.MONO_FONT, ha="left", va="center", alpha=alpha, zorder=14)
        draw.fig_rect(fig, Layout.MARGIN + 0.078 - slide, y - row_h * 0.28, 0.004, row_h * 0.56,
                      colour, alpha, zorder=14)
        name = goal["scorer"] or goal["team"]
        suffix = " (OG)" if goal["own_goal"] else (" (PEN)" if goal["penalty"] else "")
        draw.fit_text(
            fig, Layout.MARGIN + 0.100 - slide, y, (name + suffix).upper(), fontsize=min(23, row_h * 620),
            max_width=0.54, max_lines=1, min_fontsize=11, ha="left", va="center",
            color=TEXT, family=theme.DISPLAY_FONT, fontweight="bold", alpha=alpha, zorder=14,
        )
        fig.text(1 - Layout.MARGIN - 0.006, y, goal["score_after"], color=colour,
                 fontsize=min(26, row_h * 640), fontweight="bold", family=theme.DISPLAY_FONT,
                 ha="right", va="center", alpha=alpha, zorder=14)


def _stat_keys(scene: dict[str, Any], fallback: list[str]) -> list[str]:
    keys = scene.get("stat_keys") or fallback
    return [key for key in keys][:5]


# ---------------------------------------------------------------------------
# viral hook
# ---------------------------------------------------------------------------

def _hook_lines(scene: dict[str, Any]) -> list[str]:
    lines = scene.get("lines")
    if isinstance(lines, list) and any(str(item).strip() for item in lines):
        return [str(item).strip() for item in lines if str(item).strip()]
    parts = [
        str(scene.get("title") or "").strip(),
        str(scene.get("subtitle") or "").strip(),
        str(scene.get("insight") or "").strip(),
    ]
    return [part for part in parts if part]


def _interrupt(progress: float, duration: float) -> tuple[bool, float, float]:
    """Return (flash_bg, zoom, shake). Flash is a background slam, text stays on top."""
    t = max(0.0, progress) * max(0.05, duration)
    flash = t < 0.15
    zoom = 1.0
    if t < 0.28:
        zoom = 1.0 + 0.18 * (1.0 - t / 0.28)
    shake = 0.0
    if t < 0.22:
        decay = 1.0 - t / 0.22
        shake = 0.010 * decay * math.sin(t * 95.0)
    return flash, zoom, shake


def _hook_badges(fig, bundle: MatchBundle, design: dict[str, Any], *,
                 y: float = 0.30, shake: float = 0.0, size: float = 0.132) -> None:
    """Home and away crests, centred under the slam text. No score."""
    gap = 0.118
    draw.team_badge(
        fig, bundle.home, 0.5 - gap + shake, y, size,
        identity=design["home"], alpha=1.0, zorder=22,
    )
    draw.team_badge(
        fig, bundle.away, 0.5 + gap + shake, y, size,
        identity=design["away"], alpha=1.0, zorder=22,
    )


def render_hook_claim(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Huge contradiction, no score. Crests sit under the type on the slam."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    duration = float(scene.get("seconds") or 0.85)
    t = progress * duration
    flash, zoom, shake = _interrupt(progress, duration)
    ink = "#120e08" if flash else TEXT
    if flash:
        draw.fig_rect(fig, 0.0, 0.0, 1.0, 1.0, theme.WARNING, 1.0, zorder=5)
    lines = _hook_lines(scene)
    n = max(1, len(lines))
    base = 62.0 if n <= 2 else 48.0
    start_y = 0.66 + (n - 1) * 0.008
    step = 0.13 if n <= 2 else 0.112

    for index, line in enumerate(lines):
        appear = index * 0.16
        if t + 0.001 < appear:
            continue
        local = min(1.0, (t - appear) / 0.10) if appear else 1.0
        size = base * (zoom if index == 0 else 1.0 + 0.10 * (1.0 - local))
        y = start_y - index * step
        draw.fit_text(
            fig, 0.5 + shake, y, line.upper(),
            fontsize=size, max_width=0.90, max_lines=2, min_fontsize=26.0,
            ha="center", va="center", color=ink, family=theme.DISPLAY_FONT, fontweight="bold",
            linespacing=0.88, alpha=1.0, zorder=20, path_effects=draw.soft_shadow(),
        )

    _hook_badges(fig, bundle, design, y=0.28, shake=shake)
    draw.save_figure(fig, path)


def render_hook_punch(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """Hard-cut payoff line. Still no score."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    duration = float(scene.get("seconds") or 0.70)
    flash, zoom, shake = _interrupt(progress, duration)
    line = (_hook_lines(scene) or [str(scene.get("title") or "")])[0]
    if flash:
        draw.fig_rect(fig, 0.0, 0.0, 1.0, 1.0, "#fff4d6", 1.0, zorder=5)
    color = "#120e08" if flash else theme.WARNING
    draw.fit_text(
        fig, 0.5 + shake, 0.58, line.upper(),
        fontsize=78.0 * zoom, max_width=0.92, max_lines=3, min_fontsize=32.0,
        ha="center", va="center", color=color, family=theme.DISPLAY_FONT, fontweight="bold",
        linespacing=0.86, alpha=1.0, zorder=20, path_effects=draw.soft_shadow(),
    )
    _hook_badges(fig, bundle, design, y=0.28, shake=shake)
    draw.save_figure(fig, path)


def render_micro_hook(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    """0.7s claim slam before the next card. Same interrupt language as the open."""
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    duration = float(scene.get("seconds") or 0.70)
    flash, zoom, shake = _interrupt(progress, duration)
    line = (_hook_lines(scene) or [str(scene.get("title") or "")])[0]
    cream = str(scene.get("flash") or "orange") == "cream"
    if flash:
        draw.fig_rect(fig, 0.0, 0.0, 1.0, 1.0, "#fff4d6" if cream else theme.WARNING, 1.0, zorder=5)
    color = "#120e08" if flash else (theme.WARNING if cream else TEXT)
    size = 58.0 if len(line) > 26 else 70.0
    draw.fit_text(
        fig, 0.5 + shake, 0.58, line.upper(),
        fontsize=size * zoom, max_width=0.90, max_lines=3, min_fontsize=28.0,
        ha="center", va="center", color=color, family=theme.DISPLAY_FONT, fontweight="bold",
        linespacing=0.86, alpha=1.0, zorder=20, path_effects=draw.soft_shadow(),
    )
    _hook_badges(fig, bundle, design, y=0.28, shake=shake)
    draw.save_figure(fig, path)


def render_title(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                 path: Path, progress: float = 1.0) -> None:
    """Kept for old plans. New opens use hook_claim / hook_punch."""
    render_hook_claim(bundle, audit, scene, path, progress)


# ---------------------------------------------------------------------------
# baseline stats
# ---------------------------------------------------------------------------

def render_standard_stats(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                          path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]

    content_top = _chrome(fig, bundle, scene, tl)
    key_row_y = content_top - KEY_ROW_HEIGHT / 2
    _team_key_row(fig, design, bundle, key_row_y, tl.cue(0.08, 0.24))

    keys = [key for key in _stat_keys(scene, ["shots", "shots_on_target", "pass_share_pct"])
            if key in home and key in away]
    if not keys:
        keys = ["shots"]

    top = key_row_y - KEY_ROW_HEIGHT / 2 - 0.014
    bottom = STAGE_FLOOR + 0.036
    step = (top - bottom) / len(keys)
    for index, key in enumerate(keys):
        local = tl.stagger(index, len(keys), start=0.14, span=0.44, duration=0.34)
        if local <= 0.005:
            continue
        y = top - step * (index + 1) + step * 0.34
        draw.comparison_bar(
            fig, y, stat_label(key), float(home.get(key) or 0), float(away.get(key) or 0),
            design["home"]["chart"], design["away"]["chart"], progress=local,
            suffix="%" if key.endswith("_pct") else "",
        )

    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# goal timeline
# ---------------------------------------------------------------------------

def render_goal_timeline(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                         path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    timeline = audit["goal_timeline"]

    content_top = _chrome(fig, bundle, scene, tl)
    key_row_y = content_top - KEY_ROW_HEIGHT / 2
    _team_key_row(fig, design, bundle, key_row_y, tl.cue(0.08, 0.24))

    if not timeline:
        fig.text(0.5, 0.5, i18n.t("no_goals_in_match"), color=TEXT_DIM, fontsize=30,
                 family=theme.DISPLAY_FONT, fontweight="bold", ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    top = key_row_y - KEY_ROW_HEIGHT / 2 - 0.014
    bottom = STAGE_FLOOR + 0.028
    count = len(timeline)
    row_h = min(0.112, (top - bottom) / count)
    block_height = row_h * count
    block_top = top - ((top - bottom) - block_height) / 2

    spine_x = 0.500
    spine_alpha = tl.cue(0.10, 0.28)
    grown = block_height * draw.ease_out_cubic(draw.clamp01((tl.t - 0.10) / 0.55))
    draw.fig_rect(fig, spine_x - 0.0013, block_top - grown, 0.0026, grown,
                  design["hairline"], 0.95 * spine_alpha, zorder=6)

    for index, goal in enumerate(timeline):
        local = tl.stagger(index, count, start=0.16, span=0.50, duration=0.28)
        if local <= 0.01:
            continue
        alpha = min(1.0, local * 1.5)
        y = block_top - row_h * (index + 0.5)
        is_home = goal["h_a"] == "h"
        colour = theme.side_color(design, goal["h_a"])
        slide = (1.0 - local) * (0.055 if is_home else -0.055)

        card_w = 0.335
        card_x = spine_x - 0.052 - card_w if is_home else spine_x + 0.052
        card_h = row_h * 0.76
        draw.fig_panel(fig, card_x + slide, y - card_h / 2, card_w, card_h,
                       color=design["surface"], alpha=0.92 * alpha, edge=colour,
                       radius=0.010, zorder=8, lw=1.1)

        text_x = card_x + card_w - 0.018 if is_home else card_x + 0.018
        ha = "right" if is_home else "left"
        name = goal["scorer"] or goal["team"]
        suffix = " (OG)" if goal["own_goal"] else (" (PEN)" if goal["penalty"] else "")
        draw.fit_text(
            fig, text_x + slide, y + card_h * 0.16, (name + suffix).upper(),
            fontsize=25, max_width=card_w - 0.036, max_lines=1, min_fontsize=12,
            ha=ha, va="center", color=TEXT, family=theme.DISPLAY_FONT, fontweight="bold",
            alpha=alpha, zorder=14,
        )
        fig.text(text_x + slide, y - card_h * 0.22, f"{goal['team'].upper()}   {goal['minute']}'",
                 color=colour, fontsize=11.5, family=theme.MONO_FONT, ha=ha, va="center",
                 alpha=alpha * 0.95, zorder=14)

        draw.score_badge(
            fig, spine_x, y, goal["score_after"],
            edge=colour, alpha=alpha, max_height=min(0.068, card_h * 0.92),
        )

    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# shot map
# ---------------------------------------------------------------------------

def render_shot_map(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                    path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]

    content_top = _chrome(fig, bundle, scene, tl)

    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.032, bottom=0.168)
    draw.fig_panel(fig, rect[0] - 0.012, rect[1] - draw.y_of(0.012),
                   rect[2] + 0.024, rect[3] + 2 * draw.y_of(0.012),
                   color="#080b09", alpha=0.80 * tl.cue(0.04, 0.24),
                   edge=design["hairline"], radius=0.012, zorder=2)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))
    draw.pitch_grid_fade(ax, alpha=0.045 * tl.cue(0.06, 0.26))

    left = rect[0]
    right = rect[0] + rect[2]
    ax.set_zorder(3)
    alpha = tl.cue(0.08, 0.26)

    # Home attacks the top of the frame, away attacks the bottom, so the two
    # sets of shots are aimed at different goals as they were in the match.
    for side, y, arrow in (
        ("h", rect[1] + rect[3] + 0.020, i18n.t("attacking_up")),
        ("a", rect[1] - 0.032, i18n.t("attacking_down")),
    ):
        name = bundle.team(side)
        team_stats = stats[name]
        colour = theme.side_color(design, side)
        draw.fit_text(
            fig, left, y, name.upper(), fontsize=24, max_width=0.40, max_lines=1,
            min_fontsize=12, ha="left", va="center", color=colour,
            family=theme.DISPLAY_FONT, fontweight="bold", alpha=alpha, zorder=20,
        )
        fig.text(right, y + 0.008,
                 i18n.t("shots_on_target_line", shots=team_stats["shots"], on_target=team_stats["shots_on_target"]),
                 color=TEXT_DIM, fontsize=theme.label_size(11), family=theme.LABEL_FONT, fontweight="bold",
                 ha="right", va="center",
                 alpha=alpha, zorder=20)
        fig.text(right, y - 0.010, arrow, color=TEXT_FAINT, fontsize=theme.label_size(8.5),
                 family=theme.LABEL_FONT, fontweight="bold",
                 ha="right", va="center", alpha=alpha * 0.85, zorder=20)

    shots = sorted(audit["shots"], key=lambda s: (s["minute"] or 0))
    visible = tl.reveal_count(len(shots), start=0.14, span=0.52)

    # Markers are collected by shape and drawn as three collections rather than
    # one scatter call per shot, which is far cheaper per frame.
    batches: dict[str, dict[str, list]] = {
        key: {"x": [], "y": [], "s": [], "c": [], "a": []}
        for key in ("dot", "ring", "cross", "big_chance")
    }
    # Two goals from nearly the same spot would otherwise print their scorers
    # on top of each other; the second label is dropped instead.
    scorer_labels: list[tuple[float, float]] = []
    for index, shot in enumerate(shots):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(shots)), start=0.14, span=0.52, duration=0.14,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        flip = shot["h_a"] == "a"
        px, py = draw.to_pitch(shot["x"], shot["y"], flip=flip)
        style = OUTCOME_STYLE.get(shot["outcome"], OUTCOME_STYLE["off_target"])
        colour = design["goal"] if shot["outcome"] == "goal" else theme.side_color(design, shot["h_a"])
        # `local` overshoots past 1 so markers pop and settle; sizes use it raw
        # while opacities are clamped.
        size = style["size"] * (0.6 + 0.4 * local) * local
        fade = draw.opacity(local)

        batch = batches[style["marker"]]
        batch["x"].append(px)
        batch["y"].append(py)
        batch["s"].append(size)
        batch["c"].append(colour)
        batch["a"].append(fade * (1.0 if style["marker"] == "dot" else 0.9))

        if shot["big_chance"] and shot["outcome"] != "goal" and local > 0.4:
            big = batches["big_chance"]
            big["x"].append(px)
            big["y"].append(py)
            big["s"].append(size * 2.4)
            big["c"].append(theme.WARNING)
            big["a"].append(draw.opacity((local - 0.4) * 1.2))

        if shot["outcome"] == "goal":
            draw.impact_burst(ax, px, py, design["goal"], fade, base_radius=2.0, zorder=15)
            surname = (shot["player"] or "").split()[-1][:12]
            offset = 4.8 if not flip else -4.8
            label_at = (px, py + offset)
            crowded = any(
                abs(px - other_x) < 16 and abs(label_at[1] - other_y) < 4.0
                for other_x, other_y in scorer_labels
            )
            if surname and local > 0.5 and not crowded:
                scorer_labels.append(label_at)
                ax.text(label_at[0], label_at[1], surname.upper(), color=TEXT,
                        fontsize=8.5, family=theme.MONO_FONT, ha="center",
                        va="bottom" if not flip else "top", path_effects=draw.outline(),
                        alpha=draw.opacity((local - 0.5) * 2), zorder=16)

    draw.scatter_batch(ax, batches["big_chance"]["x"], batches["big_chance"]["y"],
                       sizes=batches["big_chance"]["s"], colors=batches["big_chance"]["c"],
                       alphas=batches["big_chance"]["a"], filled=False, linewidth=1.2, zorder=10)
    draw.scatter_batch(ax, batches["ring"]["x"], batches["ring"]["y"],
                       sizes=batches["ring"]["s"], colors=batches["ring"]["c"],
                       alphas=batches["ring"]["a"], filled=False, linewidth=1.9, zorder=11)
    draw.scatter_batch(ax, batches["cross"]["x"], batches["cross"]["y"],
                       sizes=batches["cross"]["s"], colors=batches["cross"]["c"],
                       alphas=batches["cross"]["a"], marker="x", filled=False,
                       linewidth=1.9, zorder=11)
    draw.scatter_batch(ax, batches["dot"]["x"], batches["dot"]["y"],
                       sizes=batches["dot"]["s"], colors=batches["dot"]["c"],
                       alphas=batches["dot"]["a"], linewidth=1.0, zorder=12)

    present = {shot["outcome"] for shot in shots}
    entries = [
        (OUTCOME_STYLE[key]["marker"], design["goal"] if key == "goal" else TEXT_DIM,
         i18n.t(OUTCOME_STYLE[key]["label_key"]))
        for key in ("goal", "saved", "off_target", "blocked", "woodwork")
        if key in present
    ]
    legend_alpha = tl.cue(0.52, 0.26)
    draw.legend_row(fig, 0.118, entries, alpha=legend_alpha, fontsize=theme.label_size(10))
    fig.text(0.5, 0.096, i18n.t("markers_team_colour"), color=TEXT_FAINT,
             fontsize=theme.label_size(8.5), family=theme.LABEL_FONT, fontweight="bold",
             ha="center", va="center", alpha=legend_alpha * 0.9, zorder=20)
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# momentum
# ---------------------------------------------------------------------------

def render_momentum(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                    path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    rows = audit["momentum"]

    content_top = _chrome(fig, bundle, scene, tl)
    key_row_y = content_top - KEY_ROW_HEIGHT / 2
    _team_key_row(fig, design, bundle, key_row_y, tl.cue(0.08, 0.24))

    if len(rows) < 2:
        fig.text(0.5, 0.5, i18n.t("pressure_curve_empty"), color=TEXT_DIM,
                 fontsize=22, family=theme.DISPLAY_FONT, ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    chart_top = key_row_y - KEY_ROW_HEIGHT / 2 - 0.036
    chart_bottom = 0.240
    rect = [Layout.MARGIN, chart_bottom, Layout.CONTENT_W, chart_top - chart_bottom]
    ax = fig.add_axes(rect, zorder=4)
    ax.set_facecolor("#0b0f0d")
    for spine in ax.spines.values():
        spine.set_visible(False)

    axis = audit["clock_axis"]
    span = max(1.0, float(axis["end"]))
    starts = np.array([row["start"] for row in rows], dtype=float)
    swing = np.array([row["swing"] for row in rows], dtype=float)
    limit = max(6.0, float(np.abs(swing).max()) * 1.30)

    ax.set_xlim(0, span)
    ax.set_ylim(-limit, limit)
    ax.set_yticks([])
    ax.set_xticks([tick["at"] for tick in axis["ticks"]])
    ax.set_xticklabels([tick["label"] for tick in axis["ticks"]], color=TEXT_FAINT,
                       fontsize=10, family=theme.MONO_FONT)
    ax.tick_params(axis="x", length=0, pad=6)

    reveal = draw.ease_in_out(draw.clamp01((tl.t - 0.12) / 0.55))
    cutoff = span * reveal
    keep = starts <= max(starts[0], cutoff)
    x = np.append(starts[keep], cutoff) if keep.any() else np.array([0.0])
    y = np.append(swing[keep], swing[keep][-1] if keep.any() else 0.0)

    ax.axhline(0, color=design["pitch_line"], lw=1.4, alpha=0.9, zorder=6)
    for boundary in axis["boundaries"]:
        ax.axvline(boundary["at"], color=design["hairline"], lw=1.0, alpha=0.9,
                   ls=(0, (3, 4)), zorder=3)
        ax.text(boundary["at"], limit * 0.96, i18n.period_label(boundary["label"]), color=TEXT_FAINT,
                fontsize=9.5, family=theme.MONO_FONT, ha="center", va="top",
                alpha=tl.cue(0.20, 0.30), zorder=7)

    if len(x) > 1:
        ax.fill_between(x, 0, np.maximum(y, 0), step="post", color=design["home"]["chart"],
                        alpha=0.75, zorder=4, linewidth=0)
        ax.fill_between(x, 0, np.minimum(y, 0), step="post", color=design["away"]["chart"],
                        alpha=0.75, zorder=4, linewidth=0)
        ax.step(x, y, where="post", color=TEXT, lw=1.9, alpha=0.85, zorder=8)

    peak_alpha = tl.cue(0.54, 0.28)
    peak = max(rows, key=lambda row: abs(row["swing"]))
    if peak_alpha > 0.01:
        up = peak["swing"] >= 0
        colour = design["home"]["chart"] if up else design["away"]["chart"]
        # A bracket under the peak bucket, rather than a shaded column that
        # reads as a hole punched through the chart.
        edge = limit * 0.985 if up else -limit * 0.985
        ax.plot([peak["start"], peak["end"]], [edge, edge], color=colour, lw=2.6,
                alpha=peak_alpha, zorder=11, solid_capstyle="butt")
        ax.text(
            (peak["start"] + peak["end"]) / 2, edge * 0.90,
            i18n.t("peak", block=f"{peak['minute_block']}'"), color=colour, fontsize=11,
            family=theme.MONO_FONT, fontweight="bold", ha="center",
            va="top" if up else "bottom",
            path_effects=draw.outline(), alpha=peak_alpha, zorder=12,
        )

    # Goal markers. A home goal is labelled above the line and an away goal
    # below it, matching the side of the chart that team occupies.
    goal_alpha = tl.cue(0.34, 0.28)
    if goal_alpha > 0.01:
        for goal in audit["goal_timeline"]:
            at = float(goal["clock"])
            if at > cutoff + 1:
                continue
            colour = theme.side_color(design, goal["h_a"])
            ax.axvline(at, color=colour, lw=1.5, alpha=0.5 * goal_alpha, zorder=7)
            ax.scatter([at], [0], s=90, color=colour, edgecolor=TEXT, linewidth=1.2,
                       zorder=10, alpha=goal_alpha)
            offset = limit * (0.62 if goal["h_a"] == "h" else -0.62)
            ax.text(at, offset, f"{goal['minute']}'", color=colour, fontsize=11,
                    family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
                    path_effects=draw.outline(), alpha=goal_alpha, zorder=11)

    fig.text(Layout.MARGIN, chart_top + 0.014, i18n.t("attacking_pressure"),
             color=TEXT_FAINT, fontsize=theme.label_size(10), family=theme.LABEL_FONT, fontweight="bold",
             ha="left", va="center",
             alpha=tl.cue(0.14, 0.26), zorder=20)

    _pressure_summary(fig, audit, design, tl, top=chart_bottom - 0.030)
    draw.save_figure(fig, path)


def _pressure_summary(fig, audit: dict[str, Any], design: dict[str, Any],
                      tl: Timeline, *, top: float) -> None:
    """Pressure share per period, taken from the period column rather than guessed."""
    phases = audit.get("phase_pressure") or []
    alpha = tl.cue(0.46, 0.30)
    if not phases or alpha <= 0.01:
        return

    height = 0.070
    slot = Layout.CONTENT_W / len(phases)
    for index, phase in enumerate(phases):
        share = phase["home_share_pct"] / 100.0
        x = Layout.MARGIN + slot * index + slot * 0.035
        width = slot * 0.93
        y = top - height

        draw.fig_panel(fig, x, y, width, height, color=design["surface"],
                       alpha=0.9 * alpha, edge=design["hairline"], radius=0.009, zorder=10)
        fig.text(x + width / 2, y + height * 0.72, i18n.period_label(phase["label"]).upper(), color=TEXT_FAINT,
                 fontsize=theme.label_size(9.5), family=theme.LABEL_FONT, fontweight="bold",
                 ha="center", va="center", alpha=alpha, zorder=14)
        bar_y = y + height * 0.38
        bar_w = width * 0.84
        bar_x = x + width * 0.08
        draw.fig_rect(fig, bar_x, bar_y, bar_w, 0.010, "#171d19", alpha, zorder=12)
        draw.fig_rect(fig, bar_x, bar_y, bar_w * share, 0.010, design["home"]["chart"], alpha, zorder=13)
        draw.fig_rect(fig, bar_x + bar_w * share, bar_y, bar_w * (1 - share), 0.010,
                      design["away"]["chart"], alpha, zorder=13)
        fig.text(bar_x, y + height * 0.15, f"{phase['home_share_pct']:.0f}%",
                 color=design["home"]["chart"], fontsize=13, fontweight="bold",
                 family=theme.DISPLAY_FONT, ha="left", va="center", alpha=alpha, zorder=14)
        fig.text(bar_x + bar_w, y + height * 0.15, f"{100 - phase['home_share_pct']:.0f}%",
                 color=design["away"]["chart"], fontsize=13, fontweight="bold",
                 family=theme.DISPLAY_FONT, ha="right", va="center", alpha=alpha, zorder=14)


# ---------------------------------------------------------------------------
# zone control
# ---------------------------------------------------------------------------

def render_zone_control(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    zones = audit["zone_control"]

    content_top = _chrome(fig, bundle, scene, tl)

    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.026, bottom=0.140)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=0.0)
    if not zones:
        fig.text(0.5, 0.5, i18n.t("no_touch_coords"), color=TEXT_DIM,
                 fontsize=20, family=theme.DISPLAY_FONT, ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    x_bins = max(z["xbin"] for z in zones) + 1
    y_bins = max(z["ybin"] for z in zones) + 1
    cell_w = 100 / y_bins   # across the pitch on screen
    cell_h = 100 / x_bins   # up the pitch on screen
    home_colour = design["home"]["chart"]
    away_colour = design["away"]["chart"]
    busiest = max((z["total_touches"] for z in zones), default=1) or 1

    for zone in zones:
        # xbin runs up the pitch and ybin across it; the vertical frame swaps them.
        row, col = zone["xbin"], zone["ybin"]
        local = tl.stagger(row, x_bins, start=0.10, span=0.48, duration=0.30)
        if local <= 0.01:
            continue

        share = zone["home_share_pct"] / 100.0
        home_leads = share >= 0.5
        # Hue says who owned the zone; a blend toward grey says by how little.
        # Mixing the two team colours instead produced a muddy purple everywhere.
        margin = abs(share - 0.5) * 2
        base = home_colour if home_leads else away_colour
        colour = theme.mix("#5b6660", base, 0.30 + 0.70 * margin)
        volume = zone["total_touches"] / busiest
        weight = 0.20 + 0.58 * volume

        draw.add_shape(
            ax,
            Rectangle((col * cell_w, row * cell_h), cell_w, cell_h, facecolor=colour,
                      edgecolor="none", alpha=draw.opacity(weight * local), zorder=4),
        )
        if zone["total_touches"] > 0 and local > 0.55:
            label_alpha = min(1.0, (local - 0.55) * 3)
            cx = col * cell_w + cell_w / 2
            cy = row * cell_h + cell_h / 2
            ax.text(cx, cy + cell_h * 0.08, str(zone["total_touches"]), color=TEXT,
                    fontsize=18, fontweight="bold", family=theme.DISPLAY_FONT, ha="center",
                    va="center", path_effects=draw.outline(), alpha=label_alpha, zorder=14)
            leader_share = share if home_leads else 1 - share
            ax.text(cx, cy - cell_h * 0.20, f"{leader_share * 100:.0f}%",
                    color=base, fontsize=11, fontweight="bold", family=theme.MONO_FONT,
                    ha="center", va="center", path_effects=draw.outline(),
                    alpha=label_alpha, zorder=14)

    # One uniform grid on top, so cell edges do not vary with each cell's alpha.
    grid_alpha = 0.55 * tl.cue(0.10, 0.26)
    for index in range(1, y_bins):
        ax.plot([index * cell_w] * 2, [0, 100], color="#0a0d0b", lw=1.6,
                alpha=grid_alpha, zorder=12)
    for index in range(1, x_bins):
        ax.plot([0, 100], [index * cell_h] * 2, color="#0a0d0b", lw=1.6,
                alpha=grid_alpha, zorder=12)

    draw.draw_pitch_markings(ax, line=design["pitch_line"], alpha=0.9 * tl.cue(0.06, 0.24),
                             lw=1.5, zorder=15)

    alpha = tl.cue(0.10, 0.26)
    _direction_note(fig, rect, bundle.home, home_colour, alpha, above=True)
    _direction_note(fig, rect, bundle.away, away_colour, alpha, above=False)
    draw.legend_row(
        fig, 0.196,
        [("bar", home_colour, f"{bundle.home[:12]} zones"),
         ("bar", away_colour, f"{bundle.away[:12]} zones")],
        alpha=tl.cue(0.52, 0.26), fontsize=theme.label_size(10),
    )
    draw.save_figure(fig, path)


def _direction_note(fig, rect: list[float], team: str, colour: str, alpha: float,
                    *, above: bool) -> None:
    """`TEAM ATTACK ^` above the pitch, or `v` below it."""
    if alpha <= 0.01:
        return
    y = rect[1] + rect[3] + 0.018 if above else rect[1] - 0.026
    x = rect[0] if above else rect[0] + rect[2]
    ha = "left" if above else "right"
    label = f"{team.upper()} ATTACK"
    artist, _ = draw.fit_text(
        fig, x, y, label, fontsize=11, max_width=0.40, max_lines=1, min_fontsize=8,
        ha=ha, va="center", color=colour, family=theme.MONO_FONT, alpha=alpha, zorder=20,
    )
    width, _ = draw._extent_fractions(fig, artist) if artist else (0.0, 0.0)
    tip_x = (x + width + 0.016) if above else (x - width - 0.016)
    arm = 0.007
    fig.patches.append(
        Polygon(
            [(tip_x - arm, y - draw.y_of(arm)), (tip_x + arm, y - draw.y_of(arm)), (tip_x, y + draw.y_of(arm))]
            if above else
            [(tip_x - arm, y + draw.y_of(arm)), (tip_x + arm, y + draw.y_of(arm)), (tip_x, y - draw.y_of(arm))],
            closed=True, transform=fig.transFigure, facecolor=colour, edgecolor="none",
            alpha=alpha, zorder=20,
        )
    )


# ---------------------------------------------------------------------------
# goal build-up
# ---------------------------------------------------------------------------

def render_goal_chain(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                      path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    chain = best_goal_chain(audit)

    content_top = _chrome(fig, bundle, scene, tl)

    if not chain:
        fig.text(0.5, 0.5, "NO BUILD-UP RECORDED", color=TEXT_DIM, fontsize=26,
                 family=theme.DISPLAY_FONT, ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top, bottom=0.148)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))

    side = "home" if chain["h_a"] == "h" else "away"
    colour = design[side]["chart"]
    # A team's own secondary colour is often white or a near-match for its
    # primary, so the assist gets a highlight picked for contrast instead.
    accent = theme.highlight_against(colour)
    events = chain["events"]
    passes = [
        event for event in events
        if event["type"] == "Pass" and event["x"] is not None and event["endX"] is not None
    ]

    visible = tl.reveal_count(len(passes), start=0.12, span=0.50)
    dot_x: list[float] = []
    dot_y: list[float] = []
    dot_a: list[float] = []
    for index, event in enumerate(passes):
        if index >= visible:
            break
        local = tl.stagger(index, max(1, len(passes)), start=0.12, span=0.50, duration=0.16)
        if local <= 0.02:
            continue
        start = draw.to_pitch(event["x"], event["y"])
        finish = draw.to_pitch(event["endX"], event["endY"])
        drawn = (
            start[0] + (finish[0] - start[0]) * local,
            start[1] + (finish[1] - start[1]) * local,
        )
        is_assist = str(event.get("eventId")) == str(chain.get("assist_event_id"))
        draw.add_shape(
            ax,
            FancyArrowPatch(
                start, drawn, arrowstyle="-|>",
                mutation_scale=20 if is_assist else 12,
                lw=3.8 if is_assist else 2.2,
                color=accent if is_assist else colour,
                alpha=draw.opacity(1.0 if is_assist else 0.35 + 0.55 * (index + 1) / max(1, len(passes))),
                zorder=10 if is_assist else 8,
                shrinkA=0, shrinkB=0,
            ),
        )
        dot_x.append(start[0])
        dot_y.append(start[1])
        dot_a.append(draw.opacity(local))
        if index == 0 or is_assist:
            name = (event.get("player") or "").split()[-1][:11]
            if name:
                ax.text(start[0], start[1] - 3.2, name.upper(), color=TEXT, fontsize=8.5,
                        family=theme.MONO_FONT, ha="center", va="top",
                        path_effects=draw.outline(), alpha=draw.opacity(local), zorder=13)

    draw.scatter_batch(ax, dot_x, dot_y, sizes=[26] * len(dot_x), colors=[TEXT] * len(dot_x),
                       alphas=dot_a, linewidth=0.8, zorder=11)

    finish_events = [event for event in events if event["type"] in {"Goal", "SavedShot", "MissedShots"}]
    target = finish_events[-1] if finish_events else (events[-1] if events else None)
    if target and target["x"] is not None:
        burst = tl.cue(0.58, 0.30)
        point = draw.to_pitch(target["x"], target["y"])
        draw.impact_burst(ax, point[0], point[1], design["goal"], burst,
                          base_radius=3.0, zorder=16, size=260)
        if burst > 0.3:
            ax.text(point[0], point[1] + 6.0, chain["scorer"].upper()[:18], color=design["goal"],
                    fontsize=12, fontweight="bold", family=theme.DISPLAY_FONT, ha="center", va="bottom",
                    path_effects=draw.outline(), alpha=(burst - 0.3) / 0.7, zorder=18)

    chips = [
        (f"{int(round(tl.count_to(chain['passes'], start=0.16, duration=0.42)))}", i18n.t("passes")),
        (f"{tl.count_to(chain['pass_distance_m'], start=0.20, duration=0.44):.0f}", i18n.t("metres")),
        (f"{tl.count_to(chain['duration_seconds'], start=0.24, duration=0.44):.0f}s", i18n.t("build_up")),
        (f"{chain['minute']}'", i18n.t("goal")),
    ]
    _chip_row(fig, chips, y=0.100, alpha=tl.cue(0.30, 0.28), design=design, accent=colour)
    draw.save_figure(fig, path)


def _chip_row(fig, chips: list[tuple[str, str]], *, y: float, alpha: float,
              design: dict[str, Any], accent: str) -> None:
    if alpha <= 0.01 or not chips:
        return
    slot = Layout.CONTENT_W / len(chips)
    for index, (value, label) in enumerate(chips):
        x = Layout.MARGIN + slot * index + slot * 0.05
        width = slot * 0.90
        draw.fig_panel(fig, x, y - 0.026, width, 0.062, color=design["surface"],
                       alpha=0.9 * alpha, edge=design["hairline"], radius=0.010, zorder=10)
        fig.text(x + width / 2, y + 0.014, value, color=accent, fontsize=30, fontweight="bold",
                 family=theme.DISPLAY_FONT, ha="center", va="center", alpha=alpha, zorder=14)
        fig.text(x + width / 2, y - 0.014, str(label).upper(), color=TEXT_FAINT,
                 fontsize=theme.label_size(9), family=theme.LABEL_FONT, fontweight="bold",
                 ha="center", va="center", alpha=alpha, zorder=14)


# ---------------------------------------------------------------------------
# goalmouth placement
# ---------------------------------------------------------------------------

def render_goalmouth(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                     path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)

    content_top = _chrome(fig, bundle, scene, tl)

    on_target = [
        shot for shot in audit["shots"]
        if shot["outcome"] in {"goal", "saved"} and shot["goal_mouth_y"] is not None
        and shot["goal_mouth_z"] is not None
    ]
    if len(on_target) < 2:
        fig.text(0.5, 0.5, i18n.t("too_few_shots_frame"), color=TEXT_DIM, fontsize=22,
                 family=theme.DISPLAY_FONT, ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    # A real goal is 7.32m x 2.44m. Showing it square, as the old renderer did,
    # squashed every shot into a corner of a meaningless box.
    view_y_min, view_y_max = GOAL_Y_MIN - 1.4, GOAL_Y_MAX + 1.4
    view_z_max = GOAL_Z_MAX * 1.18
    metres_wide = (view_y_max - view_y_min) / (GOAL_Y_MAX - GOAL_Y_MIN) * 7.32
    metres_tall = view_z_max / GOAL_Z_MAX * 2.44

    key_row_y = content_top - KEY_ROW_HEIGHT / 2
    frame_top = key_row_y - KEY_ROW_HEIGHT / 2 - 0.032
    rect = Layout.fitted_rect(metres_wide / metres_tall, top=frame_top, bottom=0.470, align="top")
    ax = fig.add_axes(rect, zorder=4)
    ax.set_xlim(view_y_min, view_y_max)
    ax.set_ylim(0, view_z_max)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor("#0a0d0c")
    for spine in ax.spines.values():
        spine.set_visible(False)

    frame_alpha = tl.cue(0.06, 0.26)
    ax.plot([view_y_min, view_y_max], [0, 0], color=design["pitch_line"], lw=2.0,
            alpha=frame_alpha, zorder=6)

    # Counts per zone rather than a dot per shot: WhoScored quantises a lot of
    # saved-shot heights to the same value, which would draw a fake straight row.
    third = (GOAL_Y_MAX - GOAL_Y_MIN) / 3
    half = GOAL_Z_MAX / 2
    for col in range(3):
        for row in range(2):
            y0 = GOAL_Y_MIN + third * col
            z0 = half * row
            inside = [
                shot for shot in on_target
                if y0 <= shot["goal_mouth_y"] < y0 + third and z0 <= shot["goal_mouth_z"] < z0 + half
            ]
            local = tl.stagger(col + row * 3, 6, start=0.12, span=0.40, duration=0.26)
            if local <= 0.02:
                continue
            if not inside:
                # An untested corner of the goal still needs to read as part of the frame.
                draw.add_shape(
                    ax,
                    Rectangle((y0, z0), third, half, facecolor="#121814", edgecolor="none",
                              alpha=draw.opacity(0.55 * local), zorder=7),
                )
                continue
            goals_here = sum(1 for shot in inside if shot["outcome"] == "goal")
            weight = min(0.62, 0.16 + 0.13 * len(inside))
            colour = design["goal"] if goals_here else "#6f7d75"
            draw.add_shape(
                ax,
                Rectangle((y0, z0), third, half, facecolor=colour, edgecolor="none",
                          alpha=draw.opacity(weight * local), zorder=7),
            )
            ax.text(y0 + third / 2, z0 + half * 0.60, str(len(inside)), color=TEXT,
                    fontsize=26, fontweight="bold", family=theme.DISPLAY_FONT, ha="center",
                    va="center", path_effects=draw.outline(), alpha=local, zorder=12)
            ax.text(y0 + third / 2, z0 + half * 0.26,
                    i18n.t("scored_n", n=goals_here) if goals_here else i18n.t("all_stopped"),
                    color=design["goal"] if goals_here else TEXT_DIM, fontsize=9.5,
                    family=theme.MONO_FONT, fontweight="bold", ha="center", va="center",
                    path_effects=draw.outline(), alpha=local, zorder=12)

    # Net over the fills, then posts and bar on top of everything.
    for step in range(1, 6):
        z = GOAL_Z_MAX * step / 6
        ax.plot([GOAL_Y_MIN, GOAL_Y_MAX], [z, z], color="#8d9a92", lw=0.6,
                alpha=0.30 * frame_alpha, zorder=9)
    for step in range(1, 9):
        y = GOAL_Y_MIN + (GOAL_Y_MAX - GOAL_Y_MIN) * step / 9
        ax.plot([y, y], [0, GOAL_Z_MAX], color="#8d9a92", lw=0.6,
                alpha=0.30 * frame_alpha, zorder=9)
    ax.plot([GOAL_Y_MIN, GOAL_Y_MIN, GOAL_Y_MAX, GOAL_Y_MAX], [0, GOAL_Z_MAX, GOAL_Z_MAX, 0],
            color=TEXT, lw=4.5, alpha=frame_alpha, zorder=13, solid_capstyle="round")

    for shot in on_target:
        if shot["outcome"] != "goal":
            continue
        local = tl.cue(0.44, 0.30, ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        ax.scatter([shot["goal_mouth_y"]], [shot["goal_mouth_z"]], s=190 * local,
                   color=design["goal"], edgecolor=TEXT, linewidth=1.6, zorder=15,
                   alpha=draw.opacity(local))

    fig.text(rect[0], rect[1] + rect[3] + 0.019, i18n.t("shots_reached_target"),
             color=TEXT_FAINT, fontsize=theme.label_size(10), family=theme.LABEL_FONT, fontweight="bold",
             ha="left", va="center",
             alpha=tl.cue(0.10, 0.24), zorder=20)
    fig.text(rect[0] + rect[2], rect[1] + rect[3] + 0.019, i18n.t("count_per_zones"),
             color=TEXT_FAINT, fontsize=theme.label_size(10), family=theme.LABEL_FONT,
             fontweight="bold", ha="right", va="center",
             alpha=tl.cue(0.10, 0.24), zorder=20)

    stats = audit["team_stats"]
    keys = ["shots_on_target", "saves", "goals"]
    # A goal is wide and short, so the frame never fills the stage; the bars
    # start immediately beneath it instead of at a fixed height.
    top = rect[1] - 0.048
    step = (top - (STAGE_FLOOR + 0.036)) / len(keys)
    for index, key in enumerate(keys):
        local = tl.stagger(index, len(keys), start=0.34, span=0.34, duration=0.30)
        if local <= 0.01:
            continue
        y = top - step * (index + 1) + step * 0.32
        draw.comparison_bar(
            fig, y, stat_label(key),
            float(stats[bundle.home].get(key) or 0), float(stats[bundle.away].get(key) or 0),
            design["home"]["chart"], design["away"]["chart"], progress=local,
        )
    _team_key_row(fig, design, bundle, key_row_y, tl.cue(0.08, 0.24))
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# pass network
# ---------------------------------------------------------------------------

def render_pass_network(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                        path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)

    focus = dominant_team(bundle, audit, "pass_attempts") or bundle.home
    h_a = audit["team_stats"][focus]["h_a"]
    identity = design["home" if h_a == "h" else "away"]

    content_top = _chrome(fig, bundle, scene, tl)

    rect = Layout.fitted_rect(draw.PITCH_ASPECT, top=content_top - 0.026, bottom=0.148)
    ax = draw.vertical_pitch(fig, rect, face=design["pitch"], line=design["pitch_line"],
                             alpha=tl.cue(0.06, 0.26))
    network = build_pass_network(bundle, h_a)
    nodes = network["nodes"]

    if not nodes:
        fig.text(0.5, 0.5, i18n.t("not_enough_passes"), color=TEXT_DIM, fontsize=22,
                 family=theme.DISPLAY_FONT, ha="center", va="center", zorder=14)
        draw.save_figure(fig, path)
        return

    colour = identity["chart"]
    busiest = max(node["count"] for node in nodes.values())

    visible_edges = tl.reveal_count(len(network["edges"]), start=0.12, span=0.40)
    for index, edge in enumerate(network["edges"]):
        if index >= visible_edges:
            break
        local = tl.stagger(index, max(1, len(network["edges"])), start=0.12, span=0.40, duration=0.20)
        source, target = nodes.get(edge["source"]), nodes.get(edge["target"])
        if not source or not target:
            continue
        start = draw.to_pitch(source["x"], source["y"])
        finish = draw.to_pitch(target["x"], target["y"])
        width = 0.9 + edge["count"] / max(1, network["max_edge"]) * 4.6
        ax.plot([start[0], start[0] + (finish[0] - start[0]) * local],
                [start[1], start[1] + (finish[1] - start[1]) * local],
                color=colour, lw=width, alpha=0.42 * local, zorder=6, solid_capstyle="round")

    ordered = sorted(nodes.items(), key=lambda item: item[1]["count"], reverse=True)
    # Names sit under the circles rather than inside them, and a name is dropped
    # when it would land on one already placed. Busier players win the space.
    placed: list[tuple[float, float]] = []
    node_x, node_y, node_s, node_a = [], [], [], []
    for index, (player, node) in enumerate(ordered):
        local = tl.stagger(index, len(ordered), start=0.24, span=0.42, duration=0.24,
                           ease=draw.ease_out_back)
        if local <= 0.02:
            continue
        point = draw.to_pitch(node["x"], node["y"])
        size = 200 + node["count"] / busiest * 620
        node_x.append(point[0])
        node_y.append(point[1])
        node_s.append(size * local)
        node_a.append(draw.opacity(local))

        if local <= 0.6:
            continue
        radius = math.sqrt(size / math.pi) * 0.11
        label_y = point[1] - radius - 2.2
        if any(abs(point[0] - px) < 13 and abs(label_y - py) < 3.4 for px, py in placed):
            continue
        placed.append((point[0], label_y))
        ax.text(point[0], label_y, (player.split()[-1])[:10].upper(), color=TEXT,
                fontsize=9.0, fontweight="bold", family=theme.MONO_FONT, ha="center", va="top",
                path_effects=draw.outline(), alpha=draw.opacity((local - 0.6) * 2.5), zorder=12)

    draw.scatter_batch(ax, node_x, node_y, sizes=node_s, colors=[colour] * len(node_x),
                       alphas=node_a, linewidth=1.4, zorder=10)

    stats = audit["team_stats"][focus]
    chips = [
        (f"{int(round(tl.count_to(stats['passes_completed'], start=0.20, duration=0.44)))}", i18n.t("completed")),
        (f"{stats['pass_accuracy_pct']:.0f}%", i18n.t("accuracy")),
        (f"{stats['final_third_passes']}", i18n.t("final_third")),
        (f"{stats['box_entry_passes']}", i18n.t("into_the_box")),
    ]
    _chip_row(fig, chips, y=0.100, alpha=tl.cue(0.34, 0.28), design=design, accent=colour)
    fig.text(rect[0], rect[1] + rect[3] + 0.017, i18n.t("attacking_up_with_team", team=focus.upper()),
             color=colour, fontsize=12, family=theme.MONO_FONT, ha="left", va="center",
             alpha=tl.cue(0.10, 0.26), zorder=20)
    fig.text(rect[0] + rect[2], rect[1] + rect[3] + 0.017, "CIRCLE SIZE = INVOLVEMENT",
             color=TEXT_FAINT, fontsize=9.5, family=theme.MONO_FONT, ha="right", va="center",
             alpha=tl.cue(0.10, 0.26), zorder=20)
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# control versus threat
# ---------------------------------------------------------------------------

def render_sterile_domination(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                              path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]

    content_top = _chrome(fig, bundle, scene, tl)
    key_row_y = content_top - KEY_ROW_HEIGHT / 2
    _team_key_row(fig, design, bundle, key_row_y, tl.cue(0.08, 0.24))

    # A funnel from having the ball to actually scoring. Each stage is a real
    # count, and the bar shows each team's share of that stage.
    funnel = [
        ("pass_share_pct", i18n.t("pass_share")),
        ("final_third_passes", i18n.t("final_third_short")),
        ("box_entry_passes", i18n.t("into_box_short")),
        ("shots", stat_label("shots")),
        ("shots_on_target", stat_label("shots_on_target")),
        ("goals", stat_label("goals")),
    ]

    top = key_row_y - KEY_ROW_HEIGHT / 2 - 0.010
    bottom = STAGE_FLOOR + 0.036
    step = (top - bottom) / len(funnel)
    for index, (key, label) in enumerate(funnel):
        local = tl.stagger(index, len(funnel), start=0.12, span=0.48, duration=0.30)
        if local <= 0.005:
            continue
        home_value = float(home.get(key) or 0)
        away_value = float(away.get(key) or 0)
        y = top - step * (index + 1) + step * 0.30
        # The funnel narrows toward the goal so the drop-off is visible.
        inset = 0.055 * (index / max(1, len(funnel) - 1))
        draw.comparison_bar(
            fig, y, label, home_value, away_value,
            design["home"]["chart"], design["away"]["chart"], progress=local,
            left=0.215 + inset, right=0.785 - inset,
            suffix="%" if key.endswith("_pct") else "",
        )
    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

def render_close(bundle: MatchBundle, audit: dict[str, Any], scene: dict[str, Any],
                 path: Path, progress: float = 1.0) -> None:
    design = theme.match_design(bundle.home, bundle.away)
    fig = draw.new_figure(design)
    tl = Timeline(progress)
    stats = audit["team_stats"]
    home, away = stats[bundle.home], stats[bundle.away]

    draw.fig_rect(fig, 0.0, 0.962, 0.5, 0.004, design["home"]["chart"], tl.cue(0.02, 0.22), zorder=18)
    draw.fig_rect(fig, 0.5, 0.962, 0.5, 0.004, design["away"]["chart"], tl.cue(0.02, 0.22), zorder=18)

    qualifier = bundle.score.qualifier
    end = _scoreboard(fig, bundle, design, tl, top=0.918, row_height=0.116,
                      show_qualifier=bool(qualifier), instant=True)

    keys = _stat_keys(scene, ["shots", "shots_on_target", "big_chances", "corners"])
    keys = [key for key in keys if key in home and key in away][:4]
    top = end - 0.028
    bottom = STAGE_FLOOR + 0.036
    step = (top - bottom) / max(1, len(keys))
    for index, key in enumerate(keys):
        local = tl.stagger(index, len(keys), start=0.34, span=0.34, duration=0.28)
        if local <= 0.01:
            continue
        y = top - step * (index + 0.5)
        alpha = min(1.0, local * 1.6)
        slide = (1.0 - local) * 0.03
        fig.text(Layout.MARGIN + 0.004 - slide, y, stat_label(key).upper(), color=TEXT_DIM,
                 fontsize=theme.label_size(14), family=theme.LABEL_FONT, fontweight="bold",
                 ha="left", va="center", alpha=alpha, zorder=14)
        fig.text(1 - Layout.MARGIN - 0.004, y,
                 f"{format_stat(key, home.get(key, 0))}  /  {format_stat(key, away.get(key, 0))}",
                 color=TEXT, fontsize=30, fontweight="bold", family=theme.DISPLAY_FONT,
                 ha="right", va="center", alpha=alpha, zorder=14)
        draw.fig_rect(fig, Layout.MARGIN, y - step * 0.42, Layout.CONTENT_W, 0.0018,
                      design["hairline"], 0.9 * alpha, zorder=10)

    draw.save_figure(fig, path)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

RENDERERS: dict[str, Renderer] = {
    "hook_claim": render_hook_claim,
    "hook_punch": render_hook_punch,
    "micro_hook": render_micro_hook,
    "live_clip": render_hook_claim,
    "title": render_title,
    "standard_stats": render_standard_stats,
    "goal_timeline": render_goal_timeline,
    "shot_map": render_shot_map,
    "momentum": render_momentum,
    "zone_control": render_zone_control,
    "goal_chain": render_goal_chain,
    "goalmouth": render_goalmouth,
    "pass_network": render_pass_network,
    "sterile_domination": render_sterile_domination,
    "close": render_close,
}


def renderer_for(visualization: str) -> Renderer:
    try:
        return RENDERERS[visualization]
    except KeyError:
        raise KeyError(
            f"No renderer registered for {visualization!r}. "
            f"Known visualizations: {', '.join(sorted(RENDERERS))}"
        ) from None
