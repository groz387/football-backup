"""Whole-story contextual translation and restored script defaults."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from recap import translation
from recap.data import MatchBundle, Score
from video_pipeline import parse_args


def bundle() -> MatchBundle:
    return MatchBundle(
        match_dir=Path("/tmp/new-match"),
        summary={
            "home": {"name": "Barcelona"},
            "away": {"name": "Elche"},
            "league": "LaLiga",
        },
        events=pd.DataFrame(),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(),
        score=Score(5, 1),
    )


AUDIT = {
    "match": {"score_display": "5-1"},
    "facts": ["Barcelona 5-1 Elche.", "Shots: Barcelona 19, Elche 8."],
    "team_stats": {
        "Barcelona": {"shots": 19, "shots_on_target": 9},
        "Elche": {"shots": 8, "shots_on_target": 3},
    },
    "goal_timeline": [{"minute": 12, "scorer": "Lamine Yamal"}],
    "definitions": {"shots": "Attempts"},
    "data_health": {"blocked_claims": ["xG"]},
}

SCENES = [
    {
        "id": "shot_map",
        "visualization": "shot_map",
        "kicker": "SHOT MAP",
        "title": "19 SHOTS",
        "subtitle": "",
        "insight": "Barcelona led 19 to 8.",
        "narration": "Barcelona produced 19 attempts against Elche's 8, with 9 of them testing the goalkeeper.",
        "comment_bait": "",
        "lines": [],
    },
    {
        "id": "close",
        "visualization": "close",
        "kicker": "FULL TIME",
        "title": "BARCELONA 5-1 ELCHE",
        "subtitle": "",
        "insight": "Who was best?",
        "narration": "Barcelona won 5-1. Who was best?",
        "comment_bait": "Who was best?",
        "lines": [],
    },
]


class TranslationTests(unittest.TestCase):
    def test_payload_contains_entire_story_and_audit_context(self):
        payload = translation.translation_payload(SCENES, "es", bundle(), AUDIT)
        self.assertEqual(len(payload["scenes"]), 2)
        self.assertEqual(payload["match_context"]["team_stats"]["Barcelona"]["shots"], 19)
        self.assertIn("Lamine Yamal", payload["protected_names"])

    def test_contextual_result_preserves_numbers_and_names(self):
        class Groq:
            enabled = True

            @staticmethod
            def translate(payload):
                return {"scenes": [
                    {
                        "id": "shot_map", "kicker": "MAPA DE TIROS", "title": "19 TIROS",
                        "subtitle": "", "insight": "Barcelona mandó 19 a 8.",
                        "narration": "Barcelona produjo 19 intentos ante los 8 de Elche, y 9 probaron al portero.",
                        "comment_bait": "", "lines": [],
                    },
                    {
                        "id": "close", "kicker": "FINAL", "title": "BARCELONA 5-1 ELCHE",
                        "subtitle": "", "insight": "¿Quién fue el mejor?",
                        "narration": "Barcelona ganó 5-1. ¿Quién fue el mejor?",
                        "comment_bait": "¿Quién fue el mejor?", "lines": [],
                    },
                ]}

        result = translation.translate_story(
            SCENES, "es", bundle(), AUDIT, provider="groq", groq=Groq(),
        )
        self.assertTrue(result.ok, result.warnings)
        self.assertEqual(result.provider, "groq")
        self.assertIn("19", result.scenes[0]["narration"])
        self.assertIn("Barcelona", result.scenes[0]["narration"])
        self.assertIn("Elche", result.scenes[0]["narration"])

    def test_digit_drift_is_rejected_per_field(self):
        class Gemini:
            enabled = True

            @staticmethod
            def translate_contextual_script(payload):
                rows = [dict(row) for row in payload["scenes"]]
                rows[0]["narration"] = "Barcelona produjo 20 intentos."
                return {"scenes": rows}

        result = translation.translate_story(
            SCENES, "es", bundle(), AUDIT, provider="gemini", gemini=Gemini(),
        )
        self.assertFalse(result.ok)
        self.assertIn("digit lock", " ".join(result.warnings))
        self.assertEqual(result.scenes[0]["narration"], SCENES[0]["narration"])

    def test_offline_translation_is_never_claimed_complete(self):
        result = translation.translate_story(
            SCENES, "az", bundle(), AUDIT, provider="offline",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.provider, "offline_partial")
        self.assertTrue(result.warnings)

    def test_restored_defaults_are_four_cards_and_seventeen_words(self):
        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertEqual(args.visualizations, 4)
        self.assertEqual(args.words_per_section, 17)
        self.assertEqual(args.target_seconds, 34.0)

    def test_cli_accepts_groq_translator(self):
        args = parse_args([
            "--auto", "--match-dir", "output/x", "--translation-provider", "groq",
        ])
        self.assertEqual(args.translation_provider, "groq")


class GroqClientTests(unittest.TestCase):
    def test_posts_to_groq_json_endpoint(self):
        captured: dict = {}

        class Resp:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": '{"scenes":[]}'}}]}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            captured["auth"] = kwargs["headers"]["Authorization"]
            return Resp()

        with mock.patch("recap.translation.requests.post", fake_post):
            client = translation.GroqTranslator(api_key="gsk_test", model="qwen/qwen3.8-27b")
            parsed = client.translate({"task": "x"})
        self.assertEqual(parsed, {"scenes": []})
        self.assertEqual(captured["url"], translation.GROQ_URL)
        self.assertEqual(captured["json"]["model"], "qwen/qwen3.8-27b")
        self.assertEqual(captured["json"]["response_format"], {"type": "json_object"})
        self.assertTrue(captured["auth"].startswith("Bearer gsk_"))
        self.assertEqual(client.last_model, "qwen/qwen3.8-27b")

    def test_falls_back_when_preferred_model_is_gone(self):
        models: list[str] = []

        class Resp:
            def __init__(self, status, payload):
                self.status_code = status
                self.ok = status == 200
                self.text = payload if isinstance(payload, str) else json.dumps(payload)
                self._payload = payload if isinstance(payload, dict) else {}

            def json(self):
                return self._payload

        def fake_post(url, **kwargs):
            model = kwargs["json"]["model"]
            models.append(model)
            if model == "qwen/qwen3.8-27b":
                return Resp(404, '{"error":{"message":"model not found"}}')
            return Resp(200, {"choices": [{"message": {"content": '{"scenes":[{"id":"x"}]}'}}]})

        with mock.patch("recap.translation.requests.post", fake_post):
            client = translation.GroqTranslator(api_key="gsk_test", model="qwen/qwen3.8-27b")
            parsed = client.translate({"task": "x"})
        self.assertEqual(parsed, {"scenes": [{"id": "x"}]})
        self.assertEqual(models[0], "qwen/qwen3.8-27b")
        self.assertIn(client.last_model, translation.GROQ_MODEL_CANDIDATES)
        self.assertNotEqual(client.last_model, "qwen/qwen3.8-27b")


if __name__ == "__main__":
    unittest.main()
