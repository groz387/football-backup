"""Every English catalog key exists in every locale (or is explicitly listed)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recap import i18n, locale_meta  # noqa: E402
from recap.locales import available_codes  # noqa: E402

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@pytest.fixture(autouse=True)
def _reset_language() -> None:
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text or ""))


def test_supported_matches_locale_meta() -> None:
    codes = set(available_codes())
    assert set(i18n.SUPPORTED) == codes
    assert codes == set(locale_meta.META)
    assert "ar" in codes and locale_meta.is_rtl("ar")
    assert locale_meta.rtl_codes() == ("ar",)


def test_every_english_key_is_covered() -> None:
    report = i18n.coverage_report()
    failures = []
    for row in report["languages"]:
        if not row["complete"]:
            failures.append(
                f"{row['code']}: missing ui={row['missing_ui'][:8]} stat={row['missing_stat']}"
            )
    assert not failures, "\n".join(failures)


def test_placeholders_match_english() -> None:
    en = i18n.pack("en")
    bad = []
    for code in available_codes():
        if code == "en":
            continue
        other = i18n.pack(code)
        for key, template in en.ui.items():
            if key in other.explicit_fallbacks:
                continue
            got = other.ui.get(key)
            if got is None:
                continue
            want = _placeholders(template)
            have = _placeholders(got)
            if want != have:
                bad.append(f"{code}.{key}: en={sorted(want)} got={sorted(have)}")
    assert not bad, "\n".join(bad[:20])


def test_t_falls_back_to_english() -> None:
    english = i18n.t("insight_nothing_board", lang="en")
    turkish = i18n.t("insight_nothing_board", lang="tr")
    assert turkish and turkish != english
    assert i18n.t("__no_such_key__", lang="ar") == "__no_such_key__"
    led_en = i18n.t("graph_led_everything", lang="en", team="Spain")
    led_az = i18n.t("graph_led_everything", lang="az", team="Spain")
    assert "Spain" in led_en and "Spain" in led_az
    assert led_en != led_az


def test_missing_locale_key_uses_english() -> None:
    pack = i18n.pack("tr")
    stolen = pack.ui.pop("cta_save", None)
    try:
        assert stolen is not None
        assert i18n.t("cta_save", lang="tr") == i18n.t("cta_save", lang="en")
    finally:
        if stolen is not None:
            pack.ui["cta_save"] = stolen


def test_format_score_is_universal() -> None:
    for code in available_codes():
        i18n.set_language(code)
        assert i18n.format_score(2, 1) == "2-1"
        assert i18n.format_score(0, 0) == "0-0"


def test_number_and_date_locales() -> None:
    assert "1.234" in i18n.format_number(1234.5, lang="de", decimals=1)
    assert "," in i18n.format_number(1234.5, lang="de", decimals=1)
    assert i18n.format_date("2026-09-02", lang="ja") == "2026/09/02"
    assert i18n.format_date("2026-09-02", lang="en") == "02.09.2026"


def test_aliases() -> None:
    assert i18n.normalize_language("pt-br") == "pt-BR"
    assert i18n.normalize_language("pt_PT") == "pt-PT"
    assert i18n.normalize_language("ua") == "uk"
    assert i18n.normalize_language("jp") == "ja"
    assert i18n.normalize_language("kr") == "ko"
    assert i18n.parse_languages("az,tr,ar") == ["az", "tr", "ar"]
    assert i18n.parse_languages("") == []


def test_arabic_shape_does_not_crash() -> None:
    shaped = i18n.shape_text("هدف", lang="ar")
    assert shaped
    display = i18n.prepare_display("هدف", upper=True, lang="ar")
    assert display
    engine = i18n.rtl_engine()
    assert engine in {"reshaper+bidi", "fallback-ltr"}
    x, ha = i18n.headline_anchor(0.08, "left", lang="ar")
    assert ha == "right" and x > 0.5


def test_social_copy_has_required_fields() -> None:
    copy = i18n.social_copy("Spain", "France", "2-1", "Euro", lang="ar")
    assert copy["rtl"] is True
    assert copy["captions"]["hook"]
    assert copy["ctas"]
    assert copy["comment_bait"]
    assert "2-1" in copy["endcard"]["score"]


def test_cli_exposes_language_flags() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "video_pipeline.py"), "--help"],
        capture_output=True, text=True, check=True,
    )
    help_text = result.stdout
    assert "--language" in help_text
    assert "--batch-languages" in help_text
    for code in ("tr", "pt-BR", "ar", "ja", "hi"):
        assert code in help_text


def test_ffmpeg_style_names_a_font() -> None:
    style = locale_meta.ffmpeg_subtitle_style("ar")
    assert "Fontname=" in style
    assert "Noto" in style or "Bai" in style
    latin = locale_meta.ffmpeg_subtitle_style("en")
    assert "Bai Jamjuree" in latin
