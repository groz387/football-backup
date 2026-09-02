"""Find short match-action beats to put in front of the graphic package.

WhoScored event exports do not contain video. Recap runs now **auto-fetch** a
short public highlight of *this* fixture (yt-dlp / YouTube) unless the editor
already dropped footage or passed ``--no-fetch-clip``:

    output/<match>/clips/*.mp4          cache + downloads land here
    output/<match>/highlights/*.mp4
    output/<match>/*.mp4
    --clip path/to/file.mp4

A file longer than about an hour is treated as a match tape and cut around
goal timestamps from the audit. Shorter files are treated as highlights and
sampled as 0.4–0.8s punches. Fetch failures never block the recap: the
graphics-only path still runs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .data import MatchBundle, safe_name, write_json
from .theme import FRAME_H, FRAME_W

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
FULL_MATCH_SECONDS = 70 * 60
HIGHLIGHT_SECONDS = 8.0
MICRO_CUT = 0.42
SINGLE_CUT = 0.70
MAX_BEATS = 2

# Download policy: prefer a real highlight. Never pull an unbounded full match
# when a highlight exists; always cap when duration is unknown or huge.
HIGHLIGHT_KEEP_SECONDS = 20 * 60
DOWNLOAD_CAP_SECONDS = 12 * 60
MAX_FILESIZE = "250M"
SEARCH_LIMIT = 8
SEARCH_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 180
INSTALL_TIMEOUT = 90
MIN_ACCEPT_SCORE = 4.0
SIDECAR_NAME = "fetch.json"

SearchFn = Callable[[list[str]], list[dict[str, Any]]]
DownloadFn = Callable[[dict[str, Any], Path], Path | None]


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def _ytdlp_cmd() -> list[str] | None:
    exe = shutil.which("yt-dlp") or shutil.which("yt_dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "yt_dlp"]


def ensure_ytdlp() -> list[str] | None:
    """Return an argv prefix for yt-dlp, installing the package if needed."""
    found = _ytdlp_cmd()
    if found:
        return found
    print("  [clips] yt-dlp missing; trying pip install yt-dlp")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "yt-dlp"],
            capture_output=True, text=True, timeout=INSTALL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  [clips] could not install yt-dlp: {exc}")
        return None
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:300]
        print(f"  [clips] pip install yt-dlp failed: {err}")
        return None
    found = _ytdlp_cmd()
    if not found:
        print("  [clips] yt-dlp installed but still not importable.")
    return found


def duration_seconds(path: Path) -> float | None:
    probe = _ffprobe()
    if not probe or not path.exists():
        return None
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        value = float((result.stdout or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def discover_sources(match_dir: Path, extra: list[Path] | None = None) -> list[Path]:
    """Local video files that belong to this match, longest first."""
    root = Path(match_dir)
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not path.is_file():
            return
        if path.suffix.lower() not in VIDEO_EXTS:
            return
        try:
            if path.stat().st_size < 1024:
                return
        except OSError:
            return
        seen.add(resolved)
        found.append(path)

    for path in extra or []:
        add(Path(path))
    for folder in (root / "clips", root / "highlights"):
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                add(path)
    if root.is_dir():
        for path in sorted(root.iterdir()):
            add(path)
    found.sort(key=lambda item: item.stat().st_size if item.exists() else 0, reverse=True)
    return found


TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "south korea": ("korea", "korea republic", "republic of korea", "corea del sur"),
    "korea republic": ("south korea", "korea", "corea del sur"),
    "united states": ("usa", "usmnt", "united states of america", "usmwt"),
    "usa": ("united states", "usmnt"),
    "cote d ivoire": ("ivory coast", "côte d'ivoire"),
    "ivory coast": ("cote d ivoire", "côte d'ivoire"),
    "netherlands": ("holland",),
    "iran": ("ir iran", "iran islamic republic"),
    "turkiye": ("turkey",),
    "turkey": ("turkiye",),
    "czechia": ("czech republic",),
    "czech republic": ("czechia",),
    "north macedonia": ("macedonia",),
    "bosnia and herzegovina": ("bosnia",),
    "republic of ireland": ("ireland",),
    "china pr": ("china",),
}

_HIGHLIGHT_WORDS = {
    "en": ("highlights", "goals"),
    "es": ("resumen", "goles"),
    "ru": ("обзор", "голы"),
    "az": ("icmal", "qollar"),
}

_OFFICIALISH = (
    "fifa", "uefa", "premier league", "la liga", "bundesliga", "serie a",
    "ligue 1", "mls", "conmebol", "caf", "afc", "concacaf",
    "nbc sports", "cbs sports", "tnt sports", "bbc sport", "sky sports",
    "fox soccer", "espn", "dazn", "beinsports", "bein sports",
)

_POSITIVE_TITLE = (
    (r"\bextended highlights?\b", 8.0),
    (r"\bmatch highlights?\b", 7.0),
    (r"\bhighlights?\b", 6.0),
    (r"\ball goals?\b", 5.5),
    (r"\bgoals?\b", 3.0),
    (r"\bresumen\b", 5.5),
    (r"\bобзор\b", 5.5),
    (r"\bicmal\b", 4.0),
    (r"\bgoles\b", 3.0),
    (r"\bголы\b", 3.0),
)

_NEGATIVE_TITLE = (
    (r"\bpress(?:\s|-)?conference\b", 20.0),
    (r"\bpresser\b", 16.0),
    (r"\bpost[\s-]?match interview\b", 14.0),
    (r"\bwatch[\s-]?along\b", 16.0),
    (r"\breaction\b", 10.0),
    (r"\bpreview\b", 12.0),
    (r"\bprediction\b", 14.0),
    (r"\bfantasy\b", 14.0),
    (r"\btraining\b", 10.0),
    (r"\bpodcast\b", 16.0),
    (r"\bstreaming live\b", 16.0),
    (r"\blive stream\b", 16.0),
    (r"\bfull(?:\s|-)?(?:match|game|90)\b", 12.0),
    (r"\b90\s*minutes\b", 8.0),
    (r"\bextended interview\b", 12.0),
    (r"\bline[\s-]?ups?\b", 8.0),
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("ß", "ss")
    cleaned = re.sub(r"[^a-z0-9]+", " ", stripped.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _team_terms(name: str) -> list[str]:
    folded = _fold(name)
    if not folded:
        return []
    terms = [folded, *TEAM_ALIASES.get(folded, ())]
    last = folded.split()[-1]
    if len(last) >= 5 and last not in terms:
        terms.append(last)
    return terms


def _name_in_text(name: str, text: str) -> bool:
    hay = f" {_fold(text)} "
    return any(f" {_fold(term)} " in hay for term in _team_terms(name) if term)


def _score_variants(score: str) -> list[str]:
    digits = re.findall(r"\d+", score or "")
    if len(digits) < 2:
        return []
    a, b = digits[0], digits[1]
    return [f"{a}-{b}", f"{a} {b}", f"{a}:{b}", f"{a}–{b}"]


def _date_bits(kickoff: str) -> dict[str, str]:
    raw = (kickoff or "")[:10]
    year = ""
    iso = raw
    pretty = ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        year, month, day = raw.split("-")
        months = (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        )
        pretty = f"{int(day)} {months[int(month) - 1]} {year}"
    return {"iso": iso, "year": year, "pretty": pretty}


def _competition_short(league: str) -> str:
    text = (league or "").strip()
    text = re.sub(r"^FIFA\s+", "", text, flags=re.I)
    return text


def _scorers(audit: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for goal in (audit or {}).get("goal_timeline") or []:
        raw = str(goal.get("scorer") or "").strip()
        if not raw:
            continue
        surname = raw.split()[-1]
        key = _fold(surname)
        if key in seen or len(surname) < 3:
            continue
        seen.add(key)
        minute = int(goal.get("minute") or 0)
        names.append(f"{surname} {minute}'" if minute else surname)
    return names


def search_queries(
    bundle: MatchBundle,
    audit: dict[str, Any] | None = None,
    language: str = "en",
) -> list[str]:
    """English-first YouTube queries, unique to this fixture."""
    home, away = bundle.home, bundle.away
    display = getattr(getattr(bundle, "score", None), "display", "") or ""
    score = str(display).replace(":", "-").replace(" ", "")
    dates = _date_bits(getattr(bundle, "kickoff", "") or "")
    league = _competition_short(getattr(bundle, "league", "") or "")
    year = dates["year"]
    scorers = _scorers(audit)
    local_words = _HIGHLIGHT_WORDS.get(language, _HIGHLIGHT_WORDS["en"])

    def join(*parts: str) -> str:
        return " ".join(p for p in parts if p).strip()

    queries = [
        join(home, "vs", away, score, league, year, "highlights"),
        join(home, away, score, year, "extended highlights"),
        join(home, "vs", away, dates["pretty"] or dates["iso"], "highlights goals"),
    ]
    if scorers:
        queries.append(join(home, away, scorers[0], "goal", year, "highlights"))
    if language != "en":
        queries.append(join(home, "vs", away, year, *local_words[:2]))
    queries.append(join(home, away, "highlights", year or league))

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = re.sub(r"\s+", " ", query).strip()
        if len(key) < 8 or key.lower() in seen:
            continue
        seen.add(key.lower())
        unique.append(key)
    return unique


def search_query(bundle: MatchBundle, audit: dict[str, Any] | None = None) -> str:
    queries = search_queries(bundle, audit)
    return queries[0] if queries else "highlights"


def _duration_bonus(seconds: float | None) -> float:
    if seconds is None or seconds <= 0:
        return 0.0
    if 90 <= seconds <= 900:
        return 8.0
    if 30 <= seconds < 90:
        return 2.0
    if 900 < seconds <= 1800:
        return 4.0
    if seconds > FULL_MATCH_SECONDS:
        return -14.0
    if seconds > 45 * 60:
        return -8.0
    return 0.0


def _title_vs_sides(title: str) -> tuple[str, str] | None:
    match = re.search(
        r"(.{2,48}?)\s+(?:vs\.?|v(?:ersus)?)\s+(.{2,48}?)(?:\s*[\-|:|•/]|\s+\d|\s*$)",
        title or "",
        flags=re.I,
    )
    if not match:
        return None
    return match.group(1).strip(" .:-|"), match.group(2).strip(" .:-|")


def reject_reason(
    candidate: dict[str, Any],
    bundle: MatchBundle,
    audit: dict[str, Any] | None = None,
) -> str | None:
    del audit
    title = str(candidate.get("title") or "")
    live = str(candidate.get("live_status") or "").lower()
    if live in {"is_live", "is_upcoming"}:
        return "live or upcoming stream"
    if not title.strip():
        return "empty title"
    home, away = bundle.home, bundle.away
    if not _name_in_text(home, title) or not _name_in_text(away, title):
        return "both teams must appear in the title"
    sides = _title_vs_sides(title)
    if sides:
        left, right = sides
        left_ours = _name_in_text(home, left) or _name_in_text(away, left)
        right_ours = _name_in_text(home, right) or _name_in_text(away, right)
        if not (left_ours and right_ours):
            return "title is a different fixture"
    folded = _fold(title)
    for pattern, penalty in _NEGATIVE_TITLE:
        if penalty >= 16 and re.search(pattern, folded):
            if any(tag in pattern for tag in ("press", "watch", "stream", "podcast")):
                return "non-match video"
    duration = candidate.get("duration")
    try:
        seconds = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None and seconds > 3 * 3600:
        return "unbounded full-match dump"
    return None


def score_candidate(
    candidate: dict[str, Any],
    bundle: MatchBundle,
    audit: dict[str, Any] | None = None,
) -> float:
    title = str(candidate.get("title") or "")
    folded = _fold(title)
    points = 0.0
    if _name_in_text(bundle.home, title):
        points += 5.0
    if _name_in_text(bundle.away, title):
        points += 5.0
    display = str(getattr(getattr(bundle, "score", None), "display", "") or "")
    collapsed = title.replace(" ", "")
    if any(variant in collapsed or _fold(variant) in folded for variant in _score_variants(display)):
        points += 3.5
    dates = _date_bits(getattr(bundle, "kickoff", "") or "")
    if dates["year"] and dates["year"] in title:
        points += 2.0
    if dates["pretty"] and _fold(dates["pretty"]) in folded:
        points += 2.5
    league = _fold(_competition_short(getattr(bundle, "league", "") or ""))
    if league and league in folded:
        points += 1.5
    for pattern, bonus in _POSITIVE_TITLE:
        if re.search(pattern, folded):
            points += bonus
            break
    for pattern, penalty in _NEGATIVE_TITLE:
        if re.search(pattern, folded):
            points -= penalty
    channel = _fold(
        str(candidate.get("uploader") or "") + " " + str(candidate.get("channel") or "")
    )
    if any(tag in channel or tag in folded for tag in _OFFICIALISH):
        points += 3.0
    try:
        seconds = float(candidate["duration"]) if candidate.get("duration") is not None else None
    except (TypeError, ValueError):
        seconds = None
    points += _duration_bonus(seconds)
    for marker in _scorers(audit):
        surname = marker.split()[0]
        if _fold(surname) and _fold(surname) in folded:
            points += 2.0
            break
    return points


def rank_candidates(
    candidates: list[dict[str, Any]],
    bundle: MatchBundle,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        if reject_reason(item, bundle, audit):
            continue
        item["rank_score"] = round(score_candidate(item, bundle, audit), 3)
        if item["rank_score"] < MIN_ACCEPT_SCORE:
            continue
        ranked.append(item)
    ranked.sort(key=lambda row: row.get("rank_score") or 0, reverse=True)
    return ranked


def _run_ytdlp(
    args: list[str],
    *,
    timeout: float,
    ytdlp: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = list(ytdlp or ensure_ytdlp() or [])
    if not cmd:
        raise FileNotFoundError("yt-dlp is not available")
    return subprocess.run(
        cmd + args, capture_output=True, text=True, timeout=timeout,
    )


def _normalize_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    video_id = str(entry.get("id") or "").strip()
    title = str(entry.get("title") or "").strip()
    if not video_id or not title or video_id == "NA":
        return None
    url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
    if not url or url.startswith("ytsearch"):
        url = f"https://www.youtube.com/watch?v={video_id}"
    duration = entry.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "id": video_id,
        "title": title,
        "url": url,
        "duration": duration,
        "uploader": str(entry.get("uploader") or entry.get("channel") or ""),
        "channel": str(entry.get("channel") or entry.get("uploader") or ""),
        "live_status": str(entry.get("live_status") or ""),
    }


def search_youtube(
    queries: list[str],
    *,
    limit: int = SEARCH_LIMIT,
    timeout: float = SEARCH_TIMEOUT,
    ytdlp: list[str] | None = None,
) -> list[dict[str, Any]]:
    ytdlp = ytdlp or ensure_ytdlp()
    if not ytdlp:
        print("  [clips] yt-dlp is not on PATH; cannot search.")
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries:
        print(f"  [clips] searching YouTube for {query!r}")
        args = [
            "--flat-playlist",
            "--no-warnings",
            "--skip-download",
            "--socket-timeout", "15",
            "--retries", "1",
            "--extractor-retries", "1",
            "-J",
            f"ytsearch{max(1, int(limit))}:{query}",
        ]
        try:
            result = _run_ytdlp(args, timeout=timeout, ytdlp=ytdlp)
        except subprocess.TimeoutExpired:
            print(f"  [clips] search timed out after {timeout:.0f}s")
            continue
        except (OSError, FileNotFoundError) as exc:
            print(f"  [clips] search failed: {exc}")
            return found
        if result.returncode not in (0, 101):
            err = (result.stderr or result.stdout or "").strip()[:400]
            print(f"  [clips] search failed: {err}")
            continue
        raw = (result.stdout or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print("  [clips] search returned non-JSON; skipping query")
            continue
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if entries is None and isinstance(payload, dict) and payload.get("id"):
            entries = [payload]
        for entry in entries or []:
            item = _normalize_entry(entry if isinstance(entry, dict) else None)
            if not item or item["id"] in seen:
                continue
            item["query"] = query
            seen.add(item["id"])
            found.append(item)
        if len(found) >= limit:
            break
    return found


def _section_flags(candidate: dict[str, Any], audit: dict[str, Any] | None) -> list[str]:
    try:
        duration = float(candidate["duration"]) if candidate.get("duration") is not None else None
    except (TypeError, ValueError):
        duration = None
    flags: list[str] = []
    if duration is not None and duration <= HIGHLIGHT_KEEP_SECONDS:
        return flags
    if duration is not None and duration >= FULL_MATCH_SECONDS:
        for goal in (audit or {}).get("goal_timeline") or []:
            start = max(0, int(goal.get("minute") or 0) * 60 + int(goal.get("second") or 0) - 6)
            end = start + 20
            flags.extend(["--download-sections", f"*{start}-{end}"])
            if len(flags) >= MAX_BEATS * 2:
                break
        if flags:
            flags.append("--force-keyframes-at-cuts")
            return flags
    flags.extend([
        "--download-sections", f"*0-{int(DOWNLOAD_CAP_SECONDS)}",
        "--force-keyframes-at-cuts",
    ])
    return flags


def download_video(
    candidate: dict[str, Any],
    dest_dir: Path,
    *,
    audit: dict[str, Any] | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
    ytdlp: list[str] | None = None,
) -> Path | None:
    ytdlp = ytdlp or ensure_ytdlp()
    if not ytdlp:
        print("  [clips] yt-dlp is not on PATH; cannot download.")
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    video_id = safe_name(str(candidate.get("id") or "highlight"))[:24]
    stem = f"yt_{video_id}"
    output = dest_dir / f"{stem}.%(ext)s"
    url = str(candidate.get("url") or "")
    if not url:
        return None
    args = [
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout", "20",
        "--retries", "2",
        "--fragment-retries", "2",
        "--no-mtime",
        "-f", "bv*[height<=720]+ba/b[height<=720]/b",
        "--merge-output-format", "mp4",
        "--max-filesize", MAX_FILESIZE,
        "-o", str(output),
        *_section_flags(candidate, audit),
        url,
    ]
    print(f"  [clips] downloading {candidate.get('title', '')!r}")
    print(f"  [clips] url: {url}")
    try:
        result = _run_ytdlp(args, timeout=timeout, ytdlp=ytdlp)
    except subprocess.TimeoutExpired:
        print(f"  [clips] download timed out after {timeout:.0f}s")
        return None
    except (OSError, FileNotFoundError) as exc:
        print(f"  [clips] download failed: {exc}")
        return None
    if result.returncode not in (0, 101):
        err = (result.stderr or result.stdout or "").strip()[:400]
        print(f"  [clips] download failed: {err}")
        return None
    matches = sorted(
        dest_dir.glob(f"{stem}.*"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    video = next((path for path in matches if path.suffix.lower() in VIDEO_EXTS), None)
    if video:
        print(f"  [clips] saved {video}")
    return video


def _write_sidecar(video: Path, meta: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **meta,
        "path": str(video),
        "filename": video.name,
        "bytes": video.stat().st_size if video.exists() else 0,
        "local_duration": duration_seconds(video),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    video.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_json(video.parent / SIDECAR_NAME, payload)
    return payload


def read_fetch_meta(match_dir: Path) -> dict[str, Any]:
    path = Path(match_dir) / "clips" / SIDECAR_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def cached_highlight(dest_dir: Path) -> tuple[Path | None, dict[str, Any]]:
    dest_dir = Path(dest_dir)
    meta: dict[str, Any] = {}
    sidecar = dest_dir / SIDECAR_NAME
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        stored = Path(meta.get("path") or "")
        if not stored.is_file():
            stored = dest_dir / str(meta.get("filename") or "")
        if stored.is_file() and stored.suffix.lower() in VIDEO_EXTS:
            return stored, meta
    videos = [
        path for path in dest_dir.glob("yt_*.*")
        if path.suffix.lower() in VIDEO_EXTS and path.is_file()
    ]
    if videos:
        videos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return videos[0], meta
    return None, meta


def fetch_highlight(
    bundle: MatchBundle,
    dest_dir: Path,
    *,
    audit: dict[str, Any] | None = None,
    language: str = "en",
    refetch: bool = False,
    search_fn: SearchFn | None = None,
    download_fn: DownloadFn | None = None,
) -> Path | None:
    """Search, rank, download. Returns a local path or None. Never raises."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not refetch:
        cached, meta = cached_highlight(dest_dir)
        if cached:
            title = meta.get("title") or cached.name
            print(f"  [clips] cache hit: {cached.name}  ({title})")
            if meta.get("url"):
                print(f"  [clips] url: {meta['url']}")
            return cached

    queries = search_queries(bundle, audit, language=language)
    try:
        searcher = search_fn or search_youtube
        candidates = searcher(queries)
    except Exception as exc:
        print(f"  [clips] search raised {exc!r}; continuing without a clip")
        return None

    if not candidates:
        print("  [clips] no search results; recap continues graphics-only")
        return None

    ranked = rank_candidates(candidates, bundle, audit)
    if not ranked:
        print("  [clips] search hits were all the wrong fixture or non-match videos")
        return None

    downloader = download_fn or (
        lambda cand, dest: download_video(cand, dest, audit=audit)
    )
    last_error = ""
    for candidate in ranked[:3]:
        print(
            f"  [clips] picked {candidate.get('title')!r} "
            f"(score {candidate.get('rank_score')})"
        )
        if candidate.get("url"):
            print(f"  [clips] url: {candidate['url']}")
        try:
            video = downloader(candidate, dest_dir)
        except Exception as exc:
            last_error = str(exc)
            print(f"  [clips] download raised {exc!r}")
            video = None
        if not video:
            continue
        meta = {
            "id": candidate.get("id"),
            "url": candidate.get("url"),
            "title": candidate.get("title"),
            "uploader": candidate.get("uploader"),
            "duration": candidate.get("duration"),
            "query": candidate.get("query") or (queries[0] if queries else ""),
            "queries": queries,
            "rank_score": candidate.get("rank_score"),
            "kind": "highlight",
            "capped": bool(_section_flags(candidate, audit)),
        }
        _write_sidecar(video, meta)
        return video
    if last_error:
        print(f"  [clips] fetch failed: {last_error}")
    else:
        print("  [clips] fetch failed; recap continues graphics-only")
    return None


def acquire_sources(
    bundle: MatchBundle,
    match_dir: Path,
    extra: list[Path] | None = None,
    *,
    fetch: bool = True,
    refetch: bool = False,
    audit: dict[str, Any] | None = None,
    language: str = "en",
    search_fn: SearchFn | None = None,
    download_fn: DownloadFn | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    """Local files first, then cache, then network. Always returns a report."""
    match_dir = Path(match_dir)
    extra = [Path(p) for p in extra or []]
    dest = match_dir / "clips"
    local = discover_sources(match_dir, extra)
    report: dict[str, Any] = {
        "mode": "none",
        "queries": search_queries(bundle, audit, language=language),
    }

    extra_hits = [path for path in extra if path.is_file()]
    if extra_hits and not refetch:
        report.update({"mode": "local", "path": str(local[0] if local else extra_hits[0])})
        return discover_sources(match_dir, extra), report

    if local and not refetch:
        meta = read_fetch_meta(match_dir)
        mode = "cache" if meta else "local"
        report.update({
            **{k: meta.get(k) for k in ("url", "title", "id", "query", "rank_score") if meta.get(k)},
            "mode": mode,
            "path": str(local[0]),
        })
        return local, report

    if not fetch:
        report.update({"mode": "skipped", "reason": "fetch disabled"})
        return local, report

    fetched = fetch_highlight(
        bundle, dest, audit=audit, language=language, refetch=refetch,
        search_fn=search_fn, download_fn=download_fn,
    )
    sources = discover_sources(match_dir, extra)
    meta = read_fetch_meta(match_dir)
    if fetched:
        report.update({
            "mode": "fetched",
            "path": str(fetched),
            "url": meta.get("url"),
            "title": meta.get("title"),
            "id": meta.get("id"),
            "query": meta.get("query"),
            "rank_score": meta.get("rank_score"),
        })
        return sources or [fetched], report

    report.update({
        "mode": "failed",
        "reason": "no usable highlight",
        "url": meta.get("url"),
        "title": meta.get("title"),
    })
    return sources, report


def _goal_offsets(audit: dict[str, Any], tape_seconds: float) -> list[float]:
    offsets: list[float] = []
    for goal in audit.get("goal_timeline") or []:
        minute = int(goal.get("minute") or 0)
        second = int(goal.get("second") or 0)
        start = max(0.0, minute * 60 + second - 1.2)
        if start + SINGLE_CUT < tape_seconds - 1:
            offsets.append(start)
    return offsets[:MAX_BEATS] or [min(12.0, max(0.0, tape_seconds * 0.35))]


def _sample_offsets(tape_seconds: float, count: int) -> list[float]:
    if tape_seconds <= HIGHLIGHT_SECONDS:
        return [0.0]
    usable = max(0.4, tape_seconds - SINGLE_CUT)
    if count <= 1:
        return [min(usable * 0.35, usable)]
    return [usable * (index + 1) / (count + 1) for index in range(count)]


def plan_beats(
    bundle: MatchBundle,
    audit: dict[str, Any],
    sources: list[Path],
    *,
    max_beats: int = MAX_BEATS,
) -> list[dict[str, Any]]:
    """0.4–0.8s punches taken from whatever footage we actually have."""
    beats: list[dict[str, Any]] = []
    for source in sources:
        length = duration_seconds(source)
        if not length or length < 0.35:
            continue
        if length >= FULL_MATCH_SECONDS:
            offsets = _goal_offsets(audit, length)
            span = SINGLE_CUT
        elif length >= HIGHLIGHT_SECONDS:
            want = max_beats - len(beats)
            offsets = _sample_offsets(length, max(1, want))
            span = MICRO_CUT if want > 1 else SINGLE_CUT
        else:
            offsets = [0.0]
            span = min(SINGLE_CUT, length)
        for offset in offsets:
            duration = min(span, max(0.35, length - offset))
            if duration < 0.35:
                continue
            timeline = audit.get("goal_timeline") or []
            scorer = ""
            if length >= FULL_MATCH_SECONDS and len(timeline) > len(beats):
                scorer = str(timeline[len(beats)].get("scorer") or "")
            beats.append(
                {
                    "path": str(source),
                    "start": round(float(offset), 3),
                    "duration": round(float(duration), 3),
                    "label": scorer or f"{bundle.home} — {bundle.away}",
                }
            )
            if len(beats) >= max_beats:
                return beats
    return beats


def _scale_filter() -> str:
    return (
        f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=increase,"
        f"crop={FRAME_W}:{FRAME_H},setsar=1"
    )


def extract_frames(
    beat: dict[str, Any],
    dest_dir: Path,
    *,
    fps: int,
    frame_count: int,
    pattern: str = "frame_%05d.png",
) -> int:
    ffmpeg = _ffmpeg()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not ffmpeg:
        return 0
    source = Path(beat["path"])
    if not source.exists():
        return 0
    target = dest_dir / pattern
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{float(beat.get('start') or 0):.3f}",
        "-i", str(source),
        "-t", f"{float(beat.get('duration') or 0.5):.3f}",
        "-vf", f"{_scale_filter()},fps={fps}",
        "-frames:v", str(max(2, frame_count)),
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    written = sorted(dest_dir.glob("frame_*.png"))
    if result.returncode != 0 or not written:
        return 0
    while len(written) < frame_count:
        clone = dest_dir / (pattern % (len(written) + 1))
        shutil.copyfile(written[-1], clone)
        written.append(clone)
    extra = written[frame_count:]
    for path in extra:
        path.unlink(missing_ok=True)
    return min(len(written), frame_count)


def extract_still(beat: dict[str, Any], dest: Path) -> bool:
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return False
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = float(beat.get("start") or 0) + max(0.05, float(beat.get("duration") or 0.5) * 0.4)
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(beat["path"]),
        "-frames:v", "1",
        "-vf", _scale_filter(),
        str(dest),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode == 0 and dest.exists()


def describe_beats(beats: list[dict[str, Any]]) -> str:
    if not beats:
        return "no clip (auto-fetch found nothing; recap continues graphics-only)"
    bits = []
    for beat in beats:
        name = safe_name(Path(beat["path"]).stem)[:28]
        bits.append(f"{name} @{beat['start']:.1f}s ({beat['duration']:.2f}s)")
    return "; ".join(bits)


def log_report(report: dict[str, Any]) -> None:
    mode = report.get("mode") or "none"
    print(f"  [clips] mode: {mode}")
    if report.get("title"):
        print(f"  [clips] title: {report['title']}")
    if report.get("url"):
        print(f"  [clips] url: {report['url']}")
    if report.get("path"):
        print(f"  [clips] path: {report['path']}")
    if report.get("query"):
        print(f"  [clips] query: {report['query']}")
    if report.get("reason"):
        print(f"  [clips] {report['reason']}")
