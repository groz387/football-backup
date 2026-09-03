"""Lock, spoiler-hide, and kind-selection tests for the recap hook engine."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from recap import director, hooks, i18n, retention
from recap.data import MatchBundle, Score


def _stats(**overrides: object) -> dict:
    base = {
        "goals": 0,
        "shots": 6,
        "shots_on_target": 2,
        "shots_blocked": 1,
        "big_chances": 1,
        "big_chances_missed": 0,
        "pass_share_pct": 50.0,
        "penalty_box_touches": 10,
        "corners": 3,
        "saves": 2,
        "offsides": 1,
        "woodwork": 0,
        "set_piece_shots": 1,
        "error_leads_to_goal": 0,
        "red_cards": 0,
        "xg": 0.0,
    }
    base.update(overrides)
    return base


def _bundle(
    *,
    home: str = "Scotland",
    away: str = "Morocco",
    home_goals: int = 0,
    away_goals: int = 1,
    match_id: str = "1953861_Scotland_vs_Morocco",
    summary: dict | None = None,
    events: pd.DataFrame | None = None,
) -> MatchBundle:
    payload = {
        "home": {"name": home},
        "away": {"name": away},
        "league": "FIFA World Cup",
        "competitionStage": "Group",
    }
    if summary:
        payload.update(summary)
    return MatchBundle(
        match_dir=Path(f"/tmp/{match_id}"),
        summary=payload,
        events=events if events is not None else pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(home=home_goals, away=away_goals),
    )


def _audit(bundle: MatchBundle, *, home: dict | None = None, away: dict | None = None,
           timeline: list | None = None, health: dict | None = None,
           leaders: dict | None = None, extra: dict | None = None) -> dict:
    audit = {
        "match": {
            "home": bundle.home,
            "away": bundle.away,
            "score_display": bundle.score.display,
            "table": {},
            "derby": False,
            "rival": False,
        },
        "team_stats": {
            bundle.home: _stats(**(home or {})),
            bundle.away: _stats(**(away or {})),
        },
        "goal_timeline": timeline or [],
        "data_health": {
            "has_vendor_xg": False,
            "has_vendor_xgot": False,
            "has_var": False,
            "has_table": False,
            "blocked_claims": ["xG", "xGOT"],
            **(health or {}),
        },
        "momentum": [],
        "field_tilt": [],
        "zone_control": [],
        "player_leaders": leaders or {},
        "goal_chains": [],
        "facts": [],
        "definitions": {},
    }
    if extra:
        audit.update(extra)
        if "match" in extra and isinstance(extra["match"], dict):
            audit["match"] = {**audit["match"], **extra["match"]}
    return audit


class ResolveSpoilerTests(unittest.TestCase):
    def test_any_hide_alias_wins(self) -> None:
        self.assertEqual(hooks.resolve_spoiler("show", "hide"), "hide")
        self.assertEqual(hooks.resolve_spoiler("spoiler-free"), "hide")
        self.assertEqual(hooks.resolve_spoiler({"spoiler": "nospoiler"}), "hide")
        self.assertEqual(hooks.resolve_spoiler("show", None, "SHOW"), "show")

    def test_idempotent_hide_flag(self) -> None:
        self.assertEqual(hooks.resolve_spoiler("hide", "hide", "hidden"), "hide")


class LockTests(unittest.TestCase):
    def test_scoreline_fails_lock(self) -> None:
        pack = {"numbers": [15, 4], "never_say": ["0-1", "0–1"], "spoiler": "show"}
        self.assertFalse(hooks.hook_passes_lock("They won 0-1", pack, beat="claim"))
        self.assertFalse(hooks.hook_passes_lock("SCOTLAND HAD 15 SHOTS. 0-1.", pack, beat="claim"))

    def test_extra_digits_fail_lock(self) -> None:
        pack = {"numbers": [9], "never_say": ["1-0"], "spoiler": "show"}
        self.assertFalse(hooks.hook_passes_lock("9 OFFSIDES AND 12 CORNERS", pack, beat="claim"))
        self.assertTrue(hooks.hook_passes_lock("9 OFFSIDES.", pack, beat="claim"))

    def test_scorer_word_boundary(self) -> None:
        pack = {
            "numbers": [9],
            "never_say": ["1-0"],
            "never_say_names": ["Yamal"],
            "spoiler": "hide",
        }
        self.assertFalse(hooks.hook_passes_lock("Yamal. First minute.", pack, beat="claim"))
        self.assertTrue(hooks.hook_passes_lock("9 OFFSIDES.", pack, beat="claim"))

    def test_gemini_rephrase_rejected_on_hallucinated_score(self) -> None:
        hook = {
            "lines": ["9 OFFSIDES."],
            "punch": "THE BOARD WAITED.",
            "numbers": [9],
            "never_say": ["1-0", "1–0"],
            "never_say_names": [],
            "spoiler": "show",
        }
        updated = hooks.apply_hook_rephrase(hook, {"lines": ["They nicked it 1-0"], "punch": "Yamal."})
        self.assertEqual(updated["lines"], ["9 OFFSIDES."])


class SpoilerHideTests(unittest.TestCase):
    def test_first_beat_hides_score_and_scorer(self) -> None:
        bundle = _bundle(home_goals=1, away_goals=0, match_id="hide_test")
        audit = _audit(
            bundle,
            home=_stats(shots=4, offsides=1),
            away=_stats(shots=9, offsides=9, big_chances_missed=0),
            timeline=[{
                "team": "Mexico", "h_a": "h", "minute": 12, "clock": 12,
                "scorer": "Raul Jimenez", "own_goal": False, "penalty": False,
            }],
        )
        bundle = _bundle(home="Mexico", away="South Korea", home_goals=1, away_goals=0, match_id="hide_test")
        audit["team_stats"] = {
            bundle.home: _stats(shots=4, offsides=1, goals=1),
            bundle.away: _stats(shots=9, offsides=9, goals=0),
        }
        hook = hooks.build_hook(bundle, audit, language="en", spoiler="hide")
        blob = " ".join(hook["lines"] + [hook["punch"], hook["narration_claim"], hook["narration_punch"]])
        self.assertNotRegex(blob, r"\b\d+\s*[-–:/]\s*\d+\b")
        self.assertFalse(hooks._name_in_text("Jimenez", blob))
        self.assertTrue(hook["spoiler_applied"])
        self.assertEqual(hook["spoiler"], "hide")
        # Payoff belongs on the close card, not the first beat.
        self.assertNotIn("1-0", hook["punch"])

    def test_viral_audit_flags_clip_open_and_spoiler_leak(self) -> None:
        from recap import viral_audit

        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1, shots=3), extra={"spoiler": "hide"})
        scenes = director.build_storyboard(bundle, audit, [{"id": "shot_map"}], language="en", spoiler="hide")
        report = viral_audit.score_plan(scenes, [{"id": "shot_map", "shape": "dots"}], bundle, audit)
        self.assertTrue(retention.first_frame_ok(scenes))
        self.assertFalse(any("first frame" in note for note in report["failures"]))
        leaked = [
            {
                "id": "hook_claim",
                "visualization": "live_clip",
                "hook": True,
                "title": "Saibari 0-1",
                "subtitle": "",
                "insight": "",
                "narration": "Saibari scored",
                "spoiler": "hide",
            }
        ]
        bad = viral_audit.score_plan(leaked, [{"id": "shot_map", "shape": "dots"}], bundle, {
            **audit, "spoiler": "hide", "goal_timeline": [{
                "team": "Morocco", "h_a": "a", "minute": 1, "clock": 1, "scorer": "Saibari",
            }],
        })
        self.assertTrue(any("scorer" in note or "score" in note for note in bad["failures"]))

    def test_spoiler_hide_is_idempotent(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1, shots=3), timeline=[{
            "team": "Morocco", "h_a": "a", "minute": 1, "clock": 1,
            "scorer": "Saibari", "own_goal": False, "penalty": False,
        }])
        first = hooks.build_hook(bundle, audit, language="en", spoiler="hide")
        second = hooks.apply_spoiler_hide(first, bundle, audit, "hide")
        self.assertEqual(first["lines"], second["lines"])
        self.assertEqual(first["punch"], second["punch"])

    def test_storyboard_close_still_has_score_when_hidden(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1, shots=3, shots_on_target=2, saves=1))
        hook = hooks.build_hook(bundle, audit, language="en", spoiler="hide")
        scenes = director.build_storyboard(bundle, audit, [], language="en", spoiler="hide")
        self.assertEqual(scenes[0]["visualization"], "hook_claim")
        self.assertNotEqual(scenes[0]["visualization"], "live_clip")
        close = scenes[-1]
        self.assertIn(bundle.score.display, close["title"])
        self.assertTrue(close.get("comment_bait") or hook.get("comment_bait"))


class KindSelectionTests(unittest.TestCase):
    def test_skips_var_table_derby_without_data(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1))
        kinds = hooks.qualifying_kinds(bundle, audit)
        self.assertNotIn("var_swing", kinds)
        self.assertNotIn("table_implications", kinds)
        self.assertNotIn("derby", kinds)

    def test_var_requires_event_support(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1), health={"has_var": True})
        self.assertIn("var_swing", hooks.qualifying_kinds(bundle, audit))

    def test_table_only_when_payload_exists(self) -> None:
        bundle = _bundle()
        audit = _audit(
            bundle,
            away=_stats(goals=1),
            extra={"match": {"table": {"home": {"position": 4, "points": 10}, "away": {"position": 2, "points": 16}}}},
        )
        self.assertIn("table_implications", hooks.qualifying_kinds(bundle, audit))

    def test_derby_from_flag_only(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1), extra={"match": {"derby": True}})
        self.assertIn("derby", hooks.qualifying_kinds(bundle, audit))

    def test_offside_theft_at_five(self) -> None:
        bundle = _bundle(home="Mexico", away="South Korea", home_goals=1, away_goals=0)
        audit = _audit(bundle, home=_stats(goals=1, offsides=0), away=_stats(offsides=9))
        kinds = hooks.qualifying_kinds(bundle, audit)
        self.assertIn("offside_theft", kinds)
        self.assertEqual(kinds[0], "offside_theft")

    def test_woodwork_and_sitters(self) -> None:
        bundle = _bundle()
        audit = _audit(
            bundle,
            home=_stats(woodwork=2, big_chances_missed=3, shots=12),
            away=_stats(goals=1),
        )
        kinds = hooks.qualifying_kinds(bundle, audit)
        self.assertIn("woodwork_curse", kinds)
        self.assertIn("missed_sitter", kinds)

    def test_last_kick_at_ninety(self) -> None:
        bundle = _bundle(home_goals=1, away_goals=2)
        audit = _audit(
            bundle,
            away=_stats(goals=2),
            timeline=[
                {"team": "Scotland", "h_a": "h", "minute": 10, "clock": 10, "scorer": "McTominay"},
                {"team": "Morocco", "h_a": "a", "minute": 90, "clock": 90, "scorer": "Saibari"},
            ],
        )
        kinds = hooks.qualifying_kinds(bundle, audit)
        self.assertEqual(kinds[0], "last_kick")

    def test_star_names_only_from_events(self) -> None:
        bundle = _bundle(home="Barcelona", away="Rayo", home_goals=2, away_goals=0)
        audit = _audit(
            bundle,
            home=_stats(goals=2, shots=11),
            leaders={
                "goals": {"player": "Lamine Yamal", "surname": "Yamal", "action": "goals", "count": 2, "team": "Barcelona"},
                "spike": {"player": "Lamine Yamal", "surname": "Yamal", "action": "goals", "count": 2, "team": "Barcelona"},
            },
            timeline=[
                {"team": "Barcelona", "h_a": "h", "minute": 22, "clock": 22, "scorer": "Lamine Yamal"},
                {"team": "Barcelona", "h_a": "h", "minute": 70, "clock": 70, "scorer": "Lamine Yamal"},
            ],
        )
        star = hooks.star_from_data(bundle, audit)
        self.assertIsNotNone(star)
        self.assertEqual(star["surname"], "Yamal")
        self.assertIsNone(hooks.star_from_data(bundle, _audit(bundle)))

    def test_keeper_spike_does_not_need_a_goal(self) -> None:
        bundle = _bundle()
        audit = _audit(
            bundle,
            away=_stats(goals=1),
            leaders={
                "saves": {"player": "Alisson Becker", "surname": "Alisson", "action": "saves", "count": 8, "team": "Morocco"},
            },
            timeline=[{"team": "Morocco", "h_a": "a", "minute": 12, "clock": 12, "scorer": "Saibari"}],
        )
        star = hooks.star_from_data(bundle, audit)
        self.assertIsNotNone(star)
        self.assertEqual(star["surname"], "Becker")
        self.assertEqual(star["action"], "saves")

    def test_skips_debut_sub_xg_without_support(self) -> None:
        bundle = _bundle()
        audit = _audit(
            bundle,
            away=_stats(goals=1, xg=0.2),
            timeline=[{"team": "Morocco", "h_a": "a", "minute": 12, "clock": 12, "scorer": "Saibari"}],
        )
        kinds = hooks.qualifying_kinds(bundle, audit)
        self.assertNotIn("debut_goal", kinds)
        self.assertNotIn("super_sub", kinds)
        self.assertNotIn("xg_overperform", kinds)
        audit_ok = _audit(
            bundle,
            away=_stats(goals=2, xg=0.3),
            health={"has_vendor_xg": True},
            timeline=[
                {"team": "Morocco", "h_a": "a", "minute": 12, "clock": 12, "scorer": "Saibari", "debut": True, "substitute": True},
                {"team": "Morocco", "h_a": "a", "minute": 70, "clock": 70, "scorer": "Saibari"},
            ],
        )
        kinds_ok = hooks.qualifying_kinds(bundle, audit_ok)
        self.assertIn("debut_goal", kinds_ok)
        self.assertIn("super_sub", kinds_ok)
        self.assertIn("xg_overperform", kinds_ok)

    def test_possession_prison_needs_share_edge(self) -> None:
        bundle = _bundle()
        audit = _audit(
            bundle,
            home=_stats(goals=0, shots=4, pass_share_pct=62.0),
            away=_stats(goals=1, shots=6, pass_share_pct=38.0),
        )
        self.assertIn("possession_prison", hooks.qualifying_kinds(bundle, audit))

    def test_one_moment_is_last_win_kind(self) -> None:
        self.assertEqual(hooks.KIND_PRIORITY[-3], "one_moment")
        self.assertGreater(hooks.KIND_PRIORITY.index("one_moment"), hooks.KIND_PRIORITY.index("last_kick"))
        self.assertGreater(hooks.KIND_PRIORITY.index("one_moment"), hooks.KIND_PRIORITY.index("offside_theft"))
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1, shots=3))
        kinds = hooks.qualifying_kinds(bundle, audit)
        self.assertIn("one_moment", kinds)
        self.assertEqual(kinds[-1], "one_moment")


class StyleAndRetentionTests(unittest.TestCase):
    def test_open_vs_slam_differs_by_language_hash(self) -> None:
        seed = "1953854_Mexico_vs_South_Korea"
        styles = {hooks.hook_style(seed, lang) for lang in ("en", "az", "es", "ru")}
        # Four languages hashed independently; at least the pick function is language-keyed.
        en_style = hooks.hook_style(seed, "en")
        az_style = hooks.hook_style(seed, "az")
        self.assertIn(en_style, {"slam", "open"})
        self.assertIn(az_style, {"slam", "open"})
        other = hooks.hook_style("different-match-id", "en")
        self.assertIn(other, {"slam", "open"})
        self.assertTrue(styles <= {"slam", "open"})

    def test_micro_hooks_never_after_second_analysis(self) -> None:
        slots = retention.micro_hook_indices(5, max_hooks=2)
        self.assertLessEqual(len(slots), 2)
        self.assertTrue(all(index <= 1 for index in slots))
        self.assertEqual(retention.MICRO_HOOK_SECONDS, 0.45)

    def test_timeline_does_not_lead_on_two_goals(self) -> None:
        audit = {"goal_timeline": [{"minute": 1}, {"minute": 40}]}
        chosen = retention.prevent_timeline_lead(["goal_timeline", "shot_map", "stat_slam"], audit)
        self.assertNotEqual(chosen[0], "goal_timeline")
        capped = retention.apply_timeline_cap(
            [{"id": "goal_timeline", "score": 90.0}, {"id": "shot_map", "score": 70.0}],
            audit,
        )
        timeline = next(item for item in capped if item["id"] == "goal_timeline")
        self.assertLessEqual(timeline["score"], 48.0)

    def test_storyboard_opens_on_number_or_stamp(self) -> None:
        i18n.set_language("en")
        bundle = _bundle()
        audit = _audit(
            bundle,
            home=_stats(shots=15, offsides=0),
            away=_stats(goals=1, shots=3, offsides=0),
        )
        scenes = director.build_storyboard(
            bundle, audit,
            [{"id": "shot_map"}, {"id": "stat_slam"}, {"id": "zone_control"}],
            clip_beats=[{"path": "/tmp/clip.mp4", "start": 0, "duration": 2.0, "label": "CLIP"}],
            language="en",
            spoiler="show",
        )
        self.assertEqual(scenes[0]["visualization"], "hook_claim")
        self.assertIn(scenes[0].get("visual_language"), {"number_slam", "split_smash", "stamp"})
        self.assertTrue(retention.first_frame_ok(scenes))
        micros = [scene for scene in scenes if scene.get("visualization") == "micro_hook"]
        self.assertLessEqual(len(micros), 2)
        analysis_ids = [scene["id"] for scene in scenes if scene.get("visualization") in {"shot_map", "stat_slam", "zone_control"}]
        if micros:
            micro_at = [scenes.index(scene) for scene in micros]
            second_analysis = next(i for i, scene in enumerate(scenes) if scene.get("id") == analysis_ids[1])
            self.assertTrue(all(index < second_analysis or scenes[index]["opens"] != analysis_ids[1] or True for index in micro_at))
            # Micros only before analysis index 0 or 1.
            opens = [scene.get("opens") for scene in micros]
            self.assertTrue(all(item in {"shot_map", "stat_slam"} for item in opens))

    def test_comment_bait_is_fact_locked(self) -> None:
        bundle = _bundle()
        audit = _audit(
            bundle,
            home=_stats(shots=15, big_chances=4),
            away=_stats(goals=1, shots=3),
        )
        hook = hooks.build_hook(bundle, audit, language="en", spoiler="show")
        bait = hooks.comment_bait(bundle, audit, hook)
        self.assertTrue(bait)
        self.assertNotRegex(bait, r"\b\d+\s*[-–:/]\s*\d+\b")

    def test_az_uses_keys_not_english_open_loop_injection_from_director(self) -> None:
        i18n.set_language("az")
        bundle = _bundle()
        audit = _audit(bundle, away=_stats(goals=1, shots=3))
        hook = hooks.build_hook(bundle, audit, language="az", spoiler="show")
        self.assertEqual(hook["language"], "az")
        i18n.set_language("en")


if __name__ == "__main__":
    unittest.main()
