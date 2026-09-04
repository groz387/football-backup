"""Dashboard-first orchestration over the restored recap core.

The web app is the product. This module deliberately calls the same
``video_pipeline`` functions as the CLI so script, timing and render behaviour
cannot drift into a second implementation.
"""

from __future__ import annotations

import json
import os
import re
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import audit as audit_mod
from . import colors, director, elevenlabs_tts, i18n, scrape as scrape_mod
from . import source_chain, theme, timing, translation
from .data import describe_match_dir, list_match_dirs, load_match, read_json, write_json

import video_pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"
VIDEO_ROOT = REPO_ROOT / "video_output"
STUDIO_DIR = REPO_ROOT / "studio"
SETTINGS_PATH = STUDIO_DIR / "settings.json"
JOBS_DIR = STUDIO_DIR / "jobs"

DEFAULT_SETTINGS: dict[str, Any] = {
    "url": "",
    "match_dir": "",
    "languages": ["az", "en", "es"],
    "selected_visualizations": [],
    "visualization_count": 4,
    "words_per_section": 17,
    "target_seconds": 34,
    "fps": 30,
    "hook_claim": "",
    "hook_punch": "",
    "bait_text": "",
    "team": "club",
    "colors": [],
    "format": "short",
    "spoiler": "show",
    "star": "auto",
    "platforms": "tiktok,reels,shorts",
    "series_id": "",
    "instruction": "",
    "use_gemini": True,
    "gemini_model": "",
    "gemini_script_model": "",
    "translation_provider": "auto",
    "require_context_translation": True,
    "eleven_style": "robust",
    "voice_name": "Liam Callahan - Witty Media Person",
    "voice_id": "",
    "eleven_model": "eleven_v3",
    "kids": False,
    "scrape_wait": 15,
}

LANGUAGES = [
    {"code": "az", "name": "Azerbaijani", "native": "Azərbaycanca", "rtl": False},
    {"code": "en", "name": "English", "native": "English", "rtl": False},
    {"code": "es", "name": "Spanish", "native": "Español", "rtl": False},
    {"code": "ru", "name": "Russian", "native": "Русский", "rtl": False},
]

_WHO_ID = re.compile(r"/matches?/(\d{5,10})", re.I)
_LOCK = threading.RLock()
_RENDER_LOCK = threading.Lock()
_PRODUCE_THREADS: dict[str, threading.Thread] = {}
_SCRAPE_THREADS: dict[str, threading.Thread] = {}


def configure(
    *,
    repo_root: Path | None = None,
    settings_path: Path | None = None,
    jobs_dir: Path | None = None,
) -> None:
    global REPO_ROOT, OUTPUT_ROOT, VIDEO_ROOT, STUDIO_DIR, SETTINGS_PATH, JOBS_DIR
    if repo_root is not None:
        REPO_ROOT = Path(repo_root)
        OUTPUT_ROOT = REPO_ROOT / "output"
        VIDEO_ROOT = REPO_ROOT / "video_output"
        STUDIO_DIR = REPO_ROOT / "studio"
        SETTINGS_PATH = STUDIO_DIR / "settings.json"
        JOBS_DIR = STUDIO_DIR / "jobs"
    if settings_path is not None:
        SETTINGS_PATH = Path(settings_path)
    if jobs_dir is not None:
        JOBS_DIR = Path(jobs_dir)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def load_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                settings.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(updates: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = load_settings()
    for key, value in (updates or {}).items():
        if key in DEFAULT_SETTINGS:
            settings[key] = value
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return settings


def list_languages() -> list[dict[str, Any]]:
    return [dict(row) for row in LANGUAGES]


def _match_payload(path: Path) -> dict[str, Any]:
    summary = read_json(path / "match_summary.json")
    return {
        "match_dir": _rel(path),
        "name": path.name,
        "label": describe_match_dir(path),
        "home": (summary.get("home") or {}).get("name") or "Home",
        "away": (summary.get("away") or {}).get("name") or "Away",
        "score": summary.get("score") or summary.get("ftScore") or "",
        "date": str(summary.get("startDate") or "")[:10],
        "match_id": str(summary.get("matchId") or path.name.split("_", 1)[0]),
        "league": summary.get("league") or "",
    }


def list_matches(output_root: Path | None = None) -> list[dict[str, Any]]:
    return [_match_payload(path) for path in list_match_dirs(output_root or OUTPUT_ROOT)]


def resolve_match_dir(match_dir: str | Path) -> Path:
    raw = Path(str(match_dir)).expanduser()
    candidates = [raw] if raw.is_absolute() else [REPO_ROOT / raw, OUTPUT_ROOT / raw.name, raw]
    for path in candidates:
        if path.is_dir() and (path / "match_summary.json").exists() and (path / "all_events.csv").exists():
            return path.resolve()
    raise FileNotFoundError(f"Match export not found: {match_dir}")


def _find_id(match_id: str) -> Path | None:
    for path in list_match_dirs(OUTPUT_ROOT):
        if path.name.startswith(f"{match_id}_"):
            return path
    return None


def preview_colors(
    match_dir: str | Path,
    team: str = "club",
    colors_override: list[str] | None = None,
    colors: list[str] | None = None,
) -> dict[str, Any]:
    bundle = load_match(resolve_match_dir(match_dir))
    overrides = colors_override or colors or []
    home_override = overrides[0] if len(overrides) >= 2 else None
    away_override = overrides[1] if len(overrides) >= 2 else None
    pair = colors_module().resolve_pair(
        bundle.home, bundle.away, kind=team,
        override_home=home_override, override_away=away_override,
    )
    payload = pair.as_dict()
    # The UI's main swatch reads primary; show the actual selected shirt fill.
    payload["home"]["primary"] = payload["home"]["fill"]
    payload["away"]["primary"] = payload["away"]["fill"]
    payload.update({"auto": not bool(home_override or away_override), "team": team, "ink": "#000000"})
    return payload


def colors_module():
    return colors


def resolve_source(url: str = "", match_dir: str = "") -> dict[str, Any]:
    raw_url = str(url or "").strip()
    if match_dir:
        try:
            path = resolve_match_dir(match_dir)
            return {
                "ok": True, "needs_scrape": False, "match": _match_payload(path),
                "colors": preview_colors(path), "url": raw_url,
            }
        except FileNotFoundError:
            pass
    match_id = None
    if raw_url.isdigit():
        match_id = raw_url
    else:
        found = _WHO_ID.search(raw_url)
        match_id = found.group(1) if found else None
    if match_id:
        path = _find_id(match_id)
        if path:
            return {
                "ok": True, "needs_scrape": False, "match": _match_payload(path),
                "colors": preview_colors(path), "url": raw_url, "match_id": match_id,
            }
    if raw_url:
        classified = scrape_mod.classify_source(raw_url)
        return {
            "ok": False,
            "needs_scrape": True,
            "can_scrape": bool(classified.get("can_scrape")),
            "scrape_kind": classified.get("kind"),
            "scrape_url": classified.get("whoscored_url") or "",
            "scrape_hint": classified.get("hint") or "",
            "stub": (
                "No local export. Run the source chain; Livescore searches "
                "WhoScored first and Flashscore only when needed."
            ),
            "match": None,
            "colors": None,
            "url": raw_url,
            "match_id": match_id,
        }
    return {
        "ok": False, "needs_scrape": False, "can_scrape": False,
        "stub": "Pick an export or paste a match URL.", "match": None, "colors": None,
    }


def visualization_options(match_dir: str | Path, count: int = 4) -> dict[str, Any]:
    path = resolve_match_dir(match_dir)
    bundle = load_match(path)
    audit = audit_mod.build_audit(bundle)
    selected, candidates = director.select_visualizations(
        bundle, audit, max(3, min(4, int(count or 4))), None, "",
    )
    selected_ids = [row["id"] for row in selected]
    return {
        "selected": selected_ids,
        "options": [
            {
                "id": row["id"],
                "title": row.get("title") or row["id"].replace("_", " ").title(),
                "available": bool(row.get("available")),
                "score": round(float(row.get("score") or 0), 1),
                "reason": row.get("reason") or "",
                "selected": row["id"] in selected_ids,
            }
            for row in sorted(candidates, key=lambda item: float(item.get("score") or 0), reverse=True)
        ],
    }


def capabilities() -> dict[str, Any]:
    return {
        "scrape": scrape_mod.scrape_available(),
        "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
        "deepseek_key": bool(os.getenv("DEEPSEEK_API_KEY")),
        "elevenlabs": True,
        "elevenlabs_configured": elevenlabs_tts.configured(),
        "stubbed": {"elevenlabs_tts": not elevenlabs_tts.configured()},
    }


def elevenlabs_health() -> dict[str, Any]:
    return elevenlabs_tts.check_account()


def _scrape_path(job_id: str) -> Path:
    return JOBS_DIR / f"scrape_{job_id}.json"


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _save(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload)
    return payload


def get_scrape_job(job_id: str) -> dict[str, Any]:
    path = _scrape_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown scrape job {job_id}")
    return read_json(path)


def _run_scrape_job(job_id: str) -> None:
    job = get_scrape_job(job_id)
    log = list(job.get("log") or [])

    def say(line: str) -> None:
        log.append(str(line))
        current = get_scrape_job(job_id)
        current.update({"status": "running", "log": log[-100:], "stage": str(line), "percent": min(90, current.get("percent", 5) + 7)})
        _save(_scrape_path(job_id), current)

    try:
        url = str(job.get("url") or "")
        if "livescore.com" in urlparse(url).netloc.lower():
            result = source_chain.resolve_chain(
                url, output_root=OUTPUT_ROOT, wait=job["wait"],
                allow_spawn=True, on_log=say,
            )
        else:
            result = scrape_mod.run_scrape(
                url=url, html_path=str(job.get("html_path") or ""),
                output_root=OUTPUT_ROOT, wait=job["wait"], log=say,
            )
        if not result.get("ok") or not result.get("match_dir"):
            raise FileNotFoundError(result.get("message") or "No export was produced.")
        path = Path(result["match_dir"])
        current = get_scrape_job(job_id)
        current.update({
            "ok": True, "status": "done", "percent": 100, "stage": "done",
            "match_dir": _rel(path), "match": _match_payload(path),
            "colors": preview_colors(path), "steps": result.get("steps") or [],
            "log": log[-100:], "error": "",
        })
        _save(_scrape_path(job_id), current)
    except Exception as exc:  # noqa: BLE001
        current = get_scrape_job(job_id)
        current.update({
            "ok": False, "status": "failed", "stage": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "log": log[-100:] + [traceback.format_exc(limit=5)],
        })
        _save(_scrape_path(job_id), current)


def start_scrape(url: str = "", html_path: str = "", wait: int | None = None) -> dict[str, Any]:
    classified = scrape_mod.classify_source(url, html_path)
    if not classified.get("can_scrape"):
        raise ValueError(classified.get("hint") or "Need a valid source URL or saved HTML.")
    job_id = uuid.uuid4().hex[:10]
    job = {
        "id": job_id, "created_at": _now(), "status": "queued", "ok": False,
        "percent": 1, "stage": "queued", "url": url, "html_path": html_path,
        "wait": max(8, min(60, int(wait or 15))), "kind": classified.get("kind"),
        "log": [classified.get("hint") or "queued"], "steps": [], "error": "",
    }
    _save(_scrape_path(job_id), job)
    thread = threading.Thread(target=_run_scrape_job, args=(job_id,), daemon=True)
    _SCRAPE_THREADS[job_id] = thread
    thread.start()
    return job


def _apply_operator_copy(
    scenes: list[dict[str, Any]],
    hook_claim: str,
    hook_punch: str,
    bait: str,
) -> list[dict[str, Any]]:
    out = []
    for scene in scenes:
        updated = dict(scene)
        viz = scene.get("visualization")
        if viz == "hook_claim" and hook_claim:
            updated.update({"title": hook_claim, "narration": hook_claim, "lines": [hook_claim]})
        elif viz == "hook_punch" and hook_punch:
            updated.update({"title": hook_punch, "narration": hook_punch, "lines": [hook_punch]})
        elif viz == "close" and bait:
            old = str(updated.get("narration") or "").rstrip(". ")
            updated.update({"insight": bait, "comment_bait": bait, "narration": f"{old}. {bait}"})
        out.append(updated)
    return out


def _scene_view(scene: dict[str, Any]) -> dict[str, Any]:
    narration = str(scene.get("narration") or "")
    return {
        "id": scene.get("id"), "visualization": scene.get("visualization"),
        "title": scene.get("title") or "", "narration": narration,
        "insight": scene.get("insight") or "",
        "comment_bait": scene.get("comment_bait") or "",
        "kicker": scene.get("kicker") or "", "hook": bool(scene.get("hook")),
        "lines": list(scene.get("lines") or []),
        "word_count": timing.word_count(narration),
        "fact_numbers": list((scene.get("fact_pack") or {}).get("numbers") or []),
    }


def _script_warnings(
    scenes: list[dict[str, Any]],
    selected_ids: list[str],
    target_words: int,
) -> list[str]:
    warnings: list[str] = []
    for scene in scenes:
        if scene.get("visualization") not in selected_ids:
            continue
        words = timing.word_count(scene.get("narration") or "")
        if words < max(10, target_words - 3) or words > min(24, target_words + 3):
            warnings.append(
                f"{scene.get('visualization')}: {words} words; target is {target_words}"
            )
        allowed = [
            str(value)
            for value in (
                scene.get("fact_numbers")
                or (scene.get("fact_pack") or {}).get("numbers")
                or []
            )
        ]
        narration = str(scene.get("narration") or "")
        if allowed and not any(value and value in narration for value in allowed):
            warnings.append(
                f"{scene.get('visualization')}: narration cites no number from its fact pack"
            )
    return warnings


def _selected_objects(bundle, audit: dict[str, Any], ids: list[str], count: int) -> list[dict[str, Any]]:
    candidates = director.visualization_candidates(bundle, audit)
    available = {row["id"]: row for row in candidates if row.get("available")}
    chosen = [available[vid] for vid in ids if vid in available][:4]
    if 3 <= len(chosen) <= 4:
        return chosen
    selected, _ = director.select_visualizations(bundle, audit, count, None, "")
    return selected


def _translation_needed(target: str, hooks: list[str], bait: str) -> bool:
    if target != "en":
        return True
    return any(text and translation.detect_language(text)[0] != "en" for text in [*hooks, bait])


def draft_scripts(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    settings.update({key: payload[key] for key in DEFAULT_SETTINGS if key in payload})
    languages = [code for code in settings.get("languages") or [] if code in i18n.SUPPORTED]
    if not languages:
        raise ValueError("Pick at least one language.")
    path = resolve_match_dir(settings.get("match_dir") or "")
    bundle = load_match(path)
    audit = audit_mod.build_audit(bundle)
    count = max(3, min(4, int(settings.get("visualization_count") or 4)))
    selected = _selected_objects(
        bundle, audit, list(settings.get("selected_visualizations") or []), count,
    )
    settings["selected_visualizations"] = [row["id"] for row in selected]
    settings["visualization_count"] = len(selected)
    save_settings(settings)

    gemini = director.Gemini(
        enabled=bool(settings.get("use_gemini")),
        required=False,
        model=str(settings.get("gemini_model") or "") or None,
        script_model=str(settings.get("gemini_script_model") or "") or None,
    )
    canonical, _ = video_pipeline.build_script(
        bundle, audit, selected, gemini, str(settings.get("instruction") or ""),
        float(settings.get("target_seconds") or 34), "en",
        words_per_section=int(settings.get("words_per_section") or 17),
        translation_provider="offline",
    )
    hook_texts = [str(settings.get("hook_claim") or ""), str(settings.get("hook_punch") or "")]
    bait = str(settings.get("bait_text") or "")
    canonical = _apply_operator_copy(canonical, *hook_texts, bait)
    packs: dict[str, Any] = {}
    provider = str(settings.get("translation_provider") or "auto")
    for language in languages:
        if _translation_needed(language, hook_texts, bait):
            translated = translation.translate_story(
                canonical, language, bundle, audit, provider=provider, gemini=gemini,
                force=True,
            )
            scenes = translated.scenes
            translation_provider = translated.provider
            warnings = list(translated.warnings)
        else:
            scenes = [dict(scene) for scene in canonical]
            translation_provider = "source"
            warnings = []
        # Keep exact operator copy in its detected language.
        exact_hook = hook_texts[0] if hook_texts[0] and translation.detect_language(hook_texts[0])[0] == language else ""
        exact_punch = hook_texts[1] if hook_texts[1] and translation.detect_language(hook_texts[1])[0] == language else ""
        exact_bait = bait if bait and translation.detect_language(bait)[0] == language else ""
        scenes = _apply_operator_copy(scenes, exact_hook, exact_punch, exact_bait)
        views = [_scene_view(scene) for scene in scenes]
        claim = next((scene for scene in views if scene["visualization"] == "hook_claim"), {})
        punch = next((scene for scene in views if scene["visualization"] == "hook_punch"), {})
        close = next((scene for scene in views if scene["visualization"] == "close"), {})
        packs[language] = {
            "language": language, "language_name": i18n.language_name(language),
            "script_status": "pending", "voice_status": "none", "voice_path": "",
            "voice_stub": False, "hook_claim": claim.get("title") or "",
            "hook_punch": punch.get("title") or "", "bait": close.get("comment_bait") or close.get("insight") or "",
            "scenes": views, "visualizations": [row["id"] for row in selected],
            "translation_provider": translation_provider,
            "translation_warnings": warnings,
            "script_warnings": _script_warnings(
                scenes, [row["id"] for row in selected],
                int(settings.get("words_per_section") or 17),
            ),
            "operator_copy": {
                "source_language": translation.detect_language(hook_texts[0] or bait)[0] if (hook_texts[0] or bait) else "director",
                "provider": translation_provider,
            },
        }
    job_id = uuid.uuid4().hex[:10]
    job = {
        "id": job_id, "created_at": _now(), "match_dir": _rel(path),
        "match": _match_payload(path), "settings": settings, "languages": languages,
        "packs": packs, "colors": preview_colors(path, settings.get("team") or "club", settings.get("colors") or []),
        "production": {"status": "idle", "percent": 0, "stage": "review", "log": ["Scripts drafted. Review evidence, translation and timing."], "results": [], "error": ""},
        "capabilities": capabilities(),
    }
    return _save(_job_path(job_id), job)


def get_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown studio job {job_id}")
    return read_json(path)


def _pack(job: dict[str, Any], language: str) -> dict[str, Any]:
    pack = (job.get("packs") or {}).get(language)
    if not pack:
        raise KeyError(f"Language {language} is not in this job.")
    return pack


def edit_script(job_id: str, language: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    job = get_job(job_id)
    pack = _pack(job, language)
    patches = {str(row.get("id")): row for row in scenes}
    for scene in pack["scenes"]:
        patch = patches.get(str(scene.get("id")))
        if not patch:
            continue
        for field in ("title", "narration", "insight", "comment_bait", "kicker", "lines"):
            if field in patch and patch[field] is not None:
                scene[field] = patch[field]
        scene["word_count"] = timing.word_count(scene.get("narration") or "")
    pack["script_status"] = "edited"
    pack["translation_reviewed"] = True
    pack["script_warnings"] = _script_warnings(
        pack["scenes"], list(pack.get("visualizations") or []),
        int((job.get("settings") or {}).get("words_per_section") or 17),
    )
    return _save(_job_path(job_id), job)


def approve_script(job_id: str, language: str) -> dict[str, Any]:
    job = get_job(job_id)
    _pack(job, language)["script_status"] = "approved"
    return _save(_job_path(job_id), job)


def _voice_text(pack: dict[str, Any]) -> str:
    return "\n\n".join(
        str(scene.get("narration") or "").strip()
        for scene in pack.get("scenes") or []
        if str(scene.get("narration") or "").strip()
    )


def regenerate_voice(job_id: str, language: str, voice_id: str | None = None) -> dict[str, Any]:
    job = get_job(job_id)
    pack = _pack(job, language)
    settings = job.get("settings") or {}
    dest = JOBS_DIR / job_id / f"voice_{language}.mp3"
    try:
        path = elevenlabs_tts.synthesize(
            _voice_text(pack), dest, language=language,
            voice_id=voice_id or settings.get("voice_id") or None,
            model=settings.get("eleven_model") or None,
            style=settings.get("eleven_style") or "robust",
            regenerate=True,
        )
        pack.update({"voice_status": "ready", "voice_path": str(path), "voice_note": "", "voice_stub": False})
    except elevenlabs_tts.ElevenLabsError as exc:
        pack.update({
            "voice_status": "failed", "voice_path": "", "voice_stub": False,
            "voice_note": str(exc), "voice_error": exc.as_dict(),
        })
    return _save(_job_path(job_id), job)


def approve_voice(job_id: str, language: str) -> dict[str, Any]:
    job = get_job(job_id)
    pack = _pack(job, language)
    if pack.get("voice_status") == "ready" and Path(pack.get("voice_path") or "").exists():
        pack["voice_status"] = "approved"
    return _save(_job_path(job_id), job)


def voice_file(job_id: str, language: str) -> Path:
    path = Path(_pack(get_job(job_id), language).get("voice_path") or "")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"No voiceover for {language}")
    return path


def _restore_scenes(views: list[dict[str, Any]], canonical: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row.get("id")): row for row in views}
    out = []
    for scene in canonical:
        updated = dict(scene)
        patch = by_id.get(str(scene.get("id"))) or {}
        for field in ("title", "narration", "insight", "comment_bait", "kicker", "lines"):
            if field in patch:
                updated[field] = patch[field]
        out.append(updated)
    return out


def _run_produce(job_id: str, mode: str) -> None:
    with _RENDER_LOCK:
        job = get_job(job_id)
        production = job["production"]
        production.update({"status": "running", "stage": "starting", "percent": 1, "error": "", "results": []})
        _save(_job_path(job_id), job)
        try:
            total = len(job["languages"])
            results = []
            if mode == "plan":
                for code in job["languages"]:
                    pack = job["packs"][code]
                    results.append({
                        "language": code, "format": "short", "status": "planned",
                        "out_dir": str(VIDEO_ROOT / code / Path(job["match_dir"]).name),
                        "video": "", "error": "",
                    })
            else:
                for index, code in enumerate(job["languages"], 1):
                    current = get_job(job_id)
                    current["production"].update({
                        "stage": f"rendering {code}", "percent": int((index - 1) / total * 90) + 5,
                    })
                    current["production"]["log"].append(f"Rendering {code}: {index}/{total}")
                    _save(_job_path(job_id), current)
                    settings = job["settings"]
                    colors_preview = job["colors"]
                    argv = [
                        "--match-dir", str(resolve_match_dir(job["match_dir"])),
                        "--output-root", str(VIDEO_ROOT / code),
                        "--auto", "--language", code,
                        "--team", settings.get("team") or "club",
                        "--visualizations", str(len(pack["visualizations"])),
                        "--target-seconds", str(settings.get("target_seconds") or 34),
                        "--words-per-section", str(settings.get("words_per_section") or 17),
                        "--fps", str(settings.get("fps") or 30),
                        "--no-gemini",
                        "--colors", colors_preview["home"]["primary"], colors_preview["away"]["primary"],
                    ]
                    if mode != "silent" and pack.get("voice_path"):
                        argv += ["--voiceover-file", pack["voice_path"]]
                    else:
                        argv.append("--skip-audio")
                    args = video_pipeline.parse_args(argv)
                    original_build = video_pipeline.build_script

                    def approved_build(*call_args, **call_kwargs):
                        base_scenes, _ = original_build(*call_args, **call_kwargs)
                        return _restore_scenes(pack["scenes"], base_scenes), True

                    video_pipeline.build_script = approved_build
                    try:
                        out_dir = video_pipeline.run(args)
                    finally:
                        video_pipeline.build_script = original_build
                    video_path = Path(out_dir) / "match_video.mp4"
                    results.append({
                        "language": code, "format": "short",
                        "status": "ok" if video_path.exists() else "failed",
                        "out_dir": str(out_dir), "video": str(video_path) if video_path.exists() else "",
                        "error": "" if video_path.exists() else "match_video.mp4 was not produced",
                    })
            current = get_job(job_id)
            current["production"].update({
                "status": "done" if all(row["status"] != "failed" for row in results) else "failed",
                "stage": "done", "percent": 100, "results": results,
                "error": next((row["error"] for row in results if row["error"]), ""),
            })
            _save(_job_path(job_id), current)
        except Exception as exc:  # noqa: BLE001
            current = get_job(job_id)
            current["production"].update({
                "status": "failed", "stage": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "log": current["production"]["log"] + [traceback.format_exc(limit=8)],
            })
            _save(_job_path(job_id), current)


def start_produce(job_id: str, mode: str = "full") -> dict[str, Any]:
    if mode not in {"full", "plan", "silent"}:
        raise ValueError("mode must be full, plan, or silent")
    job = get_job(job_id)
    if mode in {"full", "silent"}:
        pending_scripts = [code for code, pack in job["packs"].items() if pack["script_status"] != "approved"]
        if pending_scripts:
            raise ValueError("Approve scripts: " + ", ".join(pending_scripts))
    if mode == "full":
        pending_voice = [code for code, pack in job["packs"].items() if pack["voice_status"] != "approved"]
        if pending_voice:
            raise ValueError("Approve voiceovers: " + ", ".join(pending_voice))
    thread = threading.Thread(target=_run_produce, args=(job_id, mode), daemon=True)
    _PRODUCE_THREADS[job_id] = thread
    thread.start()
    return get_job(job_id)


def bootstrap() -> dict[str, Any]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "settings": load_settings(), "languages": list_languages(),
        "matches": list_matches(), "capabilities": capabilities(),
        "roots": {"repo": str(REPO_ROOT), "output": "output", "video": "video_output"},
    }
