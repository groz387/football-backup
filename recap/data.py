"""Loading a scraped WhoScored export into something the renderers can trust."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import i18n

TRUE_VALUES = {"true", "1", "yes", "y", "t"}

NUMERIC_COLUMNS = (
    "minute",
    "second",
    "expandedMinute",
    "x",
    "y",
    "endX",
    "endY",
    "goalMouthY",
    "goalMouthZ",
    "blockedX",
    "blockedY",
)

EXTRA_TIME_PERIODS = {"FirstPeriodOfExtraTime", "SecondPeriodOfExtraTime"}
SHOOTOUT_PERIODS = {"PenaltyShootout"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", str(value), flags=re.ASCII).strip("_")
    return cleaned or "match"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def num(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric view of *col*, or an all-NaN column when it is missing."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def flag(df: pd.DataFrame, col: str) -> pd.Series:
    """Boolean view of a WhoScored flag column, tolerant of str/bool/NaN mixes."""
    if col not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    series = df[col]
    if series.dtype == bool:
        return series.fillna(False)
    return series.fillna(False).astype(str).str.strip().str.lower().isin(TRUE_VALUES)


def text_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[col].fillna("").astype(str)


def clean_text(value: Any, fallback: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return fallback
    text = str(value).strip()
    return text if text and text.lower() != "nan" else fallback


def parse_qualifiers(raw: Any) -> list[dict[str, Any]]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Score:
    """A displayable scoreline.

    WhoScored writes the aggregate as e.g. ``"*3 : 1"``, where the asterisk
    means the tie was settled after ninety minutes. Nothing outside this class
    should ever touch that raw string.
    """

    home: int
    away: int
    after_extra_time: bool = False
    after_shootout: bool = False
    ninety_minute: tuple[int, int] | None = None

    @property
    def display(self) -> str:
        return f"{self.home}-{self.away}"

    @property
    def qualifier(self) -> str:
        return i18n.score_qualifier(self.after_extra_time, self.after_shootout)

    @property
    def total_goals(self) -> int:
        return self.home + self.away

    @property
    def margin(self) -> int:
        return abs(self.home - self.away)

    @property
    def is_draw(self) -> bool:
        return self.home == self.away

    def sentence(self, home_name: str, away_name: str) -> str:
        base = f"{home_name} {self.home}-{self.away} {away_name}"
        return f"{base} ({self.qualifier.lower()})" if self.qualifier else base

    def as_dict(self) -> dict[str, Any]:
        return {
            "home": self.home,
            "away": self.away,
            "display": self.display,
            "after_extra_time": self.after_extra_time,
            "after_shootout": self.after_shootout,
            "ninety_minute": list(self.ninety_minute) if self.ninety_minute else None,
        }


def _digit_pair(raw: Any) -> tuple[int, int] | None:
    digits = re.findall(r"\d+", str(raw or ""))
    if len(digits) < 2:
        return None
    return int(digits[0]), int(digits[1])


def build_score(summary: dict[str, Any], events: pd.DataFrame) -> Score:
    pair = _digit_pair(summary.get("score")) or _digit_pair(summary.get("ftScore"))
    if pair is None:
        pair = (0, 0)

    periods = set(text_col(events, "period").unique()) if not events.empty else set()
    max_minute = float(num(events, "minute").max()) if not events.empty else 0.0
    summary_max = float(summary.get("maxMinute") or 0)

    went_to_extra_time = bool(
        periods & EXTRA_TIME_PERIODS or max(max_minute, summary_max) > 105
    )
    went_to_shootout = bool(
        periods & SHOOTOUT_PERIODS or flag(events, "penaltyShootoutScored").any()
    )
    # The asterisk prefix is WhoScored's own marker for "not settled in 90".
    marked = str(summary.get("score") or "").strip().startswith("*")

    ninety = _digit_pair(summary.get("ftScore"))
    if ninety == pair:
        ninety = None

    return Score(
        home=pair[0],
        away=pair[1],
        after_extra_time=(went_to_extra_time or marked) and not went_to_shootout,
        after_shootout=went_to_shootout,
        ninety_minute=ninety,
    )


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------

@dataclass
class MatchBundle:
    match_dir: Path
    summary: dict[str, Any]
    events: pd.DataFrame
    passes: pd.DataFrame
    shots: pd.DataFrame
    touches: pd.DataFrame
    players: pd.DataFrame
    score: Score

    @property
    def home(self) -> str:
        return clean_text(self.summary.get("home", {}).get("name"), "Home")

    @property
    def away(self) -> str:
        return clean_text(self.summary.get("away", {}).get("name"), "Away")

    @property
    def league(self) -> str:
        return clean_text(self.summary.get("league"), "")

    @property
    def stage(self) -> str:
        return clean_text(self.summary.get("competitionStage"), "")

    @property
    def venue(self) -> str:
        return clean_text(self.summary.get("venueName"), "")

    @property
    def kickoff(self) -> str:
        return clean_text(self.summary.get("startDate"), "")[:10]

    @property
    def last_minute(self) -> int:
        """Final minute of play, including stoppage and extra time."""
        value = num(self.events, "minute").max()
        if pd.isna(value):
            return 90
        return int(max(90, value))

    def team(self, h_a: str) -> str:
        return self.home if h_a == "h" else self.away

    def team_id(self, h_a: str) -> int | None:
        side = self.summary.get("home" if h_a == "h" else "away") or {}
        raw = side.get("teamId")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def home_team_id(self) -> int | None:
        return self.team_id("h")

    @property
    def away_team_id(self) -> int | None:
        return self.team_id("a")

    def competition_line(self) -> str:
        bits = [self.league, self.stage]
        return " / ".join(bit for bit in bits if bit)


def load_match(match_dir: Path) -> MatchBundle:
    match_dir = Path(match_dir)
    summary_path = match_dir / "match_summary.json"
    events_path = match_dir / "all_events.csv"
    missing = [p.name for p in (summary_path, events_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"{match_dir} is not a complete export; missing {', '.join(missing)}")

    summary = read_json(summary_path)
    events = read_csv_if_exists(events_path)
    passes = read_csv_if_exists(match_dir / "passes.csv")
    shots = read_csv_if_exists(match_dir / "shots.csv")
    touches = read_csv_if_exists(match_dir / "heatmap_touches.csv")
    players = read_csv_if_exists(match_dir / "player_stats.csv")

    for frame in (events, passes, shots, touches):
        for col in NUMERIC_COLUMNS:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")

    return MatchBundle(
        match_dir=match_dir,
        summary=summary,
        events=events,
        passes=passes,
        shots=shots,
        touches=touches,
        players=players,
        score=build_score(summary, events),
    )


def event_seconds(df: pd.DataFrame) -> pd.Series:
    return num(df, "minute").fillna(0) * 60 + num(df, "second").fillna(0)


def list_match_dirs(output_root: Path) -> list[Path]:
    output_root = Path(output_root)
    if not output_root.exists():
        return []
    found = [
        child
        for child in output_root.iterdir()
        if child.is_dir()
        and (child / "match_summary.json").exists()
        and (child / "all_events.csv").exists()
    ]

    def sort_key(path: Path) -> tuple[str, str]:
        try:
            summary = read_json(path / "match_summary.json")
            return (clean_text(summary.get("startDate")), path.name)
        except Exception:
            return ("", path.name)

    return sorted(found, key=sort_key, reverse=True)


def describe_match_dir(path: Path) -> str:
    try:
        summary = read_json(path / "match_summary.json")
    except Exception:
        return path.name
    home = summary.get("home", {}).get("name", "Home")
    away = summary.get("away", {}).get("name", "Away")
    pair = _digit_pair(summary.get("score")) or (0, 0)
    date = clean_text(summary.get("startDate"))[:10]
    return f"{home} {pair[0]}-{pair[1]} {away}  ({date})"
