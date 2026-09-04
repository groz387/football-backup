"""Dashboard controls the restored evidence-first pipeline."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
