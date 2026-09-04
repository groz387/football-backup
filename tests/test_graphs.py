"""Lightweight graph tests: empty audit does not crash; packs stay unique."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from recap import director, draw, graphs, theme
from recap.draw import Timeline
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

    def test_duel_tower_clamps_overshooting_opacity(self) -> None:
        self.audit["duels"] = {
            "home": {"tackles": 9, "aerials": 7, "take_ons": 6, "total": 22},
            "away": {"tackles": 8, "aerials": 6, "take_ons": 5, "total": 19},
            "total": 41,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duel_tower_midpoint.png"
            graphs.render_duel_tower(self.bundle, self.audit, self.scene, path, 0.5)
            self.assertTrue(path.exists())

    def test_landscape_figure_does_not_crash(self) -> None:
        theme.set_frame_size(1920, 1080)
        design = theme.match_design("Scotland", "Morocco")
        fig = draw.new_figure(design)
        self.assertGreater(fig.get_figwidth(), fig.get_figheight())
        draw.save_figure(fig, Path(tempfile.mkdtemp()) / "land.png")

    def test_opening_frame_stays_pitch_black(self) -> None:
        import matplotlib.pyplot as plt

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, renderer in (
                ("slam", graphs.render_stat_slam),
                ("split", graphs.render_halftime_split),
                ("bench", graphs.render_bench_impact),
                ("heat", graphs.render_touch_heatmap),
            ):
                path = folder / f"{name}.png"
                renderer(self.bundle, self.audit, self.scene, path, 0.0)
                pixels = plt.imread(path)
                self.assertLess(
                    float(pixels[..., :3].mean()),
                    0.05,
                    f"{name} opening frame is not pitch black",
                )

    def test_territory_cards_do_not_interpolate(self) -> None:
        import inspect
        from recap import scenes

        sources = {
            "heatmap": inspect.getsource(graphs.render_touch_heatmap),
            "zone": inspect.getsource(scenes.render_zone_control),
            "time": inspect.getsource(graphs.render_time_zones),
            "pitch": inspect.getsource(draw.heat_pitch),
        }
        for name, src in sources.items():
            self.assertNotIn('interpolation="bilinear"', src, name)
            self.assertNotIn("interpolation='bilinear'", src, name)
        self.assertIn("mosaic_cells", sources["heatmap"])
        self.assertIn("mosaic_cells", sources["zone"])
        self.assertIn("Rectangle", inspect.getsource(draw.mosaic_cells))

    def test_touch_mosaic_paints_event_bins_on_black(self) -> None:
        import matplotlib.pyplot as plt

        self.audit["touch_heatmap"] = {
            "x_bins": 4,
            "y_bins": 3,
            "home": [[4, 0, 0], [0, 2, 0], [0, 0, 0], [3, 0, 1]],
            "away": [[0, 2, 0], [0, 0, 5], [1, 0, 0], [0, 0, 0]],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mosaic.png"
            graphs.render_touch_heatmap(self.bundle, self.audit, self.scene, path, 1.0)
            pixels = plt.imread(path)
            self.assertLess(float(pixels[8, 8, :3].mean()), 0.08)
            self.assertGreater(float(pixels[..., :3].max()), 0.15)

    def test_heat_pitch_is_mosaic_not_imshow(self) -> None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        before = len(ax.patches)
        draw.heat_pitch(ax, [[0, 2], [4, 0]], "#ff0000", progress=1.0)
        self.assertGreater(len(ax.patches), before)
        self.assertEqual(len(ax.images), 0)
        plt.close(fig)


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

    def test_graphs_module_does_not_import_scenes(self) -> None:
        import ast
        from pathlib import Path

        tree = ast.parse(Path(graphs.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("scenes", alias.name.split("."))
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("scenes", node.module.split("."))

    def test_colliding_shape_ids_flags_shared_family(self) -> None:
        hits = director.colliding_shape_ids(["shot_map", "keeper_frame", "momentum"])
        self.assertEqual(hits, [("shot_map", "keeper_frame")])

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

    def test_hold_count_decimals_hold_on_tenths(self) -> None:
        seen = [draw.hold_count(1.8, frame / 24.0) for frame in range(24)]
        self.assertEqual(draw.hold_count(1.8, 1.0), 1.8)
        self.assertTrue(all(abs(value * 10 - round(value * 10)) < 1e-6 or value == 1.8 for value in seen))

    def test_insight_stamp_finishes_by_hold(self) -> None:
        tl = Timeline(draw.HOLD_AT)
        self.assertGreaterEqual(tl.stamp(), 0.99)
        self.assertGreaterEqual(tl.wipe(0.02, 0.58), 0.99)

    def test_ghost_stroke_vanishes_at_low_alpha(self) -> None:
        self.assertEqual(draw.soft_shadow(0.05), [])
        self.assertEqual(draw.outline(0.10), [])
        self.assertTrue(draw.soft_shadow(1.0))

    def test_ring_gauge_is_silent_until_ink_is_visible(self) -> None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        before = len(ax.patches)
        draw.ring_gauge(ax, 0.5, 0.5, 8, 10, "#ffffff", progress=0.0)
        self.assertEqual(len(ax.patches), before)
        draw.ring_gauge(ax, 0.5, 0.5, 8, 10, "#ffffff", progress=1.0)
        self.assertGreater(len(ax.patches), before)
        plt.close(fig)

    def test_radar_polygon_is_silent_until_ink_is_visible(self) -> None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        before = len(ax.patches) + len(ax.lines)
        draw.radar_polygon(ax, [0.8, 0.6, 0.4, 0.7, 0.5, 0.9], "#ffffff", progress=0.0)
        self.assertEqual(len(ax.patches) + len(ax.lines), before)
        draw.radar_polygon(ax, [0.8, 0.6, 0.4, 0.7, 0.5, 0.9], "#ffffff", progress=1.0)
        self.assertGreater(len(ax.patches) + len(ax.lines), before)
        plt.close(fig)

    def test_assembly_fades_instead_of_wiping_type(self) -> None:
        from recap import video

        scenes = [
            {"clip": 2.0, "cut": "hard", "visualization": "hook_claim"},
            {"clip": 5.0, "cut": "wipe", "visualization": "momentum"},
            {"clip": 5.0, "cut": "wipe", "visualization": "close"},
        ]
        graph, _ = video._assembly_filter(scenes, 24)
        self.assertNotIn("wiperight", graph)
        self.assertIn("xfade=transition=fade", graph)

    def test_analysis_frames_are_seeded(self) -> None:
        from recap import video

        self.assertEqual(video.frame_progress(0, 100, full_motion=True), 0.0)
        self.assertGreater(video.frame_progress(0, 100, full_motion=False), 0.04)
        self.assertEqual(video.frame_progress(99, 100, full_motion=False), 1.0)


if __name__ == "__main__":
    unittest.main()
