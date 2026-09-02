#!/usr/bin/env python
"""Turn a scraped WhoScored export into a narrated match recap.

One command covers the short-form farm cut, an optional YouTube long-form
recap, and a language × platform batch. It never scrapes — point it at an
existing ``output/<match>/`` export.

    python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto
    python video_pipeline.py --match-dir output/... --auto --format long
    python video_pipeline.py --match-dir output/... --auto --format both \\
        --batch-languages az,en,es,tr --platforms tiktok,reels,shorts \\
        --write-growth --series-id barca-26-27
    python video_pipeline.py --match-dir output/... --print-plan --format both \\
        --batch-languages az,en,es,tr
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from recap import audit as audit_mod
from recap import batch, clips, director, hooks, i18n, logos, longform, theme, timing, video, voice, viral_audit
from recap.data import describe_match_dir, list_match_dirs, load_match, safe_name, write_json


class _Help(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


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


def _job_format(args: argparse.Namespace) -> str:
    job = getattr(args, "_job", None)
    if job is not None:
        return job.fmt
    flag = getattr(args, "format", None) or longform.SHORT
    if flag == "both":
        return longform.SHORT
    return flag


def _package_out_dir(args: argparse.Namespace, match_dir: Path, fmt: str) -> Path:
    job = getattr(args, "_job", None)
    if job is not None:
        return Path(job.out_dir)
    batched = bool(getattr(args, "batch_languages", "") or "")
    language = getattr(args, "language", None) or "en"
    return batch.package_dir(
        Path(args.output_root), match_dir.name, language, fmt, batched=batched,
    )


# ---------------------------------------------------------------------------
# pipeline (one language × one format)
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> Path:
    """Render a single package. ``run_batch`` loops this for farm jobs."""
    batch.register_farm_languages()
    job = getattr(args, "_job", None)
    fmt = _job_format(args)
    series_id = str((job.series_id if job else None) or getattr(args, "series_id", "") or "")
    language = batch.activate_language(job.language if job else args.language)
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
    out_dir = _package_out_dir(args, match_dir, fmt)
    out_dir.mkdir(parents=True, exist_ok=True)
    say(f"  format: {fmt}")
    say(f"  language: {batch.language_label(language)} ({language})")
    say(f"  output: {out_dir}")
    if series_id:
        say(f"  series-id: {series_id} (growth JSON only — not burned into frames)")
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
    sources, clip_report = batch.acquire_clip_sources(
        bundle, match_dir, extra_clips,
        fetch=bool(getattr(args, "fetch_clip", True)),
        refetch=bool(getattr(args, "refetch_clip", False)),
        audit=audit,
        language=language,
    )
    batch.log_clip_report(clip_report, say)
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
    candidates_all = director.visualization_candidates(bundle, audit)
    available_n = sum(1 for item in candidates_all if item.get("available"))
    viz_count = longform.viz_count_for(fmt, getattr(args, "visualizations", None), available_n)
    target_seconds = longform.target_seconds_for(fmt, getattr(args, "target_seconds", None))
    say(f"  picking {viz_count} distinct viz (available {available_n}); script target {target_seconds:.0f}s")
    selected, candidates = director.select_visualizations(
        bundle, audit, viz_count, gemini, args.instruction
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
            selected = manual_selection(candidates, viz_count) or selected
            break
        selected, candidates = director.select_visualizations(
            bundle, audit, viz_count, gemini,
            f"{args.instruction} Choose a different angle to the previous attempt.",
        )

    # -- 3. script ---------------------------------------------------------
    stage("3. Script")
    instruction = args.instruction
    if fmt == longform.LONG:
        extra = (
            "YouTube long-form recap. Slow the punch after a hook that lands in "
            "the first three seconds. More distinct visualizations, chapter-sized "
            "beats. Do not pad with filler or repeat a card."
        )
        instruction = f"{instruction} {extra}".strip()
    already_localized = False
    viral_report: dict[str, Any] = {}
    while True:
        scene_list, already_localized = build_script(
            bundle, audit, selected, gemini, instruction, target_seconds, language,
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
                translator = director.Gemini(enabled=True, required=False)
            try:
                scene_list, method = i18n.localize_scenes(scene_list, language, translator)
            except ValueError:
                method = "en"
            if method == "gemini":
                say(f"  localized free-form copy via Gemini ({batch.language_label(language)}).")
            elif method != "en":
                say(
                    f"  localized UI + known lines offline ({batch.language_label(language)}). "
                    "Set GEMINI_API_KEY for fuller narration translation."
                )
        try:
            scene_list = i18n.scrub_english_leftovers(scene_list, language)
        except ValueError:
            pass
        scene_list = director.lock_hook_cards(scene_list, bundle, audit)
        try:
            scene_list = i18n.scrub_english_leftovers(scene_list, language)
        except ValueError:
            pass
        say(script_preview(scene_list))

    # -- 4. timing and narration ------------------------------------------
    stage("4. Timing")
    scene_list = longform.pace_scenes(scene_list, fmt)
    if fmt == longform.LONG and not longform.hook_lands_in_window(scene_list):
        say("  [warn] hook does not start inside the first 3 seconds")
    note = longform.runtime_note(
        timing.total_seconds(scene_list), [item["id"] for item in selected],
    ) if fmt == longform.LONG else ""
    if note:
        say(f"  {note}")
    narration_text = "\n\n".join(scene["narration"] for scene in scene_list)
    write_script_files(out_dir, timing.timeline(scene_list), audit)

    audio_path = voice.prepare(out_dir, narration_text, voice.VoiceConfig(
        voiceover_file=args.voiceover_file, use_sapi=args.sapi_tts, skip_audio=args.skip_audio
    ))
    audio_seconds = voice.duration(audio_path)
    if audio_seconds:
        say(f"  narration audio is {audio_seconds:.2f}s; fitting the scenes to it")
        if fmt == longform.LONG:
            scene_list = longform.scale_to_audio(scene_list, audio_seconds)
        else:
            scene_list = timing.scale_to_audio(scene_list, audio_seconds)

    scene_list = video.quantize_to_frames(scene_list, args.fps)
    scene_list = timing.timeline(scene_list)
    say(timing_table(scene_list))
    chapters = longform.chapter_markers(scene_list) if fmt == longform.LONG else []
    if chapters:
        say("  chapters:")
        for chapter in chapters:
            say(f"    {longform.format_runtime(chapter['start'])}  {chapter['title']}")

    cues = timing.build_subtitles(scene_list)
    (out_dir / "subtitles.srt").write_text(timing.render_srt(cues), encoding="utf-8")
    write_script_files(out_dir, scene_list, audit)
    if fmt == longform.LONG:
        longform.write_youtube_sidecars(
            out_dir, chapters, audit,
            series_id=series_id,
            total_seconds=timing.total_seconds(scene_list),
        )

    write_json(out_dir / "video_plan.json", {
        "match": audit["match"],
        "generation": {
            "format": fmt,
            "language": language,
            "language_name": batch.language_label(language),
            "team_kind": team_kind,
            "badge_shape": theme.badge_shape(team_kind),
            "series_id": series_id or None,
            "series_burned_in_video": False,
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
            "target_seconds": target_seconds,
            "total_seconds": timing.total_seconds(scene_list),
            "sfx": bool(getattr(args, "sfx", True)),
            "burn_captions": bool(getattr(args, "burn_captions", True)),
            "clips": {
                "mode": clip_report.get("mode"),
                "url": clip_report.get("url"),
                "title": clip_report.get("title"),
                "path": clip_report.get("path"),
                "query": clip_report.get("query"),
                "id": clip_report.get("id"),
                "beats": [
                    {k: beat.get(k) for k in ("path", "start", "duration", "label")}
                    for beat in clip_beats
                ],
            },
        },
        "chapters": chapters,
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
        sfx=bool(getattr(args, "sfx", True)),
        burn_captions=bool(getattr(args, "burn_captions", True)),
        music_file=getattr(args, "music_file", "") or None,
        srt_path=out_dir / "subtitles.srt",
    )
    if not path:
        say("  no mp4 was produced; the frames and script are still in place.")
        return out_dir

    if fmt == longform.LONG and chapters:
        muxed = longform.mux_chapters(path, chapters, timing.total_seconds(scene_list))
        if muxed:
            say("  muxed YouTube chapter markers into the mp4")

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
    script_language = language
    try:
        i18n.normalize_language(language)
    except ValueError:
        script_language = "en"
    if gemini is not None and gemini.enabled:
        editorial = gemini.choose_angle(bundle, audit, script_language)
        if editorial.get("angle"):
            angle = str(editorial["angle"])
        hook = director.build_hook(bundle, audit)
        rewrite = gemini.rephrase_hook(hook, script_language)
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
        say(f"  asking Gemini for roughly {budget} words per scene ({batch.language_label(language)})")
        overrides = gemini.write_script(
            bundle, audit, scene_list, budget, instruction, language=script_language,
            angle=angle, audit_notes=[instruction] if instruction else [],
        )
        if overrides:
            scene_list = director.apply_script(scene_list, overrides)
            already_localized = language != "en" and script_language == language

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _language_arg(value: str) -> str:
    try:
        return batch.normalize_lang(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _batch_languages_arg(value: str) -> str:
    if not (value or "").strip():
        return ""
    codes = batch.parse_languages(value)
    if not codes:
        raise argparse.ArgumentTypeError("--batch-languages needs at least one code, e.g. az,en,es,tr")
    return ",".join(codes)


def _format_arg(value: str) -> str:
    try:
        longform.formats_from(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value.strip().lower()


EPILOG = """
This command does not scrape. Feed it a finished export under output/<match>/.
Rerunning the same match-dir is idempotent: a matching run_stamp.json skips
the render unless you pass --force.

formats:
  short   Vertical farm cut (default). Hook in the first 3s, ~40s, five cards.
  long    YouTube recap, ~3–8 min. More distinct viz, chapter markers, slower
          punch. If the match cannot fill 3 minutes without repeating a card,
          the cut is shorter — never padded with silence.
  both    Render short then long.

languages:
  --language CODE           One package (default en). Codes: en, az, es, ru, tr
                            (tr is a farm code; full catalogs may come from the
                            i18n module when it merges).
  --batch-languages a,b,c   Copy variants in video_output/<lang>/<match>/.
                            Implies --auto (no prompts).

optional sibling modules (imported if present, skipped if not):
  recap.platforms / recap.export_pack
                    --platforms tiktok,reels,shorts,youtube
  recap.growth      --write-growth  (always writes growth.json; enriches if
                    the module exists). --series-id is stored there, never
                    burned into frames.

examples:
  Short-form farm cut from an existing export:
    python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto

  Graphics-only (do not hit YouTube for a highlight):
    python video_pipeline.py --match-dir output/... --auto --no-fetch-clip

  YouTube long-form with chapters:
    python video_pipeline.py --match-dir output/... --auto --format long --team club

  Four-language farm + long-form, growth JSON, no babysitting:
    python video_pipeline.py --match-dir output/... --auto --format both \\
        --batch-languages az,en,es,tr --platforms tiktok,reels,shorts \\
        --write-growth --series-id "barca-26-27"

  Dry-run the editorial plan (hook / angle / viz / duration / langs / platforms):
    python video_pipeline.py --match-dir output/... --print-plan --format both \\
        --batch-languages az,en,es,tr --platforms tiktok,reels --series-id barca-26-27
""".strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    batch.register_farm_languages()
    langs = ", ".join(batch.known_languages())
    parser = argparse.ArgumentParser(
        prog="video_pipeline.py",
        description=(
            "Build a narrated match recap from a WhoScored export. "
            "Default is a short-form farm cut. Add --format long for a YouTube "
            "recap with chapters, and --batch-languages to render copy variants "
            "without sitting through prompts."
        ),
        epilog=EPILOG,
        formatter_class=_Help,
    )

    match = parser.add_argument_group("Match and output")
    match.add_argument("--match-dir", help="Finished export directory under output/ (not a scrape)")
    match.add_argument("--scrape-output-root", default="output",
                       help="Where existing scraper exports live (this command does not scrape)")
    match.add_argument("--output-root", default="video_output",
                       help="Package root. Batch languages write video_output/<lang>/<match>/")
    match.add_argument("--force", action="store_true",
                       help="Rebuild even when run_stamp.json says this package is complete")

    editorial = parser.add_argument_group("Format, languages, farm batch")
    editorial.add_argument(
        "--format", type=_format_arg, default="short",
        help="short (farm, default), long (YouTube 3–8 min + chapters), or both",
    )
    editorial.add_argument(
        "--batch-languages", type=_batch_languages_arg, default="",
        metavar="CODES",
        help=f"Comma-separated copy variants into video_output/<lang>/. Codes: {langs}",
    )
    editorial.add_argument(
        "--language", type=_language_arg, default="en",
        help=f"Single-run copy language when --batch-languages is omitted. Codes: {langs}",
    )
    editorial.add_argument(
        "--platforms", default="", metavar="IDS",
        help="Comma-separated platform ids passed to recap.platforms / recap.export_pack "
             "if those modules exist (e.g. tiktok,reels,shorts,youtube). "
             "Warns and continues if they do not.",
    )
    editorial.add_argument(
        "--write-growth", action="store_true",
        help="Write growth.json (series_id, language, format, match). Calls recap.growth "
             "to enrich it when that module is importable.",
    )
    editorial.add_argument(
        "--series-id", default="", metavar="ID",
        help="Optional series key for growth JSON, e.g. barca-26-27 for a "
             "'Barça 26/27 recap series'. Never burned into the video.",
    )
    editorial.add_argument(
        "--print-plan", action="store_true",
        help="Dry-run: print hook, angle, viz, duration, languages, platforms, chapters. "
             "No frames, no clip fetch, no Gemini.",
    )

    pace = parser.add_argument_group("Pacing")
    pace.add_argument(
        "--visualizations", type=int, default=None,
        help="Tactical cards between hook and close. Default: 5 for short, "
             "every distinct available card for long (never repeats)",
    )
    pace.add_argument(
        "--target-seconds", type=float, default=None,
        help="Word-budget the script is written to fill. Default: 40 short, ~240 long. "
             "Long-form will still cut shorter than 3:00 rather than pad.",
    )
    pace.add_argument("--fps", type=int, default=video.DEFAULT_FPS, help="Output frame rate")

    run_mode = parser.add_argument_group("Run mode")
    run_mode.add_argument("--interactive", action="store_true",
                          help="Pick the match and approve each stage")
    run_mode.add_argument("--auto", action="store_true",
                          help="Approve every stage without prompting")

    look = parser.add_argument_group("Look")
    look.add_argument("--team", default="national",
                      choices=list(theme.TEAM_KINDS),
                      help="Badge style: national flags (rect) or club crests (circle + logos)")
    look.add_argument(
        "--colors", nargs=2, metavar=("HOME", "AWAY"),
        help="Home and away hex colours, e.g. --colors \"#004170\" \"#95BFE5\" "
             "(quote them in PowerShell; # without quotes is a comment)",
    )

    gem = parser.add_argument_group("Gemini (optional)")
    gem.add_argument("--instruction", default="", help="Editorial note passed to Gemini")
    gem.add_argument("--model", default=None, help="Gemini model for viz pick (defaults to GEMINI_MODEL)")
    gem.add_argument("--script-model", default=None,
                     help="Gemini model for copy (defaults to GEMINI_SCRIPT_MODEL or gemini-2.5-pro)")
    gem.add_argument("--no-gemini", action="store_true", help="Use only the deterministic script")
    gem.add_argument("--require-gemini", action="store_true", help="Fail rather than fall back")

    audio = parser.add_argument_group("Audio")
    audio.add_argument("--voiceover-file", default="", help="Recorded narration to attach")
    audio.add_argument("--sapi-tts", action="store_true", help="Synthesise narration for a rough cut (Windows)")
    audio.add_argument("--skip-audio", action="store_true", help="Render silent")
    audio.add_argument("--sfx", dest="sfx", action="store_true", default=True,
                       help="Mix synthesized hits under the master (default on)")
    audio.add_argument("--no-sfx", dest="sfx", action="store_false", help="Skip SFX hits")
    audio.add_argument("--music-file", default="", help="Optional music bed (ducked under VO)")
    audio.add_argument("--burn-captions", dest="burn_captions", action="store_true", default=True,
                       help="Burn subtitles into the social master (default on)")
    audio.add_argument("--no-burn-captions", dest="burn_captions", action="store_false",
                       help="Keep captions as an external SRT only")

    footage = parser.add_argument_group("Clips")
    footage.add_argument("--clip", action="append", default=[],
                         help="Path to a match clip or highlight (repeatable). Also reads match-dir/clips/")
    footage.add_argument(
        "--fetch-clip", action=argparse.BooleanOptionalAction, default=True,
        help="Search YouTube via yt-dlp for a short highlight when none is cached "
             "(default on). --no-fetch-clip skips the network; graphics-only still runs.",
    )
    footage.add_argument(
        "--refetch-clip", action="store_true",
        help="Ignore the cached highlight under match-dir/clips/ and search again",
    )

    render = parser.add_argument_group("Render")
    render.add_argument("--still", action="store_true", help="Render one image per scene instead of a video")
    render.add_argument("--still-positions", type=float, nargs="+", default=[1.0],
                        help="Animation positions to capture with --still")
    render.add_argument("--no-crossfade", action="store_true", help="Hard cuts instead of dissolves")
    render.add_argument("--skip-video", action="store_true", help="Render frames but do not encode")

    args = parser.parse_args(argv)
    if args.require_gemini and args.no_gemini:
        parser.error("--require-gemini and --no-gemini cannot be combined")
    if args.visualizations is not None and args.visualizations < 1:
        parser.error("--visualizations must be >= 1")
    if args.target_seconds is not None and args.target_seconds <= 0:
        parser.error("--target-seconds must be positive")
    batch_mode = bool(args.batch_languages) or bool(args.print_plan) or args.format == "both"
    if batch_mode:
        args.auto = True
        args.interactive = False
    elif not args.auto and not args.interactive:
        args.interactive = True
    return args


def main(argv: list[str] | None = None) -> list[batch.JobResult]:
    args = parse_args(argv)
    batch.theme_ready(args)
    return batch.run_batch(args, render_one=run, choose_match=choose_match, say=say)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nInterrupted.")
        raise SystemExit(130)
