"""Livescore source search, visible command, and fallback order."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from recap import source_chain
from recap.resolve_match import parse_livescore_url

ROOT = Path(__file__).resolve().parents[1]
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"
BARCA = ROOT / "output" / "1993920_Barcelona_vs_Rayo_Vallecano"


class SearchTests(unittest.TestCase):
    def test_candidate_ranking_uses_both_teams_and_date(self):
        fixture = parse_livescore_url(
            "https://www.livescore.com/en/football/international/friendly/"
            "scotland-vs-morocco/2026-06-19/"
        )
        html = """
        <a href="/matches/111/live/scotland-morocco">Scotland vs Morocco 2025-01-01</a>
        <a href="/matches/1953861/live/scotland-morocco">Scotland vs Morocco 2026-06-19</a>
        """
        result = source_chain.rank_candidates(
            source_chain.parse_search_candidates(
                html, "https://www.whoscored.com", source="whoscored",
            ),
            fixture,
        )
        self.assertEqual(result["status"], "found")
        self.assertIn("1953861", result["candidate"]["url"])

    def test_ambiguous_candidates_are_not_guessed(self):
        fixture = parse_livescore_url(
            "https://www.livescore.com/en/football/spain/laliga/barcelona-vs-elche/"
        )
        rows = [
            {"url": "https://www.whoscored.com/matches/1/live", "text": "Barcelona Elche", "context": "Barcelona Elche", "date": ""},
            {"url": "https://www.whoscored.com/matches/2/live", "text": "Barcelona Elche", "context": "Barcelona Elche", "date": ""},
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

    def test_linux_command_is_direct(self):
        with mock.patch.object(source_chain.os, "name", "posix"):
            command = source_chain.visible_command(
                "flashscore", "https://www.flashscore.com/match/abc", "/tmp/output", 12,
            )
        self.assertIn("scrape_flashscore.py", command[1])
        self.assertIn("--url", command)


class ChainTests(unittest.TestCase):
    def test_whoscored_full_stops_before_flashscore(self):
        calls = []

        def search(fixture, source, **kwargs):
            calls.append(source)
            return {"status": "found", "candidate": {"url": f"https://{source}.test/match"}, "candidates": []}

        result = source_chain.resolve_chain(
            "https://www.livescore.com/en/football/international/friendly/"
            "foo-vs-bar/2026-06-19/",
            output_root=ROOT / "output",
            searcher=search,
            spawner=lambda *a, **k: None,
            watcher=lambda *a, **k: SCOTLAND,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["full"])
        self.assertEqual(result["source"], "whoscored")
        self.assertEqual(calls, ["whoscored"])

    def test_limited_whoscored_tries_flashscore(self):
        calls = []

        def search(fixture, source, **kwargs):
            calls.append(source)
            return {"status": "found", "candidate": {"url": f"https://{source}.test/match"}, "candidates": []}

        result = source_chain.resolve_chain(
            "https://www.livescore.com/en/football/spain/laliga/foo-vs-bar/",
            output_root=ROOT / "output",
            searcher=search,
            spawner=lambda *a, **k: None,
            watcher=lambda *a, **k: BARCA,
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["full"])
        self.assertEqual(result["source"], "flashscore")
        self.assertEqual(calls, ["whoscored", "flashscore"])


if __name__ == "__main__":
    unittest.main()
