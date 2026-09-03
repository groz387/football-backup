"""Flashscore fallback only exports source-backed fields."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from recap.flashscore import export_flashscore, parse_flashscore_html


class FlashscoreTests(unittest.TestCase):
    def test_saved_html_exports_score_and_incidents_without_fake_xy(self):
        payload = {
            "@type": "SportsEvent",
            "identifier": "flash123",
            "name": "Barcelona - Elche",
            "homeTeam": {"name": "Barcelona"},
            "awayTeam": {"name": "Elche"},
            "startDate": "2026-09-03T20:00:00Z",
            "result": {"homeScore": 5, "awayScore": 1},
            "events": [
                {"id": 1, "minute": 12, "type": "Goal", "player": "Yamal", "team": "Barcelona"},
                {"id": 2, "minute": 31, "type": "Yellow Card", "player": "Smith", "team": "Elche"},
            ],
        }
        html = f"<html><head><script type='application/ld+json'>{json.dumps(payload)}</script></head></html>"
        parsed = parse_flashscore_html(html, url="https://www.flashscore.com/match/foo/flash123/")
        self.assertEqual(parsed["summary"]["score"], "5 : 1")
        self.assertEqual(parsed["summary"]["coordinate_source"], "unavailable")
        self.assertEqual(len(parsed["events"]), 2)
        self.assertIsNone(parsed["events"][0]["x"])

        dest = export_flashscore(parsed, Path(tempfile.mkdtemp()))
        self.assertTrue((dest / "match_summary.json").exists())
        self.assertTrue((dest / "SOURCE.md").exists())
        frame = pd.read_csv(dest / "all_events.csv")
        self.assertEqual(len(frame), 2)
        self.assertTrue(frame["x"].isna().all())
        self.assertNotIn("xG", frame.columns)

    def test_missing_teams_fails_instead_of_inventing(self):
        with self.assertRaises(ValueError):
            parse_flashscore_html("<html><title>Flashscore</title></html>")


if __name__ == "__main__":
    unittest.main()
