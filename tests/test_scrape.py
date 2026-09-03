"""WhoScored scrape classifier + mocked runner."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from recap import scrape


class ClassifyTests(unittest.TestCase):
    def test_bare_id_builds_live_url(self):
        info = scrape.classify_source("1821295")
        self.assertEqual(info["kind"], "match_id")
        self.assertTrue(info["can_scrape"])
        self.assertEqual(info["whoscored_url"], "https://www.whoscored.com/matches/1821295/live")

    def test_whoscored_url(self):
        info = scrape.classify_source("https://www.whoscored.com/matches/1993920/live/spain-laliga")
        self.assertEqual(info["kind"], "whoscored")
        self.assertEqual(info["match_id"], "1993920")
        self.assertTrue(info["can_scrape"])

    def test_livescore_id_is_not_treated_as_whoscored_id(self):
        info = scrape.classify_source("https://www.livescore.com/en/football/spain/laliga/foo-vs-bar/1821295")
        self.assertEqual(info["kind"], "livescore")
        self.assertTrue(info["can_scrape"])
        self.assertEqual(info["whoscored_url"], "")
        self.assertIn("chalkboard", info["hint"].lower())

    def test_livescore_without_id_uses_search_chain(self):
        info = scrape.classify_source("https://www.livescore.com/en/football/spain/laliga/barcelona-vs-elche/")
        self.assertEqual(info["kind"], "livescore")
        self.assertTrue(info["can_scrape"])
        self.assertIn("Flashscore", info["hint"])

    def test_html_file(self):
        tmp = Path(tempfile.mkdtemp()) / "1821295_source.html"
        tmp.write_text("<html></html>", encoding="utf-8")
        info = scrape.classify_source("", html_path=str(tmp))
        self.assertEqual(info["kind"], "html")
        self.assertTrue(info["can_scrape"])
        self.assertEqual(info["match_id"], "1821295")


class RunScrapeTests(unittest.TestCase):
    def test_mocked_url_scrape_detects_new_export(self):
        root = Path(tempfile.mkdtemp())
        dest = root / "output"
        dest.mkdir()

        def fake_scrape(url, output_dir, *args, **kwargs):
            folder = Path(output_dir) / "1821295_Home_vs_Away"
            folder.mkdir()
            (folder / "match_summary.json").write_text(
                '{"matchId":"1821295","home":{"name":"Home"},"away":{"name":"Away"}}',
                encoding="utf-8",
            )
            (folder / "all_events.csv").write_text("id\n1\n", encoding="utf-8")
            return None

        result = scrape.run_scrape(
            url="1821295",
            output_root=dest,
            wait=12,
            scrape_url_fn=fake_scrape,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(Path(result["match_dir"]).name.startswith("1821295_"))

    def test_empty_refuses_to_invent(self):
        with self.assertRaises(ValueError):
            scrape.run_scrape(url="")


if __name__ == "__main__":
    unittest.main()
