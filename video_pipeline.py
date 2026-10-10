#!/usr/bin/env python
"""Interactive CLI for vertical match-recap videos.

    python video_pipeline.py
    python video_pipeline.py --match-dir output/1999238_Argentina_vs_Switzerland --auto
    python video_pipeline.py --language az --auto

You pick the language first. Gemini writes the script in that language —
titles, insights and narration — instead of writing English and translating.
Several codes (az,es) get a separately authored script each, plus their own
video and narration files. Voiceover is skipped; attach a recording later
with --voiceover-file if needed.
"""

from __future__ import annotations

import argparse
import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import freeze_support
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from recap import audit as audit_mod
from recap import clips, director, hooks, i18n, logos, theme, timing, video, voice, viral_audit
from recap.data import describe_match_dir, list_match_dirs, load_match, safe_name, write_json


# ---------------------------------------------------------------------------
# console
# ---------------------------------------------------------------------------

def _console_safe(text: str) -> str:
    """Windows consoles are often cp1252; never let a player's name crash a run."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def say(text: str = "") -> None:
    print(_console_safe(text))


def stage(name: str) -> None:
    say(f"\n{'=' * 66}\n{name}\n{'=' * 66}")


def ask(prompt: str, options: tuple[str, ...], auto: bool) -> str:
    if auto:
        say(f"  {prompt} -> ok (auto)")
        return "ok"
    joined = "/".join(options)
    while True:
        answer = input(f"  {prompt} [{joined}]: ").strip().lower()
        if answer in options:
            return answer
        if answer == "" and "ok" in options:
            return "ok"
        say(f"  Please answer one of: {joined}")


def choose_match(output_root: Path, interactive: bool) -> Path:
    candidates = list_match_dirs(output_root)
    if not candidates:
        raise SystemExit(f"No complete match exports found under {output_root}/")
    if not interactive:
        return candidates[0]
    say("\nExported matches:")
    for index, path in enumerate(candidates, 1):
        say(f"  {index:2d}. {describe_match_dir(path)}   [{path.name}]")
    while True:
        answer = input("Match number: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        say("Please enter a number from the list.")


def choose_languages(args: argparse.Namespace) -> list[str]:
    chosen = list(getattr(args, "language_list", None) or ["en"])
    if getattr(args, "language_explicit", False) or args.auto:
        return chosen
    say(f"  Supported: {', '.join(i18n.SUPPORTED)}")
    say("  Gemini writes the script in the language you pick — it does not translate English.")
    say("  One code = one video. Several (example: az,es) = a native script per language.")
    while True:
        answer = input(f"  Languages [{','.join(chosen)}]: ").strip()
        if not answer:
            return chosen
        try:
            picked = i18n.parse_languages(answer)
        except ValueError as exc:
            say(f"  {exc}")
            continue
        if picked:
            return picked
        say("  Enter at least one language code.")


def package_dir(output_root: Path, match_name: str, language: str, multi: bool) -> Path:
    root = Path(output_root)
    if multi or language != "en":
        return root / language / match_name
    return root / match_name


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def script_preview(scene_list: list[dict[str, Any]]) -> str:
    lines = []
    for index, scene in enumerate(scene_list, 1):
        words = timing.word_count(scene.get("narration", ""))
        lines.append(f"  {index}. [{scene['visualization']}] {scene.get('title', '')}")
        if scene.get("insight"):
            lines.append(f"     insight: {scene['insight']}")
        lines.append(f"     narration ({words}w): {scene.get('narration', '')}")
    return "\n".join(lines)


def timing_table(scene_list: list[dict[str, Any]]) -> str:
    lines = [f"  {'scene':<20} {'words':>5} {'on screen':>10} {'starts':>8}"]
    for scene in scene_list:
        lines.append(
            f"  {scene['visualization']:<20} {timing.word_count(scene.get('narration', '')):>5}"
            f" {scene['on_screen']:>9.2f}s {scene['visible_start']:>7.2f}s"
        )
    lines.append(f"  {'TOTAL':<20} {'':>5} {timing.total_seconds(scene_list):>9.2f}s")
    return "\n".join(lines)


def write_script_files(out_dir: Path, scene_list: list[dict[str, Any]], audit: dict[str, Any]) -> None:
    match = audit["match"]
    header = [
        f"# {match['home']} {match['score_display']} {match['away']}",
        "",
        f"- Competition: {match['league']} {match['stage']}".rstrip(),
        f"- Kick-off: {match['kickoff']}",
        f"- Runtime: {timing.total_seconds(scene_list):.1f}s across {len(scene_list)} scenes",
        "",
    ]
    body: list[str] = []
    narration: list[str] = []
    recording = [
        "# Narration recording script",
        "",
        "Read each line straight through. The target time is in brackets; staying",
        "close to it keeps the captions and the animation in sync.",
        "",
    ]
    for index, scene in enumerate(scene_list, 1):
        text = scene.get("narration", "")
        body += [
            f"## {index}. {scene.get('title', scene['visualization'])}",
            "",
            f"*{scene['visualization']} — {scene['on_screen']:.2f}s — {timing.word_count(text)} words*",
            "",
            text,
            "",
        ]
        if scene.get("insight"):
            body += [f"> On screen: {scene['insight']}", ""]
        narration.append(text)
        recording.append(f"{index}. [{scene['on_screen']:.1f}s] {text}")

    (out_dir / "SCRIPT.md").write_text("\n".join(header + body), encoding="utf-8")
    (out_dir / "narration.txt").write_text("\n\n".join(narration) + "\n", encoding="utf-8")
    (out_dir / "voiceover_recording_script.txt").write_text("\n".join(recording) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------

def build_script(
    bundle,
    audit: dict[str, Any],
    selected: list[dict[str, Any]],
    gemini: director.Gemini | None,
    instruction: str,
    clip_beats: list[dict[str, Any]] | None = None,
    words_per_section: int = 17,
    language: str = "en",
) -> list[dict[str, Any]]:
    """Storyboard plus Gemini copy, authored in ``language``. Not a translation."""
    lang = i18n.normalize_language(language)
    previous = i18n.get_language()
    i18n.set_language(lang)
    try:
        scene_list = director.build_storyboard(bundle, audit, selected, clip_beats=clip_beats)
        angle = director.pick_angle(bundle, audit)
        if gemini is not None and gemini.enabled:
            editorial = gemini.choose_angle(bundle, audit, lang)
            if editorial.get("angle"):
                angle = str(editorial["angle"])
            hook = director.build_hook(bundle, audit)
            rewrite = gemini.rephrase_hook(hook, lang)
            hook = hooks.apply_hook_rephrase(hook, rewrite)
            scene_list = director.apply_script(
                scene_list,
                {
                    "hook_claim": {
                        "title": (hook.get("lines") or [hook.get("punch")])[0],
                        "narration": hook.get("narration_claim") or "",
                    },
                    "hook_punch": {
                        "title": hook.get("punch") or "",
                        "narration": hook.get("narration_punch") or "",
                    },
                },
            )
            budget = max(10, min(24, int(words_per_section or 17)))
            lang_name = i18n.language_name(lang)
            say(f"  asking Gemini to write {budget} evidence words per section in {lang_name}")
            overrides = gemini.write_script(
                bundle, audit, scene_list, budget, instruction, language=lang,
                angle=angle, audit_notes=[instruction] if instruction else [],
            )
            if overrides:
                scene_list = director.apply_script(scene_list, overrides)
            elif gemini.last_error:
                say(f"  [warn] Gemini script pass failed ({gemini.last_error[:110]}); using the audited script.")

        problems = director.copy_problems(scene_list, audit)
        if problems:
            say("  [warn] copy check found unsupported claims; reverting those scenes to the audited script:")
            for problem in problems[:6]:
                say(f"    - {problem}")
            safe = director.build_storyboard(bundle, audit, selected, clip_beats=clip_beats)
            by_id = {scene["id"]: scene for scene in safe}
            flagged = {problem.split(".")[0] for problem in problems}
            scene_list = [by_id.get(scene["id"], scene) if scene["id"] in flagged else scene
                          for scene in scene_list]
        return director.lock_hook_cards(scene_list, bundle, audit)
    finally:
        i18n.set_language(previous)


def polish_native_script(
    scenes: list[dict[str, Any]],
    language: str,
    bundle,
    audit: dict[str, Any],
) -> list[dict[str, Any]]:
    """Drop leftover English chrome. Do not replace Gemini titles with catalog copy."""
    target = i18n.normalize_language(language)
    scenes = [copy.deepcopy(scene) for scene in scenes]
    if target == "en":
        return scenes
    previous = i18n.get_language()
    i18n.set_language(target)
    try:
        scenes = i18n.scrub_english_leftovers(scenes, target)
        scenes = director.lock_hook_cards(scenes, bundle, audit)
        fallback = director.storyboard_by_id(scenes, bundle, audit)
        scenes = i18n.patch_leftover_copy(scenes, fallback, target)
        return i18n.scrub_english_leftovers(scenes, target)
    finally:
        i18n.set_language(previous)


def prepare_language_package(
    *,
    out_dir: Path,
    scene_list: list[dict[str, Any]],
    audit: dict[str, Any],
    language: str,
    args: argparse.Namespace,
    gemini: director.Gemini | None,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    viral_report: dict[str, Any],
    team_kind: str,
    fps: int,
) -> tuple[list[dict[str, Any]], Path | None]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timed = timing.plan_durations([copy.deepcopy(scene) for scene in scene_list])
    write_script_files(out_dir, timing.timeline(timed), audit)

    audio_path = None
    if not args.skip_audio:
        narration_text = "\n\n".join(scene["narration"] for scene in timed)
        audio_path = voice.prepare(out_dir, narration_text, voice.VoiceConfig(
            voiceover_file=args.voiceover_file, use_sapi=args.sapi_tts, skip_audio=False,
        ))
        audio_seconds = voice.duration(audio_path)
        if audio_seconds:
            timed = timing.scale_to_audio(timed, audio_seconds)

    timed = video.quantize_to_frames(timed, fps)
    timed = timing.timeline(timed)
    cues = timing.build_subtitles(timed)
    (out_dir / "subtitles.srt").write_text(timing.render_srt(cues), encoding="utf-8")
    write_script_files(out_dir, timed, audit)
    write_json(out_dir / "video_plan.json", {
        "match": audit["match"],
        "generation": {
            "language": language,
            "language_name": i18n.language_name(language),
            "team_kind": team_kind,
            "badge_shape": theme.badge_shape(team_kind),
            "colors": {
                "home": theme.get_team_colors()[0],
                "away": theme.get_team_colors()[1],
            },
            "gemini_used": bool(gemini and gemini.enabled),
            "gemini_model": gemini.model if gemini else None,
            "gemini_script_model": gemini.script_model if gemini else None,
            "gemini_error": (gemini.last_error or None) if gemini else None,
            "fps": fps,
            "transition_seconds": timing.TRANSITION,
            "target_seconds": args.target_seconds,
            "total_seconds": timing.total_seconds(timed),
            "sfx": bool(getattr(args, "sfx", True)),
            "burn_captions": bool(getattr(args, "burn_captions", False)),
        },
        "viral_audit": viral_report,
        "selected_visualizations": selected,
        "all_candidates": candidates,
        "scenes": timed,
        "subtitles": cues,
    })
    return timed, audio_path


def render_packages(jobs: list[dict[str, Any]], parallel: bool) -> list[dict[str, Any]]:
    if not jobs:
        return []
    if not parallel or len(jobs) == 1:
        results = []
        for job in jobs:
            try:
                results.append(video.render_language_job(job))
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "language": job["language"],
                    "out_dir": job["out_dir"],
                    "path": "",
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return results
    try:
        workers = min(len(jobs), 4)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(video.render_language_job, jobs))
    except Exception as exc:  # noqa: BLE001
        say(f"  [warn] parallel render failed ({exc}); rendering one language at a time")
        return render_packages(jobs, parallel=False)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> list[Path]:
    team_kind = theme.set_team_kind(args.team)
    if args.colors:
        try:
            home_hex, away_hex = theme.set_team_colors(args.colors[0], args.colors[1])
        except ValueError as exc:
            raise SystemExit(f"  {exc}") from exc
        say(f"  colors: home {home_hex} / away {away_hex}")
    else:
        home_hex, away_hex = theme.get_team_colors()

    match_dir = Path(args.match_dir) if args.match_dir else choose_match(
        Path(args.scrape_output_root), args.interactive
    )
    bundle = load_match(match_dir)
    match_name = safe_name(match_dir.name)
    say(f"  typeface: {theme.DISPLAY_FONT} / {theme.LABEL_FONT}")
    say(f"  team mode: {team_kind} ({'circular crests + logos' if team_kind == 'club' else 'rectangular flags'})")
    if team_kind == "club":
        resolved = logos.warm_logos(
            bundle.home, bundle.away, bundle.home_team_id, bundle.away_team_id
        )
        for name, path in resolved.items():
            say(f"  crest {name}: {path or 'initials fallback'}")

    stage("1. Data audit")
    audit = audit_mod.build_audit(bundle)
    if ask("Accept these numbers?", ("ok", "quit"), args.auto) == "quit":
        raise SystemExit("Stopped at the data audit.")

    stage("2. Language")
    languages = choose_languages(args)
    primary_language = languages[0]
    i18n.set_language(primary_language)
    say("  writing in " + ", ".join(f"{i18n.language_name(code)} ({code})" for code in languages))
    say("  Gemini will compose each script in that language, not translate English.")

    extra_clips = [Path(p) for p in (args.clip or [])]
    sources = clips.discover_sources(match_dir, extra_clips)
    if args.fetch_clip and not sources:
        fetched = clips.fetch_highlight(bundle, match_dir / "clips")
        if fetched:
            sources = [fetched]
    clip_beats = clips.plan_beats(bundle, audit, sources)
    say(f"  opening clips: {clips.describe_beats(clip_beats)}")

    gemini = None
    if not args.no_gemini:
        gemini = director.Gemini(
            enabled=True,
            required=args.require_gemini,
            model=args.model,
            script_model=getattr(args, "script_model", None),
        )
        if gemini.enabled:
            say(f"  Gemini enabled ({gemini.model} / script {gemini.script_model}).")
        else:
            say("  Gemini disabled (GEMINI_API_KEY is not set); using the deterministic script.")

    stage("3. Visualization plan")
    selected, candidates = director.select_visualizations(
        bundle, audit, args.visualizations, gemini, args.instruction
    )
    requested_ids = [
        value.strip()
        for value in str(getattr(args, "selected_visualizations", "") or "").split(",")
        if value.strip()
    ]
    if requested_ids:
        available = {row["id"]: row for row in candidates if row.get("available")}
        invalid = [value for value in requested_ids if value not in available]
        if invalid:
            raise SystemExit(
                "Selected visualizations are unavailable for this export: "
                + ", ".join(invalid)
            )
        selected = [available[value] for value in requested_ids]
    while True:
        for candidate in sorted(candidates, key=lambda c: c["score"], reverse=True):
            mark = "  " if candidate["available"] else "x "
            chosen = "*" if any(s["id"] == candidate["id"] for s in selected) else " "
            say(f"  {chosen}{mark}{candidate['id']:<20} {candidate['score']:>6.1f}  {candidate['reason']}")
        say("  Selected: " + ", ".join(item["id"] for item in selected))
        action = ask("Keep this plan?", ("ok", "change", "redo", "quit"), args.auto)
        if action == "quit":
            raise SystemExit("Stopped at the visualization plan.")
        if action == "ok":
            break
        if action == "change":
            selected = manual_selection(candidates, args.visualizations) or selected
            break
        selected, candidates = director.select_visualizations(
            bundle, audit, args.visualizations, gemini,
            f"{args.instruction} Choose a different angle to the previous attempt.",
        )

    stage("4. Script")
    instruction = args.instruction
    viral_report: dict[str, Any] = {}
    scene_list: list[dict[str, Any]] = []
    while True:
        scene_list = build_script(
            bundle, audit, selected, gemini, instruction,
            clip_beats=clip_beats,
            words_per_section=args.words_per_section,
            language=primary_language,
        )
        viral_report = viral_audit.score_plan(
            scene_list, selected, bundle, audit, output_root=Path(args.output_root),
        )
        say(f"  viral score: {viral_report['score']}")
        for note in viral_report.get("warnings") or []:
            say(f"  [viral] {note}")
        say(script_preview(scene_list))
        action = ask("Use this script?", ("ok", "change", "redo", "quit"), args.auto)
        if action == "quit":
            raise SystemExit("Stopped at the script.")
        if action == "ok":
            break
        if action == "change":
            instruction = input("  What should change? ").strip() or instruction
        else:
            instruction = viral_audit.redo_instruction(instruction, viral_report)

    viral_audit.remember_punch(
        Path(args.output_root),
        str(viral_report.get("punch") or ""),
        match_dir.name,
        str(viral_report.get("hook_kind") or ""),
    )

    multi = len(languages) > 1
    localized: dict[str, list[dict[str, Any]]] = {
        primary_language: polish_native_script(scene_list, primary_language, bundle, audit),
    }
    for code in languages:
        if code == primary_language:
            continue
        say(f"  [{code}] writing a native {i18n.language_name(code)} script (not a translation)")
        extra = build_script(
            bundle, audit, selected, gemini, instruction,
            clip_beats=clip_beats,
            words_per_section=args.words_per_section,
            language=code,
        )
        localized[code] = polish_native_script(extra, code, bundle, audit)
        say(f"  [{code}] script ready")

    prepared: dict[str, tuple[list[dict[str, Any]], Path | None, Path]] = {}
    for code in languages:
        out_dir = package_dir(Path(args.output_root), match_name, code, multi)
        write_json(out_dir / "data_audit.json", audit)
        timed, audio_path = prepare_language_package(
            out_dir=out_dir,
            scene_list=localized[code],
            audit=audit,
            language=code,
            args=args,
            gemini=gemini,
            selected=selected,
            candidates=candidates,
            viral_report=viral_report,
            team_kind=team_kind,
            fps=args.fps,
        )
        prepared[code] = (timed, audio_path, out_dir)
        say(f"  [{code}] wrote {out_dir / 'narration.txt'}")
        say(timing_table(timed))

    if args.still:
        stage("5. Still preview")
    else:
        stage("5. Render")
        if not args.auto and ask("Assemble the video(s)?", ("ok", "quit"), False) == "quit":
            raise SystemExit("Stopped before assembly. Narration files are already written.")

    jobs = []
    for code in languages:
        timed, audio_path, out_dir = prepared[code]
        jobs.append({
            "language": code,
            "team": team_kind,
            "home_color": home_hex,
            "away_color": away_hex,
            "match_dir": str(match_dir),
            "out_dir": str(out_dir),
            "audit": audit,
            "scene_list": timed,
            "fps": args.fps,
            "still": bool(args.still),
            "still_positions": list(args.still_positions),
            "skip_video": bool(args.skip_video),
            "no_crossfade": bool(args.no_crossfade),
            "sfx": bool(getattr(args, "sfx", True)),
            "burn_captions": bool(getattr(args, "burn_captions", False)),
            "music_file": getattr(args, "music_file", "") or "",
            "audio_path": str(audio_path) if audio_path else "",
        })

    results = render_packages(jobs, parallel=multi and not args.still)
    written: list[Path] = []
    for row in results:
        out = Path(row["out_dir"])
        written.append(out)
        if row.get("error") and row["error"] != "no mp4":
            say(f"  [{row['language']}] render failed: {row['error']}")
            continue
        if row.get("path"):
            path = Path(row["path"])
            actual = video.probe_duration(path) if path.suffix == ".mp4" else 0.0
            say(f"  [{row['language']}] wrote {path}")
            if actual:
                say(f"  [{row['language']}] duration {actual:.2f}s")
        else:
            say(f"  [{row['language']}] frames and narration are in {out}")
    return written


def manual_selection(candidates: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    available = {c["id"]: c for c in candidates if c["available"]}
    say("  Available: " + ", ".join(available))
    answer = input(f"  Enter up to {count} ids, comma separated: ").strip()
    chosen = [available[key.strip()] for key in answer.split(",") if key.strip() in available]
    if not chosen:
        say("  Nothing valid entered; keeping the previous plan.")
    return chosen[:count]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a vertical match recap from a WhoScored export.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--match-dir", help="An export directory under output/")
    parser.add_argument("--scrape-output-root", default="output", help="Where scraper exports live")
    parser.add_argument("--output-root", default="video_output", help="Where video packages are written")
    parser.add_argument("--visualizations", type=int, default=4,
                        help="Tactical visualizations between the hook and the closing score")
    parser.add_argument(
        "--selected-visualizations", default="", metavar="IDS",
        help="Exact comma-separated visualization ids",
    )
    parser.add_argument("--target-seconds", type=float, default=34.0,
                        help="Runtime the script is written to fill")
    parser.add_argument("--words-per-section", type=int, default=17,
                        help="Evidence-rich narration target for each selected statistic")
    parser.add_argument("--fps", type=int, default=video.DEFAULT_FPS, help="Output frame rate")

    parser.add_argument("--interactive", action="store_true", help="Pick the match and approve each stage")
    parser.add_argument("--auto", action="store_true", help="Approve every stage without prompting")

    parser.add_argument(
        "--language", "--languages", dest="languages", default=None, metavar="CODES",
        help="Language Gemini writes in (en,az,es,ru). Comma-separated list = "
             "one native script and video per code, not a translation of English.",
    )
    parser.add_argument("--team", default="national",
                        choices=list(theme.TEAM_KINDS),
                        help="Badge style: national flags (rect) or club crests (circle + logos)")
    parser.add_argument(
        "--colors", nargs=2, metavar=("HOME", "AWAY"),
        help="Home and away hex colours, e.g. --colors \"#004170\" \"#95BFE5\" "
             "(quote them in PowerShell; # without quotes is a comment)",
    )
    parser.add_argument("--instruction", default="", help="Editorial note passed to Gemini")
    parser.add_argument("--model", default=None, help="Gemini model for viz pick (allowlist: Gemma 4 31B, Gemini 3.5/3.1 Flash and Flash-Lite, Gemini 3 Flash, Gemini 2.5 Flash)")
    parser.add_argument("--script-model", default=None,
                        help="Gemini model for copy (same allowlist as --model)")
    parser.add_argument("--no-gemini", action="store_true", help="Use only the deterministic script")
    parser.add_argument("--require-gemini", action="store_true", help="Fail rather than fall back")
    parser.add_argument(
        "--translation-provider", default="auto",
        choices=("auto", "gemini", "groq", "offline"),
        help="Unused for the main path: Gemini authors each language. Kept for tests.",
    )
    parser.add_argument(
        "--require-context-translation", action="store_true",
        help="Unused for the main path. Kept so older flags still parse.",
    )

    parser.add_argument("--voiceover-file", default="", help="Optional recorded narration to attach")
    parser.add_argument("--sapi-tts", action="store_true", help="Windows SAPI rough-cut (off by default)")
    parser.add_argument("--skip-audio", dest="skip_audio", action="store_true", default=True,
                        help="Silent video; narration files are still written (default)")
    parser.add_argument("--with-audio", dest="skip_audio", action="store_false",
                        help="Attach --voiceover-file or --sapi-tts")
    parser.add_argument("--sfx", dest="sfx", action="store_true", default=True,
                        help="Mix synthesized hits under the master (default on)")
    parser.add_argument("--no-sfx", dest="sfx", action="store_false", help="Skip SFX hits")
    parser.add_argument("--music-file", default="", help="Optional music bed")
    parser.add_argument("--burn-captions", dest="burn_captions", action="store_true", default=False,
                        help="Burn subtitles into the master (off by default)")
    parser.add_argument("--no-burn-captions", dest="burn_captions", action="store_false",
                        help="Keep captions as an external SRT only")

    parser.add_argument("--clip", action="append", default=[],
                        help="Path to a match clip or highlight (repeatable). Also reads match-dir/clips/")
    parser.add_argument("--fetch-clip", action="store_true",
                        help="Search YouTube via yt-dlp for a highlight if no local clip exists")

    parser.add_argument("--still", action="store_true", help="Render one image per scene instead of a video")
    parser.add_argument("--still-positions", type=float, nargs="+", default=[1.0],
                        help="Animation positions to capture with --still")
    parser.add_argument("--no-crossfade", action="store_true", help="Hard cuts instead of dissolves")
    parser.add_argument("--skip-video", action="store_true", help="Write narration and plan, do not encode")

    args = parser.parse_args(argv)
    if not args.auto and not args.interactive:
        args.interactive = True
    if args.require_gemini and args.no_gemini:
        parser.error("--require-gemini and --no-gemini cannot be combined")
    if not 10 <= args.words_per_section <= 24:
        parser.error("--words-per-section must be between 10 and 24")
    if args.voiceover_file or args.sapi_tts:
        args.skip_audio = False
    args.language_explicit = bool(args.languages)
    try:
        args.language_list = i18n.parse_languages(args.languages) if args.languages else ["en"]
    except ValueError as exc:
        parser.error(str(exc))
    args.language = args.language_list[0]
    return args


if __name__ == "__main__":
    freeze_support()
    try:
        run(parse_args())
    except KeyboardInterrupt:
        say("\nInterrupted.")
        raise SystemExit(130)
