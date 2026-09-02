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
INK = "#0b1014"          # page background — lifted off pure black so team tint can read
SURFACE = "#0e1211"      # cards and panels
SURFACE_HI = "#161b19"   # raised rows
PITCH = "#0a0f0b"
PITCH_LINE = "#4c5c51"
HAIRLINE = "#232b27"

# --- type -------------------------------------------------------------------
TEXT = "#f7faf6"
TEXT_DIM = "#c5d0c8"
TEXT_FAINT = "#8d9a93"

# --- accents ----------------------------------------------------------------
GOAL = "#ff3b5c"         # goals / decisive moments
POSITIVE = "#4ade80"
WARNING = "#fbbf24"

# Neutral team fallbacks, used before a team is resolved against the table.
NEUTRAL_HOME = "#f0a132"
NEUTRAL_AWAY = "#4fd1a5"

WATERMARK = ""
DATA_SOURCE = "WhoScored / Opta event feed"

# Badge presentation. ``national`` draws rectangular flags; ``club`` draws
# circular crests (logo when available, initials otherwise).
TEAM_KINDS = ("national", "club")
_team_kind = "national"

# Default 1080x1920. Callers may switch to landscape via set_frame_size.
FRAME_W, FRAME_H = 1080, 1920
ASPECT = FRAME_W / FRAME_H
SAFE_TOP = 0.945
SAFE_BOTTOM = 0.055


def set_frame_size(width: int, height: int) -> tuple[int, int]:
    """Point every renderer at a new output size. Portrait and landscape both work."""
    global FRAME_W, FRAME_H, ASPECT
    FRAME_W = max(1, int(width))
    FRAME_H = max(1, int(height))
    ASPECT = FRAME_W / FRAME_H
    return FRAME_W, FRAME_H


def normalize_team_kind(value: str | None) -> str:
    raw = (value or "national").strip().lower()
    aliases = {
        "national": "national",
        "nation": "national",
        "country": "national",
        "intl": "national",
        "international": "national",
        "club": "club",
        "clubs": "club",
        "team": "club",
    }
    kind = aliases.get(raw)
    if kind is None:
        raise ValueError(f"Unsupported --team value {value!r}. Choose national or club.")
    return kind


def set_team_kind(kind: str) -> str:
    global _team_kind
    _team_kind = normalize_team_kind(kind)
    _team_identity_cached.cache_clear()
    return _team_kind


def get_team_kind() -> str:
    return _team_kind


_HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{3}$|^[0-9A-Fa-f]{6}$")
_override_home: str | None = None
_override_away: str | None = None


def parse_hex_color(value: str) -> str:
    """Accept ``#004170``, ``004170`` or ``#07A``. Returns ``#rrggbb``."""
    raw = str(value or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    raw = raw.lstrip("#").strip()
    if not _HEX_COLOR.fullmatch(raw):
        raise ValueError(
            f"Invalid colour {value!r}. Use a 3- or 6-digit hex value, "
            f"e.g. #004170 or 95BFE5 (quote it in PowerShell so # is not a comment)."
        )
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return f"#{raw.lower()}"


def set_team_colors(home: str | None = None, away: str | None = None) -> tuple[str | None, str | None]:
    """Override home / away chart colours for this run. ``None`` keeps the default."""
    global _override_home, _override_away
    _override_home = parse_hex_color(home) if home else None
    _override_away = parse_hex_color(away) if away else None
    _team_identity_cached.cache_clear()
    _separated_charts.cache_clear()
    return _override_home, _override_away


def get_team_colors() -> tuple[str | None, str | None]:
    return _override_home, _override_away


def badge_shape(kind: str | None = None) -> str:
    """``rect`` for national flags, ``circle`` for club crests."""
    return "circle" if (kind or _team_kind) == "club" else "rect"


def _register_bundled_fonts() -> None:
    root = Path(__file__).resolve().parent.parent
    for path in list(root.glob("*.ttf")) + list(root.glob("Fonts/**/*.ttf")):
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


# Latin languages use Bai Jamjuree (all caps). It has no Cyrillic, so Russian
# recaps switch to Gilroy-Bold for headlines and Gilroy-Medium for labels.
_LATIN_DISPLAY = _first_available("Bai Jamjuree", "BaiJamjuree", "Segoe UI", "DejaVu Sans")
_LATIN_BODY = _first_available("Bai Jamjuree", "Inter", "Segoe UI", "DejaVu Sans")
_LATIN_LABEL = _first_available("Bai Jamjuree", "BaiJamjuree", "Segoe UI", "DejaVu Sans")
_LATIN_MONO = _first_available(
    "Bai Jamjuree", "JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono"
)
_CYRILLIC_DISPLAY = _first_available("Gilroy-Bold", "Gilroy-Medium", "Segoe UI", "DejaVu Sans")
_CYRILLIC_BODY = _first_available("Gilroy-Medium", "Gilroy-Bold", "Segoe UI", "DejaVu Sans")

DISPLAY_FONT = _LATIN_DISPLAY
BODY_FONT = _LATIN_BODY
LABEL_FONT = _LATIN_LABEL
MONO_FONT = _LATIN_MONO

# Small chrome labels only — headlines and subtitles are untouched.
LABEL_SCALE = 1.30


def label_size(base: float) -> float:
    """Bump micro-label type ~30% without touching display headlines."""
    return round(float(base) * LABEL_SCALE, 1)


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


def readable_on(color: str, background: str = INK, minimum: float = 5.5) -> str:
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
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "paris saint-germain": "paris saint germain",
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
}

_CLUB_COLORS: dict[str, tuple[str, str]] = {
    "arsenal": ("#ef0107", "#ffffff"),
    "aston villa": ("#670e36", "#95bfe5"),
    "atletico madrid": ("#c8102e", "#ffffff"),
    "barcelona": ("#a50044", "#004d98"),
    "bayern munich": ("#dc052d", "#ffffff"),
    "benfica": ("#e32636", "#ffffff"),
    "borussia dortmund": ("#fde100", "#000000"),
    "chelsea": ("#034694", "#ffffff"),
    "inter milan": ("#010e80", "#000000"),
    "juventus": ("#000000", "#ffffff"),
    "liverpool": ("#c8102e", "#ffffff"),
    "manchester city": ("#6cabdd", "#1c2c5b"),
    "manchester united": ("#da291c", "#000000"),
    "milan": ("#fb090b", "#000000"),
    "ac milan": ("#fb090b", "#000000"),
    "napoli": ("#12a0d7", "#ffffff"),
    "newcastle united": ("#241f20", "#ffffff"),
    "paris saint germain": ("#004170", "#da291c"),
    "porto": ("#003893", "#ffffff"),
    "real madrid": ("#ffffff", "#00529f"),
    "sevilla": ("#d4a574", "#ffffff"),
    "tottenham hotspur": ("#132257", "#ffffff"),
    "ajax": ("#d2122e", "#ffffff"),
    "lyon": ("#003da5", "#ffffff"),
    "marseille": ("#2faee0", "#ffffff"),
    "monaco": ("#e30613", "#ffffff"),
    "leverkusen": ("#e32221", "#000000"),
    "rb leipzig": ("#dd0741", "#ffffff"),
}


def canonical_team_key(name: str) -> str:
    key = normalize_team_key(name)
    if key in _TEAM_ALIASES:
        key = _TEAM_ALIASES[key]
    for table in (_CLUB_COLORS, _TEAM_COLORS):
        if key in table:
            return key
        compact = key.replace(" ", "")
        for candidate in table:
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


def _colors_for(name: str, kind: str) -> tuple[str, str]:
    key = canonical_team_key(name)
    if kind == "club":
        if key in _CLUB_COLORS:
            return _CLUB_COLORS[key]
        if key not in _TEAM_COLORS:
            return _generated_colors(name)
    if key in _TEAM_COLORS:
        return _TEAM_COLORS[key]
    if key in _CLUB_COLORS:
        return _CLUB_COLORS[key]
    return _generated_colors(name)


@lru_cache(maxsize=256)
def _team_identity_cached(name: str, kind: str) -> tuple[tuple[str, str], ...]:
    key = canonical_team_key(name)
    primary, secondary = _colors_for(name, kind)
    chart = readable_on(primary)
    return (
        ("key", key),
        ("name", name),
        ("abbr", team_abbreviation(name)),
        ("primary", primary),
        ("fill", primary),
        ("secondary", secondary),
        ("chart", chart),
        ("glow", mix(chart, "#ffffff", 0.18)),
        ("accent", readable_on(secondary, minimum=3.2)),
        ("kind", kind),
        ("shape", badge_shape(kind)),
    )


def team_identity(name: str) -> dict[str, str]:
    """Colours and labels for one team.

    Cached because the contrast search runs a loop and every renderer resolves
    the design once per frame.
    """
    return dict(_team_identity_cached(str(name), get_team_kind()))


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


def separate(color_a: str, color_b: str, minimum: float = 2.2) -> tuple[str, str]:
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


def _apply_color_override(identity: dict[str, str], hex_color: str | None) -> dict[str, str]:
    if not hex_color:
        return identity
    updated = dict(identity)
    updated["primary"] = hex_color
    updated["fill"] = hex_color
    updated["chart"] = readable_on(hex_color)
    updated["glow"] = mix(updated["chart"], "#ffffff", 0.18)
    return updated


def match_design(home: str, away: str) -> dict[str, Any]:
    """Resolve the full colour scheme for one fixture."""
    home_id = _apply_color_override(team_identity(home), _override_home)
    away_id = _apply_color_override(team_identity(away), _override_away)
    home_chart, away_chart = _separated_charts(home_id["chart"], away_id["chart"])
    home_id["chart"] = home_chart
    away_id["chart"] = away_chart
    home_id["glow"] = mix(home_chart, "#ffffff", 0.18)
    away_id["glow"] = mix(away_chart, "#ffffff", 0.18)
    fill = home_id.get("fill") or home_id["primary"]
    tinted_ink = mix(INK, fill, 0.08)
    if contrast_ratio(TEXT, tinted_ink) < 7.0:
        tinted_ink = mix(INK, fill, 0.05)
    return {
        "home": home_id,
        "away": away_id,
        "team_kind": get_team_kind(),
        "badge_shape": badge_shape(),
        "ink": tinted_ink,
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


def apply_language_fonts(language: str) -> None:
    """Swap the type stack when Bai Jamjuree cannot cover the script.

    Russian uses Gilroy (Medium / Bold) from ``Fonts/Gilroy``. Other languages
    keep Bai Jamjuree. Callers must read ``theme.DISPLAY_FONT`` at draw time
    rather than importing the name once.
    """
    global DISPLAY_FONT, BODY_FONT, LABEL_FONT, MONO_FONT
    if (language or "").strip().lower() == "ru":
        DISPLAY_FONT = _CYRILLIC_DISPLAY
        BODY_FONT = _CYRILLIC_BODY
        LABEL_FONT = _CYRILLIC_BODY
        MONO_FONT = _CYRILLIC_BODY
    else:
        DISPLAY_FONT = _LATIN_DISPLAY
        BODY_FONT = _LATIN_BODY
        LABEL_FONT = _LATIN_LABEL
        MONO_FONT = _LATIN_MONO
    configure_matplotlib()
