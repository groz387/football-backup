"""Color clash + Livescore parse + WhoScored source health.

Uses the checked-in exports:

* ``1993920_Barcelona_vs_Rayo_Vallecano`` — official La Liga import, reconstructed centroids
* ``1953861_Scotland_vs_Morocco`` — WhoScored chalkboard, precise tracking x/y
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest import mock

from recap import colors, ingest, resolve_match, theme
from recap.livescore import resolve_url
from video_pipeline import parse_args

ROOT = Path(__file__).resolve().parents[1]
BARCA = ROOT / "output" / "1993920_Barcelona_vs_Rayo_Vallecano"
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"

BARCA_URL = "https://www.livescore.com/en/football/spain/laliga/barcelona-vs-rayo-vallecano/"
SCOTLAND_URL = "https://www.livescore.com/en/football/international/world-cup/scotland-vs-morocco/"


class ColorTests(unittest.TestCase):
    def tearDown(self) -> None:
        theme.set_team_colors(None, None)
        theme.set_team_kind("national")

    def test_barca_burgundy_gold(self) -> None:
        kit = colors.kit_for("Barça", "club")
        self.assertEqual(kit.primary, colors.BARCA_BURGUNDY)
        self.assertEqual(kit.secondary, colors.BARCA_GOLD)
        theme.set_team_kind("club")
        ident = theme.team_identity("FC Barcelona")
        self.assertEqual(ident["primary"].lower(), colors.BARCA_BURGUNDY)
        self.assertEqual(ident["secondary"].lower(), colors.BARCA_GOLD)

    def test_red_kits_one_wears_secondary(self) -> None:
        pair = colors.resolve_pair("Liverpool", "Arsenal", kind="club")
        self.assertTrue(pair.conflict)
        self.assertTrue(pair.away.used_secondary or pair.home.used_secondary)
        self.assertNotEqual(pair.home.fill, pair.away.fill)
        theme.set_team_kind("club")
        design = theme.match_design("Liverpool", "Manchester United")
        self.assertNotEqual(design["home"]["fill"], design["away"]["fill"])

    def test_distinct_kits_keep_primaries(self) -> None:
        pair = colors.resolve_pair("Scotland", "Morocco", kind="national")
        self.assertFalse(pair.conflict)
        self.assertFalse(pair.home.used_secondary)
        self.assertFalse(pair.away.used_secondary)

    def test_cli_colors_override(self) -> None:
        pair = colors.resolve_pair(
            "Liverpool", "Arsenal", kind="club",
            override_home="#004170", override_away="#95bfe5",
        )
        self.assertFalse(pair.conflict)
        self.assertEqual(pair.reason, "cli --colors override")
        self.assertEqual(pair.home.fill, "#004170")
        theme.set_team_kind("club")
        theme.set_team_colors("#004170", "#95bfe5")
        design = theme.match_design("Liverpool", "Arsenal")
        self.assertEqual(design["home"]["fill"], "#004170")
        self.assertEqual(design["away"]["fill"], "#95bfe5")


class LivescoreParseTests(unittest.TestCase):
    def test_canonical_path(self) -> None:
        fixture = resolve_match.parse_livescore_url(BARCA_URL)
        self.assertEqual(colors.canonical_key(fixture.home), "barcelona")
        self.assertEqual(colors.canonical_key(fixture.away), "rayo vallecano")
        self.assertIn("liga", (fixture.competition or "").lower())
        parsed = ingest.parse_livescore_url(BARCA_URL)
        self.assertEqual(parsed["home"], "Barcelona")
        self.assertEqual(parsed["away"], "Rayo Vallecano")

    def test_tabs_and_date_query(self) -> None:
        url = (
            "https://www.livescore.com/en/football/spain/laliga/"
            "fc-barcelona-vs-rayo-vallecano/1993920/lineups/?date=2026-08-31"
        )
        fixture = resolve_match.parse_livescore_url(url)
        self.assertEqual(fixture.date, "2026-08-31")
        self.assertEqual(fixture.event_id, "1993920")
        self.assertEqual(colors.canonical_key(fixture.home), "barcelona")

    def test_rejects_other_hosts(self) -> None:
        with self.assertRaises(ValueError):
            resolve_match.parse_livescore_url("https://www.whoscored.com/Matches/1953861/Live")


class SourceHealthTests(unittest.TestCase):
    def test_reconstructed_vs_real_coords(self) -> None:
        if not BARCA.is_dir() or not SCOTLAND.is_dir():
            self.skipTest("sample exports missing")
        barca = resolve_match.assess_source(BARCA)
        scotland = resolve_match.assess_source(SCOTLAND)
        self.assertEqual(barca.coordinate_source, "reconstructed")
        self.assertFalse(barca.has_precise_coordinates)
        self.assertFalse(barca.full_events)
        self.assertFalse(barca.healthy)
        self.assertFalse(barca.invented_coordinates)

        self.assertEqual(scotland.coordinate_source, "whoscored")
        self.assertTrue(scotland.has_precise_coordinates)
        self.assertTrue(scotland.full_events)
        self.assertTrue(scotland.healthy)
        self.assertGreater(scotland.unique_xy, barca.unique_xy)
        self.assertGreater(scotland.pass_rows, 100)

    def test_resolve_finds_local_without_inventing(self) -> None:
        if not BARCA.is_dir():
            self.skipTest("barca export missing")
        resolved = ingest.resolve(livescore_url=BARCA_URL, output_root=ROOT / "output")
        self.assertTrue(resolved["ok"])
        self.assertEqual(Path(resolved["match_dir"]).name, BARCA.name)
        self.assertEqual(resolved["coordinate_source"], "reconstructed")
        names = {row["name"]: row["status"] for row in resolved["adapters"]}
        self.assertEqual(names.get("sofascore"), "stub")
        self.assertEqual(names.get("fotmob"), "stub")
        self.assertEqual(names.get("understat"), "stub")

        via_studio = resolve_url(BARCA_URL, output_root=ROOT / "output")
        self.assertEqual(Path(via_studio["match_dir"]).name, BARCA.name)

        typed = resolve_match.resolve_from_livescore(BARCA_URL, output_root=ROOT / "output")
        self.assertEqual(typed.match_dir.name, BARCA.name)
        self.assertFalse(typed.health.invented_coordinates)

    def test_scotland_livescore_is_healthy_whoscored(self) -> None:
        if not SCOTLAND.is_dir():
            self.skipTest("scotland export missing")
        typed = resolve_match.resolve_from_livescore(SCOTLAND_URL, output_root=ROOT / "output")
        self.assertEqual(typed.match_dir.name, SCOTLAND.name)
        self.assertTrue(typed.health.healthy)
        self.assertEqual(typed.adapter, "whoscored_local")

    def test_missing_fixture_does_not_fabricate_xy(self) -> None:
        result = ingest.resolve(
            livescore_url="https://www.livescore.com/en/football/az/prem/qarabag-vs-imaginarytown/",
            output_root=ROOT / "output",
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["match_dir"])
        with self.assertRaises(FileNotFoundError):
            resolve_match.resolve_from_livescore(
                "https://www.livescore.com/en/football/az/prem/qarabag-vs-imaginarytown/",
                output_root=ROOT / "output",
            )


class CliFlagTests(unittest.TestCase):
    def test_livescore_url_does_not_clobber_match_dir(self) -> None:
        args = parse_args([
            "--auto", "--match-dir", "output/x",
            "--livescore-url", BARCA_URL,
        ])
        self.assertEqual(args.match_dir, "output/x")
        self.assertEqual(args.livescore_url, BARCA_URL)

    def test_help_lists_livescore_url(self) -> None:
        buf = io.StringIO()
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stdout", buf):
                parse_args(["--help"])
        self.assertIn("--livescore-url", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
