"""Curse bookends: AZ smash + local EN/ES/RU terrace talk, clean body."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import pandas as pd

from recap import culture, director, script_culture
from recap.data import MatchBundle, Score
from recap.locales import az as az_locale
from recap.locales import en as en_locale
from recap.locales import es as es_locale
from recap.locales import ru as ru_locale


_AZ_SMASH = re.compile(
    r"(g[öo]t|a[gğ]ac|soxdu|gijd[ıi]llax|peys[əe]r|sikird)",
    re.IGNORECASE,
)
_AZ_LEAK = re.compile(
    r"(g[öo]tün|gijd[ıi]llax|a[gğ]ac\s*sox|peys[əe]r|stick[- ]up[- ]the[- ]ass|"
    r"wood(?:en)? stick up)",
    re.IGNORECASE,
)


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
    home: str = "Barcelona",
    away: str = "Elche",
    home_goals: int = 3,
    away_goals: int = 0,
    match_id: str = "elche_smash",
) -> MatchBundle:
    return MatchBundle(
        match_dir=Path(f"/tmp/{match_id}"),
        summary={"home": {"name": home}, "away": {"name": away}, "league": "La Liga"},
        events=pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(home=home_goals, away=away_goals),
    )


def _audit(bundle: MatchBundle) -> dict:
    return {
        "match": {
            "home": bundle.home,
            "away": bundle.away,
            "score_display": bundle.score.display,
            "table": {},
            "derby": False,
            "rival": False,
        },
        "team_stats": {
            bundle.home: _stats(goals=bundle.score.home, shots=18),
            bundle.away: _stats(goals=bundle.score.away, shots=4),
        },
        "goal_timeline": [],
        "data_health": {
            "has_vendor_xg": False,
            "has_vendor_xgot": False,
            "has_var": False,
            "has_table": False,
            "blocked_claims": ["xG", "xGOT"],
        },
        "momentum": [],
        "field_tilt": [],
        "zone_control": [],
        "player_leaders": {},
        "goal_chains": [],
        "facts": [],
        "definitions": {},
        "spoiler": "show",
    }


def _scenes(hook: str = "open", bait: str = "who was motm?", body: str = "Eighteen shots, four on target.") -> list[dict]:
    return [
        {
            "id": "hook_claim",
            "visualization": "hook_claim",
            "title": hook,
            "narration": hook,
            "insight": "",
            "comment_bait": "",
            "lines": [hook],
        },
        {
            "id": "hook_punch",
            "visualization": "hook_punch",
            "title": "THE SIEGE",
            "narration": "The box turned into a graveyard.",
            "insight": "",
            "comment_bait": "",
        },
        {
            "id": "shot_map",
            "visualization": "shot_map",
            "title": "SHOT MAP",
            "narration": body,
            "insight": "Volume without an answer.",
            "comment_bait": "",
        },
        {
            "id": "close",
            "visualization": "close",
            "title": "FULL TIME",
            "narration": "Barcelona 3 Elche 0. The numbers were not close.",
            "insight": bait,
            "comment_bait": bait,
        },
    ]


class AzSmashTests(unittest.TestCase):
    def test_genitive_smash_title_matches_the_example(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle)
        filled = culture._fill("{team} {rival_gen} götünə ağac soxdu", bundle, audit)
        titled = culture.smash_title(filled, "az")
        self.assertEqual(titled, "Barcelona Elchenin Götünə Ağac Soxdu")

    def test_az_locale_pool_has_gijdillax_outro(self) -> None:
        self.assertTrue(any("gijdıllaxiydi" in line for line in az_locale.CURSE_OUTROS))
        self.assertTrue(any("götünə ağac soxdu" in line for line in az_locale.CURSE_HOOKS))

    def test_offline_az_hook_is_local_smash(self) -> None:
        bundle, audit = _bundle(), _audit(_bundle())
        hook = culture.offline_hook(bundle, audit, "az")
        filled = [
            culture.smash_title(culture._fill(template, bundle, audit), "az")
            for template in culture.pools_for("az")["hook"]
        ]
        self.assertIn(hook, filled)
        bait = culture.offline_bait(bundle, audit, "az")
        filled_baits = [culture._fill(template, bundle, audit) for template in culture.pools_for("az")["bait"]]
        self.assertIn(bait, filled_baits)
        self.assertTrue(any("gijdıllax" in line for line in az_locale.CURSE_OUTROS))

    def test_lock_plants_az_bookends_and_keeps_body_clean(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle)
        locked = culture.lock_bookends(
            _scenes(body="On səkkiz zərbə. Rəqibin götünə dəymədi bu kart."),
            bundle, audit, "az",
            hook_text="Barcelona Elchenin Götünə Ağac Soxdu",
            bait_text="Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?",
        )
        hook = next(s for s in locked if s["visualization"] == "hook_claim")
        close = next(s for s in locked if s["visualization"] == "close")
        body = next(s for s in locked if s["visualization"] == "shot_map")
        self.assertIn("Götünə Ağac Soxdu", hook["narration"])
        self.assertIn("gijdıllaxiydi", close["comment_bait"])
        self.assertFalse(culture.contains_curse(body["narration"], "az"), body["narration"])
        self.assertFalse(culture.contains_curse(body["insight"], "az"), body["insight"])
        review = culture.script_review(locked, "az")
        self.assertTrue(review["bookends"]["clean_body"])


class LocalTerraceTests(unittest.TestCase):
    def test_en_es_ru_are_not_literal_az(self) -> None:
        for code, mod in (("en", en_locale), ("es", es_locale), ("ru", ru_locale)):
            blob = "\n".join(
                list(mod.CURSE_HOOKS)
                + list(mod.CURSE_HOOKS_DRAW)
                + list(mod.CURSE_HOOKS_HIDE)
                + list(mod.CURSE_OUTROS)
            )
            self.assertIsNone(_AZ_LEAK.search(blob), f"{code} leaked AZ: {blob[:120]}")

    def test_offline_en_es_ru_do_not_calque_az(self) -> None:
        bundle, audit = _bundle(), _audit(_bundle())
        for code in ("en", "es", "ru"):
            hook = culture.offline_hook(bundle, audit, code)
            bait = culture.offline_bait(bundle, audit, code)
            self.assertTrue(hook, code)
            self.assertTrue(bait, code)
            self.assertIsNone(_AZ_LEAK.search(hook + " " + bait), f"{code}: {hook} / {bait}")

    def test_en_lock_strips_body_swears(self) -> None:
        bundle, audit = _bundle(), _audit(_bundle())
        locked = culture.lock_bookends(
            _scenes(body="They fucking bottled the midfield. Eighteen shots."),
            bundle, audit, "en",
        )
        body = next(s for s in locked if s["visualization"] == "shot_map")
        self.assertFalse(culture.contains_curse(body["narration"], "en"), body["narration"])
        hook = next(s for s in locked if s["visualization"] == "hook_claim")
        self.assertTrue(hook["narration"])


class VoiceoverTagTests(unittest.TestCase):
    def test_tags_only_on_bookends_and_punch(self) -> None:
        bundle, audit = _bundle(), _audit(_bundle())
        locked = culture.lock_bookends(_scenes(), bundle, audit, "az")
        text = script_culture.build_voiceover_text(locked, "az")
        self.assertIn("[mischievously]", text)
        self.assertIn("[curious]", text)
        body = next(s for s in locked if s["visualization"] == "shot_map")
        self.assertNotIn("[mischievously]", body["narration"])
        self.assertNotIn("[curious]", body["narration"])
        self.assertNotRegex(body["narration"], culture.AUDIO_TAG_RE)

    def test_gemini_rules_unpack_for_director(self) -> None:
        rules = script_culture.gemini_rules("az")
        self.assertIsInstance(rules, tuple)
        blob = " ".join(rules)
        self.assertIn("CURSE BOOKENDS", blob)
        self.assertIn("eleven", blob.lower())
        brief = script_culture.gemini_brief(_bundle(), _audit(_bundle()), language="az")
        self.assertEqual(brief["locale"], "az")
        self.assertTrue(brief["elevenlabs_v3"])
        self.assertTrue(brief["example_hook"])
        self.assertTrue(brief["example_bait"])

    def test_director_imports_script_culture(self) -> None:
        self.assertTrue(hasattr(director, "script_culture"))
        self.assertIn("CURSES ONLY", director.SYSTEM_PROMPT)
        self.assertIn("ElevenLabs v3", director.SYSTEM_PROMPT)

    def test_kids_mode_skips_curses(self) -> None:
        hook = culture.offline_hook(_bundle(), _audit(_bundle()), "az", kids=True)
        self.assertEqual(hook, "")
        pools = script_culture.curse_pools("az", kids=True)
        self.assertEqual(pools["hooks"], ())


if __name__ == "__main__":
    unittest.main()
