#!/usr/bin/env python
"""Turn a scraped WhoScored export into a narrated vertical match recap.

    python video_pipeline.py --match-dir output/1999238_Argentina_vs_Switzerland --auto
    python video_pipeline.py --interactive
    python video_pipeline.py --match-dir output/... --auto --still   # fast preview

Written to video_output/<match>/:

    data_audit.json      every metric the video is allowed to use
    video_plan.json      chosen visualizations, scene timings, final durations
    SCRIPT.md            scene-by-scene script with word counts and timings
    narration.txt        the narration as one block
    voiceover_recording_script.txt
    subtitles.srt        cues aligned to the rendered timeline
    assets/              one frame sequence per scene
    match_video.mp4

Gemini is optional. With GEMINI_API_KEY set it writes the on-screen copy and
narration; without it the deterministic script is used. Either way the numbers
come only from data_audit.json.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from recap import audit as audit_mod
from recap import audio, clips, director, hooks, i18n, logos, theme, timing, video, voice, viral_audit
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


def progress_reporter():
    last = [-1]

    def report(done: int, total: int, elapsed: float) -> None:
        percent = int(done / max(1, total) * 100)
        if percent == last[0] and done < total:
            return
        last[0] = percent
        rate = done / elapsed if elapsed > 0 else 0
        remaining = (total - done) / rate if rate > 0 else 0
        end = "\n" if done >= total else "\r"
        print(
            f"  frames {done}/{total} ({percent:3d}%)  {rate:4.1f} fps  eta {remaining:5.0f}s",
            end=end, flush=True,
        )

    return report


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> Path:
    language = i18n.set_language(args.language)
    team_kind = theme.set_team_kind(args.team)
    if args.colors:
        try:
            home_hex, away_hex = theme.set_team_colors(args.colors[0], args.colors[1])
        except ValueError as exc:
            raise SystemExit(f"  {exc}") from exc
        say(f"  colors: home {home_hex} / away {away_hex}")
    match_dir = Path(args.match_dir) if args.match_dir else choose_match(
        Path(args.scrape_output_root), args.interactive
    )
    bundle = load_match(match_dir)
    out_dir = Path(args.output_root) / safe_name(match_dir.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    say(f"  language: {i18n.language_name(language)} ({language})")
    say(f"  typeface: {theme.DISPLAY_FONT} / {theme.LABEL_FONT}")
    say(f"  team mode: {team_kind} ({'circular crests + logos' if team_kind == 'club' else 'rectangular flags'})")
    if team_kind == "club":
        resolved = logos.warm_logos(
            bundle.home, bundle.away, bundle.home_team_id, bundle.away_team_id
        )
        for name, path in resolved.items():
            say(f"  crest {name}: {path or 'initials fallback'}")

    # -- 1. audit ----------------------------------------------------------
    stage("1. Data audit")
    audit = audit_mod.build_audit(bundle)
    write_json(out_dir / "data_audit.json", audit)
    for fact in audit["facts"]:
        say(f"  - {fact}")
    if ask("Accept these numbers?", ("ok", "quit"), args.auto) == "quit":
        raise SystemExit("Stopped at the data audit.")

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

    # -- 2. visualizations -------------------------------------------------
    stage("2. Visualization plan")
    selected, candidates = director.select_visualizations(
        bundle, audit, args.visualizations, gemini, args.instruction
    )
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

    # -- 3. script ---------------------------------------------------------
    stage("3. Script")
    instruction = args.instruction
    already_localized = False
    viral_report: dict[str, Any] = {}
    while True:
        scene_list, already_localized = build_script(
            bundle, audit, selected, gemini, instruction, args.target_seconds, language,
            clip_beats=clip_beats,
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

    if language != "en":
        if not already_localized:
            translator = gemini
            if translator is None or not translator.enabled:
                # Translation-only path: still use the API key if present, even when
                # creative Gemini scripting was turned off with --no-gemini.
                translator = director.Gemini(enabled=True, required=False)
            scene_list, method = i18n.localize_scenes(scene_list, language, translator)
            if method == "gemini":
                say(f"  localized free-form copy via Gemini ({i18n.language_name(language)}).")
            else:
                say(
                    f"  localized UI + known lines offline ({i18n.language_name(language)}). "
                    "Set GEMINI_API_KEY for fuller narration translation."
                )
        # Always strip leftover English chrome. Gemini often rewrites the title
        # and leaves the English subtitle sitting under it.
        scene_list = i18n.scrub_english_leftovers(scene_list, language)
        scene_list = director.lock_hook_cards(scene_list, bundle, audit)
        scene_list = i18n.scrub_english_leftovers(scene_list, language)
        say(script_preview(scene_list))

    # -- 4. timing and narration ------------------------------------------
    stage("4. Timing")
    scene_list = timing.plan_durations(scene_list)
    narration_text = "\n\n".join(scene["narration"] for scene in scene_list)
    write_script_files(out_dir, timing.timeline(scene_list), audit)

    audio_path = voice.prepare(out_dir, narration_text, voice.VoiceConfig(
        voiceover_file=args.voiceover_file, use_sapi=args.sapi_tts, skip_audio=args.skip_audio
    ))
    audio_seconds = voice.duration(audio_path)
    if audio_seconds:
        say(f"  narration audio is {audio_seconds:.2f}s; fitting the scenes to it")
        scene_list = timing.scale_to_audio(scene_list, audio_seconds)

    skip_audio = bool(args.skip_audio)
    loudnorm = "off" if skip_audio else audio.normalize_loudnorm(getattr(args, "loudnorm", "tiktok"))
    sfx_on = False if skip_audio else bool(getattr(args, "sfx", True))
    music_path, bpm = audio.resolve_music_bed(
        getattr(args, "music_bed", "auto"),
        out_dir=out_dir,
        scenes=scene_list,
        music_file=getattr(args, "music_file", "") or None,
        skip_audio=skip_audio,
    )
    if music_path:
        scene_list = audio.snap_wipes_to_beats(scene_list, bpm)
        say(f"  music bed {music_path.name} @ {bpm:.0f} bpm; wipe cuts snapped to beats (≤120ms)")

    scene_list = video.quantize_to_frames(scene_list, args.fps)
    scene_list = timing.timeline(scene_list)
    say(timing_table(scene_list))

    cues = timing.build_subtitles(scene_list)
    (out_dir / "subtitles.srt").write_text(timing.render_srt(cues), encoding="utf-8")
    write_script_files(out_dir, scene_list, audit)

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
            "fps": args.fps,
            "transition_seconds": timing.TRANSITION,
            "target_seconds": args.target_seconds,
            "total_seconds": timing.total_seconds(scene_list),
            "sfx": sfx_on,
            "music_bed": None if skip_audio else (getattr(args, "music_bed", "auto") or "auto"),
            "music_file": str(music_path) if music_path else None,
            "bpm": bpm,
            "loudnorm": loudnorm,
            "skip_audio": skip_audio,
            "burn_captions": bool(getattr(args, "burn_captions", True)),
        },
        "viral_audit": viral_report,
        "selected_visualizations": selected,
        "all_candidates": candidates,
        "scenes": scene_list,
        "subtitles": cues,
    })

    # -- 5. render ---------------------------------------------------------
    if args.still:
        stage("5. Still preview")
        written = video.render_stills(bundle, audit, scene_list, out_dir / "stills",
                                      positions=tuple(args.still_positions))
        for path in written:
            say(f"  {path}")
        return out_dir

    stage("5. Render")
    say(f"  {sum(s['frames'] for s in scene_list)} frames at {args.fps} fps")
    rendered = video.render_frames(bundle, audit, scene_list, out_dir / "assets",
                                  fps=args.fps, on_progress=progress_reporter())

    if ask("Assemble the video?", ("ok", "quit"), args.auto) == "quit":
        raise SystemExit("Stopped before assembly.")

    # -- 6. assemble -------------------------------------------------------
    stage("6. Assemble")
    if args.skip_video:
        say("  skipped (--skip-video)")
        return out_dir

    path = video.assemble(
        out_dir, rendered, audio_path, fps=args.fps,
        crossfade=not args.no_crossfade,
        sfx=sfx_on,
        burn_captions=bool(getattr(args, "burn_captions", True)),
        music_file=music_path,
        srt_path=out_dir / "subtitles.srt",
        loudnorm=loudnorm,
        skip_audio=skip_audio,
    )
    if not path:
        say("  no mp4 was produced; the frames and script are still in place.")
        return out_dir

    actual = video.probe_duration(path)
    expected = timing.total_seconds(scene_list)
    say(f"  wrote {path}")
    say(f"  duration {actual:.2f}s (planned {expected:.2f}s)" if actual else f"  planned {expected:.2f}s")
    if actual and abs(actual - expected) > 0.35:
        say(f"  [warn] the encoded duration is {abs(actual - expected):.2f}s off the plan")
    return out_dir


def build_script(
    bundle,
    audit: dict[str, Any],
    selected: list[dict[str, Any]],
    gemini: director.Gemini | None,
    instruction: str,
    target_seconds: float,
    language: str = "en",
    clip_beats: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (scenes, already_localized_by_gemini)."""
    scene_list = director.build_storyboard(bundle, audit, selected, clip_beats=clip_beats)
    already_localized = False
    angle = director.pick_angle(bundle, audit)
    if gemini is not None and gemini.enabled:
        editorial = gemini.choose_angle(bundle, audit, language)
        if editorial.get("angle"):
            angle = str(editorial["angle"])
        hook = director.build_hook(bundle, audit)
        rewrite = gemini.rephrase_hook(hook, language)
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
        speakable = [scene for scene in scene_list if not scene.get("hook")]
        budget = timing.word_budget(target_seconds, max(1, len(speakable)))
        say(f"  asking Gemini for roughly {budget} words per scene ({i18n.language_name(language)})")
        overrides = gemini.write_script(
            bundle, audit, scene_list, budget, instruction, language=language,
            angle=angle, audit_notes=[instruction] if instruction else [],
        )
        if overrides:
            scene_list = director.apply_script(scene_list, overrides)
            already_localized = language != "en"

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
        if flagged:
            already_localized = False
    scene_list = director.lock_hook_cards(scene_list, bundle, audit)
    return scene_list, already_localized


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
        description="Build a narrated vertical match recap from a WhoScored export.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--match-dir", help="An export directory under output/")
    parser.add_argument("--scrape-output-root", default="output", help="Where scraper exports live")
    parser.add_argument("--output-root", default="video_output", help="Where video packages are written")
    parser.add_argument("--visualizations", type=int, default=5,
                        help="Tactical visualizations between the hook and the closing score")
    parser.add_argument("--target-seconds", type=float, default=40.0,
                        help="Runtime the script is written to fill")
    parser.add_argument("--fps", type=int, default=video.DEFAULT_FPS, help="Output frame rate")

    parser.add_argument("--interactive", action="store_true", help="Pick the match and approve each stage")
    parser.add_argument("--auto", action="store_true", help="Approve every stage without prompting")

    parser.add_argument("--language", default="en",
                        choices=list(i18n.SUPPORTED),
                        help="On-screen copy and narration language (en/az/es/ru)")
    parser.add_argument("--team", default="national",
                        choices=list(theme.TEAM_KINDS),
                        help="Badge style: national flags (rect) or club crests (circle + logos)")
    parser.add_argument(
        "--colors", nargs=2, metavar=("HOME", "AWAY"),
        help="Home and away hex colours, e.g. --colors \"#004170\" \"#95BFE5\" "
             "(quote them in PowerShell; # without quotes is a comment)",
    )
    parser.add_argument("--instruction", default="", help="Editorial note passed to Gemini")
    parser.add_argument("--model", default=None, help="Gemini model for viz pick (defaults to GEMINI_MODEL)")
    parser.add_argument("--script-model", default=None,
                        help="Gemini model for copy (defaults to GEMINI_SCRIPT_MODEL or gemini-2.5-pro)")
    parser.add_argument("--no-gemini", action="store_true", help="Use only the deterministic script")
    parser.add_argument("--require-gemini", action="store_true", help="Fail rather than fall back")

    parser.add_argument("--voiceover-file", default="", help="Recorded narration to attach")
    parser.add_argument("--sapi-tts", action="store_true", help="Synthesise narration for a rough cut (Windows)")
    parser.add_argument("--skip-audio", action="store_true",
                        help="Fully silent mp4 (no VO/SFX/music/loudnorm). Valid when a visual-only master is wanted.")
    parser.add_argument("--sfx", dest="sfx", action="store_true", default=True,
                        help="Mix synthesized hits under the master (default on)")
    parser.add_argument("--no-sfx", dest="sfx", action="store_false", help="Skip SFX hits")
    parser.add_argument(
        "--music-bed", default="auto", metavar="SPEC",
        help="Original bed: auto (ffmpeg lavfi loop), none, or a file path. Not a trending-song rip.",
    )
    parser.add_argument(
        "--music-file", default="",
        help="Optional music path (alias for --music-bed PATH). Ducked under voice and SFX.",
    )
    parser.add_argument(
        "--loudnorm", nargs="?", const="tiktok", default="tiktok",
        choices=("tiktok", "youtube", "off"),
        help="EBU R128 when audio is mixed: tiktok -11 LUFS, youtube -14, off. Default on.",
    )
    parser.add_argument(
        "--no-loudnorm", dest="loudnorm", action="store_const", const="off",
        help="Skip loudnorm (limiter still runs on mixed audio).",
    )
    parser.add_argument("--burn-captions", dest="burn_captions", action="store_true", default=True,
                        help="Burn subtitles into the social master (default on)")
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
    parser.add_argument("--skip-video", action="store_true", help="Render frames but do not encode")

    args = parser.parse_args(argv)
    if not args.auto and not args.interactive:
        args.interactive = True
    if args.require_gemini and args.no_gemini:
        parser.error("--require-gemini and --no-gemini cannot be combined")
    return args


if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        say("\nInterrupted.")
        raise SystemExit(130)
