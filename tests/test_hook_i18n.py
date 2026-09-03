"""Operator hook language detection and per-package localization."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from recap import hook_i18n
from recap.data import MatchBundle, Score


def bundle() -> MatchBundle:
    return MatchBundle(
        match_dir=Path("/tmp/operator-copy"),
        summary={"home": {"name": "Barcelona"}, "away": {"name": "Elche"}},
        events=pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(home=5, away=1),
    )


AUDIT = {
    "match": {"score_display": "5-1"},
    "team_stats": {
        "Barcelona": {"goals": 5},
        "Elche": {"goals": 1},
    },
    "cast": {"stars": [{"name": "Lamine Yamal", "poster_name": "Yamal"}]},
}


class DetectionTests(unittest.TestCase):
    def test_az_ascii_hook_is_not_turkish(self):
        self.assertEqual(hook_i18n.detect_language("Oyun Qapandi")[0], "az")
        self.assertEqual(hook_i18n.detect_language("Donushe Bax")[0], "az")

    def test_native_az_and_english(self):
        self.assertEqual(hook_i18n.detect_language("Bəs sizcə, kim gijdıllaxiydi?")[0], "az")
        self.assertEqual(hook_i18n.detect_language("WAS YAMAL MOTM?")[0], "en")


class LocalizationTests(unittest.TestCase):
    def test_source_language_keeps_operator_text(self):
        result = hook_i18n.localize_operator_copy(
            ["Oyun Qapandi"], "", "az", bundle=bundle(), audit=AUDIT,
        )
        self.assertEqual(result["hook_texts"], ["Oyun Qapandi"])
        self.assertEqual(result["hooks"][0]["method"], "operator_exact")

    def test_az_hook_localizes_across_packages_offline(self):
        source = "Oyun Qapandi"
        outputs = {}
        for language in ("az", "en", "es"):
            outputs[language] = hook_i18n.localize_operator_copy(
                [source], "", language, bundle=bundle(), audit=AUDIT,
            )
        self.assertEqual(outputs["az"]["hook_texts"][0], source)
        self.assertEqual(outputs["en"]["hook_texts"][0], "GAME OVER")
        self.assertEqual(outputs["es"]["hook_texts"][0], "SE ACABÓ EL PARTIDO")
        self.assertEqual(outputs["en"]["hooks"][0]["method"], "offline_intent")

    def test_digits_are_preserved(self):
        result = hook_i18n.localize_operator_copy(
            ["90 Minute"], "", "es", bundle=bundle(), audit=AUDIT,
        )
        self.assertIn("90", result["hook_texts"][0])

    def test_english_yamal_bait_becomes_az_and_keeps_name(self):
        result = hook_i18n.localize_operator_copy(
            [], "was Yamal motm?", "az", bundle=bundle(), audit=AUDIT,
        )
        self.assertNotEqual(result["bait_text"].casefold(), "was yamal motm?")
        self.assertIn("Yamal", result["bait_text"])
        self.assertEqual(result["bait"]["method"], "fallback_pool")

    def test_enabled_gemini_translation_wins(self):
        class Gemini:
            enabled = True

            @staticmethod
            def translate_operator_line(text, source, target, **kwargs):
                return "SE ACABÓ EL PARTIDO"

        result = hook_i18n.localize_operator_copy(
            ["Oyun Qapandi"], "", "es", bundle=bundle(), audit=AUDIT, gemini=Gemini(),
        )
        self.assertEqual(result["hook_texts"][0], "SE ACABÓ EL PARTIDO")
        self.assertEqual(result["hooks"][0]["method"], "gemini")


if __name__ == "__main__":
    unittest.main()
