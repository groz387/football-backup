"""Graph smoke: mosaic + backup pitch cards survive empty audits."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            "lines": ["KOREA HAD 9 SHOTS.", "KOREA HAD 3 BIG CHANCES."],
            "split": {"home": 8, "away": 9, "label": "SHOTS"},
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


    def test_mosaic_draws_rectangular_tiles_not_hex_scatter(self) -> None:
        source = Path(graphs.__file__).read_text(encoding="utf-8")
        self.assertNotIn('marker="h"', source)
        self.assertNotIn("marker='h'", source)
        self.assertIn("Rectangle", source)
        self.assertNotIn("cells[:110]", source)

        heat = {
            "x_bins": 12,
            "y_bins": 8,
            "home": [[float((x + y) % 4) for y in range(8)] for x in range(12)],
            "away": [[float((x * y) % 3) for y in range(8)] for x in range(12)],
        }
        occupied = 0
        for xi in range(12):
            for yi in range(8):
                if heat["home"][xi][yi] + heat["away"][xi][yi] > 0:
                    occupied += 1
        self.audit["touch_heatmap"] = heat
        patches: list[object] = []
        scatter_calls: list[object] = []

        original_add = graphs.draw.add_shape
        original_scatter_batch = getattr(graphs.draw, "scatter_batch", None)

        def capture_shape(ax, patch):
            patches.append(patch)
            return original_add(ax, patch)

        def capture_scatter(*args, **kwargs):
            scatter_calls.append(kwargs)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(graphs.draw, "add_shape", side_effect=capture_shape), \
                mock.patch("matplotlib.axes.Axes.scatter", side_effect=capture_scatter):
            path = Path(tmp) / "mosaic.png"
            graphs.render_touch_heatmap(self.bundle, self.audit, self.scene, path, 1.0)
        from matplotlib.patches import Rectangle
        tiles = [patch for patch in patches if isinstance(patch, Rectangle)]
        self.assertGreaterEqual(len(tiles), occupied)
        self.assertFalse(scatter_calls)

    def test_english_bridges_do_not_say_heat_map(self) -> None:
        from recap import i18n

        i18n.set_language("en")
        blob = " ".join(
            i18n.t(key, team="KOREA", n=100)
            for key in ("bridge_heat_0", "bridge_heat_1", "bridge_heat_2", "sub_heatmap")
        ).lower()
        self.assertNotIn("heat map", blob)
        self.assertNotIn("heatmap", blob.replace(" ", ""))
        self.assertNotIn("hex", blob)
        self.assertTrue("tile" in blob or "mosaic" in blob)
        copy = director._visual_copy(self.bundle, {
            **self.audit,
            "zone_control": [{"home_touches": 12, "away_touches": 9}],
            "team_stats": self.audit["team_stats"],
            "goal_timeline": [],
        }, "touch_heatmap")
        joined = f"{copy['insight']} {copy['narration']}".lower()
        self.assertNotIn("hex", joined)
        self.assertNotIn("heat map", joined)
        self.assertIn("tile", joined)

    def test_analysis_narration_lands_near_seventeen_words(self) -> None:
        from recap import timing

        stats = {
            self.bundle.home: {
                **_empty_stats(),
                "shots": 8, "shots_on_target": 4, "shots_blocked": 1,
                "big_chances": 1, "goals": 1, "pass_share_pct": 42,
                "pass_attempts": 200, "passes_completed": 160,
            },
            self.bundle.away: {
                **_empty_stats(),
                "shots": 9, "shots_on_target": 2, "shots_blocked": 2,
                "big_chances": 3, "goals": 0, "pass_share_pct": 58,
                "pass_attempts": 280, "passes_completed": 230,
            },
        }
        audit = {
            **self.audit,
            "team_stats": stats,
            "zone_control": [
                {"home_touches": 40, "away_touches": 55, "xbin": 0, "ybin": 0, "total_touches": 95, "home_share_pct": 42},
            ],
            "momentum": [{"swing": 4.2, "minute_block": "45-49", "home_pressure": 8, "away_pressure": 3}],
            "goal_timeline": [{"minute": 12, "team": self.bundle.home, "scorer": "Alpha", "h_a": "h", "own_goal": False, "penalty": False}],
            "data_health": {**self.audit["data_health"], "has_vendor_possession": False},
        }
        selected = [{"id": vid} for vid in ("shot_map", "touch_heatmap", "sterile_domination", "momentum")]
        scenes = director.build_storyboard(self.bundle, audit, selected)
        analysis = [
            scene for scene in scenes
            if scene["visualization"] in {"shot_map", "touch_heatmap", "sterile_domination", "momentum"}
        ]
        self.assertEqual(len(analysis), 4)
        for scene in analysis:
            words = timing.word_count(scene.get("narration") or "")
            self.assertGreaterEqual(words, 16, f"{scene['visualization']} is {words}: {scene.get('narration')}")
            self.assertLessEqual(words, 19, f"{scene['visualization']} is {words}: {scene.get('narration')}")
        hooks = [scene for scene in scenes if scene.get("hook") or scene["visualization"] == "close"]
        for scene in hooks:
            words = timing.word_count(scene.get("narration") or "")
            self.assertLessEqual(words, 16, f"{scene['visualization']} should stay short: {scene.get('narration')}")

        long_line = (
            "Mexico put eight shots on the map against nine and then kept adding "
            "clauses until the sentence wandered far past twenty words easily here."
        )
        fitted = director.normalize_analysis_words([
            {
                "id": "shot_map",
                "visualization": "shot_map",
                "narration": long_line,
                "insight": "8 against 9 shots",
                "fact_pack": {"numbers": [8, 9], "what_the_picture_shows": "Every attempt, by outcome"},
            },
            {
                "id": "hook_claim",
                "visualization": "hook_claim",
                "hook": True,
                "narration": "KOREA HAD 9 SHOTS.",
            },
        ])
        self.assertLessEqual(timing.word_count(fitted[0]["narration"]), 20)
        self.assertGreaterEqual(timing.word_count(fitted[0]["narration"]), 16)
        self.assertEqual(fitted[1]["narration"], "KOREA HAD 9 SHOTS.")


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
