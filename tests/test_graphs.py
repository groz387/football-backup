"""Lightweight graph tests: empty audit does not crash; packs stay unique."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from recap import director, draw, graphs, theme
from recap.data import MatchBundle, Score
from recap.director import ANGLE_VIZ, SHAPE_FAMILY, unique_shape_pack


NEW_VIZ = (
    "shot_clock_spiral",
    "press_trap",
    "pass_lanes",
    "bench_impact",
    "duel_tower",
    "aerial_war",
    "halftime_split",
)


def _empty_stats() -> dict:
    keys = (
        "shots", "shots_on_target", "shots_blocked", "big_chances", "goals",
        "pass_share_pct", "pass_accuracy_pct", "pass_attempts", "passes_completed",
        "final_third_passes", "box_entry_passes", "penalty_box_touches",
        "tackles_won", "saves", "dribbles_won", "xg",
    )
    return {key: 0 for key in keys}


def _minimal_bundle() -> MatchBundle:
    empty = pd.DataFrame()
    return MatchBundle(
        match_dir=Path("."),
        summary={"home": {"name": "Home"}, "away": {"name": "Away"}},
        events=empty,
        passes=empty,
        shots=empty,
        touches=empty,
        players=empty,
        score=Score(home=0, away=0),
    )


def _minimal_audit(bundle: MatchBundle) -> dict:
    blank_team = _empty_stats()
    return {
        "team_stats": {bundle.home: dict(blank_team), bundle.away: dict(blank_team)},
        "data_health": {
            "has_vendor_xg": False,
            "has_vendor_xgot": False,
            "has_goal_mouth_coordinates": False,
            "pass_rows": 0,
        },
        "shots": [],
        "momentum": [],
        "field_tilt": [],
        "zone_control": [],
        "goal_timeline": [],
        "clock_axis": {"end": 90.0, "ticks": [], "boundaries": []},
        "touch_heatmap": {"home": [], "away": []},
        "time_zones": [],
        "player_leaders": {"spike": None},
        "press_trap": {
            "home": {"ppda": None, "press_actions": 0, "opp_passes": 0, "audited": False},
            "away": {"ppda": None, "press_actions": 0, "opp_passes": 0, "audited": False},
            "audited": False,
            "leader": "",
            "leader_ppda": None,
        },
        "duels": {
            "home": {"tackles": 0, "aerials": 0, "take_ons": 0, "total": 0},
            "away": {"tackles": 0, "aerials": 0, "take_ons": 0, "total": 0},
            "total": 0,
        },
        "aerials": {"events": [], "home_won": 0, "away_won": 0, "total": 0},
        "bench_impact": {"subs": [], "home_count": 0, "away_count": 0},
        "halftime_split": {
            "first": {"home_shots": 0, "away_shots": 0, "home_goals": 0, "away_goals": 0,
                      "home_pressure": 0.0, "away_pressure": 0.0},
            "second": {"home_shots": 0, "away_shots": 0, "home_goals": 0, "away_goals": 0,
                       "home_pressure": 0.0, "away_pressure": 0.0},
            "ready": False,
        },
    }


class GraphEmptyAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        theme.set_frame_size(1080, 1920)
        self.bundle = _minimal_bundle()
        self.audit = _minimal_audit(self.bundle)
        self.scene = {"title": "TEST", "insight": "late stamp"}

    def tearDown(self) -> None:
        theme.set_frame_size(1080, 1920)

    def test_graph_renderers_survive_empty_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, renderer in graphs.GRAPH_RENDERERS.items():
                for progress in (0.0, 0.5, 1.0):
                    path = folder / f"{name}_{progress}.png"
                    renderer(self.bundle, self.audit, self.scene, path, progress)
                    self.assertTrue(path.exists(), f"{name} at {progress} wrote nothing")

    def test_shot_map_survives_empty_audit(self) -> None:
        from recap.scenes import render_shot_map

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shot_map.png"
            render_shot_map(self.bundle, self.audit, self.scene, path, 1.0)
            self.assertTrue(path.exists())

    def test_landscape_figure_does_not_crash(self) -> None:
        theme.set_frame_size(1920, 1080)
        design = theme.match_design("Scotland", "Morocco")
        fig = draw.new_figure(design)
        self.assertGreater(fig.get_figwidth(), fig.get_figheight())
        draw.save_figure(fig, Path(tempfile.mkdtemp()) / "land.png")


class UniquenessTests(unittest.TestCase):
    def test_new_viz_have_distinct_shape_families(self) -> None:
        for vid in NEW_VIZ:
            self.assertIn(vid, SHAPE_FAMILY, vid)
        families = [SHAPE_FAMILY[vid] for vid in NEW_VIZ]
        self.assertEqual(len(families), len(set(families)))

    def test_player_spike_is_poster(self) -> None:
        self.assertEqual(SHAPE_FAMILY["player_spike"], "poster")

    def test_angle_lists_are_unique_shape_packs(self) -> None:
        for angle, ids in ANGLE_VIZ.items():
            self.assertTrue(
                unique_shape_pack(ids),
                f"{angle} collides: {director.pack_shape_families(ids)}",
            )

    def test_hold_count_stays_on_an_integer(self) -> None:
        # ~8 frames at 24fps over a 1.5s count → each glyph holds a window.
        seen = []
        for frame in range(0, 36):
            progress = frame / 36.0
            shown = draw.hold_count(12, progress)
            seen.append(shown)
        # Consecutive identical values should span several frames.
        run = 1
        longest = 1
        for a, b in zip(seen, seen[1:]):
            if a == b:
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        self.assertGreaterEqual(longest, 3)
        self.assertEqual(draw.hold_count(12, 1.0), 12)


if __name__ == "__main__":
    unittest.main()
