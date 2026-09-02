"""Social platform profiles for football recap exports.

Vertical-first. TikTok, Reels, Shorts and Stories share a 1080x1920 master
with UI safe zones (top 180px / bottom 250px), a 0.5s hook deadline, a
21–45s default runtime and a loopable 0.4s tail. YouTube 16:9 and square
feeds are restacked from that portrait master — never letterboxed.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from . import i18n
from . import safe_zones

DEFAULT_PLATFORMS = ("tiktok", "shorts")
ASPECT_CHOICES = ("9:16", "16:9", "1:1", "all")
SPOILER_CHOICES = ("show", "hide")
HOOK_DEADLINE_SECONDS = 0.5
SHORT_DURATION = (21.0, 45.0)
LOOP_TAIL_SECONDS = 0.4
END_CARD_SECONDS = 0.8
SCORELINE = re.compile(r"\b\d+\s*[-–:/]\s*\d+\b")

_PLATFORM_ALIASES = {
    "tiktok": "tiktok",
    "tt": "tiktok",
    "reels": "reels",
    "reel": "reels",
    "ig": "reels",
    "instagram": "reels",
    "shorts": "shorts",
    "short": "shorts",
    "ytshorts": "shorts",
    "stories": "stories",
    "story": "stories",
    "igstories": "stories",
    "youtube_long": "youtube_long",
    "youtube": "youtube_long",
    "yt": "youtube_long",
    "long": "youtube_long",
    "landscape": "youtube_long",
    "square": "square",
    "feed": "square",
    "1:1": "square",
    "1x1": "square",
}

_ASPECT_ALIASES = {
    "9:16": "9:16",
    "9/16": "9:16",
    "portrait": "9:16",
    "vertical": "9:16",
    "16:9": "16:9",
    "16/9": "16:9",
    "landscape": "16:9",
    "1:1": "1:1",
    "1/1": "1:1",
    "square": "1:1",
    "all": "all",
}


@dataclass(frozen=True)
class PlatformProfile:
    id: str
    name: str
    width: int
    height: int
    aspect: str
    safe_top_px: int
    safe_bottom_px: int
    max_hook_seconds: float = HOOK_DEADLINE_SECONDS
    duration_min: float = SHORT_DURATION[0]
    duration_max: float = SHORT_DURATION[1]
    loop_tail_seconds: float = LOOP_TAIL_SECONDS
    loop_mode: str = "freeze"  # freeze | snapback
    burn_captions: bool = True
    caption_contrast: str = "high"
    chapters: bool = False
    pacing_hooks: tuple[float, float] | None = None
    end_card_seconds: float = END_CARD_SECONDS
    filename: str = ""

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def safe(self) -> safe_zones.SafeZones:
        return safe_zones.for_canvas(
            self.width, self.height,
            top_px=self.safe_top_px, bottom_px=self.safe_bottom_px,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "aspect": self.aspect,
            "safe_top_px": self.safe_top_px,
            "safe_bottom_px": self.safe_bottom_px,
            "max_hook_seconds": self.max_hook_seconds,
            "duration_min": self.duration_min,
            "duration_max": self.duration_max,
            "loop_tail_seconds": self.loop_tail_seconds,
            "loop_mode": self.loop_mode,
            "burn_captions": self.burn_captions,
            "caption_contrast": self.caption_contrast,
            "chapters": self.chapters,
            "pacing_hooks": list(self.pacing_hooks) if self.pacing_hooks else None,
            "end_card_seconds": self.end_card_seconds,
            "filename": self.filename or f"{self.id}.mp4",
            "safe_zones": self.safe().as_dict(),
        }


PROFILES: dict[str, PlatformProfile] = {
    "tiktok": PlatformProfile(
        id="tiktok",
        name="TikTok",
        width=1080, height=1920, aspect="9:16",
        safe_top_px=180, safe_bottom_px=250,
        loop_mode="snapback",
        filename="tiktok.mp4",
    ),
    "reels": PlatformProfile(
        id="reels",
        name="Instagram Reels",
        width=1080, height=1920, aspect="9:16",
        safe_top_px=180, safe_bottom_px=250,
        loop_mode="freeze",
        filename="reels.mp4",
    ),
    "shorts": PlatformProfile(
        id="shorts",
        name="YouTube Shorts",
        width=1080, height=1920, aspect="9:16",
        safe_top_px=180, safe_bottom_px=250,
        duration_max=60.0,
        loop_mode="freeze",
        filename="shorts.mp4",
    ),
    "stories": PlatformProfile(
        id="stories",
        name="Stories",
        width=1080, height=1920, aspect="9:16",
        safe_top_px=180, safe_bottom_px=250,
        duration_min=8.0, duration_max=60.0,
        loop_mode="freeze",
        filename="stories.mp4",
    ),
    "youtube_long": PlatformProfile(
        id="youtube_long",
        name="YouTube 16:9",
        width=1920, height=1080, aspect="16:9",
        safe_top_px=48, safe_bottom_px=72,
        max_hook_seconds=3.0,
        duration_min=45.0, duration_max=8 * 60,
        loop_tail_seconds=0.0,
        loop_mode="freeze",
        chapters=True,
        pacing_hooks=(3 * 60, 8 * 60),
        filename="youtube_long.mp4",
    ),
    "square": PlatformProfile(
        id="square",
        name="Square feed",
        width=1080, height=1080, aspect="1:1",
        safe_top_px=80, safe_bottom_px=120,
        duration_min=12.0, duration_max=60.0,
        loop_mode="freeze",
        filename="square.mp4",
    ),
}


# Comment-bait last frame. i18n.t() is tried first so a sibling catalog wins.
_BAIT: dict[str, dict[str, str]] = {
    "en": {
        "end_card_motm": "WHO WAS MOTM?  COMMENT.",
        "end_card_robbery": "WAS IT A ROBBERY?  YES OR NO.",
        "end_card_vote": "HOME OR AWAY — VOTE BELOW.",
        "end_card_score": "FAIR RESULT?  TELL US.",
    },
    "az": {
        "end_card_motm": "MATÇIN ADAMI KİM OLDU?  ŞƏRH YAZ.",
        "end_card_robbery": "OĞURLUQ İDİ?  BƏLİ VƏ YA XEYR.",
        "end_card_vote": "EV VƏ YA QONAQLAR — SƏS VER.",
        "end_card_score": "ƏDALƏTLİ NƏTİCƏ?  YAZ.",
    },
    "es": {
        "end_card_motm": "¿QUIÉN FUE EL MVP?  COMENTA.",
        "end_card_robbery": "¿FUE UN ROBO?  SÍ O NO.",
        "end_card_vote": "LOCAL O VISITANTE — VOTA.",
        "end_card_score": "¿RESULTADO JUSTO?  DÍNOSLO.",
    },
    "ru": {
        "end_card_motm": "КТО ИГРОК МАТЧА?  ПИШИ.",
        "end_card_robbery": "ЭТО БЫЛО ОГРАБЛЕНИЕ?  ДА ИЛИ НЕТ.",
        "end_card_vote": "ХОЗЯЕВА ИЛИ ГОСТИ — ГОЛОСУЙ.",
        "end_card_score": "ЧЕСТНЫЙ СЧЁТ?  НАПИШИ.",
    },
}

ROBBERY_KINDS = {
    "xg_robbery", "volume_upset", "sterile_upset", "waste", "keeper_wall",
}


def bait_text(key: str, *, language: str | None = None, **kwargs: Any) -> str:
    code = i18n.normalize_language(language or i18n.get_language())
    catalog = i18n.UI.get(code) or {}
    template = catalog.get(key)
    if not template:
        template = (_BAIT.get(code) or _BAIT["en"]).get(key) or _BAIT["en"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
    return template


def comment_bait(
    *,
    language: str | None = None,
    hook_kind: str = "",
    player: str = "",
) -> tuple[str, str]:
    """Return (i18n_key, text) for the 0.8s end card."""
    lang = language or i18n.get_language()
    if player:
        return "end_card_motm", bait_text("end_card_motm", language=lang)
    if hook_kind in ROBBERY_KINDS:
        return "end_card_robbery", bait_text("end_card_robbery", language=lang)
    if hook_kind in {"level", "stalemate"}:
        return "end_card_vote", bait_text("end_card_vote", language=lang)
    return "end_card_score", bait_text("end_card_score", language=lang)


def parse_platforms(raw: str | Sequence[str] | None) -> list[str]:
    if raw is None or raw == "":
        values = list(DEFAULT_PLATFORMS)
    elif isinstance(raw, str):
        if raw.strip().lower() in {"all", "*"}:
            values = list(PROFILES)
        else:
            values = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    else:
        values = [str(part).strip() for part in raw if str(part).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = _PLATFORM_ALIASES.get(item.lower())
        if key is None:
            raise ValueError(
                f"Unknown platform {item!r}. Choose from: {', '.join(PROFILES)}"
            )
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out or list(DEFAULT_PLATFORMS)


def parse_aspect(raw: str | None) -> str:
    key = _ASPECT_ALIASES.get((raw or "all").strip().lower())
    if key is None:
        raise ValueError(f"Unknown --aspect {raw!r}. Choose 9:16, 16:9, 1:1 or all.")
    return key


def parse_spoiler(raw: str | None) -> str:
    value = (raw or "show").strip().lower()
    if value not in SPOILER_CHOICES:
        raise ValueError(f"Unknown --spoiler {raw!r}. Choose show or hide.")
    return value


def resolve_exports(
    platforms: str | Sequence[str] | None = None,
    aspect: str | None = "all",
) -> list[PlatformProfile]:
    ids = parse_platforms(platforms)
    ratio = parse_aspect(aspect)
    profiles = [PROFILES[item] for item in ids]
    if ratio != "all":
        profiles = [item for item in profiles if item.aspect == ratio]
    return profiles


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Unique flag names. Skips dests a sibling parser already registered."""
    dests = {action.dest for action in parser._actions}
    if "platforms" not in dests:
        parser.add_argument(
            "--platforms", default=",".join(DEFAULT_PLATFORMS),
            help="Comma-separated exports: tiktok,reels,shorts,stories,youtube_long,square "
                 f"(default {','.join(DEFAULT_PLATFORMS)})",
        )
    if "aspect" not in dests:
        parser.add_argument(
            "--aspect", default="all", choices=list(ASPECT_CHOICES),
            help="Keep only platforms of this ratio, or all requested platforms",
        )
    if "spoiler" not in dests:
        parser.add_argument(
            "--spoiler", default="show", choices=list(SPOILER_CHOICES),
            help="hide = curiosity hook: no final score in the first 3s or the thumbnail",
        )
    if "end_card" not in dests:
        parser.add_argument(
            "--end-card", dest="end_card", action="store_true", default=True,
            help="Append a 0.8s comment-bait card (default on)",
        )
        parser.add_argument(
            "--no-end-card", dest="end_card", action="store_false",
            help="Skip the comment-bait end card",
        )


def looks_like_score(text: Any) -> bool:
    return bool(SCORELINE.search(str(text or "")))


def apply_hook_deadline(
    scenes: list[dict[str, Any]],
    *,
    deadline: float = HOOK_DEADLINE_SECONDS,
) -> list[dict[str, Any]]:
    """Trim opening live clips so the first readable hook lands by *deadline*."""
    if not scenes:
        return scenes
    readable = 0.0
    out: list[dict[str, Any]] = []
    hooked = False
    for scene in scenes:
        updated = dict(scene)
        viz = str(updated.get("visualization") or "")
        is_hook = bool(updated.get("hook")) or viz in {
            "hook_claim", "hook_punch", "micro_hook", "stat_slam",
        }
        seconds = float(updated.get("seconds") or updated.get("on_screen") or 0.0)
        if not hooked and viz == "live_clip":
            room = max(0.15, deadline - readable)
            if seconds > room:
                seconds = round(room, 3)
                updated["seconds"] = seconds
                if "on_screen" in updated:
                    updated["on_screen"] = seconds
            readable += seconds
            out.append(updated)
            continue
        if is_hook and viz != "live_clip":
            hooked = True
        readable += seconds
        out.append(updated)
    return out


def opening_has_score(scenes: list[dict[str, Any]], *, window: float = 3.0) -> bool:
    elapsed = 0.0
    for scene in scenes:
        if elapsed >= window:
            break
        blob = " ".join(
            str(scene.get(field) or "")
            for field in ("title", "subtitle", "kicker", "insight", "narration", "hook_stat")
        )
        if looks_like_score(blob):
            return True
        elapsed += float(scene.get("seconds") or scene.get("on_screen") or scene.get("clip") or 0.0)
    return False


def first_readable_at(scenes: list[dict[str, Any]]) -> float:
    elapsed = 0.0
    for scene in scenes:
        viz = str(scene.get("visualization") or "")
        if viz in {"hook_claim", "hook_punch", "stat_slam"} or scene.get("hero_number") is not None:
            return elapsed
        elapsed += float(scene.get("seconds") or scene.get("on_screen") or 0.0)
    return elapsed


def mute_first_gaps(scenes: list[dict[str, Any]]) -> list[str]:
    """Every beat must carry on-screen text (title, lines, or narration)."""
    gaps = []
    for scene in scenes:
        viz = str(scene.get("visualization") or scene.get("id") or "scene")
        title = str(scene.get("title") or "").strip()
        lines = [str(item).strip() for item in (scene.get("lines") or []) if str(item).strip()]
        narration = str(scene.get("narration") or "").strip()
        insight = str(scene.get("insight") or "").strip()
        if not (title or lines or narration or insight or scene.get("hero_number") is not None):
            gaps.append(viz)
    return gaps


def chapters_from_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """YouTube chapter list. Uses visible_start when the timeline has been planned."""
    chapters: list[dict[str, Any]] = []
    cursor = 0.0
    for scene in scenes:
        start = float(scene.get("visible_start") if scene.get("visible_start") is not None else cursor)
        title = str(scene.get("title") or scene.get("visualization") or "Beat").strip()
        title = re.sub(r"\s+", " ", title)[:80] or "Beat"
        if not chapters or start - float(chapters[-1]["start"]) >= 1.0:
            chapters.append({"start": round(start, 3), "title": title})
        cursor = float(scene.get("visible_end") or scene.get("clip_end") or (cursor + float(scene.get("clip") or scene.get("on_screen") or 0)))
    if chapters:
        chapters[0]["start"] = 0.0
    return chapters


def render_youtube_chapters(chapters: list[dict[str, Any]]) -> str:
    lines = []
    for item in chapters:
        seconds = max(0, int(item["start"]))
        stamp = f"{seconds // 60}:{seconds % 60:02d}"
        lines.append(f"{stamp} {item['title']}")
    return "\n".join(lines) + ("\n" if lines else "")


def validate_plan(
    scenes: list[dict[str, Any]],
    profile: PlatformProfile,
    *,
    spoiler: str = "show",
    total_seconds: float | None = None,
) -> list[str]:
    problems: list[str] = []
    problems.extend(safe_zones.validate_zones(profile.safe()))
    readable = first_readable_at(scenes)
    if readable > profile.max_hook_seconds + 1e-6:
        problems.append(
            f"{profile.id}: first readable hook at {readable:.2f}s "
            f"(deadline {profile.max_hook_seconds:.2f}s)"
        )
    gaps = mute_first_gaps(scenes)
    if gaps:
        problems.append(f"{profile.id}: beats without on-screen text: {', '.join(gaps)}")
    if spoiler == "hide" and opening_has_score(scenes, window=3.0):
        problems.append(f"{profile.id}: spoiler=hide but a score appears in the first 3s")
    duration = total_seconds
    if duration is None and scenes:
        duration = sum(float(s.get("on_screen") or s.get("seconds") or s.get("clip") or 0) for s in scenes)
    if duration and profile.aspect == "9:16":
        if duration + 1.5 < profile.duration_min:
            problems.append(
                f"{profile.id}: {duration:.1f}s is under the {profile.duration_min:.0f}–"
                f"{profile.duration_max:.0f}s short-form window"
            )
        if duration > profile.duration_max + 8:
            problems.append(f"{profile.id}: {duration:.1f}s overruns the {profile.duration_max:.0f}s cap")
    return problems


def dry_validate_profiles(
    platforms: str | Sequence[str] | None = None,
    aspect: str | None = "all",
) -> dict[str, Any]:
    """No match required: every requested canvas has legal dimensions and safe zones."""
    profiles = resolve_exports(platforms, aspect)
    reports = []
    ok = True
    for profile in profiles:
        zone_report = safe_zones.dry_validate(
            profile.width, profile.height,
            top_px=profile.safe_top_px, bottom_px=profile.safe_bottom_px,
        )
        row = {
            "id": profile.id,
            "size": f"{profile.width}x{profile.height}",
            "aspect": profile.aspect,
            "ok": zone_report["ok"],
            "problems": zone_report["problems"],
            "max_hook_seconds": profile.max_hook_seconds,
            "loop_tail_seconds": profile.loop_tail_seconds,
            "loop_mode": profile.loop_mode,
        }
        ok = ok and zone_report["ok"]
        reports.append(row)
    return {
        "ok": ok,
        "platforms": [p.id for p in profiles],
        "reports": reports,
        "portrait_method": (
            "9:16 is the portrait master (1080x1920). Other ratios restack hook/"
            "hero/caption bands with vstack/hstack — never pad-to-fit letterbox."
        ),
    }


def export_platforms(
    out_dir: Path | str | None = None,
    platforms: str | Sequence[str] | None = None,
    *,
    video_path: Path | str | None = None,
    package_dir: Path | str | None = None,
    plan: dict[str, Any] | None = None,
    language: str = "en",
    format: str | None = None,
    aspect: str | None = None,
    spoiler: str = "show",
    end_card: bool = True,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Hook for recap.batch.try_apply_platforms and the video_pipeline pack step."""
    from . import export_pack as export_pack_mod

    dest = Path(out_dir or package_dir or ".")
    master = Path(video_path) if video_path else dest / "match_video.mp4"
    audit: dict[str, Any] = {}
    audit_path = dest / "data_audit.json"
    plan_path = dest / "video_plan.json"
    if audit_path.exists():
        import json
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if plan is None and plan_path.exists():
        import json
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if aspect is None:
        aspect = "16:9" if str(format or "") == "long" else "all"
    flag: str | Sequence[str] | None = platforms
    if not flag:
        flag = "youtube_long" if str(format or "") == "long" else DEFAULT_PLATFORMS
    return export_pack_mod.export_pack(
        dest,
        master if master.exists() else None,
        platforms_flag=flag,
        aspect=aspect,
        spoiler=spoiler,
        end_card=end_card,
        language=language,
        audit=audit,
        plan=plan,
        srt_path=dest / "subtitles.srt",
    )


apply_platforms = export_platforms
export = export_platforms
apply = export_platforms
