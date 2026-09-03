"""Studio farm: curse bookends, kit clash, livescore parse, ElevenLabs mock, source health."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from recap import culture, farm, ingest, theme
from recap.config import eleven_style, style_voice_settings
from recap.data import MatchBundle, Score
from recap.elevenlabs_tts import ElevenLabsError, reset_caches, search_voice_id, synthesize
from recap.studio_api import cli_argv_for
from video_pipeline import parse_args

ROOT = Path(__file__).resolve().parents[1]
BARCA = ROOT / "output" / "1993920_Barcelona_vs_Rayo_Vallecano"
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"


def _bundle(home="Barcelona", away="Elche", score=(5, 1)) -> MatchBundle:
    return MatchBundle(
        match_dir=Path("/tmp/m"),
        summary={"home": {"name": home}, "away": {"name": away}},
        events=pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(home=score[0], away=score[1]),
    )


def _audit(bundle: MatchBundle) -> dict:
    return {
        "match": {"home": bundle.home, "away": bundle.away, "score_display": bundle.score.display},
        "team_stats": {
            bundle.home: {"shots": 22, "goals": bundle.score.home, "big_chances": 5},
            bundle.away: {"shots": 4, "goals": bundle.score.away, "big_chances": 1},
        },
        "data_health": {"has_precise_coordinates": False, "coordinate_source": "reconstructed", "blocked_claims": []},
        "goal_timeline": [],
        "spoiler": "show",
    }


def _scenes(hook: str, body: str, bait: str) -> list[dict]:
    return [
        {"id": "hook_claim", "visualization": "hook_claim", "title": hook, "narration": hook, "insight": ""},
        {"id": "stats", "visualization": "standard_stats", "title": "Shots", "narration": body, "insight": body},
        {
            "id": "close", "visualization": "close", "title": "FT",
            "narration": f"Barcelona won 5-1. {bait}", "comment_bait": bait, "insight": bait,
        },
    ]


class CurseBookendTests(unittest.TestCase):
    def test_lock_keeps_curses_on_hook_and_close_only(self):
        bundle = _bundle()
        audit = _audit(bundle)
        scenes = _scenes(
            "Barcelona Elchenin götünə ağac soxdu",
            "Barcelona the tape was a fucking siege with 22 shots",
            "Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?",
        )
        locked = culture.lock_bookends(scenes, bundle, audit, "az")
        self.assertTrue(culture.contains_curse(locked[0]["narration"], "az"))
        self.assertFalse(culture.contains_curse(locked[1]["narration"], "az"))
        self.assertFalse(culture.contains_curse(locked[1]["title"], "az"))
        self.assertTrue(culture.contains_curse(locked[2]["comment_bait"], "az"))
        report = culture.inspect_bookends(locked, "az")
        self.assertTrue(report["clean_body"])
        self.assertTrue(any(h["bookend"] for h in report["hits"]))

    def test_offline_pool_plants_az_register(self):
        bundle = _bundle()
        audit = _audit(bundle)
        scenes = _scenes("BARCELONA HAD 22 SHOTS", "Pass share favoured Barcelona.", "Who was MOTM?")
        locked = culture.lock_bookends(scenes, bundle, audit, "az")
        self.assertTrue(culture.contains_curse(locked[0]["narration"], "az"))
        self.assertTrue(culture.contains_curse(locked[2]["comment_bait"], "az"))
        self.assertFalse(culture.contains_curse(locked[1]["narration"], "az"))

    def test_en_is_pub_pundit_not_az_calque(self):
        bundle = _bundle("Liverpool", "Aston Villa", (2, 2))
        hook = culture.offline_hook(bundle, _audit(bundle), "en")
        self.assertTrue(culture.contains_curse(hook, "en"))
        self.assertNotIn("göt", hook.lower())
        self.assertNotIn("gijdıllax", hook.lower())

    def test_kids_mode_strips_curses(self):
        bundle = _bundle()
        scenes = _scenes(
            "Barcelona Elchenin götünə ağac soxdu",
            "Clean analysis.",
            "Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?",
        )
        locked = culture.lock_bookends(scenes, bundle, _audit(bundle), "az", kids=True)
        self.assertFalse(culture.contains_curse(locked[0]["narration"], "az"))
        self.assertFalse(culture.contains_curse(locked[2]["comment_bait"], "az"))

    def test_does_not_invent_score_in_offline_hook(self):
        bundle = _bundle()
        hook = culture.offline_hook(bundle, _audit(bundle), "az")
        self.assertNotRegex(hook, r"\b5\s*[-–]\s*1\b")


class ColorClashTests(unittest.TestCase):
    def tearDown(self):
        theme.set_team_colors(None, None)
        theme.set_team_kind("national")

    def test_barcelona_burgundy_gold(self):
        theme.set_team_kind("club")
        ident = theme.team_identity("Barcelona")
        self.assertEqual(ident["primary"].lower(), "#9e0041")
        self.assertEqual(ident["secondary"].lower(), "#ffd100")

    def test_clash_away_uses_secondary(self):
        theme.set_team_kind("club")
        # Two red shirts: Liverpool vs Arsenal.
        picked = theme.pick_kit_colors("Liverpool", "Arsenal")
        self.assertTrue(picked["clash"])
        self.assertTrue(picked["away_used_secondary"] or picked["home_used_secondary"])
        self.assertGreaterEqual(theme.contrast_ratio(picked["home"], picked["away"]), 2.0)

    def test_colors_module_override_skips_clash_swap(self):
        from recap import colors as colors_mod

        kit = colors_mod.kit_for("FC Barcelona", "club")
        self.assertEqual(kit.primary, colors_mod.BARCA_BURGUNDY)
        self.assertEqual(kit.secondary, colors_mod.BARCA_GOLD)
        clash = colors_mod.resolve_pair("Liverpool", "Arsenal", kind="club")
        self.assertTrue(clash.conflict)
        self.assertTrue(clash.home.used_secondary or clash.away.used_secondary)
        forced = colors_mod.resolve_pair(
            "Liverpool", "Arsenal", kind="club",
            override_home="#111111", override_away="#eeeeee",
        )
        self.assertFalse(forced.conflict)
        self.assertEqual(forced.home.fill, "#111111")
        self.assertEqual(forced.away.fill, "#eeeeee")

    def test_cli_override_skips_auto(self):
        report = farm.apply_auto_colors("Barcelona", "Real Madrid", override=("#111111", "#eeeeee"))
        self.assertEqual(report["source"], "cli")
        self.assertEqual(report["home"], "#111111")


class LivescoreParseTests(unittest.TestCase):
    def test_parses_laliga_slug(self):
        url = "https://www.livescore.com/en/football/spain/laliga/barcelona-vs-rayo-vallecano/"
        parsed = ingest.parse_livescore_url(url)
        self.assertEqual(parsed["home"], "Barcelona")
        self.assertEqual(parsed["away"], "Rayo Vallecano")
        self.assertEqual(parsed["country"], "Spain")
        self.assertIn("laliga", (parsed["competition"] or "").lower())
        self.assertIsNone(parsed["score_home"])

    def test_parses_score_and_date(self):
        url = "https://www.livescore.com/en/football/2026-08-31/barcelona-vs-elche/5-1/"
        parsed = ingest.parse_livescore_url(url)
        self.assertEqual(parsed["home"], "Barcelona")
        self.assertEqual(parsed["away"], "Elche")
        self.assertEqual(parsed["date"], "2026-08-31")
        self.assertEqual(parsed["score_home"], 5)
        self.assertEqual(parsed["score_away"], 1)

    def test_rejects_non_livescore(self):
        with self.assertRaises(ValueError):
            ingest.parse_livescore_url("https://whoscored.com/matches/1")

    def test_finds_local_barca_export(self):
        if not BARCA.is_dir():
            self.skipTest("barca export missing")
        fixture = ingest.parse_livescore_url(
            "https://www.livescore.com/en/football/spain/laliga/barcelona-vs-rayo-vallecano/"
        )
        found = ingest.find_local_match(fixture, ROOT / "output")
        self.assertIsNotNone(found)
        self.assertIn("Barcelona", found.name)


class SourceHealthTests(unittest.TestCase):
    def test_reconstructed_laliga_import_is_not_full(self):
        if not BARCA.is_dir():
            self.skipTest("barca export missing")
        health = ingest.health_check_export(BARCA)
        self.assertTrue(health["ok"])
        self.assertEqual(health["coordinate_source"], "reconstructed")
        self.assertFalse(health["full"])
        self.assertFalse(health["has_precise_coordinates"])

    def test_scotland_whoscored_is_full_tracking(self):
        if not SCOTLAND.is_dir():
            self.skipTest("scotland export missing")
        health = ingest.health_check_export(SCOTLAND)
        self.assertTrue(health["ok"])
        self.assertEqual(health["coordinate_source"], "whoscored")
        self.assertTrue(health["has_precise_coordinates"])
        self.assertTrue(health["full"])
        self.assertGreaterEqual(health["event_rows"], 400)
        self.assertGreaterEqual(health.get("pass_rows") or 0, 100)

        from recap import resolve_match

        typed = resolve_match.assess_source(SCOTLAND)
        self.assertTrue(typed.healthy)
        self.assertTrue(typed.full_events)
        self.assertTrue(typed.has_precise_coordinates)
        self.assertFalse(typed.invented_coordinates)

        reconstructed = resolve_match.assess_source(BARCA)
        self.assertFalse(reconstructed.healthy)
        self.assertEqual(reconstructed.coordinate_source, "reconstructed")
        self.assertFalse(reconstructed.invented_coordinates)

    def test_resolve_uses_local_whoscored_folder_without_inventing(self):
        if not BARCA.is_dir():
            self.skipTest("barca export missing")
        result = ingest.resolve(
            livescore_url="https://www.livescore.com/en/football/spain/laliga/barcelona-vs-rayo-vallecano/",
            output_root=ROOT / "output",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["match_dir"]).name, BARCA.name)
        self.assertEqual(result["coordinate_source"], "reconstructed")
        stubs = {row["name"]: row["status"] for row in result["adapters"]}
        self.assertEqual(stubs.get("sofascore"), "stub")
        self.assertEqual(stubs.get("fotmob"), "stub")
        self.assertEqual(stubs.get("understat"), "stub")

    def test_missing_fixture_is_honest(self):
        result = ingest.resolve(
            livescore_url="https://www.livescore.com/en/football/az/prem/qarabag-vs-imaginarytown/",
            output_root=ROOT / "output",
        )
        self.assertFalse(result["ok"])
        self.assertIn("Drop", result["drop_hint"])


class ElevenMockTests(unittest.TestCase):
    def tearDown(self):
        reset_caches()

    def test_style_maps_robust_higher_than_normal(self):
        self.assertEqual(eleven_style("robust"), "robust")
        robust = style_voice_settings("robust")["stability"]
        normal = style_voice_settings("normal")["stability"]
        self.assertGreater(robust, normal)

    def test_synthesize_writes_mp3_without_live_api(self):
        reset_caches()
        class FakeResp:
            ok = True
            status_code = 200
            content = b"ID3fake-mp3"
            def raise_for_status(self):
                return None
            def json(self):
                return {"voices": [{"name": "Liam Callahan - Witty Media Person", "voice_id": "abcLiamCallahan1"}]}

        session = mock.Mock()
        session.get.return_value = FakeResp()
        session.post.return_value = FakeResp()
        conf = mock.Mock()
        conf.enabled = True
        conf.slots = [type("S", (), {"api_key": "sk_test_not_real", "proxy": None, "index": 0})()]
        conf.voice_id = ""
        conf.voice_name = "Liam Callahan - Witty Media Person"
        conf.model = "eleven_v3"
        conf.style = "robust"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "az" / "voiceover.mp3"
            with mock.patch("recap.elevenlabs_tts.detect_model", return_value="eleven_v3"):
                path = synthesize("Hook line.", dest, language="az", conf=conf, session=session)
            self.assertEqual(path, dest)
            self.assertTrue(dest.exists())
            self.assertGreater(dest.stat().st_size, 0)
            payload = session.post.call_args.kwargs["json"]
            self.assertEqual(payload["model_id"], "eleven_v3")
            self.assertIn("stability", payload["voice_settings"])
            url = session.post.call_args.args[0]
            self.assertIn("abcLiamCallahan1", url)

    def test_never_logs_api_key(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            try:
                raise ElevenLabsError("failed sk_live_SUPERSECRETKEY999")
            except ElevenLabsError:
                pass
        self.assertNotIn("SUPERSECRET", buf.getvalue())


class CliFarmTests(unittest.TestCase):
    def test_languages_and_skip(self):
        args = parse_args([
            "--match-dir", "output/x", "--languages", "az,en,es,ru",
            "--skip-language", "ru", "--eleven-style", "normal",
            "--approve-script", "--approve-voice",
        ])
        langs = farm.resolve_languages(args)
        self.assertEqual(langs, ["az", "en", "es"])
        self.assertEqual(args.eleven_style, "normal")
        self.assertTrue(args.approve_script)
        self.assertTrue(args.approve_voice)
        self.assertEqual(farm.farm_layout(args), farm.LAYOUT_MATCH_LANG)

    def test_dub_languages_after_az(self):
        args = parse_args([
            "--match-dir", "output/x", "--language", "az", "--dub-languages", "en,es",
        ])
        self.assertEqual(farm.resolve_languages(args), ["az", "en", "es"])

    def test_livescore_flag_in_help(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stdout", buf):
                parse_args(["--help"])
        text = buf.getvalue()
        self.assertIn("--livescore-url", text)
        self.assertIn("--languages", text)
        self.assertIn("--eleven-style", text)
        self.assertIn("--approve-script", text)

    def test_studio_argv_matches_cli(self):
        argv = cli_argv_for(match_dir="output/x", languages=["az", "en"], hook_text="boom", auto=True)
        args = parse_args(argv)
        self.assertEqual(farm.resolve_languages(args), ["az", "en"])
        self.assertEqual(args.hook_text, ["boom"])
        self.assertTrue(args.auto)


if __name__ == "__main__":
    unittest.main()
