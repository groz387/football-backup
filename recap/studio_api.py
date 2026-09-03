"""Thin operator-console helpers.

The studio web app calls these functions. They import ``video_pipeline`` and
``recap.*`` — the same brain as the CLI. This module does not scrape, does not
draw graphs, and does not own Gemini prompts.

Sibling modules that may not have landed yet are probed and stubbed:

    recap.elevenlabs_tts   synthesize(text, language, dest, voice_id=None) -> Path
    recap.livescore        resolve_url(url, output_root=...) -> Path | dict
    recap.scrape           same optional resolve_url / import_url / scrape_url

TODO(elevenlabs): Culture-scripts worker fills ``recap.elevenlabs_tts``.
TODO(livescore): Livescore-scrape worker fills URL → export. Until then we
resolve against existing ``output/<id>_*/`` folders only.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import threading
import traceback
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from recap import audit as audit_mod
from recap import batch, cast as cast_mod, culture, director, hooks, i18n, locale_meta, longform, script_culture, theme
from recap.data import describe_match_dir, list_match_dirs, load_match, read_json, write_json

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
    "use_gemini": False,
    "eleven_style": "robust",
    "voice_name": "Liam Callahan - Witty Media Person",
    "voice_id": "",
    "kids": False,
}

_WHO_SCORED_ID = re.compile(r"/matches?/(\d{5,10})", re.I)
_BARE_MATCH_ID = re.compile(r"^\d{5,10}$")
_LOCK = threading.RLock()
_PRODUCE_THREADS: dict[str, threading.Thread] = {}

# Expected sibling callables (first match wins). CLI workers fill the modules.
_TTS_FUNCS = ("synthesize", "synthesize_voiceover", "generate", "tts", "speak")
_SCRAPE_MODS = ("recap.livescore", "recap.ingest", "recap.resolve_match", "recap.scrape", "recap.whoscored")
_SCRAPE_FUNCS = ("resolve_url", "resolve", "import_url", "scrape_url", "fetch_match")


# ---------------------------------------------------------------------------
# paths / json
# ---------------------------------------------------------------------------

def configure(*, repo_root: Path | None = None, settings_path: Path | None = None,
              jobs_dir: Path | None = None) -> None:
    """Tests point the console at a temp tree without touching the checkout."""
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


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _rel(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def optional_module(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _first_callable(mod: Any, names: tuple[str, ...]) -> Callable | None:
    if mod is None:
        return None
    for name in names:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def _call_compatible(fn: Callable, **kwargs: Any) -> Any:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(**kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)
    accepted = {k: v for k, v in kwargs.items() if k in params}
    missing = [
        name for name, p in params.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and name not in accepted
        and name not in ("self", "cls")
    ]
    if missing:
        # Fall back to positional text, language, dest if that's the sibling shape.
        args = []
        for key in ("text", "language", "dest", "url"):
            if key in kwargs and key not in accepted:
                args.append(kwargs[key])
        return fn(*args, **accepted) if args else fn(**accepted)
    return fn(**accepted)


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------

def tts_module() -> Any | None:
    return optional_module("recap.elevenlabs_tts")


def tts_available() -> tuple[Any | None, Callable | None, bool]:
    """Return (module, synthesize fn, configured-with-keys)."""
    mod = tts_module()
    fn = _first_callable(mod, _TTS_FUNCS)
    configured = False
    checker = getattr(mod, "configured", None) if mod is not None else None
    if callable(checker):
        try:
            configured = bool(checker())
        except Exception:
            configured = False
    elif fn is not None:
        configured = True
    return mod, fn, configured


def scrape_resolver() -> tuple[str | None, Callable | None]:
    for name in _SCRAPE_MODS:
        mod = optional_module(name)
        fn = _first_callable(mod, _SCRAPE_FUNCS)
        if fn is not None:
            return name, fn
    return None, None


def capabilities() -> dict[str, Any]:
    tts_mod, tts_fn, tts_configured = tts_available()
    scrape_name, scrape_fn = scrape_resolver()
    eleven_live = bool(tts_fn) and tts_configured
    return {
        "elevenlabs": bool(tts_fn),
        "elevenlabs_configured": tts_configured,
        "elevenlabs_module": tts_mod is not None,
        "scrape": scrape_fn is not None,
        "scrape_module": scrape_name,
        "gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
        "wired": {
            "video_pipeline": True,
            "recap.batch": True,
            "recap.hooks": True,
            "recap.theme": True,
            "recap.director": True,
            "recap.i18n": True,
            "recap.elevenlabs_tts": bool(tts_fn),
        },
        "stubbed": {
            "elevenlabs_tts": not eleven_live,
            "livescore_scrape": scrape_fn is None,
        },
        "notes": {
            "elevenlabs_tts": (
                "live" if eleven_live
                else (
                    "recap.elevenlabs_tts present but no API key — silent WAV stub"
                    if tts_fn
                    else "TODO: recap.elevenlabs_tts.synthesize(text, dest, language=...) — silent WAV stub"
                )
            ),
            "livescore_scrape": (
                f"live via {scrape_name}" if scrape_fn
                else "TODO: recap.livescore.resolve_url(url) — matching local output/<id>_*/ only"
            ),
        },
    }


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def load_settings() -> dict[str, Any]:
    payload = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                payload.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    return payload


def save_settings(updates: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = load_settings()
    if updates:
        for key, value in updates.items():
            if key in DEFAULT_SETTINGS or key in payload:
                payload[key] = value
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return payload


# ---------------------------------------------------------------------------
# languages / matches / colours
# ---------------------------------------------------------------------------

def list_languages() -> list[dict[str, Any]]:
    batch.register_farm_languages()
    order = list(getattr(i18n, "SUPPORTED", ()) or ())
    codes = list(dict.fromkeys([*order, *batch.known_languages()]))
    rows = []
    for code in codes:
        try:
            meta = locale_meta.for_language(code)
            rows.append({
                "code": code,
                "name": meta.name,
                "native": meta.native_name,
                "rtl": bool(meta.rtl),
            })
        except Exception:
            rows.append({
                "code": code,
                "name": batch.language_label(code),
                "native": batch.language_label(code),
                "rtl": False,
            })
    return rows


def _match_payload(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    try:
        summary = read_json(path / "match_summary.json")
    except Exception:
        summary = {}
    home = (summary.get("home") or {}).get("name") or "Home"
    away = (summary.get("away") or {}).get("name") or "Away"
    match_id = str(summary.get("matchId") or "")
    if not match_id:
        head = path.name.split("_", 1)[0]
        if head.isdigit():
            match_id = head
    return {
        "match_dir": _rel(path),
        "name": path.name,
        "label": describe_match_dir(path),
        "home": home,
        "away": away,
        "score": summary.get("score") or summary.get("ftScore") or "",
        "date": str(summary.get("startDate") or "")[:10],
        "match_id": match_id,
        "league": summary.get("competition") or (summary.get("league") or ""),
    }


def list_matches(output_root: Path | None = None) -> list[dict[str, Any]]:
    root = Path(output_root) if output_root else OUTPUT_ROOT
    return [_match_payload(path) for path in list_match_dirs(root)]


def extract_match_id(url_or_id: str) -> str | None:
    raw = (url_or_id or "").strip()
    if not raw:
        return None
    if _BARE_MATCH_ID.fullmatch(raw):
        return raw
    found = _WHO_SCORED_ID.search(raw)
    if found:
        return found.group(1)
    digits = re.search(r"(\d{6,10})", raw)
    return digits.group(1) if digits else None


def find_export(match_id: str, output_root: Path | None = None) -> Path | None:
    root = Path(output_root) if output_root else OUTPUT_ROOT
    if not match_id:
        return None
    for path in list_match_dirs(root):
        if path.name == match_id or path.name.startswith(f"{match_id}_"):
            return path
        try:
            summary = read_json(path / "match_summary.json")
        except Exception:
            continue
        if str(summary.get("matchId") or "") == str(match_id):
            return path
    return None


def resolve_match_dir(match_dir: str | Path) -> Path:
    raw = Path(str(match_dir)).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend([REPO_ROOT / raw, OUTPUT_ROOT / raw.name, Path.cwd() / raw])
    for path in candidates:
        if path.is_dir() and (path / "match_summary.json").exists():
            return path.resolve()
    raise FileNotFoundError(f"Match export not found: {match_dir}")


def _try_sibling_scrape(url: str) -> Path | None:
    """TODO(livescore): sibling fills recap.livescore.resolve_url — we only call it."""
    _name, fn = scrape_resolver()
    if fn is None:
        return None
    try:
        result = _call_compatible(
            fn, url=url, output_root=OUTPUT_ROOT, output_dir=OUTPUT_ROOT, dest=OUTPUT_ROOT,
        )
    except Exception:
        return None
    if isinstance(result, (str, Path)) and Path(result).exists():
        return Path(result)
    if isinstance(result, dict):
        for key in ("match_dir", "path", "out_dir", "export"):
            value = result.get(key)
            if value and Path(value).exists():
                return Path(value)
    return None


def resolve_source(url: str = "", match_dir: str = "") -> dict[str, Any]:
    """Paste a WhoScored/Livescore URL or pick an existing export."""
    url = (url or "").strip()
    match_dir = (match_dir or "").strip()
    path: Path | None = None
    needs_scrape = False
    stub = ""
    match_id = extract_match_id(url) if url else None

    if match_dir:
        try:
            path = resolve_match_dir(match_dir)
        except FileNotFoundError:
            path = None

    if path is None and match_id:
        path = find_export(match_id)

    if path is None and url:
        path = _try_sibling_scrape(url)

    if path is None and url:
        needs_scrape = True
        stub = (
            "TODO: recap.livescore.resolve_url / scrape_match.py — no local export "
            f"for {match_id or url!r}. Pick a match-dir or wait for the scrape worker."
        )
        return {
            "ok": False,
            "needs_scrape": True,
            "stub": stub,
            "url": url,
            "match_id": match_id,
            "match": None,
            "colors": None,
        }

    if path is None:
        return {
            "ok": False,
            "needs_scrape": False,
            "stub": "Choose a match export or paste a WhoScored/Livescore URL.",
            "url": url,
            "match_id": match_id,
            "match": None,
            "colors": None,
        }

    match = _match_payload(path)
    colors = preview_colors(str(path))
    save_settings({"url": url, "match_dir": match["match_dir"]})
    return {
        "ok": True,
        "needs_scrape": needs_scrape,
        "stub": stub,
        "url": url,
        "match_id": match.get("match_id") or match_id,
        "match": match,
        "colors": colors,
    }


def preview_colors(
    match_dir: str | Path,
    team: str = "club",
    colors: list[str] | None = None,
) -> dict[str, Any]:
    """Auto team-colour preview from ``theme.match_design`` (same tokens as render)."""
    path = resolve_match_dir(match_dir)
    bundle = load_match(path)
    kind = theme.set_team_kind(team or "club")
    override = [c for c in (colors or []) if str(c).strip()]
    if len(override) >= 2:
        home_hex, away_hex = theme.set_team_colors(override[0], override[1])
        auto = False
    else:
        theme.set_team_colors(None, None)
        home_hex = away_hex = None
        auto = True
    design = theme.match_design(bundle.home, bundle.away)
    return {
        "auto": auto,
        "team": kind,
        "home": {
            "name": bundle.home,
            "abbr": design["home"].get("abbr"),
            "primary": home_hex or design["home"]["primary"],
            "fill": design["home"]["fill"],
            "chart": design["home"]["chart"],
            "secondary": design["home"]["secondary"],
        },
        "away": {
            "name": bundle.away,
            "abbr": design["away"].get("abbr"),
            "primary": away_hex or design["away"]["primary"],
            "fill": design["away"]["fill"],
            "chart": design["away"]["chart"],
            "secondary": design["away"]["secondary"],
        },
        "ink": design.get("ink") or "#000000",
        "surface": design.get("surface"),
        "text": design.get("text"),
    }


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def _job_dir(job_id: str) -> Path:
    path = JOBS_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(job_id: str) -> Path:
    return _job_dir(job_id) / "job.json"


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        path = _job_path(job["id"])
        write_json(path, _jsonable(job))
        return job


def load_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown studio job {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_job(job_id: str) -> dict[str, Any]:
    return load_job(job_id)


def _scene_view(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": scene.get("id") or scene.get("visualization"),
        "visualization": scene.get("visualization"),
        "title": scene.get("title") or "",
        "narration": scene.get("narration") or "",
        "insight": scene.get("insight") or "",
        "comment_bait": scene.get("comment_bait") or "",
        "kicker": scene.get("kicker") or "",
        "hook": bool(scene.get("hook")),
        "lines": list(scene.get("lines") or []),
    }


def _hook_texts(settings: dict[str, Any]) -> list[str]:
    return [text for text in (settings.get("hook_claim"), settings.get("hook_punch")) if text]


def _cli_args(settings: dict[str, Any], match_dir: str, languages: list[str], extra: list[str] | None = None):
    """Build the same argparse Namespace the CLI uses — no second flag parser."""
    argv = ["--match-dir", match_dir, "--auto", "--approve-script", "--approve-voice"]
    fmt = settings.get("format") or "short"
    argv += ["--format", fmt]
    argv += ["--team", settings.get("team") or "club"]
    argv += ["--spoiler", settings.get("spoiler") or "show"]
    argv += ["--star", settings.get("star") or "auto"]
    argv += ["--eleven-style", str(settings.get("eleven_style") or "robust")]
    if languages:
        argv += ["--languages", ",".join(languages)]
    colors = [c for c in (settings.get("colors") or []) if c]
    if len(colors) >= 2:
        argv += ["--colors", colors[0], colors[1]]
    for text in _hook_texts(settings):
        argv += ["--hook-text", text]
    if settings.get("bait_text"):
        argv += ["--bait-text", str(settings["bait_text"])]
    if settings.get("instruction"):
        argv += ["--instruction", str(settings["instruction"])]
    if settings.get("platforms"):
        argv += ["--platforms", str(settings["platforms"])]
    if settings.get("series_id"):
        argv += ["--series-id", str(settings["series_id"])]
    if settings.get("kids"):
        argv.append("--kids")
    if extra:
        argv.extend(extra)
    if not settings.get("use_gemini"):
        if "--no-gemini" not in argv:
            argv.append("--no-gemini")
    else:
        argv = [item for item in argv if item != "--no-gemini"]
    return video_pipeline.parse_args(argv)


def _draft_language(
    bundle,
    audit: dict[str, Any],
    language: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    batch.activate_language(language)
    spoiler = hooks.resolve_spoiler(settings.get("spoiler") or "show")
    fmt = settings.get("format") or longform.SHORT
    candidates_all = director.visualization_candidates(bundle, audit)
    available_n = sum(1 for item in candidates_all if item.get("available"))
    viz_count = longform.viz_count_for(fmt, None, available_n)
    target_seconds = longform.target_seconds_for(fmt, None)
    selected, _candidates = director.select_visualizations(
        bundle, audit, viz_count, None, str(settings.get("instruction") or ""),
        target_seconds=target_seconds, language=language, spoiler=spoiler,
    )
    scene_list, already_localized = video_pipeline.build_script(
        bundle, audit, selected, None, str(settings.get("instruction") or ""),
        target_seconds, language, clip_beats=[], spoiler=spoiler,
    )
    if language != "en":
        if not already_localized:
            try:
                scene_list, _method = i18n.localize_scenes(scene_list, language, None)
            except ValueError:
                pass
        try:
            scene_list = i18n.scrub_english_leftovers(scene_list, language)
        except ValueError:
            pass
        winner_hook = hooks.localize_hook(None, bundle, audit, language=language, spoiler=spoiler)
        scene_list = director.lock_hook_cards(
            scene_list, bundle, audit, language=language, spoiler=spoiler, hook=winner_hook,
        )
        try:
            scene_list = i18n.scrub_english_leftovers(scene_list, language)
        except ValueError:
            pass
    scene_list = hooks.apply_cli_copy(
        scene_list,
        hook_texts=_hook_texts(settings),
        bait_text=str(settings.get("bait_text") or ""),
    )
    scene_list = culture.lock_bookends(
        scene_list, bundle, audit, language,
        spoiler=spoiler,
        kids=bool(settings.get("kids")),
        hook_text=(_hook_texts(settings) or [None])[0],
        bait_text=str(settings.get("bait_text") or "") or None,
    )
    views = [_scene_view(scene) for scene in scene_list]
    claim = next((s for s in views if s["visualization"] == "hook_claim"), {})
    punch = next((s for s in views if s["visualization"] == "hook_punch"), {})
    close = next((s for s in views if s["visualization"] == "close" or s["id"] == "close"), {})
    shocks = [
        {"kind": item.get("kind"), "label": item.get("label") or item.get("claim"),
         "claim": item.get("claim"), "punch": item.get("punch")}
        for item in hooks.shock_menu_options(
            scene_list, None, language, bundle=bundle, audit=audit,
        )[:12]
    ]
    baits = hooks.comment_bait_options(bundle, audit, language=language)
    return {
        "language": language,
        "language_name": batch.language_label(language),
        "script_status": "pending",
        "voice_status": "none",
        "voice_path": "",
        "voice_stub": False,
        "hook_claim": claim.get("title") or "",
        "hook_punch": punch.get("title") or "",
        "bait": close.get("comment_bait") or close.get("insight") or "",
        "scenes": views,
        "shock_options": shocks,
        "bait_options": baits,
        "visualizations": [item["id"] for item in selected],
    }


def draft_scripts(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate per-language scripts via ``video_pipeline.build_script``."""
    settings = load_settings()
    for key in DEFAULT_SETTINGS:
        if key in payload:
            settings[key] = payload[key]
    languages = payload.get("languages") or settings.get("languages") or ["en"]
    languages = [batch.normalize_lang(code) for code in languages]
    if not languages:
        raise ValueError("Pick at least one language to dub.")
    resolved = resolve_source(payload.get("url") or settings.get("url") or "",
                              payload.get("match_dir") or settings.get("match_dir") or "")
    if not resolved.get("ok"):
        raise FileNotFoundError(resolved.get("stub") or "Match export not found.")
    match = resolved["match"]
    path = resolve_match_dir(match["match_dir"])
    settings["languages"] = languages
    settings["match_dir"] = match["match_dir"]
    save_settings(settings)

    bundle = load_match(path)
    kind = theme.set_team_kind(settings.get("team") or "club")
    colors = [c for c in (settings.get("colors") or []) if c]
    if len(colors) >= 2:
        theme.set_team_colors(colors[0], colors[1])
    else:
        theme.set_team_colors(None, None)
    audit = audit_mod.build_audit(bundle)
    audit["spoiler"] = hooks.resolve_spoiler(settings.get("spoiler") or "show")
    audit = cast_mod.apply_cast(bundle, audit, star=settings.get("star") or "auto")
    color_preview = preview_colors(path, team=kind, colors=colors)

    job_id = uuid.uuid4().hex[:10]
    packs = {}
    for language in languages:
        packs[language] = _draft_language(bundle, audit, language, settings)

    job = {
        "id": job_id,
        "created_at": _now(),
        "match_dir": match["match_dir"],
        "match": match,
        "settings": settings,
        "colors": color_preview,
        "languages": languages,
        "packs": packs,
        "production": {
            "status": "idle",
            "percent": 0,
            "stage": "review",
            "log": ["Scripts drafted. Approve copy, then voice, then produce."],
            "results": [],
            "error": "",
        },
        "capabilities": capabilities(),
    }
    save_job(job)
    return job


def _pack(job: dict[str, Any], language: str) -> dict[str, Any]:
    code = batch.normalize_lang(language)
    pack = (job.get("packs") or {}).get(code)
    if not pack:
        raise KeyError(f"Language {language} is not in this job.")
    return pack


def edit_script(job_id: str, language: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    job = load_job(job_id)
    pack = _pack(job, language)
    current = {row["id"]: row for row in pack.get("scenes") or []}
    updated = []
    for row in pack.get("scenes") or []:
        patch = next((item for item in scenes if item.get("id") == row["id"]), None)
        if not patch:
            updated.append(row)
            continue
        merged = dict(row)
        for key in ("title", "narration", "insight", "comment_bait", "kicker", "lines"):
            if key in patch and patch[key] is not None:
                merged[key] = patch[key]
        updated.append(merged)
        current[row["id"]] = merged
    pack["scenes"] = updated
    pack["script_status"] = "edited"
    claim = next((s for s in updated if s.get("visualization") == "hook_claim"), {})
    punch = next((s for s in updated if s.get("visualization") == "hook_punch"), {})
    close = next((s for s in updated if s.get("visualization") == "close" or s.get("id") == "close"), {})
    pack["hook_claim"] = claim.get("title") or pack.get("hook_claim") or ""
    pack["hook_punch"] = punch.get("title") or pack.get("hook_punch") or ""
    pack["bait"] = close.get("comment_bait") or close.get("insight") or pack.get("bait") or ""
    save_job(job)
    return job


def approve_script(job_id: str, language: str) -> dict[str, Any]:
    job = load_job(job_id)
    pack = _pack(job, language)
    pack["script_status"] = "approved"
    save_job(job)
    return job


# ---------------------------------------------------------------------------
# voiceover
# ---------------------------------------------------------------------------

def _write_stub_wav(path: Path, seconds: float = 1.2, rate: int = 24000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, int(seconds * rate))
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * n)
    return path


def synthesize_voiceover(
    text: str,
    language: str,
    dest: Path,
    *,
    voice_id: str | None = None,
) -> dict[str, Any]:
    """Call ``recap.elevenlabs_tts`` when present; otherwise a silent WAV stub.

    Expected sibling signature (any one of):
        synthesize(text: str, language: str, dest: Path, voice_id: str | None = None) -> Path
        synthesize_voiceover(...)
        generate(...)
        tts(...)
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _mod, fn, configured = tts_available()
    if fn is not None and configured:
        try:
            result = _call_compatible(
                fn, text=text, language=language, dest=dest, out_path=dest,
                path=dest, voice_id=voice_id, voice=voice_id, regenerate=True,
            )
            path = Path(result) if result else dest
            if path.exists() and path.stat().st_size > 0:
                return {"ok": True, "stub": False, "path": str(path), "note": "recap.elevenlabs_tts"}
        except Exception as exc:  # noqa: BLE001 — console must stay up if TTS fails
            return {
                "ok": False,
                "stub": True,
                "path": str(_write_stub_wav(dest.with_suffix(".wav"))),
                "note": f"elevenlabs_tts raised {type(exc).__name__}: {exc}; wrote silent stub",
            }
    path = _write_stub_wav(dest.with_suffix(".wav") if dest.suffix.lower() != ".wav" else dest)
    note = (
        "recap.elevenlabs_tts present but no API key — silent WAV stub"
        if fn is not None
        else "TODO: recap.elevenlabs_tts.synthesize — silent WAV stub (no ElevenLabs module)"
    )
    return {"ok": True, "stub": True, "path": str(path), "note": note}


def _narration_text(pack: dict[str, Any]) -> str:
    scenes = list(pack.get("scenes") or [])
    tagged = script_culture.build_voiceover_text(scenes, pack.get("language") or "en")
    if tagged.strip():
        return tagged
    parts = [str(scene.get("narration") or "").strip() for scene in scenes]
    return "\n\n".join(part for part in parts if part)


def regenerate_voice(job_id: str, language: str, voice_id: str | None = None) -> dict[str, Any]:
    job = load_job(job_id)
    pack = _pack(job, language)
    code = batch.normalize_lang(language)
    dest = _job_dir(job_id) / f"voice_{code}.wav"
    result = synthesize_voiceover(_narration_text(pack), code, dest, voice_id=voice_id)
    pack["voice_path"] = result.get("path") or str(dest)
    pack["voice_stub"] = bool(result.get("stub"))
    pack["voice_status"] = "stubbed" if pack["voice_stub"] else "ready"
    pack["voice_note"] = result.get("note") or ""
    save_job(job)
    return job


def approve_voice(job_id: str, language: str) -> dict[str, Any]:
    job = load_job(job_id)
    pack = _pack(job, language)
    if pack.get("voice_status") in ("none", "", None):
        job = regenerate_voice(job_id, language)
        pack = _pack(job, language)
    pack["voice_status"] = "approved"
    save_job(job)
    return job


def voice_file(job_id: str, language: str) -> Path:
    job = load_job(job_id)
    pack = _pack(job, language)
    path = Path(pack.get("voice_path") or "")
    if not path.exists():
        raise FileNotFoundError(f"No voiceover for {language}")
    return path


# ---------------------------------------------------------------------------
# produce (same CLI functions)
# ---------------------------------------------------------------------------

def _overlay_scenes(scenes: list[dict[str, Any]], edited: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row.get("id"): row for row in edited}
    out = []
    for scene in scenes:
        patch = by_id.get(scene.get("id"))
        if not patch:
            out.append(scene)
            continue
        updated = dict(scene)
        for key in ("title", "narration", "insight", "comment_bait", "kicker", "lines"):
            if patch.get(key) not in (None, ""):
                updated[key] = patch[key]
        out.append(updated)
    return out


def _progress_from_log(log: list[str], n_jobs: int) -> tuple[int, str]:
    stage = "produce"
    percent = 5
    joined = "\n".join(log[-40:])
    markers = [
        ("1. Data audit", 15),
        ("2. Visualization", 30),
        ("3. Script", 45),
        ("4. Timing", 55),
        ("5. Render", 70),
        ("6. Assemble", 90),
        ("PLAN  (dry-run", 100),
        ("Before you post", 100),
    ]
    for needle, value in markers:
        if needle in joined:
            percent = max(percent, value)
            stage = needle.split(".")[-1].strip() if "." in needle else needle
    job_hits = [line for line in log if line.startswith("JOB ") or "JOB " in line[:8]]
    if job_hits and n_jobs:
        last = job_hits[-1]
        found = re.search(r"JOB\s+(\d+)/(\d+)", last)
        if found:
            done, total = int(found.group(1)), max(1, int(found.group(2)))
            percent = max(percent, int((done - 1) / total * 100) + 10)
    if any("wrote " in line and ".mp4" in line for line in log[-12:]):
        percent = max(percent, 95)
    return min(99, percent), stage


def _run_produce(job_id: str, mode: str) -> None:
    job = load_job(job_id)
    prod = job.setdefault("production", {})
    prod.update({"status": "running", "percent": 5, "stage": "starting", "error": "", "results": []})
    save_job(job)
    log: list[str] = list(prod.get("log") or [])

    def say(text: str = "") -> None:
        line = str(text)
        log.append(line)
        video_pipeline.say(text)
        current = load_job(job_id)
        current_prod = current.setdefault("production", {})
        current_prod["log"] = log[-400:]
        n_jobs = max(1, len(current.get("languages") or [1]))
        percent, stage = _progress_from_log(log, n_jobs)
        current_prod["percent"] = percent
        current_prod["stage"] = stage
        current_prod["status"] = "running"
        save_job(current)

    extra = ["--force"]
    if mode == "plan":
        extra.append("--print-plan")
    elif mode == "skip-video":
        extra.append("--skip-video")
    settings = job.get("settings") or {}
    languages = list(job.get("languages") or ["en"])
    args = _cli_args(settings, job["match_dir"], languages, extra=extra)
    original_build = video_pipeline.build_script

    def patched_build_script(*a, **kw):
        scenes, localized = original_build(*a, **kw)
        language = kw.get("language") or (a[6] if len(a) > 6 else args.language)
        pack = (job.get("packs") or {}).get(language) or {}
        if pack.get("scenes") and pack.get("script_status") in ("approved", "edited"):
            scenes = _overlay_scenes(scenes, pack["scenes"])
        return scenes, localized

    def render_one(ns):
        job_now = load_job(job_id)
        lang = ns._job.language if getattr(ns, "_job", None) else ns.language
        pack = (job_now.get("packs") or {}).get(lang) or {}
        voice_path = pack.get("voice_path") or ""
        if voice_path and Path(voice_path).exists() and not pack.get("voice_stub"):
            ns.voiceover_file = voice_path
            ns.skip_audio = False
        elif pack.get("voice_stub") or not voice_path:
            ns.skip_audio = True
        video_pipeline.build_script = patched_build_script
        try:
            return video_pipeline.run(ns)
        finally:
            video_pipeline.build_script = original_build

    try:
        video_pipeline.build_script = patched_build_script
        results = batch.run_batch(
            args, render_one=render_one, choose_match=video_pipeline.choose_match, say=say,
        )
        payload = []
        for item in results:
            payload.append({
                "language": item.job.language,
                "format": item.job.fmt,
                "status": item.status,
                "out_dir": str(item.out_dir or item.job.out_dir),
                "video": str(item.video) if item.video else "",
                "error": item.error,
            })
        current = load_job(job_id)
        current["production"] = {
            "status": "done" if all(r["status"] != "failed" for r in payload) else "failed",
            "percent": 100,
            "stage": "done",
            "log": log[-400:],
            "results": payload,
            "error": next((r["error"] for r in payload if r["error"]), ""),
            "mode": mode,
        }
        save_job(current)
    except Exception as exc:  # noqa: BLE001 — surface to the console
        current = load_job(job_id)
        current["production"] = {
            "status": "failed",
            "percent": current.get("production", {}).get("percent") or 0,
            "stage": "failed",
            "log": log[-400:] + [traceback.format_exc(limit=8)],
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
            "mode": mode,
        }
        save_job(current)
    finally:
        video_pipeline.build_script = original_build


def start_produce(job_id: str, mode: str = "full") -> dict[str, Any]:
    """Kick ``batch.run_batch`` / ``video_pipeline.run`` in a thread. Poll get_job."""
    if mode not in ("full", "plan", "skip-video"):
        raise ValueError("mode must be full, plan, or skip-video")
    job = load_job(job_id)
    existing = _PRODUCE_THREADS.get(job_id)
    if existing and existing.is_alive():
        return job
    job.setdefault("production", {})["status"] = "running"
    job["production"]["percent"] = 1
    job["production"]["stage"] = "queued"
    job["production"]["mode"] = mode
    save_job(job)
    thread = threading.Thread(target=_run_produce, args=(job_id, mode), daemon=True, name=f"studio-produce-{job_id}")
    _PRODUCE_THREADS[job_id] = thread
    thread.start()
    return load_job(job_id)


def bootstrap() -> dict[str, Any]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "settings": load_settings(),
        "languages": list_languages(),
        "matches": list_matches(),
        "capabilities": capabilities(),
        "roots": {
            "repo": str(REPO_ROOT),
            "output": _rel(OUTPUT_ROOT) if OUTPUT_ROOT.exists() else "output",
            "video": "video_output",
        },
    }


def cli_argv_for(
    *,
    match_dir: str,
    languages: list[str],
    hook_text: str = "",
    bait_text: str = "",
    eleven_style: str = "robust",
    eleven_voice: str = "",
    eleven_model: str = "",
    team: str = "club",
    skip_audio: bool = False,
    auto: bool = False,
    approve_script: bool = False,
    approve_voice: bool = False,
    still: bool = False,
    skip_video: bool = False,
    write_growth: bool = True,
    no_gemini: bool = False,
    no_elevenlabs: bool = False,
    kids: bool = False,
) -> list[str]:
    """Argv the studio (and tests) pass to ``video_pipeline.parse_args``."""
    argv = ["--match-dir", match_dir, "--team", team, "--eleven-style", eleven_style]
    if languages:
        argv += ["--languages", ",".join(languages)]
    if hook_text:
        argv += ["--hook-text", hook_text]
    if bait_text:
        argv += ["--bait-text", bait_text]
    if eleven_voice:
        argv += ["--eleven-voice", eleven_voice]
    if eleven_model:
        argv += ["--eleven-model", eleven_model]
    if skip_audio:
        argv.append("--skip-audio")
    if auto:
        argv.append("--auto")
    if approve_script:
        argv.append("--approve-script")
    if approve_voice:
        argv.append("--approve-voice")
    if still:
        argv.append("--still")
    if skip_video:
        argv.append("--skip-video")
    if write_growth:
        argv.append("--write-growth")
    else:
        argv.append("--no-write-growth")
    if no_gemini:
        argv.append("--no-gemini")
    if no_elevenlabs:
        argv.append("--no-elevenlabs")
    if kids:
        argv.append("--kids")
    if not auto:
        argv.append("--interactive")
    return argv


language_catalog = list_languages


def env_public() -> dict[str, Any]:
    """Studio health snapshot. Never includes API keys."""
    from recap import config as cfg
    snap = cfg.public_env()
    caps = capabilities()
    snap["capabilities"] = caps
    snap["gemini"] = caps.get("gemini_key")
    return snap
