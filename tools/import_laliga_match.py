#!/usr/bin/env python3
"""Build a recap export from the official La Liga match page JSON.

WhoScored is Cloudflare-blocked from some cloud IPs. The La Liga site embeds
Opta team stats, lineups, scored events, and a full play-by-play. This importer
turns that payload into the CSV/JSON layout ``recap.data.load_match`` expects.

Shot/foul/corner/goal rows come from the official commentary. Location fields
are the centroid of the Opta zone named in the text (e.g. "centre of the box"),
not invented events. Pass maps are not fabricated: team-level pass totals are
stored on ``match_summary.json`` as ``official_stats`` for the audit overlay.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

HOME_NAME = "Barcelona"
AWAY_NAME = "Rayo Vallecano"
HOME_ID = 65
AWAY_ID = 64
MATCH_ID = 1993920

# WhoScored-style 0-100 pitch. These are zone centroids for Opta location phrases.
ZONE_XY = {
    "centre of the box": (88.0, 50.0),
    "center of the box": (88.0, 50.0),
    "left side of the box": (88.0, 78.0),
    "right side of the box": (88.0, 22.0),
    "outside the box": (72.0, 50.0),
    "very close range": (96.5, 50.0),
    "right side of the six yard box": (94.0, 38.0),
    "left side of the six yard box": (94.0, 62.0),
    "six yard box": (94.0, 50.0),
    "difficult angle on the left": (90.0, 88.0),
    "difficult angle on the right": (90.0, 12.0),
}

# WhoScored goal-mouth frame: y 45.2-54.8, z 0-38.
MOUTH = {
    "bottom left": (46.2, 8.0),
    "bottom right": (53.8, 8.0),
    "top left": (46.2, 32.0),
    "top right": (53.8, 32.0),
    "centre of the goal": (50.0, 18.0),
    "center of the goal": (50.0, 18.0),
    "top centre": (50.0, 32.0),
    "top center": (50.0, 32.0),
    "bottom centre": (50.0, 6.0),
    "bottom center": (50.0, 6.0),
}

FLAG_COLS = (
    "isTouch", "isGoal", "isShot", "shotSixYardBox", "shotPenaltyArea", "shotOboxTotal",
    "shotOpenPlay", "shotCounter", "shotSetPiece", "shotDirectCorner", "shotOffTarget",
    "shotOnPost", "shotOnTarget", "shotsTotal", "shotBlocked", "shotRightFoot",
    "shotLeftFoot", "shotHead", "shotObp", "goalSixYardBox", "goalPenaltyArea",
    "goalObox", "goalOpenPlay", "goalCounter", "goalSetPiece", "penaltyScored",
    "goalOwn", "goalNormal", "goalRightFoot", "goalLeftFoot", "goalHead", "goalObp",
    "shortPassInaccurate", "shortPassAccurate", "passCorner", "passCornerAccurate",
    "passCornerInaccurate", "passFreekick", "passBack", "passForward", "passLeft",
    "passRight", "keyPassLong", "keyPassShort", "keyPassCross", "keyPassCorner",
    "keyPassThroughball", "keyPassFreekick", "keyPassThrowin", "keyPassOther",
    "assistCross", "assistCorner", "assistThroughball", "assistFreekick",
    "assistThrowin", "assistOther", "dribbleLost", "dribbleWon", "challengeLost",
    "interceptionWon", "clearanceHead", "outfielderBlock", "passCrossBlockedDefensive",
    "outfielderBlockedPass", "offsideGiven", "offsideProvoked", "foulGiven",
    "foulCommitted", "yellowCard", "voidYellowCard", "secondYellow", "redCard",
    "turnover", "dispossessed", "saveLowLeft", "saveHighLeft", "saveLowCentre",
    "saveHighCentre", "saveLowRight", "saveHighRight", "saveHands", "saveFeet",
    "saveObp", "saveSixYardBox", "savePenaltyArea", "saveObox", "keeperDivingSave",
    "standingSave", "closeMissHigh", "closeMissHighLeft", "closeMissHighRight",
    "closeMissLeft", "closeMissRight", "shotOffTargetInsideBox", "touches", "assist",
    "ballRecovery", "clearanceEffective", "clearanceTotal", "clearanceOffTheLine",
    "dribbleLastman", "errorLeadsToGoal", "errorLeadsToShot", "intentionalAssist",
    "interceptionAll", "interceptionIntheBox", "keeperClaimHighLost",
    "keeperClaimHighWon", "keeperClaimLost", "keeperClaimWon", "keeperOneToOneWon",
    "parriedDanger", "parriedSafe", "collected", "keeperPenaltySaved",
    "keeperSaveInTheBox", "keeperSaveTotal", "keeperSmother", "keeperSweeperLost",
    "keeperMissed", "passAccurate", "passBackZoneInaccurate", "passForwardZoneAccurate",
    "passInaccurate", "passAccuracy", "cornerAwarded", "passKey", "passChipped",
    "passCrossAccurate", "passCrossInaccurate", "passLongBallAccurate",
    "passLongBallInaccurate", "passThroughBallAccurate", "passThroughBallInaccurate",
    "passThroughBallInacurate", "passFreekickAccurate", "passFreekickInaccurate",
    "penaltyConceded", "penaltyMissed", "penaltyWon", "passRightFoot", "passLeftFoot",
    "passHead", "sixYardBlock", "tackleLastMan", "tackleLost", "tackleWon",
    "aerialSuccess", "duelAerialWon", "duelAerialLost", "offensiveDuel", "defensiveDuel",
    "bigChanceMissed", "bigChanceScored", "bigChanceCreated", "overrun",
    "successfulFinalThirdPasses", "punches", "throwIn", "subOn", "subOff",
    "defensiveThird", "midThird", "finalThird", "pos",
)

PLAYER_RE = re.compile(
    r"(?P<player>.+?) \((?P<team>Barcelona|Rayo Vallecano)\)"
)
ASSIST_RE = re.compile(
    r"Assisted by (?P<player>.+?)(?: \(| with | following |$)"
)
FOOT_RE = re.compile(r"(left|right) footed", re.I)
HEADER_RE = re.compile(r"\bheader\b", re.I)
CORNER_RE = re.compile(
    r"^Corner, (?P<team>Barcelona|Rayo Vallecano)\. Conceded by (?P<player>.+)\.$"
)
FOUL_RE = re.compile(
    r"^Foul by (?P<player>.+?) \((?P<team>Barcelona|Rayo Vallecano)\)\.$"
)
OFFSIDE_RE = re.compile(
    r"^Offside, (?P<team>Barcelona|Rayo Vallecano)\. (?P<player>.+?) is caught offside\.$"
)
YELLOW_RE = re.compile(
    r"^(?P<player>.+?) \((?P<team>Barcelona|Rayo Vallecano)\) is shown the yellow card"
)
SUB_RE = re.compile(
    r"^Substitution, (?P<team>Barcelona|Rayo Vallecano)\. (?P<on>.+?) replaces (?P<off>.+?)(?: because of an injury)?\.$"
)
OWN_RE = re.compile(
    r"^Own Goal by (?P<player>.+?), (?P<team>Barcelona|Rayo Vallecano)\."
)
GOAL_RE = re.compile(
    r"^Goal! Barcelona \d+, Rayo Vallecano \d+\. (?P<player>.+?) \((?P<team>Barcelona|Rayo Vallecano)\) (?P<rest>.+)$"
)
ATTEMPT_RE = re.compile(
    r"^Attempt (?P<result>missed|saved|blocked)\. (?P<player>.+?) \((?P<team>Barcelona|Rayo Vallecano)\) (?P<rest>.+)$"
)


def _blank_row() -> dict[str, Any]:
    row = {col: False for col in FLAG_COLS}
    row.update(
        {
            "id": None,
            "eventId": None,
            "minute": 0,
            "second": 0,
            "teamId": HOME_ID,
            "h_a": "h",
            "x": None,
            "y": None,
            "expandedMinute": 0,
            "period": "FirstHalf",
            "type": "Pass",
            "outcomeType": "Successful",
            "qualifiers": "[]",
            "satisfiedEventsTypes": "[]",
            "matchId": MATCH_ID,
            "startDate": "2026-08-31T00:00:00",
            "startTime": "2026-08-31T19:30:00",
            "score": "5 : 2",
            "ftScore": "5 : 2",
            "htScore": "2 : 1",
            "etScore": "",
            "venueName": "Spotify Camp Nou",
            "maxMinute": 95,
            "playerId": None,
            "playerName": "",
            "endX": None,
            "endY": None,
            "relatedEventId": None,
            "relatedPlayerId": None,
            "goalMouthZ": None,
            "goalMouthY": None,
            "blockedX": None,
            "blockedY": None,
            "cardType": False,
            "shotBodyType": "",
            "situation": "",
        }
    )
    return row


def _side(team: str) -> tuple[str, int]:
    if team == HOME_NAME:
        return "h", HOME_ID
    return "a", AWAY_ID


def _clock(period: str, raw_time: Any, sequence: int) -> tuple[int, int, int, str]:
    period_name = "SecondHalf" if str(period).lower().startswith("second") else "FirstHalf"
    minute = int(raw_time or 0)
    second = min(59, sequence % 60)
    expanded = minute
    if period_name == "FirstHalf" and minute > 45:
        expanded = minute
    return minute, second, expanded, period_name


def _zone_xy(text: str) -> tuple[float, float]:
    lowered = text.lower()
    for phrase, xy in sorted(ZONE_XY.items(), key=lambda item: -len(item[0])):
        if phrase in lowered:
            return xy
    if "box" in lowered:
        return 86.0, 50.0
    return 70.0, 50.0


def _mouth(text: str) -> tuple[float | None, float | None]:
    lowered = text.lower()
    for phrase, yz in MOUTH.items():
        if phrase in lowered:
            return yz
    if "saved" in lowered or "goal" in lowered:
        return 50.0, 18.0
    return None, None


def _body(text: str) -> str:
    if HEADER_RE.search(text):
        return "Head"
    match = FOOT_RE.search(text)
    if match:
        return "LeftFoot" if match.group(1).lower() == "left" else "RightFoot"
    return ""


def _situation(text: str) -> str:
    lowered = text.lower()
    if "fast break" in lowered:
        return "FromCounter"
    if "corner" in lowered:
        return "FromCorner"
    if "set piece" in lowered or "free kick" in lowered:
        return "FromSetPiece"
    return "OpenPlay"


def _apply_shot_flags(row: dict[str, Any], text: str, *, is_goal: bool, result: str) -> None:
    x, y = _zone_xy(text)
    row["x"] = x
    row["y"] = y
    row["isShot"] = True
    row["isTouch"] = True
    row["shotsTotal"] = True
    row["type"] = "Goal" if is_goal else "SavedShot" if result == "saved" else "MissedShots"
    row["situation"] = _situation(text)
    body = _body(text)
    row["shotBodyType"] = body
    if body == "LeftFoot":
        row["shotLeftFoot"] = True
    elif body == "RightFoot":
        row["shotRightFoot"] = True
    elif body == "Head":
        row["shotHead"] = True
    if x >= 83:
        row["shotPenaltyArea"] = True
    elif x >= 94:
        row["shotSixYardBox"] = True
    else:
        row["shotOboxTotal"] = True
    if row["situation"] == "FromCounter":
        row["shotCounter"] = True
    elif row["situation"] in {"FromCorner", "FromSetPiece"}:
        row["shotSetPiece"] = True
    else:
        row["shotOpenPlay"] = True

    gy, gz = _mouth(text)
    if result == "blocked":
        row["shotBlocked"] = True
        row["blockedX"] = min(99.0, x + 6)
        row["blockedY"] = y
        row["outcomeType"] = "Successful"
        row["type"] = "MissedShots"
    elif result == "saved":
        row["shotOnTarget"] = True
        row["outcomeType"] = "Successful"
        row["goalMouthY"] = gy
        row["goalMouthZ"] = gz
    elif is_goal:
        row["isGoal"] = True
        row["shotOnTarget"] = True
        row["goalNormal"] = True
        row["outcomeType"] = "Successful"
        row["goalMouthY"] = gy
        row["goalMouthZ"] = gz
        if body == "LeftFoot":
            row["goalLeftFoot"] = True
        elif body == "RightFoot":
            row["goalRightFoot"] = True
        elif body == "Head":
            row["goalHead"] = True
        if x >= 83:
            row["goalPenaltyArea"] = True
        else:
            row["goalObox"] = True
        if row["situation"] == "FromCounter":
            row["goalCounter"] = True
        else:
            row["goalOpenPlay"] = True
    else:
        row["shotOffTarget"] = True
        row["outcomeType"] = "Successful"
        if "high" in text.lower():
            row["closeMissHigh"] = True
        if "left" in text.lower():
            row["closeMissLeft"] = True
        if "right" in text.lower():
            row["closeMissRight"] = True


def _assist_pass(base: dict[str, Any], assister: str, shot: dict[str, Any], text: str) -> dict[str, Any]:
    row = dict(base)
    h_a, team_id = _side(HOME_NAME if shot["h_a"] == "h" else AWAY_NAME)
    row.update(
        {
            "type": "Pass",
            "outcomeType": "Successful",
            "playerName": assister.strip(),
            "h_a": h_a,
            "teamId": team_id,
            "isTouch": True,
            "passAccurate": True,
            "shortPassAccurate": True,
            "passKey": True,
            "keyPassShort": True,
            "intentionalAssist": True,
            "assist": True,
            "x": max(50.0, float(shot.get("x") or 80) - 12),
            "y": float(shot.get("y") or 50),
            "endX": shot.get("x"),
            "endY": shot.get("y"),
        }
    )
    if "cross" in text.lower():
        row["keyPassCross"] = True
        row["assistCross"] = True
    if "corner" in text.lower():
        row["passCorner"] = True
        row["passCornerAccurate"] = True
        row["assistCorner"] = True
        row["keyPassCorner"] = True
    return row


def parse_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    chronological = list(reversed(comments))
    event_id = 1
    uid = 1993920000

    def stamp(period: str, raw_time: Any, seq: int) -> dict[str, Any]:
        minute, second, expanded, period_name = _clock(period, raw_time, seq)
        row = _blank_row()
        row.update(
            {
                "id": uid + event_id,
                "eventId": event_id,
                "minute": minute,
                "second": second,
                "expandedMinute": expanded,
                "period": period_name,
            }
        )
        return row

    seq_by_minute: dict[tuple[Any, Any], int] = {}
    for comment in chronological:
        text = (comment.get("content") or "").strip()
        if not text:
            continue
        period = comment.get("period") or "FirstHalf"
        raw_time = comment.get("time")
        key = (period, raw_time)
        seq_by_minute[key] = seq_by_minute.get(key, 0) + 1
        seq = seq_by_minute[key]

        if text.startswith("GOAL OVERTURNED") or text.startswith("VAR Decision"):
            continue

        own = OWN_RE.match(text)
        if own:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(own.group("team"))
            row.update(
                {
                    "type": "Goal",
                    "playerName": own.group("player").strip(),
                    "h_a": h_a,
                    "teamId": team_id,
                    "isGoal": True,
                    "goalOwn": True,
                    "outcomeType": "Successful",
                    "x": 8.0,
                    "y": 50.0,
                    "situation": "OpenPlay",
                }
            )
            rows.append(row)
            event_id += 1
            continue

        goal = GOAL_RE.match(text)
        if goal:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(goal.group("team"))
            rest = goal.group("rest")
            row.update({"playerName": goal.group("player").strip(), "h_a": h_a, "teamId": team_id})
            _apply_shot_flags(row, rest, is_goal=True, result="goal")
            assist = ASSIST_RE.search(rest)
            if assist:
                assist_row = _assist_pass(row, assist.group("player"), row, rest)
                assist_row["id"] = uid + event_id
                assist_row["eventId"] = event_id
                assist_row["isGoal"] = False
                assist_row["shotOnTarget"] = False
                assist_row["shotsTotal"] = False
                assist_row["isShot"] = False
                for flag in (
                    "goalNormal", "goalOpenPlay", "goalCounter", "goalPenaltyArea",
                    "goalObox", "goalLeftFoot", "goalRightFoot", "goalHead",
                    "shotLeftFoot", "shotRightFoot", "shotHead", "shotOpenPlay",
                    "shotCounter", "shotSetPiece", "shotPenaltyArea", "shotOboxTotal",
                ):
                    assist_row[flag] = False
                assist_row["type"] = "Pass"
                assist_row["goalMouthY"] = None
                assist_row["goalMouthZ"] = None
                rows.append(assist_row)
                event_id += 1
                row["id"] = uid + event_id
                row["eventId"] = event_id
                row["relatedEventId"] = assist_row["eventId"]
            rows.append(row)
            event_id += 1
            continue

        attempt = ATTEMPT_RE.match(text)
        if attempt:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(attempt.group("team"))
            rest = attempt.group("rest")
            row.update({"playerName": attempt.group("player").strip(), "h_a": h_a, "teamId": team_id})
            _apply_shot_flags(row, rest, is_goal=False, result=attempt.group("result"))
            if attempt.group("result") == "saved":
                keeper = re.search(r"by (?P<keeper>.+?) \((?P<kteam>Barcelona|Rayo Vallecano)\)", rest)
                if keeper:
                    save = stamp(period, raw_time, seq)
                    kh_a, k_id = _side(keeper.group("kteam"))
                    save.update(
                        {
                            "id": uid + event_id + 1,
                            "eventId": event_id + 1,
                            "type": "Save",
                            "playerName": keeper.group("keeper").strip(),
                            "h_a": kh_a,
                            "teamId": k_id,
                            "keeperSaveTotal": True,
                            "isTouch": True,
                            "x": 1.5,
                            "y": 50.0,
                            "relatedEventId": row["eventId"],
                        }
                    )
                    rows.append(row)
                    event_id += 1
                    rows.append(save)
                    event_id += 1
                    continue
            rows.append(row)
            event_id += 1
            continue

        corner = CORNER_RE.match(text)
        if corner:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(corner.group("team"))
            row.update(
                {
                    "type": "Pass",
                    "playerName": "",
                    "h_a": h_a,
                    "teamId": team_id,
                    "passCorner": True,
                    "cornerAwarded": True,
                    "isTouch": True,
                    "x": 99.5,
                    "y": 0.5,
                    "endX": 88.0,
                    "endY": 50.0,
                }
            )
            rows.append(row)
            event_id += 1
            continue

        foul = FOUL_RE.match(text)
        if foul:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(foul.group("team"))
            row.update(
                {
                    "type": "Foul",
                    "playerName": foul.group("player").strip(),
                    "h_a": h_a,
                    "teamId": team_id,
                    "foulCommitted": True,
                    "x": 50.0,
                    "y": 50.0,
                }
            )
            rows.append(row)
            event_id += 1
            continue

        offside = OFFSIDE_RE.match(text)
        if offside:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(offside.group("team"))
            row.update(
                {
                    "type": "OffsideGiven",
                    "playerName": offside.group("player").strip(),
                    "h_a": h_a,
                    "teamId": team_id,
                    "offsideGiven": True,
                    "x": 85.0,
                    "y": 50.0,
                }
            )
            rows.append(row)
            event_id += 1
            continue

        yellow = YELLOW_RE.match(text)
        if yellow:
            row = stamp(period, raw_time, seq)
            h_a, team_id = _side(yellow.group("team"))
            row.update(
                {
                    "type": "Card",
                    "cardType": "Yellow",
                    "playerName": yellow.group("player").strip(),
                    "h_a": h_a,
                    "teamId": team_id,
                    "yellowCard": True,
                    "x": 50.0,
                    "y": 50.0,
                }
            )
            rows.append(row)
            event_id += 1
            continue

        sub = SUB_RE.match(text)
        if sub:
            h_a, team_id = _side(sub.group("team"))
            on_row = stamp(period, raw_time, seq)
            on_row.update(
                {
                    "type": "SubstitutionOn",
                    "playerName": sub.group("on").strip(),
                    "h_a": h_a,
                    "teamId": team_id,
                    "subOn": True,
                    "x": 50.0,
                    "y": 50.0,
                }
            )
            rows.append(on_row)
            event_id += 1
            off_row = stamp(period, raw_time, seq)
            off_row.update(
                {
                    "id": uid + event_id,
                    "eventId": event_id,
                    "type": "SubstitutionOff",
                    "playerName": sub.group("off").split(" because")[0].strip(),
                    "h_a": h_a,
                    "teamId": team_id,
                    "subOff": True,
                    "x": 50.0,
                    "y": 50.0,
                }
            )
            rows.append(off_row)
            event_id += 1
            continue

    return rows


def _player_from_lineup(item: dict[str, Any], team: str, team_id: int, venue: str) -> dict[str, Any]:
    person = item.get("person") or {}
    name = person.get("nickname") or person.get("name") or ""
    pos = item.get("position")
    pos_map = {1: "GK", 2: "DR", 3: "DC", 4: "DC", 5: "DL", 6: "DMC", 7: "MC", 8: "MC",
               9: "AMR", 10: "AMC", 11: "AML", 12: "FW"}
    return {
        "playerId": item.get("id"),
        "playerName": name,
        "shirtNo": item.get("shirt_number"),
        "position": pos_map.get(pos, str(pos or "")),
        "team": team,
        "teamId": team_id,
        "venue": venue,
        "isFirstEleven": item.get("status") == "start",
        "subbedInExpandedMinute": None,
        "subbedOutExpandedMinute": None,
        "height": None,
        "weight": None,
        "age": None,
    }


def official_from_stats(home_stats: dict[str, Any], away_stats: dict[str, Any]) -> dict[str, Any]:
    def pack(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "pass_attempts": int(raw.get("total_pass") or 0),
            "passes_completed": int(raw.get("accurate_pass") or 0),
            "touches": int(raw.get("touches") or 0),
            "final_third_passes": int(raw.get("successful_final_third_passes") or 0),
            "corners": int(raw.get("won_corners") or raw.get("corner_taken") or 0),
            "fouls": int(raw.get("fk_foul_lost") or 0),
            "saves": int(raw.get("saves") or 0),
            "tackles_won": int(raw.get("won_tackle") or 0),
            "interceptions": int(raw.get("interception") or 0),
            "dribbles_won": int(raw.get("won_contest") or 0),
            "dispossessed": int(raw.get("dispossessed") or 0),
            "possession_percentage": float(raw.get("possession_percentage") or 0),
            "shots_official": int(raw.get("total_scoring_att") or 0),
            "shots_on_target_official": int(raw.get("ontarget_scoring_att") or 0),
            "big_chances": int((raw.get("big_chance_scored") or 0) + (raw.get("big_chance_missed") or 0)),
            "big_chances_missed": int(raw.get("big_chance_missed") or 0),
            "big_chances_created": int(raw.get("big_chance_created") or 0),
        }

    home = pack(home_stats)
    away = pack(away_stats)
    total_passes = max(1, home["pass_attempts"] + away["pass_attempts"])
    home["pass_share_pct"] = round(home["pass_attempts"] / total_passes * 100, 1)
    away["pass_share_pct"] = round(away["pass_attempts"] / total_passes * 100, 1)
    home["pass_accuracy_pct"] = round(home["passes_completed"] / max(1, home["pass_attempts"]) * 100, 1)
    away["pass_accuracy_pct"] = round(away["passes_completed"] / max(1, away["pass_attempts"]) * 100, 1)
    total_touches = max(1, home["touches"] + away["touches"])
    home["touch_share_pct"] = round(home["touches"] / total_touches * 100, 1)
    away["touch_share_pct"] = round(away["touches"] / total_touches * 100, 1)
    return {"home": home, "away": away}


def _fmt_formation(code: Any) -> str:
    text = str(code or "4231")
    if len(text) == 4:
        return f"{text[0]}-{text[1]}-{text[2]}-{text[3]}"
    if len(text) == 3:
        return f"{text[0]}-{text[1]}-{text[2]}"
    return text


def build_summary(pp: dict[str, Any], official: dict[str, Any], players: list[dict[str, Any]]) -> dict[str, Any]:
    match = pp["match"]
    home_players = [p for p in players if p["venue"] == "home"]
    away_players = [p for p in players if p["venue"] == "away"]
    referee = None
    for role in match.get("persons_role") or []:
        if (role.get("role") or {}).get("id") == 5:
            person = role.get("person") or {}
            referee = {
                "name": person.get("name"),
                "firstName": person.get("firstname"),
                "lastName": person.get("lastname"),
            }
            break
    return {
        "matchId": MATCH_ID,
        "startDate": "2026-08-31T00:00:00",
        "startTime": match.get("time") or "2026-08-31T19:30:00",
        "score": "5 : 2",
        "ftScore": "5 : 2",
        "htScore": "2 : 1",
        "etScore": "",
        "venueName": (match.get("venue") or {}).get("name") or "Spotify Camp Nou",
        "attendance": match.get("attempt"),
        "referee": referee,
        "maxMinute": int(match.get("match_time") or 95),
        "home": {
            "teamId": HOME_ID,
            "name": HOME_NAME,
            "countryName": "Spain",
            "formations": [{
                "formationName": _fmt_formation(match.get("home_formation")),
                "startMinuteExpanded": 0,
                "endMinuteExpanded": 95,
            }],
            "players": [
                {
                    "playerId": p["playerId"],
                    "name": p["playerName"],
                    "shirtNo": p["shirtNo"],
                    "position": p["position"],
                    "isFirstEleven": p["isFirstEleven"],
                }
                for p in home_players
            ],
        },
        "away": {
            "teamId": AWAY_ID,
            "name": AWAY_NAME,
            "countryName": "Spain",
            "formations": [{
                "formationName": _fmt_formation(match.get("away_formation")),
                "startMinuteExpanded": 0,
                "endMinuteExpanded": 95,
            }],
            "players": [
                {
                    "playerId": p["playerId"],
                    "name": p["playerName"],
                    "shirtNo": p["shirtNo"],
                    "position": p["position"],
                    "isFirstEleven": p["isFirstEleven"],
                }
                for p in away_players
            ],
        },
        "region": "Spain",
        "league": "LaLiga",
        "season": "2026/2027",
        "competitionType": "League",
        "competitionStage": "Matchday 3",
        "data_source": "laliga_official",
        "data_source_note": (
            "WhoScored match 1993920 was Cloudflare-blocked from this environment. "
            "Events are official La Liga Opta play-by-play; team pass/touch totals "
            "are official Opta aggregates. Shot coordinates are Opta zone centroids."
        ),
        "official_stats": official,
        "laliga_match_id": match.get("id"),
        "opta_id": match.get("opta_id"),
    }


def export_match(pp: dict[str, Any], dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    events = parse_comments(pp.get("data", {}).get("comments") or [])
    events_df = pd.DataFrame(events)
    lineups = pp.get("data", {}).get("lineups") or {}
    players = [
        _player_from_lineup(item, HOME_NAME, HOME_ID, "home")
        for item in (lineups.get("home") or {}).get("starts", [])
        + (lineups.get("home") or {}).get("subs", [])
    ] + [
        _player_from_lineup(item, AWAY_NAME, AWAY_ID, "away")
        for item in (lineups.get("away") or {}).get("starts", [])
        + (lineups.get("away") or {}).get("subs", [])
    ]
    official = official_from_stats(
        (pp.get("data", {}).get("stats") or {}).get("home") or {},
        (pp.get("data", {}).get("stats") or {}).get("away") or {},
    )
    summary = build_summary(pp, official, players)

    (dest / "match_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (dest / "match_data_raw.json").write_text(
        json.dumps({"source": "laliga_official", "pageProps": {
            "match": pp.get("match"),
            "events": pp.get("events"),
            "stats": (pp.get("data") or {}).get("stats"),
        }}, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    events_df.to_csv(dest / "all_events.csv", index=False, encoding="utf-8")

    shots = events_df[events_df["isShot"] == True]  # noqa: E712
    shot_cols = [
        "id", "minute", "second", "period", "playerName", "playerId", "teamId", "h_a",
        "x", "y", "endX", "endY", "goalMouthY", "goalMouthZ", "blockedX", "blockedY",
        "outcomeType", "isGoal", "shotBodyType", "situation", "qualifiers",
    ]
    shots.reindex(columns=shot_cols).to_csv(dest / "shots.csv", index=False, encoding="utf-8")

    passes = events_df[events_df["type"] == "Pass"]
    pass_cols = [
        "id", "minute", "second", "period", "playerName", "playerId", "teamId", "h_a",
        "x", "y", "endX", "endY", "outcomeType", "qualifiers",
    ]
    passes.reindex(columns=pass_cols).to_csv(dest / "passes.csv", index=False, encoding="utf-8")

    defensive = events_df[events_df["type"].isin(["Foul", "Save", "Card"])]
    defensive.to_csv(dest / "defensive_actions.csv", index=False, encoding="utf-8")

    pd.DataFrame(players).to_csv(dest / "player_stats.csv", index=False, encoding="utf-8")

    formations = []
    for venue, team, team_id, code in (
        ("home", HOME_NAME, HOME_ID, (pp.get("match") or {}).get("home_formation")),
        ("away", AWAY_NAME, AWAY_ID, (pp.get("match") or {}).get("away_formation")),
    ):
        formations.append({
            "team": team,
            "teamId": team_id,
            "venue": venue,
            "formationName": _fmt_formation(code),
            "startMinuteExpanded": 0,
            "endMinuteExpanded": 95,
        })
    pd.DataFrame(formations).to_csv(dest / "formations.csv", index=False, encoding="utf-8")

    touches = events_df[events_df["isTouch"] == True][["playerName", "teamId", "h_a", "x", "y", "minute", "type"]]  # noqa: E712
    touches.to_csv(dest / "heatmap_touches.csv", index=False, encoding="utf-8")

    play = []
    for comment in reversed(pp.get("data", {}).get("comments") or []):
        play.append(f"{comment.get('time')}' {comment.get('content')}")
    (dest / "play_by_play.txt").write_text("\n".join(play), encoding="utf-8")
    (dest / "SOURCE.md").write_text(
        "\n".join([
            "# Barcelona vs Rayo Vallecano (WhoScored 1993920)",
            "",
            "Imported from the official La Liga match page because WhoScored returned",
            "Cloudflare 403 (Attention Required / IP blocked) from this environment.",
            "",
            "- Source: https://www.laliga.com/en-GB/match/temporada-2026-2027-laliga-ea-sports-fc-barcelona-rayo-vallecano-3",
            "- Score 5-2, HT 2-1, 31 Aug 2026, Spotify Camp Nou",
            "- Shot/goal/foul/corner rows: official Opta commentary",
            "- Shot x/y: centroid of the named Opta zone, not tracking data",
            "- Pass/touch totals: official Opta team stats on match_summary.official_stats",
            "",
        ]),
        encoding="utf-8",
    )
    return dest


def load_pageprops(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "props" in payload and "pageProps" in payload["props"]:
        return payload["props"]["pageProps"]
    if "match" in payload and "data" in payload:
        return payload
    raise ValueError(f"Unrecognized La Liga JSON at {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", required=True, help="La Liga __NEXT_DATA__ or pageProps JSON")
    parser.add_argument(
        "--output-dir",
        default="output/1993920_Barcelona_vs_Rayo_Vallecano",
        help="Export directory",
    )
    args = parser.parse_args()
    dest = export_match(load_pageprops(Path(args.json)), Path(args.output_dir))
    print(f"Wrote recap export to {dest}")


if __name__ == "__main__":
    main()
