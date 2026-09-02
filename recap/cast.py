"""Star-player packaging for recap videos.

People tap short-form recaps because a face and a name are on the poster
(Yamal, Pedri, Lewandowski). This module picks **1–2** players that actually
appear in the WhoScored export, locks three numbers to each, and suggests a
lowercase on-screen title.

It never invents a player. Search aliases are derived from the name string
that is already in the data (case, accents, initials, first/last splits) —
not from a celebrity dictionary. Incomplete WhoScored names (``L. Yamal``,
blank, ``Unknown``) degrade rather than get a guessed first name.

Heuristic (MOTM-like composite, then a headline role):

    score = 10*goals + 6*assists + 1.15*shots + 0.85*on_target
          + 1.35*dribbles + 2.4*saves + 1.5*key_passes + 0.8*tackles
          + 3.2*max(0, rating-6)

``--star auto`` (default) keeps the top player and a complementary second
if they clear the bar. ``--star off`` emits an empty pack. ``--star <name>``
matches aliases already derived from the export; a miss is empty, not a
made-up star.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .audit import keeper_saves
from .data import MatchBundle, clean_text, flag, text_col

MAX_CAST = 2
LOCKED_NUMBERS = 3
MIN_SCORE = 5.0
SECOND_RATIO = 0.48
KEEPER_WALL_SAVES = 4
SPIKE_POINTS = 40
PREFIX_MATCH_MIN = 4

WEIGHTS = {
    "goals": 10.0,
    "assists": 6.0,
    "shots": 1.15,
    "shots_on_target": 0.85,
    "dribbles": 1.35,
    "saves": 2.4,
    "key_passes": 1.5,
    "tackles": 0.8,
}
RATING_CENTER = 6.0
RATING_WEIGHT = 3.2

# First names that make a poor poster on their own. Surname wins instead.
# Kept small and generic so Lamine / Pedri / Brahim / Kylian stay first-name titles.
COMMON_GIVEN = frozenset(
    {
        "alex", "alexander", "andrew", "anthony", "antonio", "carlos", "chris",
        "christopher", "daniel", "david", "diego", "fernando", "francisco",
        "gabriel", "ivan", "james", "jean", "john", "jose", "juan", "kevin",
        "luis", "marco", "mark", "martin", "matthew", "michael", "miguel",
        "mohamed", "mohammed", "ahmed", "omar", "paul", "pedro", "peter",
        "pierre", "rafael", "ricardo", "robert", "sergio", "steven", "thomas",
        "william", "andres", "andrea", "lucas", "mario", "pablo",
    }
)
NAME_PARTICLES = frozenset(
    {"el", "al", "de", "da", "del", "van", "von", "di", "la", "le", "du", "bin", "bint", "ben"}
)
JUNK_NAMES = frozenset({"", "unknown", "nan", "none", "-", ".", "n/a", "player"})

# Role → keys to lead the three locked numbers (then fill from NUMBER_MENU).
ROLE_LEAD_KEYS = {
    "scorer": ("goals", "shots", "assists"),
    "assist": ("assists", "key_passes", "shots"),
    "keeper": ("saves", "rating", "touches"),
    "dribbles": ("dribbles", "shots", "key_passes"),
    "shots": ("shots", "shots_on_target", "goals"),
    "motm": ("rating", "shots", "key_passes"),
}
NUMBER_MENU = (
    ("goals", "goals"),
    ("assists", "assists"),
    ("saves", "saves"),
    ("dribbles", "dribbles"),
    ("shots", "shots"),
    ("shots_on_target", "on target"),
    ("key_passes", "key passes"),
    ("tackles", "tackles"),
    ("rating", "rating"),
    ("touches", "touches"),
)
SPIKE_ACTION = {
    "scorer": "shots",
    "shots": "shots",
    "dribbles": "dribbles",
    "keeper": "saves",
    "assist": "key_passes",
    "motm": "shots",
}
# Poster order: the face people tap first is usually the scorer.
PRESENT_ORDER = {"scorer": 0, "keeper": 1, "assist": 2, "dribbles": 3, "shots": 4, "motm": 5}

_INITIAL = re.compile(r"^[A-Za-zÀ-ÿ]\.?$")
_SPACES = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# names / aliases
# ---------------------------------------------------------------------------

def fold_ascii(text: str) -> str:
    """Lowercase ASCII fold: Díaz → diaz, so social spellings still match."""
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.replace("ß", "ss").replace("æ", "ae").replace("ø", "o")
    raw = raw.replace("'", "").replace("’", "").replace("`", "")
    raw = re.sub(r"[^a-z0-9]+", " ", raw.lower())
    return _SPACES.sub(" ", raw).strip()


def _tokens(folded: str) -> list[str]:
    return [part for part in folded.split(" ") if part]


def search_aliases(name: str) -> list[str]:
    """Social spellings that are obvious from *name* itself.

    First / last / initials / concatenated / hyphen and apostrophe stripped /
    accent-folded. Nothing is added from a famous-player table.
    """
    folded = fold_ascii(name)
    if not folded:
        return []
    tokens = _tokens(folded)
    aliases: set[str] = {folded, folded.replace(" ", "")}
    for token in tokens:
        if len(token) >= 2 and token not in NAME_PARTICLES:
            aliases.add(token)
    if len(tokens) >= 2:
        first, last = tokens[0], tokens[-1]
        aliases.add(f"{first} {last}")
        aliases.add(f"{first}{last}")
        if len(first) >= 1 and len(last) >= 2:
            aliases.add(f"{first[0]} {last}")
            aliases.add(f"{first[0]}.{last}")
            aliases.add(f"{first[0]}. {last}")
            aliases.add(f"{first[0]}{last}")
        if tokens[-2] in NAME_PARTICLES:
            compound = f"{tokens[-2]} {last}"
            aliases.add(compound)
            aliases.add(compound.replace(" ", ""))
    # Hyphenated tokens already split by fold_ascii; keep the unsplit last word
    # if the original still has a hyphen.
    if "-" in str(name):
        aliases.add(fold_ascii(name.replace("-", "")))
    return sorted({item for item in aliases if item}, key=lambda item: (len(item), item))


def name_quality(name: str) -> str:
    """How complete the WhoScored label is. Never upgraded from outside data."""
    cleaned = clean_text(name)
    if not _usable_name(cleaned):
        return "empty"
    tokens = cleaned.split()
    if tokens and _INITIAL.match(tokens[0]) and len(tokens) >= 2:
        return "initials"
    if len(tokens) == 1:
        return "single"
    return "full"


def _usable_name(name: str) -> bool:
    folded = fold_ascii(name)
    return bool(folded) and folded not in JUNK_NAMES


def _is_initial_token(token: str) -> bool:
    return bool(_INITIAL.match(token.strip()))


def split_display_name(name: str) -> tuple[str, str]:
    tokens = [part for part in clean_text(name).split() if part]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], tokens[0]
    first = tokens[0]
    if len(tokens) >= 3 and fold_ascii(tokens[-2]) in NAME_PARTICLES:
        last = f"{tokens[-2]} {tokens[-1]}"
    else:
        last = tokens[-1]
    return first, last


def suggest_title(name: str, *, role: str = "", saves: int = 0, quality: str = "") -> str:
    """Lowercase poster line: ``lamine.`` / ``the wall`` / ``lewandowski``."""
    quality = quality or name_quality(name)
    first, last = split_display_name(name)
    if role == "keeper":
        if int(saves or 0) >= KEEPER_WALL_SAVES:
            return "the wall"
        token = last if last and not _is_initial_token(last) else first
        return fold_ascii(token)
    if quality in {"initials", "empty"}:
        token = last if last and not _is_initial_token(last) else first
        return fold_ascii(token)
    if quality == "single" or fold_ascii(first) == fold_ascii(last):
        return fold_ascii(first or last)
    given = fold_ascii(first)
    if given and given not in COMMON_GIVEN and len(given) >= 5 and not _is_initial_token(first):
        return f"{given}."
    return fold_ascii(last or first)


def parse_star(value: str | None) -> tuple[str, str]:
    """Return ``(mode, query)`` for ``auto|off|<name>``. ``auto``/``off`` are reserved."""
    raw = str(value if value is not None else "auto").strip()
    if not raw:
        return "auto", ""
    key = fold_ascii(raw)
    if key == "off":
        return "off", ""
    if key == "auto":
        return "auto", ""
    return "name", raw


# ---------------------------------------------------------------------------
# roster
# ---------------------------------------------------------------------------

@dataclass
class _Player:
    key: str
    player_id: str = ""
    name: str = ""
    team: str = ""
    h_a: str = ""
    position: str = ""
    goals: int = 0
    assists: int = 0
    shots: int = 0
    shots_on_target: int = 0
    dribbles: int = 0
    saves: int = 0
    key_passes: int = 0
    tackles: int = 0
    touches: int = 0
    rating: float | None = None
    shot_points: list[dict[str, float]] = field(default_factory=list)
    dribble_points: list[dict[str, float]] = field(default_factory=list)
    save_points: list[dict[str, float]] = field(default_factory=list)
    key_pass_points: list[dict[str, float]] = field(default_factory=list)
    sides: list[str] = field(default_factory=list)

    @property
    def quality(self) -> str:
        return name_quality(self.name)

    @property
    def score(self) -> float:
        total = 0.0
        for key, weight in WEIGHTS.items():
            total += int(getattr(self, key) or 0) * weight
        if self.rating is not None:
            total += max(0.0, float(self.rating) - RATING_CENTER) * RATING_WEIGHT
        return round(total, 3)

    @property
    def role(self) -> str:
        if self.goals >= 1:
            return "scorer"
        is_keeper = self.position.upper().startswith("GK") or self.saves >= 3
        if is_keeper and self.saves >= 1 and self.saves >= max(self.shots, self.dribbles, 1):
            return "keeper"
        if self.assists >= 1 and self.assists * WEIGHTS["assists"] >= max(
            self.dribbles * WEIGHTS["dribbles"], self.shots * WEIGHTS["shots"]
        ):
            return "assist"
        if self.dribbles >= 3 and self.dribbles >= self.shots:
            return "dribbles"
        if self.shots >= 3:
            return "shots"
        return "motm"

    def qualifies(self) -> bool:
        if not _usable_name(self.name):
            return False
        if self.goals >= 1 or self.assists >= 1:
            return True
        if self.score >= MIN_SCORE:
            return True
        return self.shots >= 4 or self.dribbles >= 4 or self.saves >= 3


def _player_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() in JUNK_NAMES:
        return ""
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _coord(row: pd.Series) -> dict[str, float] | None:
    try:
        x, y = float(row.get("x")), float(row.get("y"))
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isnan(y):
        return None
    return {"x": round(x, 2), "y": round(y, 2)}


def _prefer_name(current: str, candidate: str) -> str:
    """Keep the more complete label already in the export. Never invent one."""
    cand = clean_text(candidate)
    cur = clean_text(current)
    if not _usable_name(cand):
        return cur
    if not _usable_name(cur):
        return cand
    cur_q, cand_q = name_quality(cur), name_quality(cand)
    rank = {"empty": 0, "initials": 1, "single": 2, "full": 3}
    if rank.get(cand_q, 0) > rank.get(cur_q, 0):
        return cand
    if cand_q == cur_q and len(cand) > len(cur):
        return cand
    return cur


def _rating_from_stats(row: pd.Series) -> float | None:
    values: list[float] = []
    for column, value in row.items():
        if not str(column).startswith("ratings_"):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(number) or number <= 0:
            continue
        values.append(number)
    if not values:
        return None
    return round(max(values), 2)


def _point_list(points: list[dict[str, float]]) -> list[dict[str, float]]:
    return points[:SPIKE_POINTS]


def build_roster(bundle: MatchBundle, audit: dict[str, Any] | None = None) -> list[_Player]:
    events = bundle.events
    if events is None or events.empty:
        return []

    names = text_col(events, "playerName")
    sides = text_col(events, "h_a")
    types = text_col(events, "type")
    successful = text_col(events, "outcomeType").eq("Successful")
    is_goal = flag(events, "isGoal") & ~flag(events, "goalOwn")
    is_shot = flag(events, "isShot")
    on_target = flag(events, "shotOnTarget")
    is_assist = flag(events, "assist") | flag(events, "intentionalAssist")
    is_dribble = types.eq("TakeOn") & successful
    is_save = keeper_saves(events)
    is_key = flag(events, "passKey")
    is_tackle = flag(events, "tackleWon")
    is_touch = flag(events, "isTouch")

    slots: dict[str, _Player] = {}

    def slot_for(index: int) -> _Player | None:
        pid = _player_id(events["playerId"].iloc[index]) if "playerId" in events.columns else ""
        name = clean_text(names.iloc[index])
        key = pid or fold_ascii(name)
        if not key:
            return None
        player = slots.get(key)
        if player is None:
            player = _Player(key=key, player_id=pid, name=name if _usable_name(name) else "")
            slots[key] = player
        else:
            if pid and not player.player_id:
                player.player_id = pid
            player.name = _prefer_name(player.name, name)
        h_a = clean_text(sides.iloc[index])
        if h_a in {"h", "a"}:
            player.sides.append(h_a)
        return player

    def add_point(bucket: list[dict[str, float]], row: pd.Series) -> None:
        point = _coord(row)
        if point and len(bucket) < SPIKE_POINTS:
            bucket.append(point)

    for pos in range(len(events)):
        player = slot_for(pos)
        if player is None:
            continue
        row = events.iloc[pos]
        if bool(is_goal.iloc[pos]):
            player.goals += 1
        if bool(is_assist.iloc[pos]):
            player.assists += 1
        if bool(is_shot.iloc[pos]):
            player.shots += 1
            add_point(player.shot_points, row)
            if bool(on_target.iloc[pos]):
                player.shots_on_target += 1
        if bool(is_dribble.iloc[pos]):
            player.dribbles += 1
            add_point(player.dribble_points, row)
        if bool(is_save.iloc[pos]):
            player.saves += 1
            add_point(player.save_points, row)
        if bool(is_key.iloc[pos]):
            player.key_passes += 1
            add_point(player.key_pass_points, row)
        if bool(is_tackle.iloc[pos]):
            player.tackles += 1
        if bool(is_touch.iloc[pos]):
            player.touches += 1

    _enrich_from_player_stats(bundle, slots)
    _enrich_assists_from_chains(audit, slots)

    roster: list[_Player] = []
    for player in slots.values():
        if not _usable_name(player.name):
            continue
        if player.sides:
            player.h_a = max(set(player.sides), key=player.sides.count)
        player.team = player.team or bundle.team(player.h_a or "h")
        roster.append(player)
    return roster


def _enrich_from_player_stats(bundle: MatchBundle, slots: dict[str, _Player]) -> None:
    stats = bundle.players
    if stats is None or stats.empty:
        return
    by_id: dict[str, pd.Series] = {}
    by_name: dict[str, pd.Series] = {}
    for _, row in stats.iterrows():
        pid = _player_id(row.get("playerId"))
        label = clean_text(row.get("playerName"))
        if pid:
            by_id[pid] = row
        if _usable_name(label):
            by_name[fold_ascii(label)] = row

    for player in slots.values():
        row = by_id.get(player.player_id) if player.player_id else None
        if row is None:
            row = by_name.get(fold_ascii(player.name))
        if row is None:
            continue
        player.name = _prefer_name(player.name, row.get("playerName"))
        position = clean_text(row.get("position"))
        if position:
            player.position = position
        team = clean_text(row.get("team"))
        if team:
            player.team = team
        venue = fold_ascii(clean_text(row.get("venue")))
        if venue == "home":
            player.h_a = player.h_a or "h"
        elif venue == "away":
            player.h_a = player.h_a or "a"
        rating = _rating_from_stats(row)
        if rating is not None:
            player.rating = rating


def _enrich_assists_from_chains(audit: dict[str, Any] | None, slots: dict[str, _Player]) -> None:
    """Credit ``goal_chains.assist_player`` when the event flag was missing."""
    if not audit:
        return
    by_fold = {fold_ascii(player.name): player for player in slots.values() if _usable_name(player.name)}
    for chain in audit.get("goal_chains") or []:
        if chain.get("own_goal"):
            continue
        label = clean_text(chain.get("assist_player"))
        if not _usable_name(label):
            continue
        player = by_fold.get(fold_ascii(label))
        if player is None or player.assists > 0:
            continue
        player.assists += 1


def _query_hits(player: _Player, query: str) -> bool:
    folded = fold_ascii(query)
    if not folded:
        return False
    aliases = set(search_aliases(player.name))
    if folded in aliases:
        return True
    if len(folded) >= PREFIX_MATCH_MIN:
        return any(alias.startswith(folded) for alias in aliases)
    return False


def pick_stars(roster: list[_Player]) -> list[_Player]:
    ranked = sorted(roster, key=lambda player: (-player.score, -player.goals, -player.assists, player.name))
    qualified = [player for player in ranked if player.qualifies()]
    if not qualified:
        return []
    lead = qualified[0]
    picked = [lead]
    for candidate in qualified[1:]:
        if len(picked) >= MAX_CAST:
            break
        if candidate.score < lead.score * SECOND_RATIO and candidate.goals == 0 and candidate.assists == 0:
            continue
        if candidate.role == lead.role and candidate.role in {"shots", "dribbles", "motm"}:
            if candidate.score < lead.score * 0.75:
                continue
        picked.append(candidate)
    picked.sort(key=lambda player: (PRESENT_ORDER.get(player.role, 9), -player.score, player.name))
    return picked


def _stat_value(player: _Player, key: str) -> int | float | None:
    if key == "rating":
        return None if player.rating is None else round(float(player.rating), 2)
    return int(getattr(player, key) or 0)


def locked_numbers(player: _Player) -> list[dict[str, Any]]:
    """Exactly three numbers, all taken from this player's measured stats."""
    lead = list(ROLE_LEAD_KEYS.get(player.role, ROLE_LEAD_KEYS["motm"]))
    ordered: list[str] = []
    for key in lead + [item[0] for item in NUMBER_MENU]:
        if key not in ordered:
            ordered.append(key)
    labels = {key: label for key, label in NUMBER_MENU}
    nonzero: list[dict[str, Any]] = []
    zeros: list[dict[str, Any]] = []
    for key in ordered:
        value = _stat_value(player, key)
        if value is None:
            continue
        item = {"key": key, "value": value, "label": labels.get(key, key.replace("_", " "))}
        if isinstance(value, (int, float)) and value == 0:
            zeros.append(item)
        else:
            nonzero.append(item)
    chosen = (nonzero + zeros)[:LOCKED_NUMBERS]
    return chosen


def spike_payload(player: _Player) -> dict[str, Any] | None:
    action = SPIKE_ACTION.get(player.role, "shots")
    buckets = {
        "shots": (player.shot_points, player.shots),
        "dribbles": (player.dribble_points, player.dribbles),
        "saves": (player.save_points, player.saves),
        "key_passes": (player.key_pass_points, player.key_passes),
    }
    points, count = buckets.get(action, (player.shot_points, player.shots))
    if count <= 0 and not points:
        # Fall back to whichever action actually has coordinates.
        for fallback, (bucket, n) in buckets.items():
            if n > 0 or bucket:
                action, points, count = fallback, bucket, n
                break
    if count <= 0 and not points:
        return None
    first, last = split_display_name(player.name)
    surname = last or first
    return {
        "player": player.name,
        "surname": surname,
        "team": player.team,
        "h_a": player.h_a,
        "action": action,
        "count": int(count),
        "points": _point_list(points),
        "title": suggest_title(player.name, role=player.role, saves=player.saves, quality=player.quality),
    }


def fact_pack(player: _Player) -> dict[str, Any]:
    numbers = locked_numbers(player)
    first, last = split_display_name(player.name)
    return {
        "player_id": player.player_id or None,
        "name": player.name,
        "team": player.team,
        "h_a": player.h_a,
        "position": player.position,
        "name_quality": player.quality,
        "role": player.role,
        "title": suggest_title(player.name, role=player.role, saves=player.saves, quality=player.quality),
        "score": player.score,
        "numbers": numbers,
        "aliases": search_aliases(player.name),
        "stats": {
            "goals": player.goals,
            "assists": player.assists,
            "shots": player.shots,
            "shots_on_target": player.shots_on_target,
            "dribbles": player.dribbles,
            "saves": player.saves,
            "key_passes": player.key_passes,
            "tackles": player.tackles,
            "touches": player.touches,
            "rating": player.rating,
        },
        "surname": last or first,
        "spike": spike_payload(player),
    }


def empty_cast(mode: str, query: str = "", reason: str = "") -> dict[str, Any]:
    return {"mode": mode, "query": query, "players": [], "reason": reason}


def package_cast(
    bundle: MatchBundle,
    audit: dict[str, Any] | None = None,
    star: str = "auto",
) -> dict[str, Any]:
    """Pick 1–2 cast members. Never emits a name that is not in the export."""
    mode, query = parse_star(star)
    if mode == "off":
        return empty_cast("off", reason="star packaging off")

    roster = build_roster(bundle, audit)
    if not roster:
        return empty_cast(mode, query, reason="no named players in the export")

    if mode == "name":
        hits = [player for player in roster if _query_hits(player, query)]
        if not hits:
            return empty_cast("name", query, reason=f"no player matching {query!r} in the export")
        hits.sort(key=lambda player: (-player.score, -player.goals, player.name))
        return {"mode": "name", "query": query, "players": [fact_pack(hits[0])], "reason": ""}

    picked = pick_stars(roster)
    if not picked:
        return empty_cast("auto", reason="no player cleared the star heuristic")
    return {
        "mode": "auto",
        "query": "",
        "players": [fact_pack(player) for player in picked],
        "reason": "",
    }


def apply_cast_to_audit(audit: dict[str, Any], packed: dict[str, Any]) -> dict[str, Any]:
    """Attach the pack and, when possible, reuse it as ``player_leaders.spike``."""
    audit["cast"] = packed
    players = packed.get("players") or []
    if not players:
        return audit
    spike = players[0].get("spike")
    if not isinstance(spike, dict):
        return audit
    leaders = dict(audit.get("player_leaders") or {})
    existing = leaders.get("spike") if isinstance(leaders.get("spike"), dict) else None
    if spike.get("points") or not existing:
        leaders["spike"] = spike
    leaders["cast"] = players[0].get("name")
    audit["player_leaders"] = leaders
    return audit


def apply_cast(bundle: MatchBundle, audit: dict[str, Any], star: str = "auto") -> dict[str, Any]:
    return apply_cast_to_audit(audit, package_cast(bundle, audit, star=star))


def describe_cast(packed: dict[str, Any]) -> list[str]:
    players = packed.get("players") or []
    if not players:
        reason = packed.get("reason") or "no star cast"
        return [str(reason)]
    lines = []
    for player in players:
        nums = ", ".join(f"{item['value']} {item['label']}" for item in player.get("numbers") or [])
        title = player.get("title") or ""
        name = player.get("name") or ""
        team = player.get("team") or ""
        lines.append(f"{title}  {name} ({team})  {nums}".strip())
    return lines


def compact_cast(packed: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Gemini-brief slice: name, team, title, role, three numbers."""
    rows = []
    for player in (packed or {}).get("players") or []:
        rows.append(
            {
                "name": player.get("name"),
                "team": player.get("team"),
                "title": player.get("title"),
                "role": player.get("role"),
                "numbers": player.get("numbers") or [],
            }
        )
    return rows
