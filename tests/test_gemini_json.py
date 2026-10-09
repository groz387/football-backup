"""Gemini / translator JSON must survive extra objects after a valid value."""

from __future__ import annotations

import json
import unittest

from recap import director
from recap.jsonutil import extract_json, loads_model_json
from recap.i18n import catalog_missing, leftover_english, parse_languages
from video_pipeline import parse_args


class ModelJsonTests(unittest.TestCase):
    def test_extra_data_after_first_object_is_ignored(self):
        raw = (
            '{\n'
            '  "scenes": [{"id": "shot_map", "title": "19 SHOTS", "narration": "Barcelona 19."}]\n'
            '}\n'
            '{\n'
            '  "note": "trailing object"\n'
            '}\n'
        )
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw)
        parsed = loads_model_json(raw)
        self.assertEqual(parsed["scenes"][0]["id"], "shot_map")

    def test_markdown_fence_and_leading_prose(self):
        raw = (
            "Here is the script:\n"
            "```json\n"
            '{"scenes": [{"id": "close", "title": "5-1", "narration": "Done."}]}\n'
            "```\n"
            "thanks\n"
        )
        parsed = loads_model_json(raw)
        self.assertEqual(parsed["scenes"][0]["id"], "close")

    def test_top_level_array_is_wrapped(self):
        parsed = loads_model_json('[{"id": "hook_claim", "title": "CLAIM"}]')
        self.assertEqual(parsed["scenes"][0]["id"], "hook_claim")

    def test_extract_json_stops_at_first_value(self):
        blob = extract_json('{"a": 1}\n{"b": 2}')
        self.assertEqual(json.loads(blob), {"a": 1})


class LanguageCliTests(unittest.TestCase):
    def test_parse_languages_dedupes_and_aliases(self):
        self.assertEqual(parse_languages("az, en, AZ, spanish"), ["az", "en", "es"])

    def test_cli_accepts_languages_flag(self):
        args = parse_args(["--auto", "--match-dir", "output/x", "--language", "en,az,es"])
        self.assertEqual(args.language_list, ["en", "az", "es"])
        self.assertTrue(args.language_explicit)
        self.assertTrue(args.skip_audio)

    def test_languages_alias_matches_language(self):
        args = parse_args(["--auto", "--match-dir", "output/x", "--languages", "az,en"])
        self.assertEqual(args.language_list, ["az", "en"])

    def test_voiceover_file_turns_audio_on(self):
        args = parse_args([
            "--auto", "--match-dir", "output/x", "--voiceover-file", "vo.wav",
        ])
        self.assertFalse(args.skip_audio)

    def test_ui_catalogs_cover_english_keys(self):
        for language in ("az", "es", "ru"):
            self.assertEqual(catalog_missing(language), [])

    def test_leftover_english_catches_chrome_and_keeps_azeri(self):
        self.assertTrue(leftover_english("6 saves from 8 shots on target proved decisive.", "az"))
        self.assertTrue(leftover_english("0 GOALS FROM 20 SHOTS", "az"))
        self.assertTrue(leftover_english("BIG CHANCES", "az"))
        self.assertTrue(leftover_english("Real Madrid outshot Betis 20 to 10.", "az"))
        self.assertFalse(leftover_english("Real Madrid 7 böyük şansının heç birini çevirmədi.", "az"))
        self.assertFalse(leftover_english("Çərçivəyə 8 zərbə. 6 seyvlə dayandırıldı.", "az"))
        self.assertTrue(leftover_english("10-20 shots; 5-8 çərçivəyə.", "az"))


class GeminiModelTests(unittest.TestCase):
    def test_chain_drops_retired_ids_and_prefers_an_allowlisted_one(self):
        chain = director.gemini_model_chain("gemini-3.8-flash", "gemini-2.5-flash")
        self.assertEqual(chain[0], "gemini-2.5-flash")
        self.assertEqual(len(chain), len(director.GEMINI_MODELS))
        self.assertNotIn("gemini-3.8-flash", chain)
        self.assertNotIn("gemini-3.7-flash", chain)
        self.assertNotIn("gemini-3.6-flash", chain)
        for name in (
            "gemma-4-31b-it",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
        ):
            self.assertIn(name, chain)

    def test_quota_and_server_errors_switch_immediately(self):
        self.assertEqual(
            director.gemini_failure_action("500 INTERNAL. status INTERNAL", can_strip_schema=False),
            "switch",
        )
        self.assertEqual(
            director.gemini_failure_action("403 PERMISSION_DENIED", can_strip_schema=False),
            "switch",
        )
        self.assertEqual(
            director.gemini_failure_action(
                "429 RESOURCE_EXHAUSTED. You exceeded your current quota",
                can_strip_schema=False,
            ),
            "switch",
        )
        self.assertEqual(
            director.gemini_failure_action(
                "JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
                can_strip_schema=False,
            ),
            "retry_json",
        )

    def test_server_error_tries_each_allowlisted_model_once(self):
        calls: list[str] = []

        class FakeModels:
            def generate_content(self, **kwargs):
                calls.append(kwargs["model"])
                raise RuntimeError("500 INTERNAL. {'error': {'code': 500, 'status': 'INTERNAL'}}")

        class FakeClient:
            models = FakeModels()

        client = director.Gemini(
            enabled=True, model="gemma-4-31b-it", script_model="gemma-4-31b-it",
        )
        client.enabled = True
        client._client = FakeClient()
        self.assertIsNone(client._generate({"task": "x"}, model="gemma-4-31b-it"))
        self.assertEqual(calls, list(director.GEMINI_MODELS))
        self.assertEqual(client._blocked, set(director.GEMINI_MODELS))


if __name__ == "__main__":
    unittest.main()
