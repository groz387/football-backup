"""Real Flashscore DOM shape → honest fresh-match recap data."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from recap import audit, director, hooks, i18n
from recap.data import load_match
from recap.flashscore import export_flashscore, parse_flashscore_html

URL = (
    "https://www.flashscore.com/match/football/atl-madrid-jaarqpLQ/"
    "barcelona-SKbpVP5K/?mid=8pBGO97F"
)

SUMMARY = """
<div class="duelParticipant__home"><div class="participant__participantName">Barcelona</div></div>
<div class="duelParticipant__away"><div class="participant__participantName">Atl. Madrid</div></div>
<div class="detailScore__wrapper">0 - 2</div>
<div class="duelParticipant__startTime">08.04.2026 19:00</div>
<div class="detail__breadcrumbs">Football / Europe / Champions League</div>
<div class="smv__participantRow smv__homeParticipant">
  <div class="smv__incident"><div class="smv__timeBox">44'</div>
  <button aria-label="The referee issues a red card."><div class="smv__incidentIcon">
  <svg class="card-ico redCard-ico"></svg></div></button>
  <a class="smv__playerName">Cubarsi P.</a></div>
</div>
<div class="smv__participantRow smv__awayParticipant">
  <div class="smv__incident"><div class="smv__timeBox">45'</div>
  <button aria-label="Julian Alvarez scores."><div class="smv__incidentIcon">
  <div class="smv__incidentAwayScore">0 - 1</div>
  <svg data-testid="wcl-icon-incidents-goal-soccer"></svg></div></button>
  <a class="smv__playerName">Alvarez J.</a></div>
</div>
"""


def stat(label: str, home: str, away: str) -> str:
    return f"""
    <div class="wcl-row_x" data-testid="wcl-statistics">
      <div data-testid="wcl-statistics-value">{home}</div>
      <div data-testid="wcl-statistics-category">{label}</div>
      <div data-testid="wcl-statistics-value">{away}</div>
    </div>
    """


STATS = "".join([
    stat("Expected goals (xG)", "1.10", "0.43"),
    stat("Ball possession", "58%", "42%"),
    stat("Total shots", "18", "5"),
    stat("Big chances", "2", "1"),
    stat("Touches in opposition box", "41", "10"),
])


class FreshFallbackTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        parsed = parse_flashscore_html(SUMMARY, url=URL, stats_html=STATS)
        self.path = export_flashscore(parsed, self.root)
        self.bundle = load_match(self.path)
        self.audit = audit.build_audit(self.bundle)

    def test_real_dom_fields_are_exported(self):
        self.assertEqual(self.bundle.home, "Barcelona")
        self.assertEqual(self.bundle.away, "Atl. Madrid")
        self.assertEqual(self.bundle.score.display, "0-2")
        self.assertEqual(self.bundle.kickoff, "2026-04-08")
        self.assertEqual(len(self.bundle.events), 2)
        self.assertEqual(int(self.bundle.events["isGoal"].sum()), 1)
        self.assertIn("Red", set(self.bundle.events["cardType"]))

    def test_aggregate_stats_stay_out_of_fake_events(self):
        stats = self.audit["team_stats"]
        self.assertEqual(stats["Barcelona"]["shots"], 18)
        self.assertEqual(stats["Atl. Madrid"]["shots"], 5)
        self.assertEqual(stats["Barcelona"]["possession_pct"], 58)
        self.assertEqual(stats["Barcelona"]["xg"], 1.1)
        self.assertFalse(self.audit["data_health"]["has_coordinates"])
        self.assertFalse(self.audit["data_health"]["has_precise_coordinates"])
        self.assertEqual(self.audit["data_health"]["coordinate_source"], "unavailable")

    def test_only_supported_graphs_are_selected(self):
        candidates = director.visualization_candidates(self.bundle, self.audit)
        state = {row["id"]: row["available"] for row in candidates}
        for blocked in ("shot_map", "touch_heatmap", "pass_network", "momentum"):
            self.assertFalse(state.get(blocked, False), blocked)
        selected, _ = director.select_visualizations(self.bundle, self.audit, 3, None, "")
        ids = [row["id"] for row in selected]
        self.assertGreaterEqual(len(ids), 3)
        self.assertTrue(set(ids) <= {
            "sterile_domination", "standard_stats", "goal_timeline", "goal_chain",
            "goalmouth", "zone_control",
        })
        self.assertTrue({"sterile_domination", "standard_stats"} & set(ids))

    def test_script_keeps_full_stat_sentence_instead_of_tease(self):
        selected, _ = director.select_visualizations(self.bundle, self.audit, 3, None, "")
        scenes = director.build_storyboard(self.bundle, self.audit, selected)
        analysis = [
            row for row in scenes
            if row["visualization"] in {item["id"] for item in selected}
        ]
        self.assertTrue(analysis)
        blob = " ".join(row.get("narration") or "" for row in analysis)
        self.assertIn("18", blob)
        self.assertNotIn("BUT READ", blob.upper())

    def test_missing_pool_keys_never_reach_screen(self):
        i18n.set_language("en")
        line = hooks.pool_line(
            ["hook_claim_red_missing", "hook_claim_red_0"],
            "fresh-red",
            n=1,
        )
        self.assertNotIn("hook_claim_", line)
        self.assertTrue(line)


if __name__ == "__main__":
    unittest.main()
