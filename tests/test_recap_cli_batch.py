"""CLI batch / long-form planning — no render, no scrape."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from recap import batch, longform, timing
from recap.batch import run_batch
from video_pipeline import parse_args


ROOT = Path(__file__).resolve().parents[1]
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"


class ParseArgsTests(unittest.TestCase):
    def test_help_covers_farm_flags(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            with mock.patch("sys.stdout", buf):
                parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        text = buf.getvalue()
        for needle in (
            "--format", "--batch-languages", "--print-plan", "--platforms",
            "--write-growth", "--series-id", "--no-fetch-clip", "--auto",
            "--fps", "--team", "--clip", "--language", "--colors", "--skip-audio",
            "--languages", "--dub-languages", "--skip-language",
            "--eleven-style", "--eleven-voice", "--eleven-model",
            "--approve-script", "--approve-voice", "--no-elevenlabs", "--kids",
        ):
            self.assertIn(needle, text)
        self.assertIn("livescore", text.lower())
        self.assertIn("video_output/<lang>", text)

    def test_languages_and_eleven_flags_parse(self):
        args = parse_args([
            "--match-dir", "output/x", "--auto",
            "--languages", "az,en,es",
            "--dub-languages", "ru",
            "--skip-language", "es",
            "--eleven-style", "normal",
            "--eleven-voice", "TX3LPaxmHKxFdv7VOQHJ",
            "--eleven-model", "eleven_v3",
            "--approve-script", "--approve-voice",
        ])
        self.assertEqual(args.languages, "az,en,es")
        self.assertEqual(args.dub_languages, "ru")
        self.assertEqual(args.skip_language, "es")
        self.assertEqual(args.eleven_style, "normal")
        self.assertEqual(args.eleven_voice, "TX3LPaxmHKxFdv7VOQHJ")
        self.assertEqual(args.eleven_model, "eleven_v3")
        self.assertTrue(args.approve_script)
        self.assertTrue(args.approve_voice)
        from recap.farm import resolve_languages
        self.assertEqual(resolve_languages(args), ["az", "en"])

    def test_defaults_are_short_auto_fetch_on(self):
        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertEqual(args.format, "short")
        self.assertTrue(args.fetch_clip)
        self.assertFalse(args.refetch_clip)
        self.assertEqual(args.language, "en")
        self.assertEqual(args.batch_languages, "")
        self.assertTrue(args.write_growth)
        self.assertEqual(args.series_id, "")
        self.assertTrue(args.auto)
        self.assertEqual(args.fps, 24)
        self.assertEqual(args.team, "national")
        self.assertTrue(args.skip_audio is False)

    def test_existing_flags_still_parse(self):
        args = parse_args([
            "--match-dir", "output/x", "--auto", "--fps", "30",
            "--team", "club", "--clip", "a.mp4", "--skip-audio",
            "--colors", "#004170", "#95BFE5", "--no-fetch-clip",
            "--language", "es",
        ])
        self.assertEqual(args.fps, 30)
        self.assertEqual(args.team, "club")
        self.assertEqual(args.clip, ["a.mp4"])
        self.assertTrue(args.skip_audio)
        self.assertEqual(args.colors, ["#004170", "#95BFE5"])
        self.assertFalse(args.fetch_clip)
        self.assertEqual(args.language, "es")

    def test_no_fetch_and_refetch(self):
        args = parse_args(["--auto", "--match-dir", "output/x", "--no-fetch-clip"])
        self.assertFalse(args.fetch_clip)
        args = parse_args(["--auto", "--match-dir", "output/x", "--refetch-clip"])
        self.assertTrue(args.refetch_clip)
        self.assertTrue(args.fetch_clip)

    def test_format_both_and_batch_languages_imply_auto(self):
        args = parse_args([
            "--match-dir", "output/x",
            "--format", "both",
            "--batch-languages", "az, en, es, tr",
        ])
        self.assertTrue(args.auto)
        self.assertFalse(args.interactive)
        self.assertEqual(args.format, "both")
        self.assertEqual(args.batch_languages, "az,en,es,tr")

    def test_print_plan_implies_auto(self):
        args = parse_args(["--match-dir", "output/x", "--print-plan"])
        self.assertTrue(args.print_plan)
        self.assertTrue(args.auto)

    def test_turkish_is_a_farm_language(self):
        args = parse_args(["--auto", "--match-dir", "output/x", "--language", "tr"])
        self.assertEqual(args.language, "tr")

    def test_reject_unknown_language(self):
        with self.assertRaises(SystemExit):
            parse_args(["--auto", "--match-dir", "output/x", "--language", "xx"])


class BatchLayoutTests(unittest.TestCase):
    def test_package_dir_compat_and_batch(self):
        root = Path("video_output")
        short = batch.package_dir(root, "1953861_Scotland_vs_Morocco", "en", "short", batched=False)
        self.assertEqual(short, root / "1953861_Scotland_vs_Morocco")
        long_one = batch.package_dir(root, "1953861_Scotland_vs_Morocco", "en", "long", batched=False)
        self.assertEqual(long_one, root / "1953861_Scotland_vs_Morocco" / "long")
        batched = batch.package_dir(root, "1953861_Scotland_vs_Morocco", "az", "short", batched=True)
        self.assertEqual(batched, root / "az" / "1953861_Scotland_vs_Morocco")
        batched_long = batch.package_dir(root, "1953861_Scotland_vs_Morocco", "tr", "long", batched=True)
        self.assertEqual(batched_long, root / "tr" / "1953861_Scotland_vs_Morocco" / "long")

    def test_expand_jobs_format_both_four_langs(self):
        args = parse_args([
            "--match-dir", str(SCOTLAND),
            "--format", "both",
            "--batch-languages", "az,en,es,tr",
            "--platforms", "tiktok,reels",
            "--series-id", "barca-26-27",
            "--write-growth",
        ])
        jobs = batch.expand_jobs(args, SCOTLAND)
        self.assertEqual(len(jobs), 8)
        langs = [j.language for j in jobs]
        self.assertEqual(langs.count("tr"), 2)
        self.assertTrue(all(j.series_id == "barca-26-27" for j in jobs))
        self.assertEqual(jobs[0].platforms, ["tiktok", "reels"])
        az_short = next(j for j in jobs if j.language == "az" and j.fmt == "short")
        self.assertEqual(az_short.out_dir, Path("video_output") / "az" / SCOTLAND.name)

    def test_run_batch_is_exported(self):
        self.assertTrue(callable(run_batch))


class LongformTests(unittest.TestCase):
    def _scenes(self):
        return [
            {"id": "hook_claim", "visualization": "hook_claim", "hook": True, "cut": "hard",
             "seconds": 0.85, "narration": "They had the ball.", "title": "THEY HAD THE BALL"},
            {"id": "hook_punch", "visualization": "hook_punch", "hook": True, "cut": "hard",
             "seconds": 0.7, "narration": "They took the points.", "title": "THEY TOOK THE POINTS"},
            {"id": "shot_map", "visualization": "shot_map", "cut": "wipe",
             "narration": "Six shots. None of them counted.", "title": "SHOT MAP"},
            {"id": "close", "visualization": "close", "cut": "hard",
             "narration": "Full time.", "title": "FULL TIME"},
        ]

    def test_hook_inside_three_seconds_and_no_padding(self):
        paced = longform.pace_scenes(self._scenes(), "long")
        self.assertTrue(longform.hook_lands_in_window(paced, 3.0))
        total = timing.total_seconds(timing.timeline(paced))
        self.assertLess(total, longform.LONG_TARGET_MIN)
        viz = [s["visualization"] for s in paced]
        self.assertEqual(len(viz), len(set(viz)))
        self.assertNotIn("pad", viz)
        self.assertNotIn("micro_hook", viz)
        punch = next(s for s in paced if s["visualization"] == "hook_punch")
        self.assertGreaterEqual(punch["on_screen"], 0.65)

    def test_chapters_start_at_zero(self):
        paced = longform.pace_scenes(self._scenes(), "long")
        chapters = longform.chapter_markers(paced)
        self.assertEqual(chapters[0]["start"], 0.0)
        self.assertEqual(chapters[0]["title"], "Hook")
        text = longform.youtube_chapters_text(chapters)
        self.assertTrue(text.startswith("0:00 Hook"))

    def test_series_id_is_sidecar_only(self):
        paced = longform.pace_scenes(self._scenes(), "long")
        chapters = longform.chapter_markers(paced)
        dest = Path(tempfile.mkdtemp())
        longform.write_youtube_sidecars(
            dest, chapters, {"match": {"home": "Barça", "away": "Rayo", "score_display": "1-0"}},
            series_id="barca-26-27", total_seconds=12.0,
        )
        desc = (dest / "youtube_description.md").read_text(encoding="utf-8")
        self.assertIn("barca-26-27", desc)
        self.assertIn("0:00 Hook", desc)
        for scene in paced:
            blob = json.dumps(scene)
            self.assertNotIn("barca-26-27", blob)

    def test_more_viz_on_long_than_short(self):
        self.assertEqual(longform.viz_count_for("short", None, 12), 5)
        self.assertEqual(longform.viz_count_for("long", None, 12), 12)
        self.assertEqual(longform.viz_count_for("long", 3, 12), 3)


class PrintPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SCOTLAND / "match_summary.json").exists():
            raise unittest.SkipTest("Scotland export missing")

    def test_print_plan_shows_hook_angle_viz_langs_platforms(self):
        captured: list[str] = []
        args = parse_args([
            "--match-dir", str(SCOTLAND),
            "--print-plan",
            "--format", "both",
            "--batch-languages", "az,en,es,tr",
            "--platforms", "tiktok,reels",
            "--series-id", "barca-26-27",
            "--no-fetch-clip",
            "--no-gemini",
        ])
        results = run_batch(
            args, render_one=lambda _a: Path("/tmp"), choose_match=lambda *_: SCOTLAND,
            say=captured.append,
        )
        self.assertEqual(len(results), 8)
        self.assertTrue(all(r.status == "planned" for r in results))
        text = "\n".join(captured)
        self.assertIn("PLAN", text)
        self.assertIn("hook", text.lower())
        self.assertIn("angle", text.lower())
        self.assertIn("az", text)
        self.assertIn("tr", text)
        self.assertIn("tiktok", text)
        self.assertIn("barca-26-27", text)
        self.assertIn("chapters", text.lower())
        # Dry-run must not create a video package.
        self.assertFalse((Path("video_output") / "az" / SCOTLAND.name / "match_video.mp4").exists())

    def test_idempotent_skip(self):
        dest = Path(tempfile.mkdtemp()) / "pkg"
        dest.mkdir()
        (dest / "match_video.mp4").write_bytes(b"x")
        args = parse_args(["--auto", "--match-dir", str(SCOTLAND), "--no-fetch-clip"])
        job = batch.Job(match_dir=SCOTLAND, language="en", fmt="short", out_dir=dest)
        stamp = batch.stamp_for(args, job)
        batch.write_stamp(dest, stamp)
        self.assertTrue(batch.package_complete(dest, stamp, args))
        args.force = True
        # force is checked by run_batch, not package_complete
        self.assertTrue(batch.package_complete(dest, stamp, args))


class OptionalSiblingTests(unittest.TestCase):
    def test_platforms_missing_is_a_skip_not_a_crash(self):
        dest = Path(tempfile.mkdtemp())
        with mock.patch.dict("sys.modules", {"recap.platforms": None, "recap.export_pack": None}):
            with mock.patch("recap.batch.optional_module", return_value=None):
                report = batch.try_apply_platforms(
                    dest, ["tiktok"], fmt="short", language="en", series_id="s",
                )
        self.assertEqual(report["status"], "skipped")
        self.assertIn("tiktok", report.get("requested") or ["tiktok"])

    def test_growth_writes_json_without_sibling(self):
        dest = Path(tempfile.mkdtemp())
        job = batch.Job(
            match_dir=SCOTLAND, language="es", fmt="short", out_dir=dest,
            series_id="barca-26-27", write_growth=True,
        )
        with mock.patch("recap.batch.optional_module", return_value=None):
            report = batch.try_write_growth(
                job, audit={"match": {"home": "Barça"}}, plan={"hook": "x", "angle": "upset"},
            )
        self.assertEqual(report["status"], "written")
        payload = json.loads((dest / "growth.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["series_id"], "barca-26-27")
        self.assertFalse(payload["burned_in_video"])
        self.assertEqual(payload["language"], "es")

    def test_help_text_mentions_the_farm(self):
        from video_pipeline import EPILOG
        self.assertIn("--print-plan", EPILOG)
        self.assertIn("--batch-languages", EPILOG)
        self.assertIn("--format long", EPILOG)
        self.assertIn("livescore", EPILOG.lower())


class HelpSmokeTests(unittest.TestCase):
    def test_long_print_plan_parses(self):
        ns = parse_args(["--auto", "--match-dir", "output/x", "--print-plan", "--format", "long"])
        self.assertEqual(ns.format, "long")
        self.assertTrue(ns.print_plan)


if __name__ == "__main__":
    unittest.main()
