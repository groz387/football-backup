"""Graph smoke: mosaic + backup pitch cards survive empty audits."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from recap import director, draw, graphs, scenes, theme
from recap.draw import Timeline
from recap.data import MatchBundle, Score
from recap.director import ANGLE_VIZ, SHAPE_FAMILY, unique_shape_pack

CORE_VIZ = (
    "shot_map",
    "momentum",
    "zone_control",
    "goal_chain",
    "goalmouth",
    "pass_network",
    "sterile_domination",
    "touch_heatmap",
    "goal_timeline",
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
            "has_precise_coordinates": False,
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
    }


class GraphEmptyAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        theme.set_frame_size(1080, 1920)
        self.bundle = _minimal_bundle()
        self.audit = _minimal_audit(self.bundle)
        self.scene = {"title": "TEST", "insight": "late stamp"}

    def tearDown(self) -> None:
        theme.set_frame_size(1080, 1920)

    def test_mosaic_and_backup_cards_survive_empty_audit(self) -> None:
        renderers = {
            "touch_heatmap": graphs.render_touch_heatmap,
            "shot_map": scenes.render_shot_map,
            "zone_control": scenes.render_zone_control,
            "momentum": scenes.render_momentum,
            "goal_timeline": scenes.render_goal_timeline,
            "goalmouth": scenes.render_goalmouth,
            "pass_network": scenes.render_pass_network,
            "sterile_domination": scenes.render_sterile_domination,
            "goal_chain": scenes.render_goal_chain,
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, renderer in renderers.items():
                for progress in (0.0, 0.5, 1.0):
                    path = folder / f"{name}_{progress}.png"
                    renderer(self.bundle, self.audit, self.scene, path, progress)
                    self.assertTrue(path.exists(), f"{name} at {progress} wrote nothing")

    def test_viral_graphs_are_not_registered(self) -> None:
        self.assertEqual(set(graphs.GRAPH_RENDERERS), {"touch_heatmap"})
        for vid in ("stat_slam", "shot_clock_spiral", "duel_tower", "press_trap"):
            self.assertNotIn(vid, scenes.RENDERERS)

    def test_landscape_figure_does_not_crash(self) -> None:
        theme.set_frame_size(1920, 1080)
        design = theme.match_design("Mexico", "South Korea")
        fig = draw.new_figure(design)
        self.assertGreater(fig.get_figwidth(), fig.get_figheight())
        draw.save_figure(fig, Path(tempfile.mkdtemp()) / "land.png")

    def test_opening_frame_stays_pitch_black(self) -> None:
        import matplotlib.pyplot as plt

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, renderer in (
                ("mosaic", graphs.render_touch_heatmap),
                ("shots", scenes.render_shot_map),
                ("zones", scenes.render_zone_control),
            ):
                path = folder / f"{name}.png"
                renderer(self.bundle, self.audit, self.scene, path, 0.0)
                pixels = plt.imread(path)
                self.assertLess(
                    float(pixels[..., :3].mean()),
                    0.05,
                    f"{name} opening frame is not pitch black",
                )

    def test_hook_opening_corners_stay_pitch_black(self) -> None:
        import matplotlib.pyplot as plt

        scene = {
            "title": "KOREA HAD 9 SHOTS",
            "insight": "late stamp",
            "visual_language": "number_slam",
            "hero_number": 9,
            "hero_label": "SHOTS",
            "hero_team": "South Korea",
            "seconds": 0.85,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook.png"
            scenes.render_hook_claim(self.bundle, self.audit, scene, path, 0.0)
            pixels = plt.imread(path)
            h, w = pixels.shape[:2]
            corners = (
                pixels[8, w // 2, :3],
                pixels[h // 2, w // 2, :3],
                pixels[h - 9, w // 2, :3],
            )
            for sample in corners:
                self.assertLess(
                    float(sample.mean()),
                    0.12,
                    f"hook opening sample {tuple(sample)} is not pitch black",
                )


class UniquenessTests(unittest.TestCase):
    def test_core_viz_have_shape_families(self) -> None:
        for vid in CORE_VIZ:
            self.assertIn(vid, SHAPE_FAMILY, vid)

    def test_angle_lists_are_unique_shape_packs(self) -> None:
        for angle, ids in ANGLE_VIZ.items():
            self.assertTrue(
                unique_shape_pack(ids),
                f"{angle} collides: {director.pack_shape_families(ids)}",
            )

    def test_graphs_module_does_not_import_scenes(self) -> None:
        import ast
        from pathlib import Path as P

        tree = ast.parse(P(graphs.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("scenes", alias.name.split("."))
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("scenes", node.module.split("."))

    def test_colliding_shape_ids_flags_shared_family(self) -> None:
        hits = director.colliding_shape_ids(["shot_map", "goalmouth", "momentum"])
        self.assertEqual(hits, [("shot_map", "goalmouth")])

    def test_hold_count_stays_on_an_integer(self) -> None:
        seen = []
        for frame in range(0, 36):
            progress = frame / 36.0
            shown = draw.hold_count(12, progress)
            seen.append(shown)
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

    def test_insight_stamp_finishes_by_hold(self) -> None:
        tl = Timeline(draw.HOLD_AT)
        self.assertGreaterEqual(tl.stamp(), 0.99)
        self.assertGreaterEqual(tl.wipe(0.02, 0.58), 0.99)

    def test_ghost_stroke_vanishes_at_low_alpha(self) -> None:
        self.assertEqual(draw.soft_shadow(0.05), [])
        self.assertEqual(draw.outline(0.10), [])
        self.assertTrue(draw.soft_shadow(1.0))

    def test_assembly_fades_instead_of_wiping_type(self) -> None:
        from recap import video

        scenes_plan = [
            {"clip": 2.0, "cut": "hard", "visualization": "hook_claim"},
            {"clip": 5.0, "cut": "wipe", "visualization": "momentum"},
            {"clip": 5.0, "cut": "wipe", "visualization": "close"},
        ]
        graph, _ = video._assembly_filter(scenes_plan, 24)
        self.assertNotIn("wiperight", graph)
        self.assertIn("xfade=transition=fade", graph)
        self.assertIn("settb=1/24", graph)

    def test_analysis_frames_are_seeded(self) -> None:
        from recap import video

        self.assertEqual(video.frame_progress(0, 100, full_motion=True), 0.0)
        self.assertGreater(video.frame_progress(0, 100, full_motion=False), 0.04)
        self.assertEqual(video.frame_progress(99, 100, full_motion=False), 1.0)

    def test_auto_colors_resolve_known_clubs(self) -> None:
        from recap import colors

        pair = colors.resolve_pair("Barcelona", "Atletico Madrid", kind="club")
        self.assertTrue(pair.home.fill.startswith("#"))
        self.assertTrue(pair.away.fill.startswith("#"))
        self.assertNotEqual(pair.home.fill.lower(), pair.away.fill.lower())


if __name__ == "__main__":
    unittest.main()
