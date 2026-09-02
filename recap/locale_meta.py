"""Per-language render metadata: script, RTL, fonts, ffmpeg burn-in.

matplotlib cannot layout Arabic the way a browser does. Recaps therefore:

1. Prefer ``arabic_reshaper`` + ``python-bidi`` so glyphs join and the run is
   visually RTL on an LTR canvas (the working path).
2. If those packages are missing, draw Arabic *logical* order left-to-right
   with Noto Naskh Arabic — readable, not newspaper-correct. See
   ``RTL_MATPLOTLIB_FALLBACK``.
3. Burned ffmpeg/libass captions *do* shape Arabic. Point ``FontName`` /
   ``fontfile`` at Noto so CJK / Arabic / Devanagari do not tofu.

Scores stay ``2-1`` in every language (Western digits, ASCII hyphen).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# matplotlib + libass tofu when the active font has no glyphs.
RTL_MATPLOTLIB_FALLBACK = (
    "If arabic_reshaper/python-bidi are unavailable, Arabic copy is still "
    "shipped and drawn LTR with Arabic-script glyphs (Noto Naskh Arabic). "
    "Install: pip install arabic-reshaper python-bidi. "
    "Debian/Ubuntu fonts: fonts-noto-core fonts-noto-cjk fonts-noto-ui-core "
    "(Noto Naskh Arabic, Noto Sans Arabic, Noto Sans CJK, Noto Sans Devanagari)."
)

APT_FONT_PACKAGES = (
    "fonts-noto-core",
    "fonts-noto-ui-core",
    "fonts-noto-cjk",
    "fonts-noto-cjk-extra",
)

# Common install locations. matplotlib must addfont() TTC files itself.
SYSTEM_FONT_DIRS = (
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/opentype/noto"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/freefont"),
    Path("C:/Windows/Fonts"),
)


@dataclass(frozen=True)
class LocaleMeta:
    code: str
    name: str
    native_name: str
    bcp47: str
    rtl: bool
    script: str
    # matplotlib FontProperties family names, preferred first
    display_fonts: tuple[str, ...]
    label_fonts: tuple[str, ...]
    # ffmpeg subtitles force_style FontName (libass)
    ass_font: str
    # ffmpeg drawtext fontfile search stems (matched against filenames)
    fontfile_stems: tuple[str, ...]
    decimal: str
    group: str
    date_order: str  # dmy | mdy | ymd
    uppercase_chrome: bool
    # Optional notes shown in video_plan.json
    notes: str = ""


def _latin(*extra: str) -> tuple[str, ...]:
    return extra + (
        "Bai Jamjuree",
        "BaiJamjuree",
        "Noto Sans",
        "Segoe UI",
        "DejaVu Sans",
    )


def _cyrillic(*extra: str) -> tuple[str, ...]:
    return extra + (
        "Gilroy-Bold",
        "Gilroy-Medium",
        "Noto Sans",
        "Segoe UI",
        "DejaVu Sans",
    )


META: dict[str, LocaleMeta] = {
    "en": LocaleMeta(
        "en", "English", "English", "en", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "BaiJamjuree-SemiBold", "NotoSans-Bold"),
        ".", ",", "dmy", True,
    ),
    "az": LocaleMeta(
        "az", "Azerbaijani", "Azərbaycan", "az", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", " ", "dmy", True,
        notes="Azerbaijani football register: qol, seyv, cərimə, əlavə dəqiqə.",
    ),
    "es": LocaleMeta(
        "es", "Spanish", "Español", "es", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", ".", "dmy", True,
        notes="LatAm/Spain hybrid: tiros, portería, descuento, atraco.",
    ),
    "ru": LocaleMeta(
        "ru", "Russian", "Русский", "ru", False, "Cyrl",
        _cyrillic(), _cyrillic("Gilroy-Medium"), "Gilroy-Bold",
        ("Gilroy-Bold", "NotoSans-Bold", "DejaVuSans-Bold"),
        ",", " ", "dmy", True,
    ),
    "tr": LocaleMeta(
        "tr", "Turkish", "Türkçe", "tr", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", ".", "dmy", True,
        notes="Use İ/ı correctly in running copy; chrome may stay caps.",
    ),
    "pt-BR": LocaleMeta(
        "pt-BR", "Portuguese (Brazil)", "Português (Brasil)", "pt-BR", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", ".", "dmy", True,
        notes="gol, goleiro, acréscimos — not European golo/guarda-redes.",
    ),
    "pt-PT": LocaleMeta(
        "pt-PT", "Portuguese (Portugal)", "Português (Portugal)", "pt-PT", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", " ", "dmy", True,
        notes="golo, guarda-redes, descontos da lei.",
    ),
    "fr": LocaleMeta(
        "fr", "French", "Français", "fr", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", " ", "dmy", True,
    ),
    "de": LocaleMeta(
        "de", "German", "Deutsch", "de", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", ".", "dmy", True,
    ),
    "it": LocaleMeta(
        "it", "Italian", "Italiano", "it", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", ".", "dmy", True,
    ),
    "ar": LocaleMeta(
        "ar", "Arabic", "العربية", "ar", True, "Arab",
        ("Noto Naskh Arabic", "Noto Sans Arabic", "Noto Kufi Arabic", "DejaVu Sans"),
        ("Noto Naskh Arabic", "Noto Sans Arabic", "DejaVu Sans"),
        "Noto Naskh Arabic",
        ("NotoNaskhArabic-Regular", "NotoNaskhArabic-Bold", "NotoSansArabic-Regular"),
        ".", ",", "dmy", False,
        notes=(
            "RTL. matplotlib: reshape + bidi when packages exist; otherwise "
            "LTR Arabic-script fallback. libass burned captions shape natively."
        ),
    ),
    "ja": LocaleMeta(
        "ja", "Japanese", "日本語", "ja", False, "Jpan",
        ("Noto Sans CJK JP", "Noto Sans CJK", "Noto Sans JP", "DejaVu Sans"),
        ("Noto Sans CJK JP", "Noto Sans CJK", "DejaVu Sans"),
        "Noto Sans CJK JP",
        ("NotoSansCJK-Bold", "NotoSansCJK-Regular", "NotoSansCJKjp"),
        ".", ",", "ymd", False,
    ),
    "ko": LocaleMeta(
        "ko", "Korean", "한국어", "ko", False, "Kore",
        ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans CJK", "DejaVu Sans"),
        ("Noto Sans CJK KR", "Noto Sans CJK JP", "DejaVu Sans"),
        "Noto Sans CJK KR",
        ("NotoSansCJK-Bold", "NotoSansCJK-Regular", "NotoSansCJKkr"),
        ".", ",", "ymd", False,
    ),
    "hi": LocaleMeta(
        "hi", "Hindi", "हिन्दी", "hi", False, "Deva",
        ("Noto Sans Devanagari", "Noto Sans", "DejaVu Sans"),
        ("Noto Sans Devanagari", "Noto Sans", "DejaVu Sans"),
        "Noto Sans Devanagari",
        ("NotoSansDevanagari-Bold", "NotoSansDevanagari-Regular"),
        ".", ",", "dmy", False,
    ),
    "pl": LocaleMeta(
        "pl", "Polish", "Polski", "pl", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", " ", "dmy", True,
    ),
    "nl": LocaleMeta(
        "nl", "Dutch", "Nederlands", "nl", False, "Latn",
        _latin(), _latin(), "Bai Jamjuree",
        ("BaiJamjuree-Bold", "NotoSans-Bold"),
        ",", ".", "dmy", True,
    ),
    "uk": LocaleMeta(
        "uk", "Ukrainian", "Українська", "uk", False, "Cyrl",
        _cyrillic(), _cyrillic("Gilroy-Medium"), "Gilroy-Bold",
        ("Gilroy-Bold", "NotoSans-Bold", "DejaVuSans-Bold"),
        ",", " ", "dmy", True,
    ),
}


def for_language(code: str) -> LocaleMeta:
    return META.get(code) or META["en"]


def is_rtl(code: str) -> bool:
    return bool(for_language(code).rtl)


def rtl_codes() -> tuple[str, ...]:
    return tuple(code for code, meta in META.items() if meta.rtl)


def iter_font_files() -> Iterable[Path]:
    """Font files matplotlib should register (Noto CJK is TTC)."""
    stems = {
        "NotoNaskhArabic",
        "NotoSansArabic",
        "NotoSansCJK",
        "NotoSansDevanagari",
        "NotoSans-Regular",
        "NotoSans-Bold",
        "DejaVuSans",
        "Gilroy",
        "BaiJamjuree",
        "Bai Jamjuree",
    }
    seen: set[str] = set()
    roots = [Path(__file__).resolve().parent.parent / "Fonts"]
    roots.extend(SYSTEM_FONT_DIRS)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            if not any(stem.lower() in path.name.lower() or stem in path.name for stem in stems):
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            yield path


def find_fontfile(code: str) -> str | None:
    """Absolute path for ffmpeg ``fontfile=`` / drawtext."""
    meta = for_language(code)
    candidates: list[Path] = []
    for path in iter_font_files():
        name = path.name.lower()
        if any(stem.lower() in name for stem in meta.fontfile_stems):
            candidates.append(path)
    if not candidates:
        return None
    # Prefer a regular/bold face, not thin/black.
    def rank(path: Path) -> int:
        n = path.name.lower()
        score = 0
        if "bold" in n:
            score += 2
        if "regular" in n or "medium" in n:
            score += 1
        if n.endswith(".ttc"):
            score += 3  # CJK
        if "thin" in n or "light" in n:
            score -= 4
        return -score

    candidates.sort(key=rank)
    return str(candidates[0])


def ffmpeg_subtitle_style(code: str) -> str:
    """libass ``force_style`` fragment for burned captions."""
    meta = for_language(code)
    fontfile = find_fontfile(code)
    parts = [
        f"Fontname={meta.ass_font}",
        "Fontsize=15",
        "PrimaryColour=&H00FFFFFF",
        "OutlineColour=&H00000000",
        "BorderStyle=1",
        "Outline=2",
        "Shadow=0",
        "Alignment=2",
        "MarginV=150",
        "Bold=1",
    ]
    # Alignment 2 = bottom-center. For RTL, still center; libass shapes Arabic.
    if fontfile:
        # libass Fontname is enough when the font is installed; Fontname+path
        # is passed separately for drawtext. Keep force_style portable.
        pass
    return ",".join(parts)


def ffmpeg_drawtext_fontfile(code: str) -> str:
    """``fontfile='/path/to.ttf'`` snippet, or empty if unresolved."""
    path = find_fontfile(code)
    if not path:
        return ""
    escaped = path.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    return f"fontfile='{escaped}'"


def missing_font_packages(code: str) -> tuple[str, ...]:
    """APT packages to install when the recommended face is absent."""
    from matplotlib import font_manager

    meta = for_language(code)
    available = {f.name for f in font_manager.fontManager.ttflist}
    if any(name in available for name in meta.display_fonts):
        return ()
    if meta.script in {"Arab"}:
        return ("fonts-noto-core",)
    if meta.script in {"Jpan", "Kore", "Hans", "Hant"}:
        return ("fonts-noto-cjk", "fonts-noto-cjk-extra")
    if meta.script == "Deva":
        return ("fonts-noto-core",)
    return ("fonts-noto-core", "fonts-noto-cjk")
