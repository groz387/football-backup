"""Windows 95 studio shell and operator safety gates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from recap import studio_api
from studio.app import app

ROOT = Path(__file__).resolve().parents[1]
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"


class Win95UiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        studio_api.configure(settings_path=self.tmp / "settings.json", jobs_dir=self.tmp / "jobs")
        self.client = TestClient(app)

    def tearDown(self):
        studio_api.configure(repo_root=ROOT)

    def test_shell_has_win95_skin_and_workflow_controls(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        for text in (
            "Find + scrape sources", "Generator settings", "Check ElevenLabs credits",
            "Draft scripts", "Approve script", "Regenerate VO", "Approve VO", "Produce",
        ):
            self.assertIn(text, page.text)
        css = self.client.get("/static/win95.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn("#c0c0c0", css.text)
        self.assertIn("#000080", css.text)
        self.assertIn("#008080", css.text)
        self.assertIn(".taskbar", css.text)

    def test_eleven_health_endpoint_is_safe(self):
        with mock.patch("recap.studio_api.elevenlabs_health", return_value={
            "ok": False,
            "code": "quota_exceeded",
            "message": "Credits exhausted; top up.",
        }):
            response = self.client.get("/api/elevenlabs/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "quota_exceeded")
        self.assertNotIn("sk_", response.text)

    def test_full_production_requires_script_and_voice_approval(self):
        if not SCOTLAND.exists():
            self.skipTest("sample export missing")
        job = studio_api.draft_scripts({
            "match_dir": str(SCOTLAND),
            "languages": ["en"],
            "team": "national",
            "format": "short",
            "use_gemini": False,
        })
        with self.assertRaisesRegex(ValueError, "Approve scripts"):
            studio_api.start_produce(job["id"], mode="full")
        studio_api.approve_script(job["id"], "en")
        with self.assertRaisesRegex(ValueError, "Approve voiceovers"):
            studio_api.start_produce(job["id"], mode="full")

    def test_cross_language_operator_hook_in_studio(self):
        if not SCOTLAND.exists():
            self.skipTest("sample export missing")
        job = studio_api.draft_scripts({
            "match_dir": str(SCOTLAND),
            "languages": ["az", "en", "es"],
            "hook_claim": "Oyun Qapandi",
            "bait_text": "was Yamal motm?",
            "team": "national",
            "format": "short",
            "use_gemini": False,
        })
        self.assertEqual(job["packs"]["az"]["hook_claim"], "Oyun Qapandi")
        self.assertNotEqual(job["packs"]["en"]["hook_claim"], "Oyun Qapandi")
        self.assertNotEqual(job["packs"]["es"]["hook_claim"], "Oyun Qapandi")
        self.assertEqual(
            job["packs"]["en"]["operator_copy"]["hooks"][0]["source_language"], "az",
        )


if __name__ == "__main__":
    unittest.main()
