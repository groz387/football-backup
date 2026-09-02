"""Platform pack dry-run: dimensions and safe zones, no full match render."""

from __future__ import annotations

import json
import unittest

from recap import export_pack, platforms, safe_zones
from video_pipeline import parse_args


class SafeZoneTests(unittest.TestCase):
    def test_tiktok_insets(self) -> None:
        zones = safe_zones.for_canvas(1080, 1920)
        self.assertEqual(zones.top_px, 180)
        self.assertEqual(zones.bottom_px, 250)
        self.assertEqual(zones.content_top, 180)
        self.assertEqual(zones.content_bottom, 1670)

    def test_captions_in_middle_third_not_ui(self) -> None:
        report = safe_zones.dry_validate(1080, 1920)
        self.assertTrue(report["ok"], report["problems"])
        self.assertTrue(report["caption_in_middle_third"])
        self.assertTrue(report["caption_in_content"])
        self.assertTrue(report["clip_smash_clears_keep_out"])
        self.assertIn("Outline=3", report["ass_style"])

    def test_clip_smash_misses_faces_and_ball(self) -> None:
        zones = safe_zones.for_canvas(1080, 1920)
        box = safe_zones.caption_box(zones, clip_smash=True)
        self.assertFalse(box.intersects(zones.clip_keep_out))
        self.assertFalse(box.intersects(zones.ui_top))
        self.assertFalse(box.intersects(zones.ui_bottom))
        self.assertTrue(zones.middle_third.intersects(box))

    def test_landscape_insets_shrink(self) -> None:
        zones = safe_zones.for_canvas(1920, 1080)
        self.assertLess(zones.top_px, 180)
        self.assertTrue(zones.content_height > 800)


class ProfileTests(unittest.TestCase):
    def test_default_platforms(self) -> None:
        ids = [p.id for p in platforms.resolve_exports(None, "all")]
        self.assertEqual(ids, ["tiktok", "shorts"])

    def test_vertical_profiles_are_1080x1920(self) -> None:
        for key in ("tiktok", "reels", "shorts", "stories"):
            profile = platforms.PROFILES[key]
            self.assertEqual(profile.size, (1080, 1920))
            self.assertEqual(profile.aspect, "9:16")
            self.assertEqual(profile.safe_top_px, 180)
            self.assertEqual(profile.safe_bottom_px, 250)
            self.assertEqual(profile.max_hook_seconds, 0.5)
            self.assertGreaterEqual(profile.duration_min, 8)
            self.assertLessEqual(profile.duration_max, 60)
            self.assertEqual(profile.loop_tail_seconds, 0.4)

    def test_youtube_long_and_square(self) -> None:
        long = platforms.PROFILES["youtube_long"]
        self.assertEqual(long.size, (1920, 1080))
        self.assertTrue(long.chapters)
        self.assertEqual(long.pacing_hooks, (180.0, 480.0))
        square = platforms.PROFILES["square"]
        self.assertEqual(square.size, (1080, 1080))

    def test_aspect_filter(self) -> None:
        ids = [p.id for p in platforms.resolve_exports("tiktok,reels,shorts,youtube_long,square", "9:16")]
        self.assertEqual(ids, ["tiktok", "reels", "shorts"])
        ids = [p.id for p in platforms.resolve_exports("tiktok,youtube_long,square", "16:9")]
        self.assertEqual(ids, ["youtube_long"])
        ids = [p.id for p in platforms.resolve_exports("tiktok,square", "1:1")]
        self.assertEqual(ids, ["square"])

    def test_comment_bait_i18n(self) -> None:
        key, text = platforms.comment_bait(language="en", hook_kind="volume_upset")
        self.assertEqual(key, "end_card_robbery")
        self.assertIn("ROBBERY", text.upper())
        _, es = platforms.comment_bait(language="es", hook_kind="volume_upset")
        self.assertNotEqual(es, text)
        _, motm = platforms.comment_bait(language="en", player="McTominay")
        self.assertIn("MOTM", motm)

    def test_hook_deadline_trims_opening_clip(self) -> None:
        scenes = platforms.apply_hook_deadline([
            {"visualization": "live_clip", "seconds": 0.8, "hook": True, "title": "smash"},
            {"visualization": "hook_claim", "seconds": 0.85, "hero_number": 12, "title": "12 SHOTS"},
        ])
        self.assertLessEqual(platforms.first_readable_at(scenes), 0.5)
        self.assertLessEqual(float(scenes[0]["seconds"]), 0.5)

    def test_spoiler_hide_detects_score(self) -> None:
        scenes = [{"visualization": "title", "title": "Scotland 0 : 1 Morocco", "seconds": 2.0}]
        self.assertTrue(platforms.opening_has_score(scenes, window=3.0))
        self.assertFalse(platforms.opening_has_score(
            [{"visualization": "hook_claim", "title": "12 SHOTS", "seconds": 0.85}],
        ))


class RestackTests(unittest.TestCase):
    def test_same_aspect_is_fill_crop_not_pad(self) -> None:
        filt = export_pack.restack_filter(1080, 1920, 1080, 1920)
        self.assertEqual(export_pack.composition_kind(1080, 1920, 1080, 1920), "fill_crop")
        self.assertIn("force_original_aspect_ratio=increase", filt)
        self.assertFalse(export_pack.is_letterbox_filter(filt))

    def test_landscape_to_portrait_uses_vstack(self) -> None:
        filt = export_pack.restack_filter(1920, 1080, 1080, 1920)
        self.assertEqual(export_pack.composition_kind(1920, 1080, 1080, 1920), "landscape_to_portrait")
        self.assertIn("vstack", filt)
        self.assertFalse(export_pack.is_letterbox_filter(filt))

    def test_portrait_to_landscape_uses_hstack(self) -> None:
        filt = export_pack.restack_filter(1080, 1920, 1920, 1080)
        self.assertEqual(export_pack.composition_kind(1080, 1920, 1920, 1080), "portrait_to_landscape")
        self.assertIn("hstack", filt)
        self.assertFalse(export_pack.is_letterbox_filter(filt))

    def test_letterbox_detector(self) -> None:
        self.assertTrue(export_pack.is_letterbox_filter(
            "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        ))

    def test_cover_number_from_audit_not_xg(self) -> None:
        audit = {
            "match": {"home": "Scotland", "away": "Morocco", "score_display": "0 : 1"},
            "data_health": {"has_vendor_xg": False, "unsupported_claims": ["vendor_xg"]},
            "team_stats": {
                "Scotland": {"shots": 6, "saves": 5, "goals": 0},
                "Morocco": {"shots": 12, "saves": 3, "goals": 1},
            },
        }
        plan = {
            "scenes": [{
                "visualization": "hook_claim",
                "hero_number": 12,
                "hero_label": "SHOTS",
            }],
        }
        cover = export_pack.pick_cover_stat(audit, plan, spoiler="hide")
        self.assertEqual(int(cover["number"]), 12)
        self.assertNotIn("xG", str(cover["label"]).upper().replace("XG", "xG") if False else str(cover["label"]))
        self.assertFalse(platforms.looks_like_score(cover["number"]))
        shown = export_pack.pick_cover_stat(audit, {"scenes": []}, spoiler="show")
        self.assertTrue(shown["number"] in {12, "0:1", "0 : 1"} or "SHOTS" in str(shown["label"]).upper() or ":" in str(shown["number"]))

    def test_hook_peak_is_claim_not_zero(self) -> None:
        ts = export_pack.hook_peak_seconds([
            {"visualization": "live_clip", "visible_start": 0.0, "on_screen": 0.4},
            {"visualization": "hook_claim", "hero_number": 12, "visible_start": 0.4, "on_screen": 0.85},
        ])
        self.assertGreaterEqual(ts, 0.4)
        self.assertLess(ts, 1.2)


class DryRunTests(unittest.TestCase):
    def test_dry_run_without_match(self) -> None:
        report = export_pack.dry_run(
            platforms_flag="tiktok,reels,shorts,square,youtube_long",
            aspect="all",
            spoiler="hide",
            language="es",
        )
        self.assertTrue(report["ok"], json.dumps(report, indent=2)[:1500])
        self.assertFalse(report["cover_is_score"])
        self.assertFalse(report["xg_invented"])
        self.assertEqual(report["end_card_key"], "end_card_robbery")
        self.assertLessEqual(report["hook_deadline_seconds"], 0.5)
        by_id = {row["id"]: row for row in report["posters"]}
        self.assertTrue(by_id["tiktok"]["ok"])
        self.assertTrue(by_id["youtube_long"]["ok"])
        self.assertTrue(by_id["square"]["ok"])
        self.assertFalse(by_id["tiktok"]["letterbox"])
        self.assertEqual(by_id["youtube_long"]["filter_kind"], "portrait_to_landscape")

    def test_ffmpeg_restack_smoke(self) -> None:
        smoke = export_pack._maybe_ffmpeg_restack_smoke()
        if smoke is None:
            self.skipTest("ffmpeg is not on PATH")
        self.assertTrue(smoke["ok"], smoke)
        self.assertEqual(smoke["size"], (1080, 1920))
        self.assertFalse(smoke["letterbox_filter"])


class CliTests(unittest.TestCase):
    def test_unique_flags(self) -> None:
        args = parse_args(["--auto", "--match-dir", "output/x"])
        self.assertEqual(args.platforms, "tiktok,shorts")
        self.assertEqual(args.aspect, "all")
        self.assertEqual(args.spoiler, "show")
        self.assertTrue(args.end_card)
        args = parse_args([
            "--auto", "--platforms", "tiktok,reels,shorts",
            "--aspect", "9:16", "--spoiler", "hide", "--no-end-card",
        ])
        self.assertEqual(args.platforms, "tiktok,reels,shorts")
        self.assertEqual(args.aspect, "9:16")
        self.assertEqual(args.spoiler, "hide")
        self.assertFalse(args.end_card)


if __name__ == "__main__":
    unittest.main()
