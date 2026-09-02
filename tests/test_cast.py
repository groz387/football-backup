"""Star-player packaging: heuristic, aliases, fact packs, --star flag."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from recap.cast import (
    LOCKED_NUMBERS,
    MAX_CAST,
    apply_cast,
    compact_cast,
    fold_ascii,
    name_quality,
    package_cast,
    parse_star,
    search_aliases,
    suggest_title,
)
from recap.data import MatchBundle, Score
from video_pipeline import parse_args

SCOTLAND = Path("/workspace/output/1953861_Scotland_vs_Morocco")


def _bundle(events, players=None, home="Barcelona", away="Madrid", score=(2, 0)):
    return MatchBundle(
        match_dir=Path("."),
        summary={"home": {"name": home}, "away": {"name": away}, "score": f"{score[0]} : {score[1]}"},
        events=pd.DataFrame(events),
        passes=pd.DataFrame(),
        shots=pd.DataFrame(),
        touches=pd.DataFrame(),
        players=pd.DataFrame(players or []),
        score=Score(home=score[0], away=score[1]),
    )


def _row(name, h_a="h", **kwargs):
    row = {"playerName": name, "h_a": h_a}
    row.update(kwargs)
    return row


class ParseStarTests(unittest.TestCase):
    def test_auto_off_name(self):
        self.assertEqual(parse_star(None), ("auto", ""))
        self.assertEqual(parse_star(""), ("auto", ""))
        self.assertEqual(parse_star("auto"), ("auto", ""))
        self.assertEqual(parse_star("OFF"), ("off", ""))
        self.assertEqual(parse_star("Yamal"), ("name", "Yamal"))
        self.assertEqual(parse_star("brahim diaz"), ("name", "brahim diaz"))

    def test_cli_default_and_unique_flag(self):
        default = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertEqual(default.star, "auto")
        named = parse_args(["--auto", "--match-dir", "output/x", "--star", "Yamal"])
        self.assertEqual(named.star, "Yamal")
        off = parse_args(["--auto", "--match-dir", "output/x", "--star", "off", "--still"])
        self.assertEqual(off.star, "off")
        self.assertTrue(off.still)


class AliasAndTitleTests(unittest.TestCase):
    def test_aliases_from_name_string_only(self):
        aliases = set(search_aliases("Lamine Yamal"))
        self.assertIn("lamine yamal", aliases)
        self.assertIn("yamal", aliases)
        self.assertIn("lamine", aliases)
        self.assertIn("l yamal", aliases)
        self.assertIn("lamineyamal", aliases)
        self.assertNotIn("lamine yamal jr", aliases)
        self.assertNotIn("pedri", aliases)

    def test_incomplete_name_does_not_invent_first_name(self):
        aliases = set(search_aliases("L. Yamal"))
        self.assertIn("yamal", aliases)
        self.assertNotIn("lamine", aliases)
        self.assertNotIn("lamine yamal", aliases)
        self.assertEqual(name_quality("L. Yamal"), "initials")
        self.assertEqual(suggest_title("L. Yamal"), "yamal")

    def test_titles(self):
        self.assertEqual(suggest_title("Lamine Yamal"), "lamine.")
        self.assertEqual(suggest_title("Pedri"), "pedri")
        self.assertEqual(suggest_title("Robert Lewandowski"), "lewandowski")
        self.assertEqual(suggest_title("Wojciech Szczęsny", role="keeper", saves=6), "the wall")
        self.assertEqual(suggest_title("Wojciech Szczęsny", role="keeper", saves=1), "szczesny")

    def test_accent_fold_for_social_spelling(self):
        aliases = set(search_aliases("Brahim Díaz"))
        self.assertIn("diaz", aliases)
        self.assertIn("brahim diaz", aliases)
        self.assertEqual(fold_ascii("Szczęsny"), "szczesny")


class HeuristicTests(unittest.TestCase):
    def setUp(self):
        events = []
        for x, y, goal, on in ((88, 40, True, True), (85, 50, False, True), (90, 45, False, False)):
            events.append(_row(
                "Lamine Yamal", playerId=11, isShot=True, isGoal=goal, shotOnTarget=on,
                x=x, y=y, isTouch=True,
            ))
        for _ in range(5):
            events.append(_row(
                "Lamine Yamal", playerId=11, type="TakeOn", outcomeType="Successful",
                x=72, y=18, isTouch=True,
            ))
        events.append(_row(
            "Pedri", playerId=8, type="Pass", outcomeType="Successful",
            assist=True, passKey=True, x=60, y=50, isTouch=True,
        ))
        events.append(_row(
            "Pedri", playerId=8, type="Pass", outcomeType="Successful",
            passKey=True, x=62, y=48, isTouch=True,
        ))
        events.append(_row(
            "Robert Lewandowski", playerId=9, isShot=True, x=80, y=50, isTouch=True,
        ))
        events.append(_row("Unknown", playerId=99, isShot=True, isGoal=True, x=90, y=50))
        events.append(_row("", playerId=98, isGoal=True, h_a="a"))
        events.append(_row(
            "Marc-André ter Stegen", playerId=1, type="Save", keeperSaveTotal=True,
            x=6, y=50,
        ))
        players = [
            {"playerId": 11, "playerName": "Lamine Yamal", "team": "Barcelona",
             "venue": "home", "position": "AMR", "ratings_0": 8.4},
            {"playerId": 8, "playerName": "Pedri", "team": "Barcelona",
             "venue": "home", "position": "MC", "ratings_0": 7.6},
            {"playerId": 9, "playerName": "Robert Lewandowski", "team": "Barcelona",
             "venue": "home", "position": "FW", "ratings_0": 6.4},
            {"playerId": 1, "playerName": "Marc-André ter Stegen", "team": "Barcelona",
             "venue": "home", "position": "GK", "ratings_0": 6.8},
        ]
        self.bundle = _bundle(events, players)

    def test_auto_picks_scorer_and_complement_from_data_only(self):
        packed = package_cast(self.bundle, star="auto")
        names = [player["name"] for player in packed["players"]]
        self.assertEqual(packed["mode"], "auto")
        self.assertLessEqual(len(names), MAX_CAST)
        self.assertIn("Lamine Yamal", names)
        self.assertNotIn("Unknown", names)
        self.assertNotIn("", names)
        self.assertNotIn("Erling Haaland", names)

    def test_fact_pack_schema(self):
        packed = package_cast(self.bundle, star="auto")
        star = packed["players"][0]
        self.assertEqual(star["name"], "Lamine Yamal")
        self.assertEqual(star["team"], "Barcelona")
        self.assertEqual(star["title"], "lamine.")
        self.assertEqual(star["role"], "scorer")
        self.assertEqual(len(star["numbers"]), LOCKED_NUMBERS)
        keys = {item["key"] for item in star["numbers"]}
        self.assertIn("goals", keys)
        for item in star["numbers"]:
            self.assertIn(item["key"], star["stats"])
            self.assertEqual(item["value"], star["stats"][item["key"]])
        self.assertEqual(star["stats"]["goals"], 1)
        self.assertEqual(star["stats"]["dribbles"], 5)
        self.assertIsNotNone(star["spike"])
        self.assertEqual(star["spike"]["action"], "shots")
        self.assertGreaterEqual(len(star["spike"]["points"]), 1)
        json.dumps(packed)

    def test_star_name_and_alias_hit(self):
        packed = package_cast(self.bundle, star="yamal")
        self.assertEqual(len(packed["players"]), 1)
        self.assertEqual(packed["players"][0]["name"], "Lamine Yamal")
        folded = package_cast(self.bundle, star="L. Yamal")
        self.assertEqual(folded["players"][0]["name"], "Lamine Yamal")

    def test_star_miss_does_not_invent(self):
        packed = package_cast(self.bundle, star="Haaland")
        self.assertEqual(packed["players"], [])
        self.assertIn("Haaland", packed["reason"])
        self.assertEqual(compact_cast(packed), [])

    def test_star_off(self):
        packed = package_cast(self.bundle, star="off")
        self.assertEqual(packed["mode"], "off")
        self.assertEqual(packed["players"], [])

    def test_own_goal_is_not_a_star_goal(self):
        bundle = _bundle([
            _row("Own Player", playerId=4, h_a="h", isGoal=True, goalOwn=True, isShot=True, x=10, y=50),
            _row("Quiet Mid", playerId=5, h_a="a", type="Pass", outcomeType="Successful", isTouch=True),
        ])
        packed = package_cast(bundle, star="auto")
        names = [player["name"] for player in packed["players"]]
        self.assertNotIn("Own Player", names)

    def test_incomplete_who_scored_label_stays_incomplete(self):
        bundle = _bundle([
            _row("L. Yamal", playerId=11, isShot=True, isGoal=True, shotOnTarget=True, x=88, y=40),
            _row("L. Yamal", playerId=11, isShot=True, x=84, y=44),
            _row("L. Yamal", playerId=11, type="TakeOn", outcomeType="Successful", x=70, y=20),
            _row("L. Yamal", playerId=11, type="TakeOn", outcomeType="Successful", x=71, y=22),
            _row("L. Yamal", playerId=11, type="TakeOn", outcomeType="Successful", x=72, y=18),
            _row("L. Yamal", playerId=11, type="TakeOn", outcomeType="Successful", x=73, y=19),
        ])
        packed = package_cast(bundle, star="auto")
        self.assertEqual(packed["players"][0]["name"], "L. Yamal")
        self.assertEqual(packed["players"][0]["title"], "yamal")
        self.assertNotIn("lamine", packed["players"][0]["aliases"])

    def test_keeper_wall_title_and_saves(self):
        events = []
        for i in range(5):
            events.append(_row(
                "Wojciech Szczęsny", playerId=1, type="Save", keeperSaveTotal=True,
                x=5, y=48 + i, h_a="h",
            ))
        events.append(_row("Bench Forward", playerId=2, isShot=True, x=80, y=50, h_a="a"))
        players = [
            {"playerId": 1, "playerName": "Wojciech Szczęsny", "team": "Barcelona",
             "venue": "home", "position": "GK", "ratings_0": 8.1},
        ]
        packed = package_cast(_bundle(events, players, score=(0, 0)), star="auto")
        keeper = packed["players"][0]
        self.assertEqual(keeper["role"], "keeper")
        self.assertEqual(keeper["title"], "the wall")
        self.assertEqual(keeper["stats"]["saves"], 5)

    def test_apply_cast_overlays_spike(self):
        audit = {"player_leaders": {"spike": {"player": "someone else", "count": 2, "points": []}}}
        audit = apply_cast(self.bundle, audit, star="auto")
        self.assertEqual(audit["cast"]["players"][0]["name"], "Lamine Yamal")
        self.assertEqual(audit["player_leaders"]["spike"]["player"], "Lamine Yamal")
        self.assertEqual(len(audit["cast"]["players"][0]["numbers"]), 3)


class LiveExportTests(unittest.TestCase):
    def test_scotland_morocco_cast(self):
        if not (SCOTLAND / "all_events.csv").exists():
            self.skipTest("Scotland vs Morocco export is not on disk")
        from recap.audit import build_audit
        from recap.data import load_match

        bundle = load_match(SCOTLAND)
        audit = apply_cast(bundle, build_audit(bundle), star="auto")
        names = [player["name"] for player in audit["cast"]["players"]]
        self.assertLessEqual(len(names), 2)
        self.assertEqual(names[0], "Ismael Saibari")
        self.assertTrue(all(name in set(bundle.events["playerName"].dropna().astype(str)) for name in names))
        saibari = next(player for player in audit["cast"]["players"] if player["name"] == "Ismael Saibari")
        self.assertEqual(saibari["stats"]["goals"], 1)
        self.assertEqual(len(saibari["numbers"]), 3)
        miss = package_cast(bundle, audit, star="Yamal")
        self.assertEqual(miss["players"], [])
        hit = package_cast(bundle, audit, star="saibari")
        self.assertEqual(hit["players"][0]["name"], "Ismael Saibari")
        off = package_cast(bundle, audit, star="off")
        self.assertEqual(off["players"], [])
        diaz = package_cast(bundle, audit, star="diaz")
        self.assertEqual(diaz["players"][0]["name"], "Brahim Díaz")


if __name__ == "__main__":
    unittest.main()
