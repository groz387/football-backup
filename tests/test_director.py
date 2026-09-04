"""Evidence-first scripts stay near 17 words; curses stay on the bookends."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from recap import director, timing
from recap.data import MatchBundle, Score


def _bundle() -> MatchBundle:
    empty = pd.DataFrame()
    return MatchBundle(
        match_dir=Path("."),
        summary={"home": {"name": "Barcelona"}, "away": {"name": "Atletico"}},
        events=empty,
        passes=empty,
        shots=empty,
        touches=empty,
        players=empty,
        score=Score(home=2, away=1),
    )


def _stats(shots: int, on_target: int, **extra) -> dict:
    row = {
        "shots": shots,
        "shots_on_target": on_target,
        "shots_blocked": 0,
        "big_chances": 2,
        "goals": 1,
        "pass_share_pct": 58.0,
        "possession_pct": 61.0,
        "pass_accuracy_pct": 88.0,
        "pass_attempts": 400,
        "passes_completed": 350,
        "final_third_passes": 40,
        "box_entry_passes": 12,
        "penalty_box_touches": 18,
        "tackles_won": 9,
        "saves": 3,
        "dribbles_won": 4,
        "xg": 1.4,
    }
    row.update(extra)
    return row


def _audit(bundle: MatchBundle) -> dict:
    return {
        "match": {"score_display": "2-1", "score_qualifier": "full time"},
        "facts": [],
        "definitions": {},
        "team_stats": {
            bundle.home: _stats(18, 7, goals=2, xg=2.1),
            bundle.away: _stats(5, 2, goals=1, xg=0.6, pass_share_pct=42.0),
        },
        "data_health": {
            "has_vendor_xg": True,
            "has_vendor_xgot": False,
            "has_vendor_possession": True,
            "blocked_claims": [],
        },
        "source_supported_stats": ["shots", "shots_on_target", "xg", "possession_pct"],
        "shots": [],
        "momentum": [
            {"start": 60, "end": 65, "swing": 4.2, "minute_block": "60-65", "period": "SecondHalf"}
        ],
        "field_tilt": [],
        "zone_control": [
            {"xbin": 0, "ybin": 0, "home_touches": 12, "away_touches": 3, "total_touches": 15,
             "home_share_pct": 80.0},
            {"xbin": 1, "ybin": 1, "home_touches": 4, "away_touches": 9, "total_touches": 13,
             "home_share_pct": 30.8},
        ],
        "goal_timeline": [
            {"minute": 12, "team": bundle.home, "scorer": "Lewandowski", "h_a": "h", "clock": 12},
            {"minute": 81, "team": bundle.home, "scorer": "Yamal", "h_a": "h", "clock": 81},
        ],
        "clock_axis": {"end": 90.0, "ticks": [], "boundaries": []},
        "touch_heatmap": {"home": [[1]], "away": [[1]]},
        "player_leaders": {"spike": None},
        "press_trap": {"leader": bundle.home, "leader_ppda": 7.2, "audited": True},
        "duels": {"home": {"total": 22}, "away": {"total": 14}},
        "aerials": {"home_won": 8, "away_won": 5},
        "bench_impact": {"subs": [1, 2, 3]},
        "halftime_split": {
            "first": {"home_shots": 9, "away_shots": 2},
            "second": {"home_shots": 9, "away_shots": 3},
        },
        "hook": {"kind": "volume_upset", "numbers": [18, 5], "never_say": []},
    }


class BookendTests(unittest.TestCase):
    def test_lock_bookends_strips_body_keeps_open_and_close(self) -> None:
        scenes = [
            {"id": "hook_claim", "visualization": "hook_claim",
             "narration": "This is fucking ridiculous."},
            {"id": "shot_map", "visualization": "shot_map",
             "narration": "They had 18 shots and shit finishing."},
            {"id": "micro_hook", "visualization": "micro_hook",
             "title": "bloody hell look at this", "lines": ["bloody hell look at this"]},
            {"id": "close", "visualization": "close",
             "narration": "Who the fuck was best?"},
        ]
        locked = director.lock_bookends(scenes)
        self.assertIn("fuck", locked[0]["narration"])
        self.assertNotRegex(locked[1]["narration"], r"shit")
        self.assertNotRegex(locked[2]["title"], r"bloody hell")
        self.assertIn("fuck", locked[3]["narration"])
        report = director.bookend_report(locked)
        self.assertTrue(report["clean_body"])

    def test_kids_mode_strips_the_bookends_too(self) -> None:
        scenes = [
            {"id": "hook_claim", "visualization": "hook_claim", "narration": "fucking hell"},
            {"id": "close", "visualization": "close", "narration": "Who the fuck was best?"},
        ]
        locked = director.lock_bookends(scenes, kids=True)
        self.assertNotRegex(locked[0]["narration"], r"fuck")
        self.assertNotRegex(locked[1]["narration"], r"fuck")


class EvidenceWordTests(unittest.TestCase):
    def test_fit_keeps_digits_and_caps_near_seventeen(self) -> None:
        long_line = (
            "Barcelona put 18 shots on the tape and Atletico only answered with 5 "
            "from a whole night of sterile pressure and leftover noise extra filler"
        )
        fitted = director.fit_evidence_narration(long_line)
        words = timing.word_count(fitted)
        self.assertLessEqual(words, director.EVIDENCE_WORD_MAX)
        self.assertGreaterEqual(words, director.EVIDENCE_WORD_MIN)
        self.assertIn("18", fitted)
        self.assertIn("5", fitted)

    def test_analysis_copy_stays_evidence_sized(self) -> None:
        bundle = _bundle()
        audit = _audit(bundle)
        for viz_id in ("shot_map", "zone_control", "touch_heatmap", "momentum"):
            copy = director._visual_copy(bundle, audit, viz_id)
            line = director.fit_evidence_narration(copy["narration"])
            words = timing.word_count(line)
            self.assertGreaterEqual(words, 8, f"{viz_id}: {line}")
            self.assertLessEqual(words, director.EVIDENCE_WORD_MAX, f"{viz_id}: {line}")
            self.assertRegex(line, r"\d", f"{viz_id} must keep an audited number")


if __name__ == "__main__":
    unittest.main()
