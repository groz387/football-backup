"""Batch languages / platforms / growth around one recap render.

Sibling modules (`recap.platforms`, `recap.growth`) are optional. This package
always exposes:

    from recap.batch import run_batch

`run_batch` expands `--format` × `--batch-languages` into jobs, writes each
package under `video_output/<lang>/` when batching, skips work that is already
on disk, and prints a posting checklist. It never scrapes.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import audit as audit_mod
from . import clips, director, i18n, longform, theme, timing
from .data import describe_match_dir, list_match_dirs, load_match, safe_name, write_json

FARM_LANGUAGE_NAMES = {
    "en": "English",
    "az": "Azerbaijani",
    "es": "Spanish",
    "ru": "Russian",
    "tr": "Turkish",
}
FARM_LANGUAGE_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "az": "az", "aze": "az", "azerbaijani": "az", "azeri": "az",
    "es": "es", "spa": "es", "spanish": "es", "español": "es", "espanol": "es",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "tr": "tr", "tur": "tr", "turkish": "tr",
}

STAMP_NAME = "run_stamp.json"
GROWTH_NAME = "growth.json"
PLATFORMS_MOD = "recap.platforms"
EXPORT_PACK_MOD = "recap.export_pack"
GROWTH_MOD = "recap.growth"
PLATFORM_FUNCS = (
    "export_platforms", "apply_platforms", "export", "apply", "render", "run",
)
GROWTH_FUNCS = (
    "write_growth", "write", "build_growth", "build", "export", "run",
)


# ---------------------------------------------------------------------------
# language registry — extra farm codes (tr) without waiting on the i18n PR
# ---------------------------------------------------------------------------

def register_farm_languages() -> None:
    """Teach recap.i18n about farm codes the i18n sibling may not have merged yet."""
    aliases = getattr(i18n, "ALIASES", None)
    names = getattr(i18n, "LANGUAGE_NAMES", None)
    if isinstance(aliases, dict):
        for alias, code in FARM_LANGUAGE_ALIASES.items():
            aliases.setdefault(alias, code)
    if isinstance(names, dict):
        for code, label in FARM_LANGUAGE_NAMES.items():
            names.setdefault(code, label)
    supported = getattr(i18n, "SUPPORTED", ())
    extra = tuple(code for code in FARM_LANGUAGE_NAMES if code not in supported)
    if extra and isinstance(supported, tuple):
        i18n.SUPPORTED = supported + extra
    elif extra and isinstance(supported, list):
        supported.extend(extra)


def known_languages() -> tuple[str, ...]:
    register_farm_languages()
    codes = set(getattr(i18n, "SUPPORTED", ())) | set(FARM_LANGUAGE_NAMES)
    return tuple(sorted(codes))


def normalize_lang(value: str) -> str:
    register_farm_languages()
    raw = (value or "").strip().lower()
    if not raw:
        raise ValueError("Empty language code.")
    try:
        return i18n.normalize_language(raw)
    except ValueError:
        code = FARM_LANGUAGE_ALIASES.get(raw)
        if code:
            return code
        raise ValueError(
            f"Unsupported language {value!r}. Choose from: {', '.join(known_languages())}"
        ) from None


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for part in str(raw).replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(token)
    return items


def parse_languages(raw: str | None) -> list[str]:
    return [normalize_lang(item) for item in parse_csv(raw)]


def activate_language(code: str) -> str:
    """Set i18n current language. Unknown catalogs fall back to English chrome."""
    register_farm_languages()
    resolved = normalize_lang(code)
    try:
        return i18n.set_language(resolved)
    except ValueError:
        i18n.set_language("en")
        return resolved


def language_label(code: str) -> str:
    register_farm_languages()
    try:
        return i18n.language_name(code)
    except Exception:
        return FARM_LANGUAGE_NAMES.get(code, code)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

@dataclass
class Job:
    match_dir: Path
    language: str
    fmt: str
    out_dir: Path
    platforms: list[str] = field(default_factory=list)
    series_id: str = ""
    write_growth: bool = False
    viz_count: int | None = None
    target_seconds: float | None = None
    batched: bool = False


@dataclass
class JobResult:
    job: Job
    status: str  # rendered | skipped | planned | failed
    plan: dict[str, Any] = field(default_factory=dict)
    out_dir: Path | None = None
    video: Path | None = None
    platforms: dict[str, Any] = field(default_factory=dict)
    growth: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def package_dir(
    output_root: Path,
    match_name: str,
    language: str,
    fmt: str,
    *,
    batched: bool,
) -> Path:
    """Language-first layout when batching: video_output/<lang>/<match>[/long]."""
    root = Path(output_root)
    match = safe_name(match_name)
    if batched:
        base = root / language / match
    else:
        base = root / match
    if fmt == longform.LONG:
        return base / "long"
    return base


def expand_jobs(args: argparse.Namespace, match_dir: Path) -> list[Job]:
    batched = bool(getattr(args, "batch_languages", "") or "")
    if batched:
        languages = parse_languages(args.batch_languages)
    else:
        languages = [normalize_lang(getattr(args, "language", None) or "en")]
    formats = longform.formats_from(getattr(args, "format", None) or longform.SHORT)
    platforms = parse_csv(getattr(args, "platforms", "") or "")
    series_id = str(getattr(args, "series_id", "") or "")
    write_growth = bool(getattr(args, "write_growth", False))
    output_root = Path(args.output_root)
    jobs: list[Job] = []
    for language in languages:
        for fmt in formats:
            jobs.append(Job(
                match_dir=Path(match_dir),
                language=language,
                fmt=fmt,
                out_dir=package_dir(
                    output_root, match_dir.name, language, fmt, batched=batched,
                ),
                platforms=platforms,
                series_id=series_id,
                write_growth=write_growth,
                viz_count=getattr(args, "visualizations", None),
                target_seconds=getattr(args, "target_seconds", None),
                batched=batched,
            ))
    return jobs


def stamp_for(args: argparse.Namespace, job: Job) -> dict[str, Any]:
    return {
        "match": job.match_dir.name,
        "language": job.language,
        "format": job.fmt,
        "fps": int(getattr(args, "fps", 24) or 24),
        "skip_audio": bool(getattr(args, "skip_audio", False)),
        "music_bed": getattr(args, "music_bed", "auto"),
        "loudnorm": getattr(args, "loudnorm", "tiktok"),
        "sfx": bool(getattr(args, "sfx", True)),
        "skip_video": bool(getattr(args, "skip_video", False)),
        "still": bool(getattr(args, "still", False)),
        "visualizations": job.viz_count,
        "target_seconds": job.target_seconds,
        "series_id": job.series_id or "",
        "team": getattr(args, "team", "national"),
        "colors": list(getattr(args, "colors", None) or []),
    }


def package_complete(out_dir: Path, stamp: dict[str, Any], args: argparse.Namespace) -> bool:
    out_dir = Path(out_dir)
    stamp_path = out_dir / STAMP_NAME
    if not stamp_path.exists():
        return False
    try:
        existing = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if existing != stamp:
        return False
    if getattr(args, "still", False):
        stills = out_dir / "stills"
        return stills.is_dir() and any(stills.iterdir())
    if getattr(args, "skip_video", False):
        return (out_dir / "video_plan.json").exists()
    return (out_dir / "match_video.mp4").exists()


def write_stamp(out_dir: Path, stamp: dict[str, Any]) -> None:
    write_json(Path(out_dir) / STAMP_NAME, stamp)


# ---------------------------------------------------------------------------
# editorial plan (used by --print-plan; no frames, no fetch, no Gemini)
# ---------------------------------------------------------------------------

def build_plan(
    args: argparse.Namespace,
    job: Job,
    *,
    bundle=None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    activate_language(job.language)
    if bundle is None:
        bundle = load_match(job.match_dir)
    if audit is None:
        audit = audit_mod.build_audit(bundle)
    hook = director.build_hook(bundle, audit)
    angle = director.pick_angle(bundle, audit)
    candidates = director.visualization_candidates(bundle, audit)
    available = [c for c in candidates if c.get("available")]
    count = longform.viz_count_for(job.fmt, job.viz_count, len(available))
    selected, _ = director.select_visualizations(bundle, audit, count, None, "")
    extra_clips = [Path(p) for p in (getattr(args, "clip", None) or [])]
    discover = getattr(clips, "discover_sources", None)
    sources = discover(job.match_dir, extra_clips) if callable(discover) else []
    beats = clips.plan_beats(bundle, audit, sources) if sources else []
    scenes = director.build_storyboard(bundle, audit, selected, clip_beats=beats)
    scenes = longform.pace_scenes(scenes, job.fmt)
    scenes = timing.timeline(scenes)
    viz_ids = [item["id"] for item in selected]
    total = timing.total_seconds(scenes)
    chapters = longform.chapter_markers(scenes) if job.fmt == longform.LONG else []
    hook_line = " / ".join(
        part for part in (
            " ".join(hook.get("lines") or []),
            hook.get("punch") or "",
        ) if part
    )
    note = longform.runtime_note(total, viz_ids) if job.fmt == longform.LONG else ""
    platforms_mod = optional_module(PLATFORMS_MOD)
    growth_mod = optional_module(GROWTH_MOD)
    return {
        "match": audit.get("match") or {},
        "match_dir": str(job.match_dir),
        "match_label": describe_match_dir(job.match_dir),
        "language": job.language,
        "language_name": language_label(job.language),
        "format": job.fmt,
        "angle": angle,
        "hook": hook_line,
        "hook_kind": hook.get("kind") or "",
        "hook_in_first_3s": longform.hook_lands_in_window(scenes),
        "visualizations": viz_ids,
        "available_visualizations": [c["id"] for c in available],
        "estimated_seconds": total,
        "runtime": longform.format_runtime(total),
        "chapters": chapters,
        "platforms": list(job.platforms),
        "platforms_module": platforms_mod is not None,
        "growth_module": growth_mod is not None,
        "write_growth": job.write_growth,
        "series_id": job.series_id,
        "series_burned_in_video": False,
        "out_dir": str(job.out_dir),
        "note": note,
        "local_clips": len(sources),
    }


def render_plan_text(plans: list[dict[str, Any]]) -> str:
    if not plans:
        return "No jobs to plan."
    first = plans[0]
    langs = []
    for plan in plans:
        if plan["language"] not in langs:
            langs.append(plan["language"])
    platforms = first.get("platforms") or []
    plat_state = (
        "recap.platforms ready" if first.get("platforms_module")
        else "recap.platforms not installed — flag stored, export skipped"
    )
    growth_state = (
        "recap.growth ready" if first.get("growth_module")
        else "recap.growth not installed — pipeline will write growth.json itself"
    )
    lines = [
        "PLAN  (dry-run — no frames, no clip fetch, no Gemini)",
        f"  match      {first.get('match_label')}",
        f"  angle      {first.get('angle')}",
        f"  hook       {first.get('hook')}",
        f"  languages  {', '.join(langs)}",
        f"  platforms  {', '.join(platforms) or '(none)'}  [{plat_state}]",
        f"  series-id  {first.get('series_id') or '(none)'}  [never burned into the video]",
        f"  growth     {'yes' if first.get('write_growth') else 'no'}  [{growth_state}]",
        "",
    ]
    for plan in plans:
        viz = ", ".join(plan.get("visualizations") or []) or "(none)"
        lines.append(
            f"  {plan['language']:<4} {plan['format']:<5}  ~{plan['runtime']:<6}  "
            f"hook@3s={'yes' if plan.get('hook_in_first_3s') else 'NO'}  "
            f"→ {plan['out_dir']}"
        )
        lines.append(f"           viz: {viz}")
        if plan.get("chapters"):
            ch = " | ".join(
                f"{longform.format_runtime(c['start'])} {c['title']}" for c in plan["chapters"]
            )
            lines.append(f"           chapters: {ch}")
        if plan.get("note"):
            lines.append(f"           note: {plan['note']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# optional sibling modules
# ---------------------------------------------------------------------------

def optional_module(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _call_compatible(fn: Callable, **kwargs: Any) -> Any:
    """Pass only kwargs the sibling function actually accepts."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(**kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)
    accepted = {
        key: value for key, value in kwargs.items()
        if key in params
    }
    # If the first positional is out_dir / path and we have it, send it positionally.
    names = [
        name for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and name != "self"
    ]
    if names and names[0] in accepted:
        first = accepted.pop(names[0])
        return fn(first, **accepted)
    return fn(**accepted)


def _normalize_platform_ids(raw: list[str]) -> list[str]:
    """Prefer recap.platforms.parse_platforms when the sibling has merged."""
    if not raw:
        return []
    mod = optional_module(PLATFORMS_MOD)
    parse = getattr(mod, "parse_platforms", None) if mod else None
    if callable(parse):
        try:
            return list(parse(",".join(raw)))
        except (TypeError, ValueError):
            return list(raw)
    return list(raw)


def try_apply_platforms(
    out_dir: Path,
    platforms: list[str],
    *,
    fmt: str,
    language: str,
    series_id: str,
    plan: dict[str, Any] | None = None,
    video_path: Path | None = None,
    audit: dict[str, Any] | None = None,
    fps: int = 24,
    aspect: str = "all",
    spoiler: str = "show",
    end_card: bool = True,
) -> dict[str, Any]:
    if not platforms:
        return {"status": "skipped", "reason": "no --platforms"}
    requested = _normalize_platform_ids(platforms)
    pack = optional_module(EXPORT_PACK_MOD)
    export_fn = getattr(pack, "export_pack", None) if pack else None
    if callable(export_fn):
        result = _call_compatible(
            export_fn,
            out_dir=Path(out_dir),
            master=video_path,
            platforms_flag=",".join(requested),
            aspect=aspect,
            spoiler=spoiler,
            end_card=end_card,
            language=language,
            audit=audit or {},
            plan=plan or {},
            srt_path=Path(out_dir) / "subtitles.srt",
            fps=fps,
            series_id=series_id,
            format=fmt,
        )
        return {"status": "ok", "requested": requested, "result": result}

    mod = optional_module(PLATFORMS_MOD)
    if mod is None:
        return {
            "status": "skipped",
            "reason": (
                f"{PLATFORMS_MOD} / {EXPORT_PACK_MOD} not installed; "
                f"{', '.join(requested)} stored for a later merge"
            ),
            "requested": requested,
        }
    fn = next((getattr(mod, name) for name in PLATFORM_FUNCS if callable(getattr(mod, name, None))), None)
    if fn is None:
        return {
            "status": "skipped",
            "reason": f"{PLATFORMS_MOD} has no export hook ({', '.join(PLATFORM_FUNCS)})",
            "requested": requested,
        }
    result = _call_compatible(
        fn,
        out_dir=Path(out_dir),
        platforms=requested,
        format=fmt,
        language=language,
        series_id=series_id,
        plan=plan or {},
        audit=audit or {},
        video_path=video_path,
        master=video_path,
        package_dir=Path(out_dir),
        fps=fps,
        aspect=aspect,
        spoiler=spoiler,
        end_card=end_card,
    )
    return {"status": "ok", "requested": requested, "result": result}


def growth_payload(
    job: Job,
    audit: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    video_path: Path | None,
) -> dict[str, Any]:
    match = (audit or {}).get("match") or (plan or {}).get("match") or {}
    return {
        "series_id": job.series_id or None,
        "series_label": job.series_id or None,
        "burned_in_video": False,
        "match": match,
        "match_dir": str(job.match_dir),
        "language": job.language,
        "format": job.fmt,
        "out_dir": str(job.out_dir),
        "video": str(video_path) if video_path else None,
        "platforms": list(job.platforms),
        "angle": (plan or {}).get("angle"),
        "hook": (plan or {}).get("hook"),
        "visualizations": (plan or {}).get("visualizations"),
        "runtime_seconds": (plan or {}).get("estimated_seconds"),
    }


def try_write_growth(
    job: Job,
    *,
    audit: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    video_path: Path | None = None,
) -> dict[str, Any]:
    if not job.write_growth:
        return {"status": "skipped", "reason": "no --write-growth"}
    payload = growth_payload(job, audit, plan, video_path)
    out_path = Path(job.out_dir) / GROWTH_NAME
    write_json(out_path, payload)
    mod = optional_module(GROWTH_MOD)
    if mod is None:
        return {
            "status": "written",
            "path": str(out_path),
            "reason": f"{GROWTH_MOD} is not installed; wrote {GROWTH_NAME} from the pipeline hook",
        }
    fn = next((getattr(mod, name) for name in GROWTH_FUNCS if callable(getattr(mod, name, None))), None)
    if fn is None:
        return {
            "status": "written",
            "path": str(out_path),
            "reason": f"{GROWTH_MOD} has no write hook; left {GROWTH_NAME} as-is",
        }
    result = _call_compatible(
        fn,
        out_dir=Path(job.out_dir),
        payload=payload,
        series_id=job.series_id,
        language=job.language,
        format=job.fmt,
        plan=plan or {},
        audit=audit or {},
        video_path=video_path,
        path=out_path,
    )
    return {"status": "ok", "path": str(out_path), "result": result}


# ---------------------------------------------------------------------------
# clip acquire — works with current clips.py or a sibling acquire_sources
# ---------------------------------------------------------------------------

def acquire_clip_sources(
    bundle,
    match_dir: Path,
    extra: list[Path],
    *,
    fetch: bool,
    refetch: bool = False,
    audit: dict[str, Any] | None = None,
    language: str = "en",
) -> tuple[list[Path], dict[str, Any]]:
    acquire = getattr(clips, "acquire_sources", None)
    if callable(acquire):
        try:
            result = acquire(
                bundle, match_dir, extra,
                fetch=fetch, refetch=refetch, audit=audit, language=language,
            )
        except TypeError:
            result = acquire(bundle, match_dir, extra, fetch=fetch)
        if isinstance(result, tuple) and len(result) >= 2:
            sources, report = result[0], result[1]
            return list(sources or []), dict(report or {})
        return list(result or []), {"mode": "acquired"}

    sources = list(clips.discover_sources(match_dir, extra) or [])
    report: dict[str, Any] = {"mode": "local" if sources else "none", "path": str(sources[0]) if sources else None}
    if fetch and not sources:
        dest = Path(match_dir) / "clips"
        fetch_fn = clips.fetch_highlight
        fetched = None
        try:
            fetched = fetch_fn(bundle, dest, audit=audit, refetch=refetch)
        except TypeError:
            fetched = fetch_fn(bundle, dest)
        if fetched:
            sources = [Path(fetched)]
            report = {"mode": "fetched", "path": str(fetched)}
    return sources, report


def log_clip_report(report: dict[str, Any], say: Callable[[str], None]) -> None:
    logger = getattr(clips, "log_report", None)
    if callable(logger):
        logger(report)
        return
    mode = report.get("mode") or "none"
    title = report.get("title") or report.get("path") or ""
    say(f"  clips: {mode}" + (f"  {title}" if title else ""))


# ---------------------------------------------------------------------------
# posting checklist + orchestrator
# ---------------------------------------------------------------------------

def posting_checklist(results: list[JobResult]) -> str:
    if not results:
        return "POSTING CHECKLIST\n  (nothing rendered)"
    first_plan = next((r.plan for r in results if r.plan), {})
    match_label = first_plan.get("match_label") or results[0].job.match_dir.name
    series = results[0].job.series_id
    langs = []
    for result in results:
        if result.job.language not in langs:
            langs.append(result.job.language)
    fmts = []
    for result in results:
        if result.job.fmt not in fmts:
            fmts.append(result.job.fmt)
    lines = [
        "",
        "=" * 66,
        "POSTING CHECKLIST",
        "=" * 66,
        f"  match       {match_label}",
        f"  languages   {', '.join(langs)}",
        f"  formats     {', '.join(fmts)}",
        f"  series-id   {series or '(none)'}  — used in growth JSON, never on frame",
        "",
    ]
    for result in results:
        plan = result.plan or {}
        runtime = plan.get("runtime") or "?"
        video = result.video or (Path(result.job.out_dir) / "match_video.mp4")
        exists = Path(video).exists() if video else False
        mark = "ok" if result.status in {"rendered", "skipped"} and (exists or result.status == "skipped") else result.status
        lines.append(
            f"  [{mark:<8}] {result.job.language}/{result.job.fmt}"
            f"  ~{runtime}  {result.job.out_dir}"
        )
        if plan.get("hook"):
            lines.append(f"             hook: {plan['hook']}")
        if plan.get("visualizations"):
            lines.append(f"             viz:  {', '.join(plan['visualizations'])}")
        if plan.get("chapters"):
            ch = " | ".join(
                f"{longform.format_runtime(c['start'])} {c['title']}" for c in plan["chapters"]
            )
            lines.append(f"             yt:   {ch}")
        plat = result.platforms or {}
        if plat:
            lines.append(f"             platforms: {plat.get('status')} — {plat.get('reason') or plat.get('requested') or ''}".rstrip(" — "))
        growth = result.growth or {}
        if growth:
            lines.append(f"             growth: {growth.get('status')} {growth.get('path') or growth.get('reason') or ''}".rstrip())
        if result.error:
            lines.append(f"             error: {result.error}")
    lines += [
        "",
        "  Before you post:",
        "  [ ] First 3 seconds are the hook (no logo bumper, no score spoil)",
        "  [ ] Folder language matches on-screen copy and captions",
        "  [ ] Shorts/Reels/TikTok get the short cut; YouTube long-form gets /long/",
        "  [ ] Paste youtube_chapters.txt into the YouTube description (long only)",
        "  [ ] series-id lives in the description / growth JSON, not burned in",
        "  [ ] No repeated visualizations — if a long cut is under 3:00, that is correct",
        "=" * 66,
    ]
    return "\n".join(lines)


def resolve_match_dir(args: argparse.Namespace, choose_match: Callable[[Path, bool], Path]) -> Path:
    if getattr(args, "match_dir", None):
        path = Path(args.match_dir)
        if not path.exists():
            raise SystemExit(f"Match export not found: {path}")
        return path
    return choose_match(Path(args.scrape_output_root), bool(getattr(args, "interactive", False)))


def args_for_job(args: argparse.Namespace, job: Job) -> argparse.Namespace:
    ns = argparse.Namespace(**vars(args))
    ns.language = job.language
    ns.auto = True
    ns.interactive = False
    ns.match_dir = str(job.match_dir)
    ns.format = job.fmt
    ns._job = job
    return ns


def run_batch(
    args: argparse.Namespace,
    *,
    render_one: Callable[[argparse.Namespace], Path],
    choose_match: Callable[[Path, bool], Path],
    say: Callable[[str], None] = print,
) -> list[JobResult]:
    """Expand CLI flags into jobs and render (or print) each one.

    Other agents should call this rather than looping ``video_pipeline.run``
    themselves:

        from recap.batch import run_batch
    """
    register_farm_languages()
    match_dir = resolve_match_dir(args, choose_match)
    jobs = expand_jobs(args, match_dir)
    if not jobs:
        raise SystemExit("Nothing to do.")

    if getattr(args, "print_plan", False):
        bundle = load_match(match_dir)
        audit = audit_mod.build_audit(bundle)
        plans = [build_plan(args, job, bundle=bundle, audit=audit) for job in jobs]
        say(render_plan_text(plans))
        return [
            JobResult(job=job, status="planned", plan=plan, out_dir=job.out_dir)
            for job, plan in zip(jobs, plans)
        ]

    bundle = load_match(match_dir)
    audit = audit_mod.build_audit(bundle)
    results: list[JobResult] = []
    for index, job in enumerate(jobs, 1):
        say(f"\n{'#' * 66}\nJOB {index}/{len(jobs)}  {job.language}/{job.fmt}  → {job.out_dir}\n{'#' * 66}")
        stamp = stamp_for(args, job)
        plan = build_plan(args, job, bundle=bundle, audit=audit)
        skipped = (
            not getattr(args, "force", False)
            and package_complete(job.out_dir, stamp, args)
        )
        video_path: Path | None = None
        status = "rendered"
        error = ""
        if skipped:
            say(f"  skip (already rendered; pass --force to rebuild)  {job.out_dir}")
            status = "skipped"
            candidate = job.out_dir / "match_video.mp4"
            video_path = candidate if candidate.exists() else None
        else:
            try:
                out = render_one(args_for_job(args, job))
                job.out_dir = Path(out)
                write_stamp(job.out_dir, stamp)
                mp4 = job.out_dir / "match_video.mp4"
                video_path = mp4 if mp4.exists() else None
            except SystemExit as exc:
                error = str(exc) or "stopped"
                status = "failed"
                say(f"  job failed: {error}")
            except Exception as exc:  # noqa: BLE001 — batch continues the rest of the farm
                error = f"{type(exc).__name__}: {exc}"
                status = "failed"
                say(f"  job failed: {error}")
        plat = try_apply_platforms(
            job.out_dir, job.platforms,
            fmt=job.fmt, language=job.language, series_id=job.series_id,
            plan=plan, video_path=video_path, audit=audit,
            fps=int(getattr(args, "fps", 24) or 24),
            aspect=str(getattr(args, "aspect", "all") or "all"),
            spoiler=str(getattr(args, "spoiler", "show") or "show"),
            end_card=bool(getattr(args, "end_card", True)),
        )
        growth = try_write_growth(job, audit=audit, plan=plan, video_path=video_path)
        results.append(JobResult(
            job=job, status=status, plan=plan, out_dir=job.out_dir,
            video=video_path, platforms=plat, growth=growth, error=error,
        ))

    say(posting_checklist(results))
    return results


def theme_ready(args: argparse.Namespace) -> None:
    """Apply --team / --colors once so print-plan badges match a real run."""
    if getattr(args, "team", None):
        theme.set_team_kind(args.team)
    if getattr(args, "colors", None):
        theme.set_team_colors(args.colors[0], args.colors[1])
