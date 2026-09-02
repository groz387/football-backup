"""Scoring math for the viral 0–100 and the hook A/B picker."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from recap import ab_hooks, viral_audit
from recap.data import MatchBundle, Score
from recap.viral_audit import (
    BAR_CLONE_RATIO,
    PILLAR_WEIGHTS,
    combine_score,
    hook_speed_ratio,
    length_ratio,
)
from video_pipeline import parse_args


HOME = "Aston Villa"
AWAY = "Arsenal"


def make_bundle(match_id: str = "1990001_Aston_Villa_vs_Arsenal") -> MatchBundle:
    return MatchBundle(
        match_dir=Path(f"/tmp/{match_id}"),
        summary={"home": {"name": HOME}, "away": {"name": AWAY}, "score": "1 : 2"},
        events=pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(home=1, away=2),
    )


def make_audit() -> dict:
    return {
        "team_stats": {
            HOME: {
                "shots": 15, "shots_on_target": 6, "big_chances": 4, "corners": 8,
                "shots_blocked": 5, "penalty_box_touches": 22, "saves": 2,
                "pass_share_pct": 47, "red_cards": 0, "xg": 1.4,
            },
            AWAY: {
                "shots": 7, "shots_on_target": 3, "big_chances": 1, "corners": 2,
                "shots_blocked": 1, "penalty_box_touches": 8, "saves": 5,
                "pass_share_pct": 53, "red_cards": 0, "xg": 0.8,
            },
        },
        "data_health": {"has_vendor_xg": False},
        "goal_timeline": [{
            "h_a": "a", "team": AWAY, "minute": 81,
            "penalty": False, "own_goal": False, "scorer": "Saka",
        }],
        "momentum": [],
        "field_tilt": [],
        "match": {"home": HOME, "away": AWAY, "score_display": "1-2"},
    }


HOOK_PACK = {
    "numbers": [15, 7, 8, 2],
    "never_say": ["1-2", "1–2", "1:2", "1 - 2"],
    "surnames": ["Watkins"],
}


def perfect_scenes(*, punch: str = "THEY STILL LOST.") -> list[dict]:
    return [
        {
            "id": "hook_claim",
            "visualization": "hook_claim",
            "hook": True,
            "seconds": 0.5,
            "title": "15 SHOTS",
            "subtitle": "",
            "insight": "",
            "narration": "Fifteen shots.",
            "lines": ["15 SHOTS"],
            "hero_number": 15,
            "hero_label": "SHOTS",
            "visual_language": "number_slam",
            "hook_kind": "volume_upset",
            "fact_pack": HOOK_PACK,
        },
        {
            "id": "hook_punch",
            "visualization": "hook_punch",
            "hook": True,
            "seconds": 0.7,
            "title": punch,
            "narration": punch.rstrip("."),
            "lines": [punch],
            "hook_kind": "volume_upset",
            "visual_language": "stamp",
            "fact_pack": HOOK_PACK,
        },
        {
            "id": "shot_map",
            "visualization": "shot_map",
            "seconds": 10.0,
            "title": "WATKINS HAD 15",
            "insight": "Volume without a cut-back.",
            "narration": "Villa peppered the box.",
            "fact_pack": {**HOOK_PACK, "surnames": ["Watkins"]},
        },
        {
            "id": "field_tilt_wave",
            "visualization": "field_tilt_wave",
            "seconds": 10.0,
            "title": "PINNED FOR 80",
            "insight": "The wave never flipped.",
            "narration": "Arsenal sat in and waited.",
            "fact_pack": {"numbers": [80], "surnames": []},
        },
        {
            "id": "chance_funnel",
            "visualization": "chance_funnel",
            "seconds": 8.0,
            "title": "7 SHOTS, THE POINTS",
            "insight": "Clinical, not lucky.",
            "narration": "Seven shots were enough.",
            "fact_pack": {"numbers": [7, 15], "surnames": []},
        },
        {
            "id": "close",
            "visualization": "close",
            "seconds": 4.0,
            "title": "ASTON VILLA 1-2 ARSENAL",
            "insight": "WAS IT A ROBBERY? COMMENT.",
            "narration": "Villa had the shots. Arsenal had the night.",
            "comment_bait": "WAS IT A ROBBERY? COMMENT.",
            "fact_pack": {"numbers": [1, 2, 15, 7], "never_say": []},
        },
    ]


SELECTED = [
    {"id": "shot_map", "shape": "pitch"},
    {"id": "field_tilt_wave", "shape": "time"},
    {"id": "chance_funnel", "shape": "hero"},
]

SKIPPED_CLIP = {"mode": "skipped", "skipped": True, "reason": "no-fetch"}


def score(scenes=None, **kwargs):
    kwargs.setdefault("clip_report", SKIPPED_CLIP)
    kwargs.setdefault("language", "en")
    kwargs.setdefault("spoiler", "show")
    return viral_audit.score_plan(
        scenes or perfect_scenes(), SELECTED, make_bundle(), make_audit(), **kwargs,
    )


class CombineMathTests(unittest.TestCase):
    def test_weights_sum_to_100(self) -> None:
        self.assertEqual(sum(PILLAR_WEIGHTS.values()), 100)

    def test_all_ones_with_safe_zones_skipped_is_100(self) -> None:
        ratios = {key: 1.0 for key in PILLAR_WEIGHTS}
        self.assertEqual(combine_score(ratios, skip={"safe_zones"}), 100)
        self.assertEqual(combine_score(ratios), 100)

    def test_zero_hook_speed_is_exact(self) -> None:
        ratios = {key: 1.0 for key in PILLAR_WEIGHTS}
        ratios["hook_speed"] = 0.0
        skip = {"safe_zones"}
        denom = sum(PILLAR_WEIGHTS.values()) - PILLAR_WEIGHTS["safe_zones"]
        expected = round(100 * (denom - PILLAR_WEIGHTS["hook_speed"]) / denom)
        self.assertEqual(combine_score(ratios, skip=skip), expected)

    def test_bar_clone_ratio_points(self) -> None:
        ratios = {key: 1.0 for key in PILLAR_WEIGHTS}
        ratios["viz_mix"] = BAR_CLONE_RATIO
        skip = {"safe_zones"}
        denom = 96
        expected = round(100 * (denom - PILLAR_WEIGHTS["viz_mix"] * (1 - BAR_CLONE_RATIO)) / denom)
        self.assertEqual(combine_score(ratios, skip=skip), expected)

    def test_hook_speed_curve(self) -> None:
        self.assertEqual(hook_speed_ratio(0.0, stamped=True, deadline=0.8), 1.0)
        self.assertEqual(hook_speed_ratio(0.8, stamped=True, deadline=0.8), 1.0)
        self.assertEqual(hook_speed_ratio(2.0, stamped=True, deadline=0.8), 0.0)
        self.assertAlmostEqual(hook_speed_ratio(1.4, stamped=True, deadline=0.8), 0.5)
        self.assertAlmostEqual(hook_speed_ratio(0.0, stamped=False, deadline=0.8), 0.4)

    def test_length_band(self) -> None:
        self.assertEqual(length_ratio(33.0), 1.0)
        self.assertEqual(length_ratio(21.0), 1.0)
        self.assertEqual(length_ratio(45.0), 1.0)
        self.assertEqual(length_ratio(9.0), 0.0)
        self.assertAlmostEqual(length_ratio(15.0), 0.5)
        self.assertAlmostEqual(length_ratio(55.0), 0.5)
        self.assertEqual(length_ratio(65.0), 0.0)


class ScorePlanTests(unittest.TestCase):
    def test_perfect_short_is_100(self) -> None:
        report = score()
        self.assertEqual(report["score"], 100, report["warnings"])
        self.assertEqual(report["skipped_pillars"], ["safe_zones"])
        self.assertFalse(report["failures"], report["failures"])
        self.assertEqual(report["hook_kind"], "volume_upset")
        self.assertIn("THEY STILL LOST", report["punch"])

    def test_three_bar_clones_use_published_ratio(self) -> None:
        selected = [
            {"id": "standard_stats", "shape": "bars"},
            {"id": "box_score", "shape": "bars"},
            {"id": "standard_stats", "shape": "bars"},
        ]
        scenes = perfect_scenes()
        for scene, viz in zip(scenes[2:5], ["standard_stats", "box_score", "standard_stats"]):
            scene["id"] = viz
            scene["visualization"] = viz
        report = viral_audit.score_plan(
            scenes, selected, make_bundle(), make_audit(),
            clip_report=SKIPPED_CLIP, language="en",
        )
        self.assertEqual(report["pillars"]["viz_mix"]["ratio"], BAR_CLONE_RATIO)
        ratios = {key: 1.0 for key in PILLAR_WEIGHTS}
        ratios["viz_mix"] = BAR_CLONE_RATIO
        self.assertEqual(report["score"], combine_score(ratios, skip={"safe_zones"}))
        self.assertTrue(any("bar clone" in note for note in report["failures"]))

    def test_late_hook_hurts_tiktok_more_than_youtube(self) -> None:
        scenes = perfect_scenes()
        scenes.insert(0, {
            "id": "live_clip_1",
            "visualization": "live_clip",
            "hook": True,
            "seconds": 1.2,
            "title": "smash",
            "narration": "",
        })
        report = score(scenes, clip_report={"mode": "local", "skipped": False})
        self.assertLess(report["tiktok_score"], report["youtube_score"])
        self.assertLess(report["pillars"]["hook_speed"]["ratio"], 1.0)
        self.assertTrue(any("first readable" in note for note in report["failures"]))

    def test_az_english_ui_fails_language(self) -> None:
        scenes = perfect_scenes()
        scenes[2]["title"] = "SHOT MAP"
        scenes[2]["insight"] = "pass share told the story"
        report = score(scenes, language="az")
        self.assertLess(report["pillars"]["language"]["ratio"], 1.0)
        self.assertLess(report["score"], 100)
        self.assertTrue(any("English" in note for note in report["failures"]))

    def test_number_lock_rejects_scoreline_on_hook(self) -> None:
        scenes = perfect_scenes()
        scenes[0]["title"] = "VILLA 1-2"
        scenes[0]["lines"] = ["VILLA 1-2"]
        scenes[0]["hero_number"] = None
        report = score(scenes)
        self.assertLess(report["pillars"]["number_lock"]["ratio"], 1.0)
        self.assertTrue(report["failures"])

    def test_missing_clip_without_skip_flag_fails(self) -> None:
        report = score(clip_report=None)
        self.assertEqual(report["pillars"]["live_clip"]["ratio"], 0.0)
        self.assertTrue(any("live clip" in note for note in report["failures"]))

    def test_comment_bait_and_length_and_mute(self) -> None:
        scenes = perfect_scenes()
        scenes[-1]["insight"] = "Full time."
        scenes[-1]["comment_bait"] = ""
        scenes[-1]["narration"] = "It finishes."
        scenes.append({
            "id": "dead",
            "visualization": "micro_hook",
            "hook": True,
            "seconds": 0.4,
            "title": "",
            "narration": "",
            "insight": "",
            "lines": [],
        })
        report = score(scenes)
        self.assertEqual(report["pillars"]["comment_bait"]["ratio"], 0.0)
        self.assertLess(report["pillars"]["mute_first"]["ratio"], 1.0)
        self.assertGreater(report["runtime_seconds"], 33.0)

    def test_safe_zones_skipped_without_platforms(self) -> None:
        report = score()
        self.assertIn("safe_zones", report["skipped_pillars"])
        self.assertFalse(report["safe_zones_scored"])

    def test_safe_zones_scored_when_platforms_exist(self) -> None:
        fake = SimpleNamespace(
            PROFILES={"tiktok": SimpleNamespace(id="tiktok")},
            validate_plan=lambda scenes, profile, spoiler="show": ["tiktok: caption in chrome"],
        )
        with mock.patch("recap.viral_audit._platforms", return_value=fake):
            report = score()
        self.assertNotIn("safe_zones", report["skipped_pillars"])
        self.assertTrue(report["safe_zones_scored"])
        self.assertAlmostEqual(report["pillars"]["safe_zones"]["ratio"], 1.0 - 1 / 6, places=3)
        self.assertLess(report["score"], 100)

    def test_redo_instruction_keeps_gemini_path(self) -> None:
        report = score(clip_report=None)
        text = viral_audit.redo_instruction("Rewrite.", report)
        self.assertIn("Fix these viral-audit failures", text)
        self.assertIn("live clip", text)
        self.assertIn("tiktok=", text)

    def test_spoiler_hide_consistency(self) -> None:
        scenes = perfect_scenes()
        report = score(scenes, spoiler="hide")
        # Close still shows 1-2, but hide only cares about the first 3s / hook.
        self.assertEqual(report["pillars"]["spoiler"]["ratio"], 1.0)
        scenes[0]["title"] = "1-2 ALREADY"
        scenes[0]["lines"] = ["1-2 ALREADY"]
        report = score(scenes, spoiler="hide")
        self.assertEqual(report["pillars"]["spoiler"]["ratio"], 0.0)


class MemoryTests(unittest.TestCase):
    def test_round_stores_losers_and_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            viral_audit.remember_round(
                root,
                winner={"punch": "THEY STILL LOST.", "claim": "15 SHOTS", "kind": "volume_upset", "score": 91},
                losers=[{"punch": "AND THEY BLEW IT.", "claim": "15 SHOTS", "kind": "volume_upset", "score": 80}],
                match_id="m1",
                teams=[HOME, AWAY],
                series_id="villa-26-27",
            )
            rows = viral_audit.load_memory(viral_audit.memory_path(root))
            self.assertEqual(len(rows), 2)
            roles = {row["role"] for row in rows}
            self.assertEqual(roles, {"winner", "loser"})
            used = viral_audit.series_used_fingerprints(rows, teams=[HOME], series_id="villa-26-27")
            self.assertEqual(len(used), 2)
            unused = viral_audit.series_used_fingerprints(rows, teams=["Scotland"], series_id="other")
            self.assertEqual(unused, set())

    def test_old_list_memory_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / viral_audit.MEMORY_NAME
            path.write_text('[{"punch": "OLD SLAM.", "match_id": "x", "kind": "waste"}]', encoding="utf-8")
            rows = viral_audit.load_memory(path)
            self.assertEqual(rows[0]["punch"], "OLD SLAM.")
            viral_audit.remember_punch(Path(tmp), "NEW SLAM.", "y", "blowout")
            data = viral_audit.load_memory(viral_audit.memory_path(Path(tmp)))
            punches = {row.get("punch") for row in data}
            self.assertEqual(punches, {"OLD SLAM.", "NEW SLAM."})


class AbHookTests(unittest.TestCase):
    def test_three_variants_are_deterministic_and_distinct(self) -> None:
        bundle, audit = make_bundle(), make_audit()
        first = ab_hooks.generate_hooks(bundle, audit, count=3)
        second = ab_hooks.generate_hooks(bundle, audit, count=3)
        self.assertEqual(len(first), 3)
        self.assertEqual(
            [row["fingerprint"] for row in first],
            [row["fingerprint"] for row in second],
        )
        punches = [row["punch"] for row in first]
        self.assertEqual(len(set(punches)), 3)
        self.assertEqual(len({row["fingerprint"] for row in first}), 3)
        self.assertEqual(first[0]["variant"], 0)

    def test_picker_ships_highest_score_and_skips_series_memory(self) -> None:
        bundle, audit = make_bundle(), make_audit()
        scenes = perfect_scenes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenes_a, ab_a = ab_hooks.pick_winner(
                scenes, SELECTED, bundle, audit,
                output_root=root, clip_report=SKIPPED_CLIP, language="en",
                series_id="villa-26-27",
            )
            self.assertEqual(len(ab_a["candidates"]), 3)
            winner_fp = ab_a["winner"]["fingerprint"]
            viral_audit.remember_round(
                root,
                winner=ab_a["winner"],
                losers=ab_a["losers"],
                match_id="m1",
                teams=[HOME, AWAY],
                series_id="villa-26-27",
            )
            next_bundle = make_bundle("1990002_Aston_Villa_vs_Chelsea")
            _, ab_b = ab_hooks.pick_winner(
                scenes, SELECTED, next_bundle, audit,
                output_root=root, clip_report=SKIPPED_CLIP, language="en",
                series_id="villa-26-27",
            )
            self.assertNotEqual(ab_b["winner"]["fingerprint"], winner_fp)
            punch = next(s["title"] for s in scenes_a if s["visualization"] == "hook_punch")
            self.assertEqual(punch, ab_a["winner"]["punch"])

    def test_apply_hook_overwrites_only_open_cards(self) -> None:
        scenes = perfect_scenes()
        hook = {"lines": ["22 CORNERS"], "punch": "STILL NOTHING.", "kind": "volume_upset",
                "narration_claim": "22 corners", "narration_punch": "Still nothing",
                "hero_number": 22, "visual_language": "number_slam", "numbers": [22]}
        out = ab_hooks.apply_hook(scenes, hook)
        self.assertEqual(out[0]["title"], "22 CORNERS")
        self.assertEqual(out[1]["title"], "STILL NOTHING.")
        self.assertEqual(out[2]["title"], scenes[2]["title"])


class CliTests(unittest.TestCase):
    def test_ab_hooks_default_on_and_unique_flags(self) -> None:
        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertTrue(args.ab_hooks)
        self.assertEqual(args.ab_hook_variants, 3)
        self.assertEqual(args.ab_series_id, "")
        args = parse_args([
            "--auto", "--match-dir", "output/x",
            "--no-ab-hooks", "--ab-hook-variants", "4",
            "--ab-series-id", "villa-26-27",
        ])
        self.assertFalse(args.ab_hooks)
        self.assertEqual(args.ab_hook_variants, 4)
        self.assertEqual(args.ab_series_id, "villa-26-27")

    def test_ab_hook_variants_bounds(self) -> None:
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            parse_args(["--auto", "--match-dir", "output/x", "--ab-hook-variants", "1"])


if __name__ == "__main__":
    unittest.main()
