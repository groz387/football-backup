"""Polish pass: black ink, no burned captions, AZ copy, coords, interactive apply."""

from __future__ import annotations

import argparse
import ast
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recap import audit, director, hooks, i18n, locales, theme  # noqa: E402
from recap.data import MatchBundle, Score  # noqa: E402
from recap.locales import az as az_mod  # noqa: E402


def _stats(**overrides: object) -> dict:
    base = {
        "goals": 0, "shots": 8, "shots_on_target": 2, "shots_blocked": 1,
        "big_chances": 1, "big_chances_missed": 0, "pass_share_pct": 50.0,
        "penalty_box_touches": 10, "corners": 3, "saves": 2, "offsides": 1,
        "woodwork": 0, "set_piece_shots": 1, "error_leads_to_goal": 0,
        "red_cards": 0, "xg": 0.0, "pass_attempts": 200, "passes_completed": 160,
    }
    base.update(overrides)
    return base


def _bundle(**kwargs: object) -> MatchBundle:
    return MatchBundle(
        match_dir=Path("/tmp/match"),
        summary={"home": {"name": "Barcelona"}, "away": {"name": "Rayo Vallecano"}},
        events=pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(home=1, away=0),
        **{k: v for k, v in kwargs.items() if k in MatchBundle.__dataclass_fields__},
    )


def _audit_for(bundle: MatchBundle, health: dict | None = None) -> dict:
    return {
        "match": {
            "home": bundle.home, "away": bundle.away, "score_display": bundle.score.display,
            "table": {}, "derby": False, "rival": False, "score_qualifier": "",
        },
        "team_stats": {bundle.home: _stats(shots=22, goals=1), bundle.away: _stats(shots=8, goals=0)},
        "goal_timeline": [{"minute": 67, "scorer": "Yamal", "team": bundle.home}],
        "momentum": [],
        "field_tilt": [],
        "zone_control": [],
        "goal_chains": [],
        "touch_heatmap": {},
        "press_trap": {},
        "duels": {},
        "aerials": {},
        "halftime_split": {},
        "shots": [],
        "data_health": health or {
            "has_precise_coordinates": False,
            "coordinate_source": "reconstructed",
            "blocked_claims": ["xG"],
            "pass_rows": 400,
            "shot_rows": 30,
            "has_goal_mouth_coordinates": False,
        },
        "facts": [],
        "bench_impact": {"subs": []},
        "player_leaders": {"spike": {"surname": "Yamal", "player": "Lamine Yamal", "count": 4, "action": "shots"}},
        "hook": {},
        "spoiler": "show",
        "definitions": {},
    }


class PolishCopyTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language("en")
        locales.clear_cache()
        i18n._PACKS.clear()

    def test_az_hook_and_visual_keys_are_native(self) -> None:
        englishish = (
            "the tape", "game gone", "watch the turn", "changes on the tape",
            "shots on the clock", "owned the air", "then ", "drop your",
        )
        keys = [
            "hook_claim_lastkick_0", "hook_claim_lastkick_1", "hook_punch_over_2",
            "hook_bait_motm", "hook_bait_robbery", "hook_bait_bottle",
            "hook_shock_90", "hook_shock_game_over", "hook_shock_watch_turn",
            "vis_clock_title", "vis_bench_title", "vis_split_title",
            "vis_lanes_title", "vis_duel_title", "vis_air_title",
        ]
        for key in keys:
            value = az_mod.UI[key]
            low = value.lower()
            self.assertTrue(value.strip(), key)
            for needle in englishish:
                self.assertNotIn(needle, low, f"{key} still English: {value}")

    def test_visual_copy_uses_i18n_not_hardcoded_english(self) -> None:
        i18n.set_language("az")
        bundle = MatchBundle(
            match_dir=Path("/tmp/m"),
            summary={"home": {"name": "Barcelona"}, "away": {"name": "Rayo Vallecano"}},
            events=pd.DataFrame(), passes=pd.DataFrame(), shots=pd.DataFrame(),
            touches=pd.DataFrame(), players=pd.DataFrame(), score=Score(home=1, away=0),
        )
        audit_doc = _audit_for(bundle)
        audit_doc["halftime_split"] = {
            "ready": True,
            "first": {"home_shots": 20, "away_shots": 4},
            "second": {"home_shots": 17, "away_shots": 6},
        }
        copy = director._visual_copy(bundle, audit_doc, "halftime_split")
        self.assertNotIn("THEN", copy["title"].upper())
        self.assertIn("24", copy["title"])
        self.assertIn("23", copy["title"])
        bench = director._visual_copy(bundle, audit_doc, "bench_impact")
        self.assertNotRegex(bench["title"], r"CHANGES ON THE TAPE")

    def test_scrub_hooks_and_respects_user_lock(self) -> None:
        scenes = [
            {"id": "hook_claim", "hook": True, "title": "GAME GONE", "kicker": "THE TAPE",
             "narration": "watch the turn", "lines": ["GAME GONE"]},
            {"id": "hook_claim_custom", "hook": True, "title": "GAME GONE", "user_locked": True,
             "narration": "GAME GONE", "lines": ["GAME GONE"]},
        ]
        out = i18n.scrub_english_leftovers(scenes, "az")
        self.assertNotEqual(out[0]["title"], "GAME GONE")
        self.assertEqual(out[1]["title"], "GAME GONE")

    def test_apply_shock_and_bait(self) -> None:
        scenes = [
            {"id": "hook_claim", "visualization": "hook_claim", "title": "old", "lines": ["old"], "narration": "old"},
            {"id": "hook_punch", "visualization": "hook_punch", "title": "old", "lines": ["old"], "narration": "old"},
            {"id": "micro_hook_0", "visualization": "micro_hook", "title": "old", "lines": ["old"], "narration": "old"},
            {"id": "close", "visualization": "close", "title": "FT", "insight": "score", "narration": "done", "comment_bait": ""},
        ]
        updated = hooks.apply_cli_copy(
            scenes, hook_texts=["90 DƏQİQƏ", "OYUN QAPANDI", "DÖNÜŞƏ BAX"], bait_text="Yamal MOTM idi?",
        )
        by_id = {s["id"]: s for s in updated}
        self.assertEqual(by_id["hook_claim"]["title"], "90 DƏQİQƏ")
        self.assertEqual(by_id["hook_punch"]["title"], "OYUN QAPANDI")
        self.assertEqual(by_id["micro_hook_0"]["title"], "DÖNÜŞƏ BAX")
        self.assertTrue(by_id["hook_claim"]["user_locked"])
        self.assertEqual(by_id["close"]["comment_bait"], "Yamal MOTM idi?")
        self.assertIn("Yamal MOTM idi?", by_id["close"]["narration"])

    def test_lock_replaces_english_hook_when_language_is_az(self) -> None:
        bundle = MatchBundle(
            match_dir=Path("/tmp/m"),
            summary={"home": {"name": "Barcelona"}, "away": {"name": "Rayo Vallecano"}},
            events=pd.DataFrame(), passes=pd.DataFrame(), shots=pd.DataFrame(),
            touches=pd.DataFrame(), players=pd.DataFrame(), score=Score(home=1, away=0),
        )
        audit_doc = _audit_for(bundle)
        i18n.set_language("az")
        scenes = [
            {"id": "hook_claim", "visualization": "hook_claim", "hook": True,
             "title": "GAME GONE", "lines": ["GAME GONE"], "narration": "GAME GONE"},
            {"id": "hook_punch", "visualization": "hook_punch", "hook": True,
             "title": "WATCH THE TURN", "lines": ["WATCH THE TURN"], "narration": "WATCH THE TURN"},
            {"id": "close", "visualization": "close", "comment_bait": "was yamal motm?",
             "insight": "1-0", "narration": "Barcelona 1-0."},
        ]
        locked = director.lock_hook_cards(scenes, bundle, audit_doc, language="az")
        claim = next(s for s in locked if s["visualization"] == "hook_claim")
        punch = next(s for s in locked if s["visualization"] == "hook_punch")
        close = next(s for s in locked if s["visualization"] == "close")
        self.assertFalse(i18n.looks_english(claim["title"]))
        self.assertFalse(i18n.looks_english(punch["title"]))
        self.assertNotEqual(claim["title"], "GAME GONE")
        self.assertFalse(i18n.looks_english(str(close.get("comment_bait") or "")))

    def test_user_locked_survives_lock(self) -> None:
        bundle = MatchBundle(
            match_dir=Path("/tmp/m"),
            summary={"home": {"name": "Barcelona"}, "away": {"name": "Rayo Vallecano"}},
            events=pd.DataFrame(), passes=pd.DataFrame(), shots=pd.DataFrame(),
            touches=pd.DataFrame(), players=pd.DataFrame(), score=Score(home=1, away=0),
        )
        scenes = [{
            "id": "hook_claim", "visualization": "hook_claim", "hook": True,
            "title": "Donushe Bax", "lines": ["Donushe Bax"], "narration": "Donushe Bax",
            "user_locked": True,
        }]
        locked = director.lock_hook_cards(scenes, bundle, _audit_for(bundle), language="az")
        self.assertEqual(locked[0]["title"], "Donushe Bax")


class CoordinateQualityTests(unittest.TestCase):
    def test_classify_reconstructed_centroids(self) -> None:
        shots = pd.read_csv(ROOT / "output/1993920_Barcelona_vs_Rayo_Vallecano/shots.csv")
        quality = audit.classify_coordinates(audit._xy_pairs(shots))
        self.assertEqual(quality["coordinate_source"], "reconstructed")
        self.assertFalse(quality["has_precise_coordinates"])

    def test_classify_whoscored_tracking(self) -> None:
        shots = pd.read_csv(ROOT / "output/1953861_Scotland_vs_Morocco/shots.csv")
        quality = audit.classify_coordinates(audit._xy_pairs(shots))
        self.assertEqual(quality["coordinate_source"], "whoscored")
        self.assertTrue(quality["has_precise_coordinates"])
        self.assertGreaterEqual(quality["unique_xy"], 8)

    def test_reconstructed_skips_shot_map(self) -> None:
        bundle = MatchBundle(
            match_dir=Path("/tmp/m"),
            summary={"home": {"name": "Barcelona"}, "away": {"name": "Rayo Vallecano"}},
            events=pd.DataFrame(), passes=pd.DataFrame(), shots=pd.DataFrame(),
            touches=pd.DataFrame(), players=pd.DataFrame(), score=Score(home=1, away=0),
        )
        audit_doc = _audit_for(bundle, {
            "has_precise_coordinates": False,
            "coordinate_source": "reconstructed",
            "blocked_claims": ["xG"],
            "pass_rows": 400,
            "shot_rows": 30,
            "has_goal_mouth_coordinates": False,
        })
        cands = {c["id"]: c for c in director.visualization_candidates(bundle, audit_doc)}
        self.assertFalse(cands["shot_map"]["available"])
        self.assertFalse(cands["touch_heatmap"]["available"])
        self.assertFalse(cands["pass_network"]["available"])
        self.assertFalse(cands["bench_impact"]["available"])

    def test_precise_coords_boost_maps(self) -> None:
        bundle = MatchBundle(
            match_dir=Path("/tmp/m"),
            summary={"home": {"name": "Scotland"}, "away": {"name": "Morocco"}},
            events=pd.DataFrame(), passes=pd.DataFrame(), shots=pd.DataFrame(),
            touches=pd.DataFrame(), players=pd.DataFrame(), score=Score(home=0, away=1),
        )
        audit_doc = _audit_for(bundle, {
            "has_precise_coordinates": True,
            "coordinate_source": "whoscored",
            "blocked_claims": ["xG"],
            "pass_rows": 400,
            "shot_rows": 18,
            "has_goal_mouth_coordinates": True,
        })
        audit_doc["team_stats"] = {
            bundle.home: _stats(shots=12, shots_on_target=4, pass_attempts=300),
            bundle.away: _stats(shots=9, shots_on_target=5, pass_attempts=280, goals=1),
        }
        cands = {c["id"]: c for c in director.visualization_candidates(bundle, audit_doc)}
        self.assertTrue(cands["shot_map"]["available"])
        self.assertIn("WhoScored", cands["shot_map"]["reason"])
        self.assertGreater(cands["shot_map"]["score"], 40)
        selected, _ = director.select_visualizations(
            bundle, audit_doc, 3, None, "", target_seconds=40,
        )
        ids = [item["id"] for item in selected]
        self.assertIn("shot_map", ids)


class ThemeAndCliTests(unittest.TestCase):
    def test_ink_is_pitch_black(self) -> None:
        self.assertEqual(theme.INK, "#000000")
        design = theme.match_design("Barcelona", "Rayo Vallecano")
        self.assertEqual(design["ink"], "#000000")

    def test_graphs_does_not_import_scenes(self) -> None:
        source = ast.parse((ROOT / "recap/graphs.py").read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(source):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        self.assertFalse(any("scenes" in name.split(".") for name in imported))

    def test_burn_captions_default_false_and_hook_text_flag(self) -> None:
        from video_pipeline import parse_args

        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertFalse(args.burn_captions)
        help_parser = argparse.ArgumentParser()
        # parse_args --help is tested via flags existing
        args2 = parse_args(["--auto", "--match-dir", "output/x", "--hook-text", "90 Minute", "--bait-text", "MOTM?"])
        self.assertEqual(args2.hook_text, ["90 Minute"])
        self.assertEqual(args2.bait_text, "MOTM?")

    def test_translate_script_includes_hooks(self) -> None:
        source = (ROOT / "recap/director.py").read_text(encoding="utf-8")
        start = source.index("def translate_script")
        chunk = source[start: start + 2500]
        self.assertNotIn("if not scene.get(\"hook\")", chunk)
        self.assertIn("INCLUDE hook_claim", chunk)
        self.assertIn("comment_bait", chunk)


if __name__ == "__main__":
    unittest.main()
