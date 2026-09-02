"""Growth/SEO posting pack: schema, bilingual copy, grounded numbers, thumbs."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from recap import audit as audit_mod
from recap import growth, hooks, i18n, thumbnails
from recap.data import load_match
from video_pipeline import parse_args

ROOT = Path(__file__).resolve().parents[1]
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"
MEXICO = ROOT / "output" / "1953854_Mexico_vs_South_Korea"
BARCA_RAYO = ROOT / "output" / "1993920_Barcelona_vs_Rayo_Vallecano"

_SCORELINE = re.compile(r"\b\d+\s*[-–:/]\s*\d+\b")
_XG_CLAIM = re.compile(r"\bxG(?:OT)?\b", re.I)


def _bundle_audit(match_dir: Path):
    bundle = load_match(match_dir)
    return bundle, audit_mod.build_audit(bundle)


class ArgparseDestTests(unittest.TestCase):
    def test_write_growth_default_on_unique_dest(self):
        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertTrue(args.write_growth_seo)
        self.assertEqual(args.growth_pack_dir, "")

    def test_no_write_growth_flips_dest(self):
        args = parse_args(["--auto", "--no-write-growth", "--match-dir", "output/x"])
        self.assertFalse(args.write_growth_seo)

    def test_growth_dir_unique_dest(self):
        args = parse_args(["--auto", "--growth-dir", "/tmp/growth-out", "--match-dir", "output/x"])
        self.assertEqual(args.growth_pack_dir, "/tmp/growth-out")

    def test_standalone_cli_unique_dests(self):
        args = growth.parse_growth_args([
            "--match-dir", "output/x",
            "--language", "es",
            "--growth-dir", "/tmp/g",
        ])
        self.assertEqual(args.growth_match_dir, "output/x")
        self.assertEqual(args.growth_language, "es")
        self.assertEqual(args.growth_pack_dir, "/tmp/g")
        self.assertFalse(hasattr(args, "write_growth_seo"))


@unittest.skipUnless(SCOTLAND.exists(), "Scotland export missing")
class ScotlandPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        i18n.set_language("en")
        cls.bundle, cls.audit = _bundle_audit(SCOTLAND)
        cls.hook = hooks.build_hook(cls.bundle, cls.audit)
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.dest = Path(cls.tmpdir.name) / "growth"
        cls.pack = growth.write_growth_pack(
            SCOTLAND,
            language="es",
            dest_dir=cls.dest,
            audit=cls.audit,
            bundle=cls.bundle,
            duration_seconds=42.0,
            scene_list=[
                {"visualization": "hook_claim", "visible_start": 0.0},
                {"visualization": "hook_punch", "visible_start": 0.85},
                {"visualization": "goal_chain", "visible_start": 2.0},
                {"visualization": "zone_control", "visible_start": 12.0},
                {"visualization": "close", "visible_start": 38.0},
            ],
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()
        i18n.set_language("en")

    def test_schema_and_languages(self):
        self.assertEqual(self.pack["schema"], growth.SCHEMA)
        self.assertEqual(self.pack["languages"], ["es", "en"])
        self.assertTrue((self.dest / "pack.json").exists())
        self.assertTrue((self.dest / "es" / "posting.txt").exists())
        self.assertTrue((self.dest / "en" / "posting.txt").exists())
        raw = json.loads((self.dest / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["schema"], "recap.growth.v1")

    def test_five_title_kinds_per_platform(self):
        for lang in ("es", "en"):
            platforms = self.pack["packs"][lang]["platforms"]
            self.assertEqual(set(platforms), set(growth.PLATFORMS))
            for platform, block in platforms.items():
                self.assertEqual(set(block["titles"]), set(growth.TITLE_KINDS), platform)
                for kind, title in block["titles"].items():
                    self.assertTrue(title.strip(), f"{lang}/{platform}/{kind} empty")

    def test_curiosity_has_no_score_spoiler(self):
        for lang in ("es", "en"):
            for platform, block in self.pack["packs"][lang]["platforms"].items():
                title = block["titles"]["curiosity"]
                self.assertIsNone(_SCORELINE.search(title), title)
                self.assertNotIn("0-1", title)
                self.assertNotIn("0–1", title)

    def test_spoiler_and_player_use_real_facts(self):
        en = self.pack["packs"]["en"]["platforms"]["youtube"]["titles"]
        self.assertRegex(en["spoiler_slam"], r"0-1")
        self.assertIn("Saibari", self.pack["packs"]["en"]["platforms"]["youtube"]["titles"]["player_seo"])
        es_player = self.pack["packs"]["es"]["platforms"]["tiktok"]["titles"]["player_seo"]
        self.assertIn("Saibari", es_player)
        self.assertIn("Marruecos", self.pack["packs"]["es"]["platforms"]["instagram_feed"]["titles"]["derby_language"]
                      + self.pack["packs"]["es"]["platforms"]["youtube"]["titles"]["derby_language"]
                      + self.pack["packs"]["es"]["platforms"]["shorts"]["titles"]["spoiler_slam"])

    def test_hashtags_are_5_plus_8_and_not_cloned(self):
        blobs = []
        for platform, block in self.pack["packs"]["en"]["platforms"].items():
            big = block["hashtags"]["big"]
            niche = block["hashtags"]["niche"]
            self.assertEqual(len(big), 5, platform)
            self.assertEqual(len(niche), 8, platform)
            self.assertEqual(len(set(big + niche)), 13, platform)
            blobs.append(tuple(big))
        self.assertGreater(len(set(blobs)), 1, "every platform dumped the same 5 big tags")

    def test_description_has_hook_disclaimer_cta(self):
        desc = self.pack["packs"]["en"]["platforms"]["youtube"]["description"]
        self.assertIn("WhoScored", desc)
        self.assertIn("invent", desc.lower())
        self.assertIn("Follow", desc)
        self.assertTrue(self.hook["lines"][0].split()[0] in desc or "17" in desc)
        self.assertIn("Saibari", desc)

    def test_no_fake_xg_claims(self):
        blob = json.dumps(self.pack, ensure_ascii=False)
        # Disclaimer may mention xG as something we do NOT invent.
        for lang in ("es", "en"):
            for platform, block in self.pack["packs"][lang]["platforms"].items():
                for kind, title in block["titles"].items():
                    self.assertIsNone(_XG_CLAIM.search(title), f"{platform}/{kind}: {title}")
        self.assertIn("xG", blob)
        self.assertIn("blocked_claims", blob)
        self.assertIn("xG", self.pack["match"]["blocked_claims"])

    def test_pinned_comments_are_questions(self):
        comments = self.pack["packs"]["en"]["platforms"]["tiktok"]["pinned_comments"]
        self.assertGreaterEqual(len(comments), 2)
        self.assertTrue(any("?" in row for row in comments))

    def test_youtube_long_chapters_start_at_zero(self):
        chapters = self.pack["packs"]["en"]["youtube_long"]["chapters"]
        self.assertTrue(chapters)
        self.assertEqual(chapters[0]["t"], "0:00")
        self.assertGreaterEqual(len(chapters), 3)
        ids = {row.get("id") for row in chapters}
        self.assertIn("goal_chain", ids)

    def test_thumbnail_jpgs_exist_and_overlay_is_short(self):
        thumbs = self.pack["packs"]["en"]["thumbnails"]
        self.assertIn("slam_vertical", thumbs)
        path = Path(thumbs["slam_vertical"]["path"])
        self.assertTrue(path.exists(), path)
        self.assertGreater(path.stat().st_size, 8_000)
        words = thumbs["slam_vertical"]["words"]
        self.assertGreaterEqual(words, 3)
        self.assertLessEqual(words, 5)
        self.assertIn("SAIBARI", thumbs["slam_vertical"]["text"].upper())

    def test_hook_kind_is_read_not_invented(self):
        self.assertEqual(self.pack["match"]["hook"]["kind"], self.hook["kind"])
        self.assertEqual(self.hook["kind"], "chain_shock")

    def test_spanish_and_english_titles_differ(self):
        es = self.pack["packs"]["es"]["platforms"]["tiktok"]["titles"]["question"]
        en = self.pack["packs"]["en"]["platforms"]["tiktok"]["titles"]["question"]
        self.assertNotEqual(es, en)
        self.assertTrue("¿" in es or "Quién" in es or "qué" in es.lower())

    def test_filenames_include_fixture(self):
        names = " ".join(self.pack["packs"]["en"]["platforms"]["youtube"]["filenames"])
        self.assertIn("scotland", names)
        self.assertIn("morocco", names)

    def test_derby_title_does_not_repeat_world_cup(self):
        for lang in ("en", "es"):
            for platform, block in self.pack["packs"][lang]["platforms"].items():
                title = block["titles"]["derby_language"].lower()
                self.assertNotIn("world cup world cup", title, title)


@unittest.skipUnless(MEXICO.exists() and SCOTLAND.exists(), "need two match exports")
class CrossMatchTests(unittest.TestCase):
    def test_hashtags_and_titles_are_match_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            scot = growth.write_growth_pack(SCOTLAND, dest_dir=Path(tmp) / "s", language="en")
            mex = growth.write_growth_pack(MEXICO, dest_dir=Path(tmp) / "m", language="en")
        scot_titles = scot["packs"]["en"]["platforms"]["youtube"]["titles"]
        mex_titles = mex["packs"]["en"]["platforms"]["youtube"]["titles"]
        self.assertNotEqual(scot_titles["player_seo"], mex_titles["player_seo"])
        self.assertIn("Scotland", scot_titles["derby_language"] + scot_titles["curiosity"])
        self.assertTrue(
            "Mexico" in mex_titles["curiosity"] or "México" in mex_titles["curiosity"]
            or "Korea" in mex_titles["curiosity"]
        )
        scot_tags = set(scot["packs"]["en"]["platforms"]["tiktok"]["hashtags"]["niche"])
        mex_tags = set(mex["packs"]["en"]["platforms"]["tiktok"]["hashtags"]["niche"])
        self.assertNotEqual(scot_tags, mex_tags)


class ThumbnailWordTests(unittest.TestCase):
    def test_clip_words_caps_at_five(self):
        self.assertEqual(thumbnails.clip_words("ONE TWO THREE FOUR FIVE SIX"), "ONE TWO THREE FOUR FIVE")
        self.assertEqual(thumbnails.word_count("SAIBARI 1' GOAL"), 3)


class BarcaRayoGuardTests(unittest.TestCase):
    def test_barca_rayo_dir_absent_so_scotland_is_the_sample(self):
        self.assertFalse(BARCA_RAYO.exists())
        self.assertTrue(SCOTLAND.exists())


if __name__ == "__main__":
    unittest.main()
