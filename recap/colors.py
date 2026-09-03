"""Club / national kit colours for recap fills.

``theme.match_design`` and the studio colour preview both come through here so
Barça burgundy, gold secondaries, and home/away clashes live in one place.

``--colors HOME AWAY`` (``theme.set_team_colors``) still wins: overrides skip
the clash swap. This module never invents a third shirt colour — if both
secondaries also clash, the real primaries stay and ``theme.separate`` only
tweaks chart lines for contrast.
"""

from __future__ import annotations

import colorsys
import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

BARCA_BURGUNDY = "#9e0041"
BARCA_GOLD = "#ffd100"

_HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{3}$|^[0-9A-Fa-f]{6}$")

# Match ``theme.kits_clash``: two reds with weak contrast or a tiny hue gap
# read as the same shirt on a dark 9:16 card.
MIN_PAIR_CONTRAST = 2.35
MAX_HUE_DELTA = 0.10


def parse_hex(value: str) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    raw = raw.lstrip("#").strip()
    if not _HEX_COLOR.fullmatch(raw):
        raise ValueError(f"Invalid colour {value!r}. Use 3- or 6-digit hex, e.g. #9e0041.")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return f"#{raw.lower()}"


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = parse_hex(color).lstrip("#")
    return tuple(int(value[i: i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel * 255))):02x}" for channel in rgb)


def relative_luminance(color: str) -> float:
    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def contrast_ratio(color_a: str, color_b: str) -> float:
    a, b = relative_luminance(color_a), relative_luminance(color_b)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def hue_delta(color_a: str, color_b: str) -> float:
    ha, _, _ = colorsys.rgb_to_hls(*hex_to_rgb(color_a))
    hb, _, _ = colorsys.rgb_to_hls(*hex_to_rgb(color_b))
    return min(abs(ha - hb), 1.0 - abs(ha - hb))


def too_similar(color_a: str, color_b: str) -> bool:
    """True when two kit fills would read as the same shirt on a dark frame.

    Hue is ignored for near-white / near-black (HLS saturation is meaningless
    there). Two saturated reds still clash even when one is brighter.
    """
    if parse_hex(color_a) == parse_hex(color_b):
        return True
    ha, _, sa = colorsys.rgb_to_hls(*hex_to_rgb(color_a))
    hb, _, sb = colorsys.rgb_to_hls(*hex_to_rgb(color_b))
    hue = min(abs(ha - hb), 1.0 - abs(ha - hb))
    contrast = contrast_ratio(color_a, color_b)
    if sa < 0.18 or sb < 0.18:
        return contrast < MIN_PAIR_CONTRAST
    # Saturated shirts clash when they share a hue family (two reds, two blues).
    # Dark-on-dark of different hues (Scotland blue / Morocco red) is fine.
    return hue < MAX_HUE_DELTA


def normalize_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", str(name or ""))
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()


# National kits: (primary, secondary). Primary is the flag/shirt fill.
NATIONAL_KITS: dict[str, tuple[str, str]] = {
    "argentina": ("#6cace4", "#ffffff"),
    "algeria": ("#007a3d", "#d21034"),
    "australia": ("#00843d", "#ffcd00"),
    "austria": ("#ed2939", "#ffffff"),
    "belgium": ("#fdda24", "#ef3340"),
    "bolivia": ("#007934", "#ffe000"),
    "brazil": ("#009c3b", "#ffdf00"),
    "cameroon": ("#007a5e", "#fcd116"),
    "canada": ("#d80621", "#ffffff"),
    "chile": ("#d52b1e", "#0039a6"),
    "colombia": ("#fcd116", "#003893"),
    "costa rica": ("#002b7f", "#ce1126"),
    "croatia": ("#ff0000", "#171796"),
    "czech republic": ("#d7141a", "#11457e"),
    "denmark": ("#c8102e", "#ffffff"),
    "ecuador": ("#ffd100", "#0038a8"),
    "egypt": ("#ce1126", "#c09300"),
    "england": ("#e6142a", "#ffffff"),
    "france": ("#2b4eb8", "#ed2939"),
    "germany": ("#dd0000", "#ffcc00"),
    "ghana": ("#006b3f", "#fcd116"),
    "greece": ("#0d5eaf", "#ffffff"),
    "iran": ("#239f40", "#da0000"),
    "italy": ("#0066b3", "#009246"),
    "ivory coast": ("#ff8200", "#009a44"),
    "jamaica": ("#009b3a", "#fed100"),
    "japan": ("#bc002d", "#ffffff"),
    "mexico": ("#006847", "#ce1126"),
    "morocco": ("#c1272d", "#006233"),
    "netherlands": ("#ff6600", "#21468b"),
    "new zealand": ("#00247d", "#ffffff"),
    "nigeria": ("#008751", "#ffffff"),
    "norway": ("#ba0c2f", "#00205b"),
    "panama": ("#005293", "#da121a"),
    "paraguay": ("#d52b1e", "#0038a8"),
    "peru": ("#d91023", "#ffffff"),
    "poland": ("#dc143c", "#ffffff"),
    "portugal": ("#c8102e", "#006600"),
    "qatar": ("#8a1538", "#ffffff"),
    "saudi arabia": ("#006c35", "#ffffff"),
    "scotland": ("#005eb8", "#ffffff"),
    "senegal": ("#00853f", "#fdef42"),
    "serbia": ("#c6363c", "#0c4076"),
    "south korea": ("#c60c30", "#003478"),
    "spain": ("#c60b1e", "#ffc400"),
    "sweden": ("#006aa7", "#fecc02"),
    "switzerland": ("#d52b1e", "#ffffff"),
    "tunisia": ("#e70013", "#ffffff"),
    "turkey": ("#e30a17", "#ffffff"),
    "united states": ("#0a3161", "#b31942"),
    "uruguay": ("#5bb5e6", "#ffcd00"),
    "wales": ("#c8102e", "#00a651"),
}

# Club kits. Barça is burgundy + gold (not the classic blaugrana pair).
CLUB_KITS: dict[str, tuple[str, str]] = {
    "arsenal": ("#ef0107", "#ffffff"),
    "aston villa": ("#670e36", "#95bfe5"),
    "athletic club": ("#ee2523", "#ffffff"),
    "atletico madrid": ("#c8102e", "#ffffff"),
    "barcelona": (BARCA_BURGUNDY, BARCA_GOLD),
    "bayern munich": ("#dc052d", "#ffffff"),
    "benfica": ("#e32636", "#ffffff"),
    "borussia dortmund": ("#fde100", "#000000"),
    "celta vigo": ("#8ac3e8", "#ffffff"),
    "chelsea": ("#034694", "#ffffff"),
    "espanyol": ("#1e6bb8", "#ffffff"),
    "girona": ("#cd2534", "#ffffff"),
    "inter milan": ("#010e80", "#000000"),
    "juventus": ("#000000", "#ffffff"),
    "liverpool": ("#c8102e", "#ffffff"),
    "manchester city": ("#6cabdd", "#1c2c5b"),
    "manchester united": ("#da291c", "#000000"),
    "milan": ("#fb090b", "#000000"),
    "ac milan": ("#fb090b", "#000000"),
    "napoli": ("#12a0d7", "#ffffff"),
    "newcastle united": ("#241f20", "#ffffff"),
    "osasuna": ("#d91a2a", "#00004c"),
    "paris saint germain": ("#004170", "#da291c"),
    "porto": ("#003893", "#ffffff"),
    "rayo vallecano": ("#e53027", "#ffffff"),
    "elche": ("#046a38", "#ffffff"),
    "qarabag": ("#000000", "#ffffff"),
    "real betis": ("#0bb363", "#ffffff"),
    "real madrid": ("#ffffff", "#00529f"),
    "real sociedad": ("#0067b1", "#ffffff"),
    "sevilla": ("#d4a574", "#ffffff"),
    "tottenham hotspur": ("#132257", "#ffffff"),
    "valencia": ("#ee3524", "#ffffff"),
    "villarreal": ("#ffe667", "#005187"),
    "ajax": ("#d2122e", "#ffffff"),
    "lyon": ("#003da5", "#ffffff"),
    "marseille": ("#2faee0", "#ffffff"),
    "monaco": ("#e30613", "#ffffff"),
    "leverkusen": ("#e32221", "#000000"),
    "rb leipzig": ("#dd0741", "#ffffff"),
}

TEAM_ALIASES: dict[str, str] = {
    "usa": "united states",
    "us": "united states",
    "united states of america": "united states",
    "korea republic": "south korea",
    "southkorea": "south korea",
    "republic of korea": "south korea",
    "holland": "netherlands",
    "cote d ivoire": "ivory coast",
    "ivorycoast": "ivory coast",
    "czechia": "czech republic",
    "iran islamic republic": "iran",
    "turkiye": "turkey",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "paris saint germain": "paris saint germain",
    "man city": "manchester city",
    "man utd": "manchester united",
    "manchester utd": "manchester united",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "inter": "inter milan",
    "internazionale": "inter milan",
    "bayern": "bayern munich",
    "dortmund": "borussia dortmund",
    "bvb": "borussia dortmund",
    "barca": "barcelona",
    "barça": "barcelona",
    "fc barcelona": "barcelona",
    "fc barca": "barcelona",
    "cf barcelona": "barcelona",
    "rayo": "rayo vallecano",
    "athletic bilbao": "athletic club",
    "athletic": "athletic club",
    "atletico": "atletico madrid",
    "atm": "atletico madrid",
    "celta": "celta vigo",
    "betis": "real betis",
    "sociedad": "real sociedad",
}


def _lookup_table(key: str, table: dict[str, tuple[str, str]]) -> str | None:
    if key in table:
        return key
    compact = key.replace(" ", "")
    for candidate in table:
        if candidate.replace(" ", "") == compact:
            return candidate
    return None


def canonical_key(name: str) -> str:
    key = normalize_key(name)
    if key in TEAM_ALIASES:
        key = TEAM_ALIASES[key]
    found = _lookup_table(key, CLUB_KITS) or _lookup_table(key, NATIONAL_KITS)
    return found or key


def generated_kit(name: str) -> tuple[str, str]:
    digest = int(hashlib.md5(str(name).encode("utf-8")).hexdigest(), 16)
    hue = (digest % 360) / 360.0
    primary = rgb_to_hex(colorsys.hls_to_rgb(hue, 0.52, 0.68))
    secondary = rgb_to_hex(colorsys.hls_to_rgb((hue + 0.5) % 1.0, 0.62, 0.55))
    return primary, secondary


@dataclass(frozen=True)
class Kit:
    name: str
    key: str
    kind: str
    primary: str
    secondary: str
    fill: str
    used_secondary: bool = False
    generated: bool = False

    def as_tuple(self) -> tuple[str, str]:
        return self.primary, self.secondary

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "key": self.key,
            "kind": self.kind,
            "primary": self.primary,
            "secondary": self.secondary,
            "fill": self.fill,
            "used_secondary": self.used_secondary,
            "generated": self.generated,
        }


@dataclass(frozen=True)
class Pair:
    home: Kit
    away: Kit
    conflict: bool
    conflict_side: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "home": self.home.as_dict(),
            "away": self.away.as_dict(),
            "conflict": self.conflict,
            "conflict_side": self.conflict_side,
            "reason": self.reason,
        }


def kit_for(name: str, kind: str = "national") -> Kit:
    """Auto club/national kit. Unknown names hash to a stable pair — never random."""
    key = canonical_key(name)
    kind = "club" if str(kind).strip().lower() == "club" else "national"
    generated = False
    pair: tuple[str, str] | None = None
    if kind == "club":
        club_key = _lookup_table(key, CLUB_KITS)
        if club_key:
            key = club_key
            pair = CLUB_KITS[club_key]
        elif _lookup_table(key, NATIONAL_KITS) is None:
            pair = generated_kit(name)
            generated = True
    if pair is None:
        nat_key = _lookup_table(key, NATIONAL_KITS)
        if nat_key:
            key = nat_key
            pair = NATIONAL_KITS[nat_key]
        else:
            club_key = _lookup_table(key, CLUB_KITS)
            if club_key:
                key = club_key
                pair = CLUB_KITS[club_key]
            else:
                pair = generated_kit(name)
                generated = True
    primary, secondary = pair
    return Kit(
        name=str(name),
        key=key,
        kind=kind,
        primary=primary,
        secondary=secondary,
        fill=primary,
        generated=generated,
    )


def _wear_secondary(kit: Kit) -> Kit:
    return replace(kit, fill=kit.secondary, used_secondary=True)


def resolve_pair(
    home: str,
    away: str,
    kind: str = "national",
    override_home: str | None = None,
    override_away: str | None = None,
) -> Pair:
    """Pick fills for a fixture.

    If home/away primaries are too similar, one side wears its secondary.
    CLI ``--colors`` overrides skip the swap.
    """
    home_kit = kit_for(home, kind)
    away_kit = kit_for(away, kind)
    if override_home:
        home_kit = replace(home_kit, fill=parse_hex(override_home), used_secondary=False)
    if override_away:
        away_kit = replace(away_kit, fill=parse_hex(override_away), used_secondary=False)
    if override_home or override_away:
        return Pair(
            home_kit, away_kit, conflict=False, conflict_side=None,
            reason="cli --colors override",
        )
    if not too_similar(home_kit.fill, away_kit.fill):
        return Pair(home_kit, away_kit, conflict=False, conflict_side=None, reason="distinct primaries")
    if not too_similar(home_kit.primary, away_kit.secondary):
        return Pair(
            home_kit, _wear_secondary(away_kit),
            conflict=True, conflict_side="away",
            reason="primaries too similar; away wears secondary",
        )
    if not too_similar(home_kit.secondary, away_kit.primary):
        return Pair(
            _wear_secondary(home_kit), away_kit,
            conflict=True, conflict_side="home",
            reason="primaries too similar; home wears secondary",
        )
    return Pair(
        home_kit, away_kit, conflict=True, conflict_side=None,
        reason="primaries and secondaries all clash; keep real kit colours",
    )
