"""Query building, ranking, cache, and skip-on-failure for recap clip fetch."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from recap import audit as audit_mod
from recap import clips, director
from recap.data import load_match
from video_pipeline import parse_args

ROOT = Path(__file__).resolve().parents[1]
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"
MEXICO = ROOT / "output" / "1953854_Mexico_vs_South_Korea"


def _bundle_audit(match_dir: Path):
    bundle = load_match(match_dir)
    return bundle, audit_mod.build_audit(bundle)


class QueryBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scotland, cls.scotland_audit = _bundle_audit(SCOTLAND)
        cls.mexico, cls.mexico_audit = _bundle_audit(MEXICO)

    def test_queries_pin_the_fixture(self):
        scot = clips.search_queries(self.scotland, self.scotland_audit)
        mex = clips.search_queries(self.mexico, self.mexico_audit)
        self.assertTrue(scot and mex)
        self.assertNotEqual(scot[0], mex[0])
        blob = " ".join(scot).lower()
        self.assertIn("scotland", blob)
        self.assertIn("morocco", blob)
        self.assertTrue("0-1" in blob or "0–1" in blob)
        self.assertIn("2026", blob)
        self.assertIn("highlights", blob)
        mex_blob = " ".join(mex).lower()
        self.assertIn("mexico", mex_blob)
        self.assertTrue("korea" in mex_blob)
        self.assertTrue("1-0" in mex_blob or "1–0" in mex_blob)
        self.assertTrue(any("saibari" in q.lower() for q in scot))

    def test_localized_query_keeps_english_primary(self):
        es = clips.search_queries(self.scotland, self.scotland_audit, language="es")
        ru = clips.search_queries(self.scotland, self.scotland_audit, language="ru")
        az = clips.search_queries(self.scotland, self.scotland_audit, language="az")
        self.assertIn("highlights", es[0].lower())
        self.assertTrue(any("resumen" in q.lower() for q in es))
        self.assertTrue(any("обзор" in q for q in ru))
        self.assertTrue(any("icmal" in q.lower() for q in az))

    def test_search_query_compat_wrapper(self):
        q = clips.search_query(self.scotland, self.scotland_audit)
        self.assertIn("Scotland", q)
        self.assertIn("Morocco", q)


class RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.audit = _bundle_audit(SCOTLAND)

    def test_prefers_highlights_over_presser_and_full_match(self):
        highlight = {
            "id": "hl",
            "title": "Scotland vs Morocco 0-1 FIFA World Cup 2026 Highlights",
            "duration": 412, "uploader": "FIFA", "channel": "FIFA", "live_status": "not_live",
        }
        presser = {
            "id": "pr", "title": "Scotland vs Morocco press conference",
            "duration": 600, "uploader": "TalkSPORT", "live_status": "not_live",
        }
        full = {
            "id": "fm", "title": "Scotland vs Morocco FULL MATCH 2026",
            "duration": 9000, "uploader": "Streams", "live_status": "not_live",
        }
        wrong = {
            "id": "br", "title": "Brazil vs Argentina World Cup 2026 Highlights",
            "duration": 480, "uploader": "FIFA", "live_status": "not_live",
        }
        other_wc = {
            "id": "mx", "title": "Mexico vs South Korea 1-0 FIFA World Cup 2026 Highlights",
            "duration": 390, "uploader": "FIFA", "live_status": "not_live",
        }
        ranked = clips.rank_candidates(
            [presser, full, wrong, other_wc, highlight], self.bundle, self.audit
        )
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["id"], "hl")
        ids = {row["id"] for row in ranked}
        self.assertTrue(ids.isdisjoint({"pr", "br", "mx", "fm"}))

    def test_reject_wrong_fixture_and_live(self):
        self.assertIsNotNone(clips.reject_reason(
            {"title": "Mexico vs South Korea Highlights", "duration": 300}, self.bundle))
        self.assertIsNotNone(clips.reject_reason(
            {"title": "Scotland vs Morocco Highlights", "duration": 300, "live_status": "is_live"},
            self.bundle))
        self.assertIsNone(clips.reject_reason(
            {"title": "Scotland vs Morocco Highlights", "duration": 300}, self.bundle))

    def test_section_flags_cap_long_and_keep_short(self):
        self.assertEqual(clips._section_flags({"duration": 400}, self.audit), [])
        flags = clips._section_flags({"duration": None}, self.audit)
        self.assertIn("--download-sections", flags)
        specs = [i for i in clips._section_flags({"duration": 95 * 60}, self.audit) if i.startswith("*")]
        self.assertTrue(specs)
        self.assertNotEqual(specs[0], "*0-720")


class FetchResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.audit = _bundle_audit(SCOTLAND)

    def test_search_failure_returns_none(self):
        dest = Path(tempfile.mkdtemp(prefix="clips_fail_"))

        def boom(_queries):
            raise RuntimeError("blocked domain")

        self.assertIsNone(clips.fetch_highlight(
            self.bundle, dest, audit=self.audit, search_fn=boom, refetch=True))

    def test_empty_results_continue(self):
        dest = Path(tempfile.mkdtemp(prefix="clips_empty_"))
        self.assertIsNone(clips.fetch_highlight(
            self.bundle, dest, audit=self.audit, search_fn=lambda q: [], refetch=True))

    def test_download_failure_falls_through(self):
        dest = Path(tempfile.mkdtemp(prefix="clips_dl_"))
        candidate = {
            "id": "abc", "title": "Scotland vs Morocco 0-1 FIFA World Cup 2026 Highlights",
            "duration": 400, "uploader": "FIFA", "url": "https://www.youtube.com/watch?v=abc",
            "live_status": "not_live",
        }
        self.assertIsNone(clips.fetch_highlight(
            self.bundle, dest, audit=self.audit, refetch=True,
            search_fn=lambda q: [candidate], download_fn=lambda c, d: None))

    def test_cache_hit_skips_search(self):
        dest = Path(tempfile.mkdtemp(prefix="clips_cache_"))
        video = dest / "yt_cached.mp4"
        video.write_bytes(b"x" * 2048)
        (dest / "fetch.json").write_text(json.dumps({
            "id": "cached", "url": "https://www.youtube.com/watch?v=cached",
            "title": "Scotland vs Morocco Highlights (cached)",
            "path": str(video), "filename": video.name,
        }), encoding="utf-8")
        called = {"n": 0}

        def search(_q):
            called["n"] += 1
            return []

        path = clips.fetch_highlight(
            self.bundle, dest, audit=self.audit, search_fn=search, refetch=False)
        self.assertEqual(path, video)
        self.assertEqual(called["n"], 0)

    def test_acquire_skips_network_when_disabled(self):
        dest_match = Path(tempfile.mkdtemp(prefix="clips_nofetch_"))
        (dest_match / "clips").mkdir()
        sources, report = clips.acquire_sources(
            self.bundle, dest_match, fetch=False, audit=self.audit,
            search_fn=lambda q: (_ for _ in ()).throw(RuntimeError("no")),
        )
        self.assertEqual(sources, [])
        self.assertEqual(report["mode"], "skipped")

    def test_acquire_records_fetch_metadata(self):
        dest_match = Path(tempfile.mkdtemp(prefix="clips_acq_"))
        src = Path(tempfile.mkdtemp()) / "yt_ok.mp4"
        src.write_bytes(b"x" * 4096)

        def download(candidate, dest_dir):
            target = Path(dest_dir) / "yt_ok.mp4"
            shutil.copyfile(src, target)
            return target

        candidate = {
            "id": "ok", "title": "Scotland vs Morocco 0-1 FIFA World Cup 2026 Highlights",
            "duration": 350, "uploader": "FIFA",
            "url": "https://www.youtube.com/watch?v=ok123", "live_status": "not_live",
            "query": "Scotland vs Morocco highlights",
        }
        sources, report = clips.acquire_sources(
            self.bundle, dest_match, fetch=True, refetch=True, audit=self.audit,
            search_fn=lambda q: [candidate], download_fn=download,
        )
        self.assertTrue(sources)
        self.assertEqual(report["mode"], "fetched")
        self.assertEqual(report["url"], candidate["url"])
        payload = json.loads((dest_match / "clips" / "fetch.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["url"], candidate["url"])


class BeatsAndStoryboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.audit = _bundle_audit(SCOTLAND)

    def test_plan_beats_samples_highlight_and_goals_on_tape(self):
        original = clips.duration_seconds

        def fake_duration(path: Path):
            name = Path(path).name
            if "tape" in name:
                return 95 * 60
            if "hl" in name:
                return 400.0
            return original(path)

        clips.duration_seconds = fake_duration  # type: ignore[method-assign]
        try:
            hl = clips.plan_beats(self.bundle, self.audit, [Path("/tmp/hl_fake.mp4")])
            self.assertTrue(1 <= len(hl) <= 2)
            self.assertTrue(all(0.35 <= b["duration"] <= 0.8 for b in hl))
            tape = clips.plan_beats(self.bundle, self.audit, [Path("/tmp/tape_fake.mp4")])
            self.assertTrue(tape)
            self.assertLess(tape[0]["start"], 90)
        finally:
            clips.duration_seconds = original  # type: ignore[method-assign]

    def test_single_beat_sits_between_claim_and_punch(self):
        selected, _ = director.select_visualizations(self.bundle, self.audit, 2, None, "")
        scenes = director.build_storyboard(
            self.bundle, self.audit, selected,
            clip_beats=[{"path": "/tmp/hl.mp4", "start": 12.0, "duration": 0.5, "label": "smash"}],
        )
        ids = [s["id"] for s in scenes]
        self.assertLess(ids.index("hook_claim"), ids.index("live_clip_1"))
        self.assertLess(ids.index("live_clip_1"), ids.index("hook_punch"))

    def test_two_beats_open_then_smash(self):
        selected, _ = director.select_visualizations(self.bundle, self.audit, 2, None, "")
        scenes = director.build_storyboard(
            self.bundle, self.audit, selected,
            clip_beats=[
                {"path": "/tmp/hl.mp4", "start": 5.0, "duration": 0.42, "label": "open"},
                {"path": "/tmp/hl.mp4", "start": 20.0, "duration": 0.42, "label": "smash"},
            ],
        )
        ids = [s["id"] for s in scenes]
        self.assertEqual(ids[:4], ["live_clip_1", "hook_claim", "live_clip_2", "hook_punch"])


class CliTests(unittest.TestCase):
    def test_fetch_is_on_by_default(self):
        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertTrue(args.fetch_clip)
        self.assertFalse(args.refetch_clip)

    def test_no_fetch_clip_disables(self):
        args = parse_args(["--auto", "--match-dir", "output/x", "--no-fetch-clip"])
        self.assertFalse(args.fetch_clip)

    def test_refetch_flag(self):
        args = parse_args(["--auto", "--match-dir", "output/x", "--refetch-clip"])
        self.assertTrue(args.refetch_clip and args.fetch_clip)


class ExtractTests(unittest.TestCase):
    def test_plan_and_still_from_synthetic_mp4(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg not installed")
        dest = Path(tempfile.mkdtemp(prefix="clips_syn_"))
        video = dest / "highlight.mp4"
        result = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=red:s=640x360:d=3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "3", str(video)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle, audit = _bundle_audit(SCOTLAND)
        beats = clips.plan_beats(bundle, audit, [video])
        self.assertTrue(beats)
        still = dest / "still.png"
        self.assertTrue(clips.extract_still(beats[0], still))
        self.assertGreater(still.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
