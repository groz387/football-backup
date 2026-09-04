"""Livescore → WhoScored → Flashscore chain, without guessing fixture IDs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from recap import scrape, source_chain
from recap.resolve_match import LivescoreFixture, parse_livescore_url


class ClassifyTests(unittest.TestCase):
    def test_livescore_id_is_not_treated_as_whoscored_id(self):
        url = "https://www.livescore.com/en/football/spain/laliga/foo-vs-bar/1821295"
        self.assertIsNone(scrape.extract_match_id(url))
        info = scrape.classify_source(url)
        self.assertEqual(info["kind"], "livescore")
        self.assertTrue(info["can_scrape"])
        self.assertEqual(info["whoscored_url"], "")
        self.assertIsNone(info["match_id"])
        self.assertIn("chalkboard", info["hint"].lower())
        self.assertIn("Flashscore", info["hint"])

    def test_flashscore_url_is_scrapable(self):
        info = scrape.classify_source(
            "https://www.flashscore.com/match/football/atl-madrid-jaarqpLQ/"
            "barcelona-SKbpVP5K/?mid=8pBGO97F"
        )
        self.assertEqual(info["kind"], "flashscore")
        self.assertTrue(info["can_scrape"])
        self.assertEqual(info["match_id"], "8pBGO97F")
        self.assertEqual(info["whoscored_url"], "")
        self.assertIn("8pBGO97F", info["flashscore_url"])

    def test_whoscored_url_stays_direct(self):
        info = scrape.classify_source(
            "https://www.whoscored.com/matches/1993920/live/spain-laliga"
        )
        self.assertEqual(info["kind"], "whoscored")
        self.assertEqual(info["match_id"], "1993920")
        self.assertTrue(info["can_scrape"])

    def test_bare_whoscored_id_still_extracts(self):
        self.assertEqual(scrape.extract_match_id("1953854"), "1953854")


class SearchTests(unittest.TestCase):
    def test_ranking_prefers_date_in_link_text_over_sibling_context(self):
        fixture = LivescoreFixture(
            url="https://www.livescore.com/en/football/x/y/mexico-vs-south-korea/",
            home="Mexico",
            away="South Korea",
            date="2025-08-09",
            event_id="1234567",
        )
        html = """
        <div>
          <a href="/Matches/1111111/Live/international-afc-mexico-south-korea">Mexico vs South Korea</a>
          2025-08-09 other result
        </div>
        <div>
          <a href="/Matches/1953854/Live/international-afc-mexico-south-korea">Mexico vs South Korea 2025-08-09</a>
        </div>
        """
        result = source_chain.rank_candidates(
            source_chain.parse_search_candidates(
                html, "https://www.whoscored.com", source="whoscored",
            ),
            fixture,
        )
        self.assertEqual(result["status"], "found")
        self.assertIn("1953854", result["candidate"]["url"])
        by_url = {row["url"]: row["score"] for row in result["candidates"]}
        dated = next(score for url, score in by_url.items() if "1953854" in url)
        sibling = next(score for url, score in by_url.items() if "1111111" in url)
        self.assertGreater(dated, sibling)

    def test_ambiguous_candidates_are_not_guessed(self):
        fixture = parse_livescore_url(
            "https://www.livescore.com/en/football/spain/laliga/barcelona-vs-elche/"
        )
        rows = [
            {
                "url": "https://www.whoscored.com/matches/1/live",
                "text": "Barcelona Elche", "context": "Barcelona Elche", "date": "",
            },
            {
                "url": "https://www.whoscored.com/matches/2/live",
                "text": "Barcelona Elche", "context": "Barcelona Elche", "date": "",
            },
        ]
        result = source_chain.rank_candidates(rows, fixture)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["candidate"])


class SpawnTests(unittest.TestCase):
    def test_windows_command_opens_visible_cmd(self):
        with mock.patch.object(source_chain.os, "name", "nt"):
            command = source_chain.visible_command(
                "whoscored", "https://www.whoscored.com/matches/1821295/live",
                r"C:\repo\output", 15,
            )
        self.assertEqual(command[:4], ["cmd", "/c", "start", ""])
        self.assertEqual(command[4], "cmd")
        self.assertEqual(command[5], "/k")
        self.assertIn("scrape_match.py", command[6])
        self.assertIn("1821295", command[6])

    def test_linux_flashscore_command_is_direct(self):
        with mock.patch.object(source_chain.os, "name", "posix"):
            command = source_chain.visible_command(
                "flashscore", "https://www.flashscore.com/match/abc", "/tmp/output", 12,
            )
        self.assertIn("scrape_flashscore.py", command[1])
        self.assertIn("--url", command)


class _Health:
    def __init__(self, healthy: bool, source: str = "whoscored"):
        self.healthy = healthy
        self.source = source
        self.notes = ["full event map"] if healthy else ["thin event stream"]

    def as_dict(self):
        return {"healthy": self.healthy, "source": self.source, "notes": self.notes}


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.who = self.root / "who_export"
        self.flash = self.root / "flash_export"
        self.who.mkdir()
        self.flash.mkdir()
        self.livescore = (
            "https://www.livescore.com/en/football/spain/laliga/"
            "northbridge-vs-riverside/8888888/"
        )

    def test_whoscored_full_stops_before_flashscore(self):
        calls: list[str] = []

        def search(fixture, source, **kwargs):
            calls.append(source)
            return {
                "status": "found",
                "candidate": {"url": f"https://{source}.example/match/1993920"},
                "candidates": [],
            }

        with mock.patch("recap.source_chain.assess_source", return_value=_Health(True)):
            result = source_chain.resolve_chain(
                self.livescore, output_root=self.root,
                searcher=search, spawner=lambda *a, **k: None,
                watcher=lambda *a, **k: self.who,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["full"])
        self.assertEqual(result["source"], "whoscored")
        self.assertEqual(calls, ["whoscored"])

    def test_limited_whoscored_tries_flashscore(self):
        calls: list[str] = []

        def search(fixture, source, **kwargs):
            calls.append(source)
            return {
                "status": "found",
                "candidate": {"url": f"https://{source}.example/match"},
                "candidates": [],
            }

        def assess(path):
            if Path(path) == self.who:
                return _Health(False, "reconstructed")
            return _Health(False, "unavailable")

        def watch(root, before, fixture, **kwargs):
            return self.who if calls[-1] == "whoscored" else self.flash

        with mock.patch("recap.source_chain.assess_source", side_effect=assess):
            result = source_chain.resolve_chain(
                self.livescore, output_root=self.root,
                searcher=search, spawner=lambda *a, **k: None,
                watcher=watch,
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["full"])
        self.assertEqual(result["source"], "flashscore")
        self.assertEqual(calls, ["whoscored", "flashscore"])

    def test_livescore_event_id_is_not_sent_to_whoscored_scraper(self):
        spawned: list[str] = []

        def search(fixture, source, **kwargs):
            return {
                "status": "found",
                "candidate": {"url": "https://www.whoscored.com/matches/1993920/live"},
                "candidates": [],
            }

        def spawn(source, url, *args, **kwargs):
            spawned.append(url)

        with mock.patch("recap.source_chain.assess_source", return_value=_Health(True)):
            source_chain.resolve_chain(
                self.livescore, output_root=self.root,
                searcher=search, spawner=spawn,
                watcher=lambda *a, **k: self.who,
            )
        self.assertEqual(spawned, ["https://www.whoscored.com/matches/1993920/live"])
        self.assertNotIn("8888888", spawned[0])

    def test_flashscore_html_import_writes_export(self):
        dest = self.root / "output"
        dest.mkdir()

        def fake_flashscore(*, url, html_path, output_root, wait, log):
            folder = Path(output_root) / "8pBGO97F_Home_vs_Away"
            folder.mkdir()
            (folder / "match_summary.json").write_text(
                '{"matchId":"8pBGO97F","home":{"name":"Home"},"away":{"name":"Away"}}',
                encoding="utf-8",
            )
            (folder / "all_events.csv").write_text("id\n1\n", encoding="utf-8")
            log("imported")

        html = self.root / "flash.html"
        html.write_text(
            '<div class="duelParticipant__home">Home</div>', encoding="utf-8",
        )
        result = scrape.run_scrape(
            url="https://www.flashscore.com/match/football/x/?mid=8pBGO97F",
            html_path=str(html),
            output_root=dest,
            flashscore_fn=fake_flashscore,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "flashscore")
        self.assertTrue(Path(result["match_dir"]).name.startswith("8pBGO97F_"))


if __name__ == "__main__":
    unittest.main()
