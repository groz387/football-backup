"""Shared farm orchestration for CLI and the local studio.

Language selection, auto colours, script bookends, ElevenLabs VO, and package
layout live here so `video_pipeline.py` and `studio/` cannot drift.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import config as cfg, theme
from .data import safe_name

LAYOUT_LANG_MATCH = "lang_match"   # video_output/<lang>/<match>/  (--batch-languages)
LAYOUT_MATCH_LANG = "match_lang"   # video_output/<match>/<lang>/  (--languages)


def parse_language_list(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    from . import batch
    return batch.parse_languages(raw)


def resolve_languages(args: argparse.Namespace) -> list[str]:
    """`--languages` / `--dub-languages` / `--skip-language` / `--batch-languages`."""
    skip = set(parse_language_list(getattr(args, "skip_language", "") or ""))
    from . import batch
    if getattr(args, "languages", None):
        langs = parse_language_list(args.languages)
    elif getattr(args, "dub_languages", None):
        primary = batch.normalize_lang(getattr(args, "language", None) or "az")
        langs = [primary]
        for code in parse_language_list(args.dub_languages):
            if code not in langs:
                langs.append(code)
    elif getattr(args, "batch_languages", None):
        langs = parse_language_list(args.batch_languages)
    else:
        langs = [batch.normalize_lang(getattr(args, "language", None) or "en")]
    return [code for code in langs if code not in skip]


def farm_layout(args: argparse.Namespace) -> str:
    if getattr(args, "languages", None) or getattr(args, "dub_languages", None):
        return LAYOUT_MATCH_LANG
    if getattr(args, "batch_languages", None):
        return LAYOUT_LANG_MATCH
    return LAYOUT_MATCH_LANG if len(resolve_languages(args)) > 1 else LAYOUT_LANG_MATCH


def package_dir(
    output_root: Path,
    match_name: str,
    language: str,
    fmt: str,
    *,
    layout: str,
    batched: bool,
) -> Path:
    from . import longform

    root = Path(output_root)
    match = safe_name(match_name)
    if layout == LAYOUT_MATCH_LANG:
        base = root / match / language
    elif batched:
        base = root / language / match
    else:
        base = root / match
    if fmt == longform.LONG:
        return base / "long"
    return base


def apply_auto_colors(home: str, away: str, *, override: tuple[str, str] | None = None) -> dict[str, Any]:
    """CLI `--colors` wins. Otherwise pick from the club/national table."""
    if override and len(override) == 2:
        home_hex, away_hex = theme.set_team_colors(override[0], override[1])
        return {
            "home": home_hex,
            "away": away_hex,
            "source": "cli",
            "clash": False,
            "away_used_secondary": False,
            "home_used_secondary": False,
        }
    picked_fn = getattr(theme, "pick_kit_colors", None)
    if not callable(picked_fn):
        return {
            "home": "",
            "away": "",
            "source": "default",
            "clash": False,
            "away_used_secondary": False,
            "home_used_secondary": False,
        }
    picked = picked_fn(home, away)
    theme.set_team_colors(picked["home"], picked["away"])
    picked["source"] = "auto"
    return picked


def voiceover_path(out_dir: Path) -> Path:
    return Path(out_dir) / "voiceover.mp3"


def language_status_badge(out_dir: Path) -> dict[str, Any]:
    out = Path(out_dir)
    script = (out / "SCRIPT.md").exists() or (out / "narration.txt").exists()
    voice = voiceover_path(out).exists()
    video = (out / "match_video.mp4").exists()
    growth = (out / "growth.json").exists()
    if video:
        state = "produced"
    elif voice:
        state = "voiced"
    elif script:
        state = "scripted"
    else:
        state = "empty"
    return {
        "script": script,
        "voice": voice,
        "video": video,
        "growth": growth,
        "state": state,
        "out_dir": str(out),
    }


def persist_studio_settings(path: Path, payload: dict[str, Any]) -> None:
    from .data import write_json

    allowed = {
        "languages": list(payload.get("languages") or DEFAULT_STUDIO_LANGUAGES),
        "voice_name": str(payload.get("voice_name") or cfg.DEFAULT_VOICE_NAME),
        "voice_id": str(payload.get("voice_id") or ""),
        "eleven_style": cfg.eleven_style(payload.get("eleven_style") or "robust"),
        "team": str(payload.get("team") or "club"),
    }
    write_json(path, allowed)


def load_studio_settings(path: Path) -> dict[str, Any]:
    from .data import read_json

    defaults = {
        "languages": list(cfg.DEFAULT_STUDIO_LANGUAGES),
        "voice_name": cfg.DEFAULT_VOICE_NAME,
        "voice_id": "",
        "eleven_style": "robust",
        "team": "club",
    }
    path = Path(path)
    if not path.exists():
        return defaults
    try:
        data = read_json(path)
    except Exception:
        return defaults
    if not isinstance(data, dict):
        return defaults
    defaults.update({k: data[k] for k in defaults if k in data})
    return defaults


DEFAULT_STUDIO_LANGUAGES = cfg.DEFAULT_STUDIO_LANGUAGES
KNOWN_LANGUAGES = cfg.FARM_LANGUAGES
