"""Dashboard controls the restored evidence-first pipeline."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from fastapi.testclient import TestClient

from recap import studio_api
from studio.app import app

ROOT = Path(__file__).resolve().parents[1]


def make_export(root: Path) -> Path:
    dest = root / "output" / "fresh001_Northbridge_vs_Riverside"
    dest.mkdir(parents=True)
    summary = {
        "matchId": "fresh001",
        "startDate": "2026-09-03",
        "score": "2 : 1",
        "ftScore": "2 : 1",
        "league": "Test League",
        "home": {"name": "Northbridge", "teamId": 1},
        "away": {"name": "Riverside", "teamId": 2},
    }
    (dest / "match_summary.json").write_text(
        __import__("json").dumps(summary), encoding="utf-8",
    )
    rows = []
    for index in range(120):
        side = "h" if index % 3 else "a"
        shot = index < 14
        rows.append({
            "id": index + 1,
            "minute": min(90, index),
            "second": 0,
            "type": "Shot" if shot else "Pass",
            "outcomeType": "Successful",
            "h_a": side,
            "teamId": 1 if side == "h" else 2,
            "playerName": f"Player {index % 11}",
            "isTouch": True,
            "isShot": shot,
            "isGoal": shot and index in {2, 6, 9},
            "shotOnTarget": shot and index % 2 == 0,
            "shotBlocked": shot and index % 5 == 0,
            "x": 15 + (index * 7) % 80,
            "y": 10 + (index * 11) % 80,
            "endX": 20 + (index * 9) % 75,
            "endY": 12 + (index * 13) % 75,
        })
    frame = pd.DataFrame(rows)
    frame.to_csv(dest / "all_events.csv", index=False)
    frame[frame["type"] == "Pass"].to_csv(dest / "passes.csv", index=False)
    frame[frame["isShot"]].to_csv(dest / "shots.csv", index=False)
    frame.to_csv(dest / "heatmap_touches.csv", index=False)
    return dest


class DashboardCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.export = make_export(self.tmp)
        studio_api.configure(repo_root=self.tmp)
        self.client = TestClient(app)

    def tearDown(self):
        studio_api.configure(repo_root=ROOT)

    def test_win95_dashboard_has_evidence_controls(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        for text in (
            "Words / section", "Pick 3–4 evidence graphics",
            "require contextual translation", "Find + scrape sources",
            "Render MP4s (no voice)",
            "Approve each language script",
        ):
            self.assertIn(text, page.text)

    def test_visualization_picker_is_match_specific(self):
        response = self.client.post("/api/visualizations", json={
            "match_dir": str(self.export), "count": 3,
        })
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["selected"]), 3)
        self.assertTrue(all(row["reason"] for row in payload["options"]))
        core = {
            "goal_timeline", "shot_map", "momentum", "zone_control",
            "goal_chain", "goalmouth", "pass_network", "sterile_domination",
            "touch_heatmap", "standard_stats",
        }
        self.assertTrue({row["id"] for row in payload["options"]} <= core)
        viral = {
            "stat_slam", "shot_clock_spiral", "duel_tower", "press_trap",
            "match_radar", "halftime_split",
        }
        self.assertFalse({row["id"] for row in payload["options"]} & viral)

    def test_draft_preserves_core_contract(self):
        options = studio_api.visualization_options(self.export, 3)
        job = studio_api.draft_scripts({
            "match_dir": str(self.export),
            "languages": ["en"],
            "selected_visualizations": options["selected"],
            "visualization_count": 3,
            "words_per_section": 17,
            "target_seconds": 32,
            "use_gemini": False,
        })
        pack = job["packs"]["en"]
        self.assertEqual(pack["translation_provider"], "source")
        self.assertEqual(len(pack["visualizations"]), 3)
        analysis = [
            scene for scene in pack["scenes"]
            if scene["visualization"] in pack["visualizations"]
        ]
        self.assertEqual(len(analysis), 3)
        self.assertTrue(all("word_count" in scene for scene in analysis))
        self.assertTrue(any(scene["fact_numbers"] for scene in analysis))

    def test_dashboard_advertises_groq_not_deepseek(self):
        html = (ROOT / "studio/static/index.html").read_text(encoding="utf-8")
        self.assertIn('value="groq"', html)
        self.assertNotIn("DeepSeek", html)
        caps = studio_api.capabilities()
        self.assertIn("groq_key", caps)
        self.assertTrue(caps["groq_model"])
        self.assertNotIn("deepseek_key", caps)

    def test_full_production_is_approval_gated(self):
        options = studio_api.visualization_options(self.export, 3)
        job = studio_api.draft_scripts({
            "match_dir": str(self.export),
            "languages": ["en"],
            "selected_visualizations": options["selected"],
            "visualization_count": 3,
            "use_gemini": False,
        })
        with self.assertRaisesRegex(ValueError, "Approve scripts"):
            studio_api.start_produce(job["id"], "full")
        studio_api.approve_script(job["id"], "en")
        with self.assertRaisesRegex(ValueError, "Approve voiceovers"):
            studio_api.start_produce(job["id"], "full")

    def test_burned_captions_are_off_by_default(self):
        from video_pipeline import parse_args
        args = parse_args(["--auto", "--match-dir", "output/example"])
        self.assertFalse(args.burn_captions)

    def test_operator_bait_application_is_idempotent(self):
        scenes = [{
            "id": "close", "visualization": "close",
            "narration": "Atl. Madrid won 0-2.",
            "insight": "", "comment_bait": "",
        }]
        once = studio_api._apply_operator_copy(scenes, "", "", "WHO STOLE THIS MATCH?")
        twice = studio_api._apply_operator_copy(once, "", "", "WHO STOLE THIS MATCH?")
        self.assertEqual(twice[0]["narration"].count("WHO STOLE THIS MATCH?"), 1)
        self.assertNotIn("?.", twice[0]["narration"])

    def test_plan_runs_without_voice_spend(self):
        options = studio_api.visualization_options(self.export, 3)
        job = studio_api.draft_scripts({
            "match_dir": str(self.export),
            "languages": ["en"],
            "selected_visualizations": options["selected"],
            "visualization_count": 3,
            "use_gemini": False,
        })
        studio_api.start_produce(job["id"], "plan")
        for _ in range(50):
            job = studio_api.get_job(job["id"])
            if job["production"]["status"] in {"done", "failed"}:
                break
            time.sleep(0.02)
        self.assertEqual(job["production"]["status"], "done")
        self.assertEqual(job["production"]["results"][0]["status"], "planned")

    def test_silent_render_uses_the_selected_language_pack(self):
        options = studio_api.visualization_options(self.export, 3)
        job = studio_api.draft_scripts({
            "match_dir": str(self.export),
            "languages": ["en"],
            "selected_visualizations": options["selected"],
            "visualization_count": 3,
            "use_gemini": False,
        })
        studio_api.approve_script(job["id"], "en")
        rendered = self.tmp / "rendered"

        def fake_run(_args):
            self.assertEqual(
                _args.selected_visualizations,
                ",".join(job["packs"]["en"]["visualizations"]),
            )
            rendered.mkdir(parents=True, exist_ok=True)
            (rendered / "match_video.mp4").write_bytes(b"mp4")
            return rendered

        with mock.patch("recap.studio_api.video_pipeline.run", side_effect=fake_run):
            studio_api.start_produce(job["id"], "silent")
            for _ in range(80):
                job = studio_api.get_job(job["id"])
                if job["production"]["status"] in {"done", "failed"}:
                    break
                time.sleep(0.02)
        self.assertEqual(job["production"]["status"], "done", job["production"]["error"])
        self.assertEqual(job["production"]["results"][0]["language"], "en")
        self.assertTrue(job["production"]["results"][0]["video"].endswith("match_video.mp4"))

    def test_multilingual_draft_translates_the_whole_story_once(self):
        options = studio_api.visualization_options(self.export, 3)

        class FakeGroq:
            enabled = True
            calls = 0

            def translate(self, payload):
                self.calls += 1
                rows = []
                for source in payload["scenes"]:
                    row = {"id": source["id"], "lines": list(source.get("lines") or [])}
                    for field in (
                        "kicker", "title", "subtitle", "insight",
                        "narration", "comment_bait",
                    ):
                        value = source.get(field) or ""
                        row[field] = f"ES {value}" if value else ""
                    rows.append(row)
                return {"scenes": rows}

        fake = FakeGroq()
        with mock.patch("recap.translation.GroqTranslator", return_value=fake):
            job = studio_api.draft_scripts({
                "match_dir": str(self.export),
                "languages": ["en", "es"],
                "selected_visualizations": options["selected"],
                "visualization_count": 3,
                "hook_claim": "THIS MATCH WAS ROBBED",
                "translation_provider": "groq",
                "use_gemini": False,
            })
        self.assertEqual(fake.calls, 1)
        self.assertEqual(job["packs"]["en"]["hook_claim"], "THIS MATCH WAS ROBBED")
        self.assertNotEqual(job["packs"]["es"]["hook_claim"], "THIS MATCH WAS ROBBED")
        self.assertEqual(job["packs"]["es"]["translation_provider"], "groq")
        self.assertFalse(job["packs"]["es"]["translation_warnings"])

    def test_required_context_translation_blocks_partial_offline_script(self):
        options = studio_api.visualization_options(self.export, 3)
        job = studio_api.draft_scripts({
            "match_dir": str(self.export),
            "languages": ["es"],
            "selected_visualizations": options["selected"],
            "visualization_count": 3,
            "translation_provider": "offline",
            "require_context_translation": True,
            "use_gemini": False,
        })
        self.assertEqual(job["packs"]["es"]["script_status"], "translation_blocked")
        with self.assertRaisesRegex(ValueError, "contextual translation"):
            studio_api.approve_script(job["id"], "es")
        first = job["packs"]["es"]["scenes"][0]
        studio_api.edit_script(job["id"], "es", [{
            "id": first["id"], "narration": "Revisión humana completa.",
        }])
        approved = studio_api.approve_script(job["id"], "es")
        self.assertEqual(approved["packs"]["es"]["script_status"], "approved")

    def test_lock_bookends_keeps_spice_off_analysis_cards(self):
        from recap.director import lock_bookends

        scenes = [
            {"visualization": "hook_claim", "narration": "They fucked that chance."},
            {"visualization": "shot_map", "narration": "Shit finishing: 19 shots, 1 goal."},
            {"visualization": "close", "narration": "Who stole this shit?"},
        ]
        locked = lock_bookends(scenes)
        self.assertIn("fucked", locked[0]["narration"])
        self.assertNotIn("Shit", locked[1]["narration"])
        self.assertIn("19", locked[1]["narration"])
        self.assertIn("shit", locked[2]["narration"])
        kids = lock_bookends(scenes, kids=True)
        self.assertNotIn("fucked", kids[0]["narration"])
        self.assertNotIn("shit", kids[2]["narration"].lower())


if __name__ == "__main__":
    unittest.main()
