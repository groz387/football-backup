"""Design tokens: palette, typography and per-team identity.

Every colour that reaches the screen goes through here, so contrast against the
dark background is enforced in one place instead of per renderer.
"""

from __future__ import annotations

import colorsys
import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import matplotlib
from matplotlib import font_manager

# --- surfaces ---------------------------------------------------------------
INK = "#07090a"          # page background
SURFACE = "#0e1211"      # cards and panels
SURFACE_HI = "#161b19"   # raised rows
PITCH = "#0a0f0b"
PITCH_LINE = "#4c5c51"
HAIRLINE = "#232b27"

# --- type -------------------------------------------------------------------
TEXT = "#f5f8f3"
TEXT_DIM = "#9aa8a1"
TEXT_FAINT = "#5e6b65"

# --- accents ----------------------------------------------------------------
GOAL = "#ff3b5c"         # goals / decisive moments
POSITIVE = "#4ade80"
WARNING = "#fbbf24"

# Neutral team fallbacks, used before a team is resolved against the table.
NEUTRAL_HOME = "#f0a132"
NEUTRAL_AWAY = "#4fd1a5"

WATERMARK = "EVENT DATA RECAP"
DATA_SOURCE = "WhoScored / Opta event feed"

# 1080x1920 output. Social overlays eat roughly the top 10% and bottom 16%,
# so all primary content is kept inside the safe band.
FRAME_W, FRAME_H = 1080, 1920
ASPECT = FRAME_W / FRAME_H
SAFE_TOP = 0.945
SAFE_BOTTOM = 0.055


def _register_bundled_fonts() -> None:
    for path in Path(__file__).resolve().parent.parent.glob("*.ttf"):
        try:
            font_manager.fontManager.addfont(str(path))
        except Exception:
            continue


_register_bundled_fonts()


def _first_available(*preferences: str) -> str:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in preferences:
        if name in available:
            return name
    return preferences[-1]


DISPLAY_FONT = _first_available("FWC2026", "Bebas Neue", "Anton", "Segoe UI Black", "DejaVu Sans")
BODY_FONT = _first_available("Inter", "Segoe UI", "DejaVu Sans")
MONO_FONT = _first_available("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono")


# ---------------------------------------------------------------------------
# colour maths
# ---------------------------------------------------------------------------

def hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i: i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel * 255))):02x}" for channel in rgb)


def mix(color_a: str, color_b: str, amount: float) -> str:
    """Blend *color_a* toward *color_b*. amount=0 returns a, amount=1 returns b."""
    amount = max(0.0, min(1.0, amount))
    a = hex_to_rgb(color_a)
    b = hex_to_rgb(color_b)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * amount for i in range(3)))  # type: ignore[arg-type]


def relative_luminance(color: str) -> float:
    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def contrast_ratio(color_a: str, color_b: str) -> float:
    a, b = relative_luminance(color_a), relative_luminance(color_b)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def readable_on(color: str, background: str = INK, minimum: float = 4.5) -> str:
    """Lighten *color* until it is legible on *background*."""
    if contrast_ratio(color, background) >= minimum:
        return color
    hue, lightness, saturation = colorsys.rgb_to_hls(*hex_to_rgb(color))
    for step in range(1, 20):
        candidate = rgb_to_hex(
            colorsys.hls_to_rgb(
                hue,
                min(0.90, lightness + step * 0.035),
                min(1.0, saturation + step * 0.015),
            )
        )
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return rgb_to_hex(colorsys.hls_to_rgb(hue, 0.86, min(1.0, saturation + 0.2)))


def ink_on(color: str) -> str:
    """Pick the text colour that reads on a filled *color* swatch."""
    return "#07090a" if relative_luminance(color) > 0.42 else TEXT


def normalize_team_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


# ---------------------------------------------------------------------------
# team identity
# ---------------------------------------------------------------------------
# "primary" is the shirt/flag colour used for fills and flags; "chart" is the
# contrast-corrected variant used for lines, bars and text on the dark frame.

_TEAM_COLORS: dict[str, tuple[str, str]] = {
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

_TEAM_ALIASES = {
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
}


def canonical_team_key(name: str) -> str:
    key = normalize_team_key(name)
    if key in _TEAM_ALIASES:
        return _TEAM_ALIASES[key]
    if key in _TEAM_COLORS:
        return key
    compact = key.replace(" ", "")
    for candidate in _TEAM_COLORS:
        if candidate.replace(" ", "") == compact:
            return candidate
    return key


def _generated_colors(name: str) -> tuple[str, str]:
    """Deterministic, pleasant colours for teams we do not have on file."""
    digest = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    hue = (digest % 360) / 360.0
    primary = rgb_to_hex(colorsys.hls_to_rgb(hue, 0.52, 0.68))
    secondary = rgb_to_hex(colorsys.hls_to_rgb((hue + 0.5) % 1.0, 0.62, 0.55))
    return primary, secondary


@lru_cache(maxsize=256)
def _team_identity_cached(name: str) -> tuple[tuple[str, str], ...]:
    key = canonical_team_key(name)
    primary, secondary = _TEAM_COLORS.get(key, _generated_colors(name))
    return (
        ("key", key),
        ("name", name),
        ("abbr", team_abbreviation(name)),
        ("primary", primary),
        ("secondary", secondary),
        ("chart", readable_on(primary)),
        ("accent", readable_on(secondary, minimum=3.2)),
    )


def team_identity(name: str) -> dict[str, str]:
    """Colours and labels for one team.

    Cached because the contrast search runs a loop and every renderer resolves
    the design once per frame.
    """
    return dict(_team_identity_cached(str(name)))


_ABBR_OVERRIDES = {
    "united states": "USA",
    "south korea": "KOR",
    "netherlands": "NED",
    "germany": "GER",
    "switzerland": "SUI",
    "croatia": "CRO",
    "denmark": "DEN",
    "portugal": "POR",
    "uruguay": "URU",
    "saudi arabia": "KSA",
    "ivory coast": "CIV",
    "czech republic": "CZE",
    "new zealand": "NZL",
    "costa rica": "CRC",
    "south africa": "RSA",
}


def team_abbreviation(name: str) -> str:
    key = canonical_team_key(name)
    if key in _ABBR_OVERRIDES:
        return _ABBR_OVERRIDES[key]
    words = [w for w in re.split(r"[^A-Za-z]+", str(name)) if w]
    if not words:
        return "TBD"
    if len(words) == 1:
        return words[0][:3].upper()
    joined = "".join(word[0] for word in words).upper()
    return joined[:3] if len(joined) >= 3 else (words[0][:3].upper())


# Candidates for highlighting one element against a team's own colour. A team's
# secondary colour is often white or the same hue as the primary, which makes it
# useless for "this is the important one" emphasis.
_HIGHLIGHTS = ("#ffc53d", "#4cc9f0", "#f472b6", "#a3e635")


def highlight_against(color: str) -> str:
    """Pick the accent that stands out most from *color* and the background."""
    return max(
        _HIGHLIGHTS,
        key=lambda candidate: min(contrast_ratio(candidate, color), contrast_ratio(candidate, INK)),
    )


def separate(color_a: str, color_b: str, minimum: float = 1.8) -> tuple[str, str]:
    """Keep two team colours visually distinct from each other."""
    if contrast_ratio(color_a, color_b) >= minimum:
        return color_a, color_b
    hue, lightness, saturation = colorsys.rgb_to_hls(*hex_to_rgb(color_b))
    for step in range(1, 14):
        shifted = rgb_to_hex(
            colorsys.hls_to_rgb((hue + 0.06 * step) % 1.0, min(0.78, lightness + 0.02 * step), saturation)
        )
        if contrast_ratio(color_a, shifted) >= minimum and contrast_ratio(shifted, INK) >= 4.0:
            return color_a, shifted
    return color_a, readable_on(mix(color_b, TEXT, 0.4))


@lru_cache(maxsize=64)
def _separated_charts(home_chart: str, away_chart: str) -> tuple[str, str]:
    return separate(home_chart, away_chart)


def match_design(home: str, away: str) -> dict[str, Any]:
    """Resolve the full colour scheme for one fixture."""
    home_id = team_identity(home)
    away_id = team_identity(away)
    home_chart, away_chart = _separated_charts(home_id["chart"], away_id["chart"])
    home_id["chart"] = home_chart
    away_id["chart"] = away_chart
    return {
        "home": home_id,
        "away": away_id,
        "ink": INK,
        "surface": SURFACE,
        "surface_hi": SURFACE_HI,
        "pitch": PITCH,
        "pitch_line": PITCH_LINE,
        "hairline": HAIRLINE,
        "text": TEXT,
        "text_dim": TEXT_DIM,
        "goal": GOAL,
    }


def side_color(design: dict[str, Any], h_a: str, key: str = "chart") -> str:
    return str(design["home" if h_a == "h" else "away"][key])


def configure_matplotlib() -> None:
    matplotlib.rcParams.update(
        {
            "figure.facecolor": INK,
            "savefig.facecolor": INK,
            "text.color": TEXT,
            "axes.facecolor": INK,
            "axes.edgecolor": HAIRLINE,
            "font.family": BODY_FONT,
            "path.simplify": True,
            "agg.path.chunksize": 10000,
        }
    )
