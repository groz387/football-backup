"""Local operator console — studio web app + recap.studio_api."""

from __future__ import annotations

import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from recap import studio_api
from studio.app import app, parse_launch_args


ROOT = Path(__file__).resolve().parents[1]
SCOTLAND = ROOT / "output" / "1953861_Scotland_vs_Morocco"
BARCA = ROOT / "output" / "1993920_Barcelona_vs_Rayo_Vallecano"


class StudioApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        studio_api.configure(settings_path=self.tmp / "settings.json", jobs_dir=self.tmp / "jobs")

    def tearDown(self):
        studio_api.configure(repo_root=ROOT)

    def test_languages_include_farm_codes(self):
        codes = [row["code"] for row in studio_api.list_languages()]
        for code in ("az", "en", "es", "ru"):
            self.assertIn(code, codes)
        az = next(row for row in studio_api.list_languages() if row["code"] == "az")
        self.assertTrue(az["native"])

    def test_list_matches_finds_exports(self):
        names = [row["name"] for row in studio_api.list_matches()]
        self.assertTrue(any("Scotland" in name for name in names))
        self.assertTrue(any("Barcelona" in name for name in names))

    def test_resolve_whoscored_url_to_existing_export(self):
        url = "https://www.whoscored.com/matches/1993920/live/spain-laliga-2026-2027-barcelona-rayo-vallecano"
        result = studio_api.resolve_source(url=url)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["match_id"], "1993920")
        self.assertIn("Barcelona", result["match"]["home"])
        self.assertFalse(result["needs_scrape"])

    def test_resolve_unknown_url_offers_scrape(self):
        result = studio_api.resolve_source(url="https://www.livescore.com/en/football/match/1821295")
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_scrape"])
        self.assertTrue(result["can_scrape"])
        self.assertEqual(result["match_id"], "1821295")
        self.assertIn("1821295", result["scrape_url"])
        self.assertIn("whoscored.com", result["scrape_url"])
        self.assertNotIn("TODO", result["stub"])
        self.assertIn("Scrape", result["stub"])

    def test_resolve_bare_id_offers_scrape(self):
        result = studio_api.resolve_source(url="1821295")
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_scrape"])
        self.assertTrue(result["can_scrape"])
        self.assertEqual(result["scrape_url"], "https://www.whoscored.com/matches/1821295/live")

    def test_scrape_mocked_creates_job_and_selects_export(self):
        def fake_run(**kwargs):
            self.assertIn("1821295", kwargs.get("url") or "")
            return {
                "ok": True,
                "match_dir": str(SCOTLAND),
                "match_id": "1953861",
                "source": "whoscored",
                "kind": "match_id",
            }

        with mock.patch("recap.studio_api.scrape_mod.run_scrape", fake_run):
            job = studio_api.start_scrape(url="1821295", wait=12)
            for _ in range(40):
                job = studio_api.get_scrape_job(job["id"])
                if job["status"] in ("done", "failed"):
                    break
                time.sleep(0.05)
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertTrue(job["ok"])
        self.assertIn("Scotland", job["match"]["home"])

    def test_resolve_match_dir(self):
        result = studio_api.resolve_source(match_dir=str(SCOTLAND))
        self.assertTrue(result["ok"], result)
        self.assertIn("Scotland", result["match"]["home"])

    def test_auto_color_preview_barcelona(self):
        from recap import theme
        theme.set_team_kind("club")
        theme.set_team_colors(None, None)
        design = theme.match_design("Barcelona", "Rayo Vallecano")
        preview = studio_api.preview_colors(BARCA, team="club")
        self.assertTrue(preview["auto"])
        self.assertEqual(preview["home"]["name"], "Barcelona")
        self.assertTrue(preview["home"]["primary"].startswith("#"))
        self.assertTrue(preview["away"]["primary"].startswith("#"))
        self.assertEqual(preview["home"]["primary"].lower(), design["home"]["primary"].lower())
        self.assertEqual(preview["away"]["primary"].lower(), design["away"]["primary"].lower())

    def test_color_override(self):
        preview = studio_api.preview_colors(BARCA, team="club", colors=["#9e0041", "#c0ae33"])
        self.assertFalse(preview["auto"])
        self.assertEqual(preview["home"]["primary"].lower(), "#9e0041")

    def test_settings_persist(self):
        saved = studio_api.save_settings({"languages": ["az", "es"], "bait_text": "MOTM?"})
        self.assertEqual(saved["languages"], ["az", "es"])
        self.assertEqual(studio_api.load_settings()["bait_text"], "MOTM?")
        self.assertTrue((self.tmp / "settings.json").exists())

    def test_capabilities_mark_elevenlabs_stub_without_keys(self):
        caps = studio_api.capabilities()
        self.assertTrue(caps["wired"]["video_pipeline"])
        self.assertEqual(caps["stubbed"]["elevenlabs_tts"], not caps.get("elevenlabs_configured"))
        if not caps.get("elevenlabs_configured"):
            self.assertIn("stub", caps["notes"]["elevenlabs_tts"].lower())

    def test_draft_edit_approve_and_stub_voice(self):
        if not (SCOTLAND / "match_summary.json").exists():
            self.skipTest("Scotland export missing")
        job = studio_api.draft_scripts({
            "match_dir": str(SCOTLAND),
            "languages": ["en"],
            "team": "national",
            "format": "short",
            "use_gemini": False,
        })
        self.assertIn("en", job["packs"])
        pack = job["packs"]["en"]
        self.assertGreaterEqual(len(pack["scenes"]), 3)
        self.assertTrue(any(s["visualization"] == "hook_claim" for s in pack["scenes"]))
        scene = pack["scenes"][0]
        job = studio_api.edit_script(job["id"], "en", [{
            "id": scene["id"], "title": "OPERATOR TITLE", "narration": "operator line.",
        }])
        self.assertEqual(job["packs"]["en"]["script_status"], "edited")
        self.assertEqual(job["packs"]["en"]["scenes"][0]["title"], "OPERATOR TITLE")
        job = studio_api.approve_script(job["id"], "en")
        self.assertEqual(job["packs"]["en"]["script_status"], "approved")
        job = studio_api.regenerate_voice(job["id"], "en")
        voice = job["packs"]["en"]
        self.assertTrue(voice["voice_stub"])
        self.assertTrue(Path(voice["voice_path"]).exists())
        job = studio_api.approve_voice(job["id"], "en")
        self.assertEqual(job["packs"]["en"]["voice_status"], "approved")

    def test_produce_plan_uses_cli_batch(self):
        if not (SCOTLAND / "match_summary.json").exists():
            self.skipTest("Scotland export missing")
        job = studio_api.draft_scripts({
            "match_dir": str(SCOTLAND),
            "languages": ["en"],
            "team": "national",
            "format": "short",
            "use_gemini": False,
        })
        studio_api.approve_script(job["id"], "en")
        studio_api.start_produce(job["id"], mode="plan")
        for _ in range(80):
            job = studio_api.get_job(job["id"])
            if job["production"]["status"] in ("done", "failed"):
                break
            time.sleep(0.25)
        self.assertEqual(job["production"]["status"], "done", job["production"].get("error"))
        self.assertEqual(job["production"]["results"][0]["status"], "planned")


class StudioHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        studio_api.configure(settings_path=self.tmp / "settings.json", jobs_dir=self.tmp / "jobs")
        self.client = TestClient(app)

    def tearDown(self):
        studio_api.configure(repo_root=ROOT)

    def test_health_and_index(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Recap Studio", page.text)
        self.assertIn("Scrape WhoScored", page.text)
        css = self.client.get("/static/styles.css")
        self.assertEqual(css.status_code, 200)

    def test_bootstrap_and_resolve_http(self):
        boot = self.client.get("/api/bootstrap")
        self.assertEqual(boot.status_code, 200)
        body = boot.json()
        self.assertIn("az", [row["code"] for row in body["languages"]])
        resolved = self.client.post("/api/resolve", json={
            "url": "https://www.whoscored.com/matches/1953861/live/international",
        })
        self.assertEqual(resolved.status_code, 200)
        self.assertTrue(resolved.json()["ok"])
        colors = self.client.post("/api/preview-colors", json={
            "match_dir": str(SCOTLAND),
            "team": "national",
        })
        self.assertEqual(colors.status_code, 200)
        self.assertIn("primary", colors.json()["home"])

    def test_settings_http_roundtrip(self):
        posted = self.client.post("/api/settings", json={"languages": ["az", "ru"], "format": "long"})
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["languages"], ["az", "ru"])
        got = self.client.get("/api/settings")
        self.assertEqual(got.json()["format"], "long")

    def test_launch_args(self):
        args = parse_launch_args(["--host", "127.0.0.1", "--port", "8765"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)

    def test_help_mentions_localhost(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            with mock.patch("sys.stdout", buf):
                parse_launch_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("localhost", buf.getvalue().lower())

    def test_scrape_http_mocked(self):
        def fake_run(**kwargs):
            return {
                "ok": True,
                "match_dir": str(SCOTLAND),
                "match_id": "1953861",
                "source": "whoscored",
                "kind": "whoscored",
            }

        with mock.patch("recap.studio_api.scrape_mod.run_scrape", fake_run):
            posted = self.client.post("/api/scrape", json={"url": "1821295", "wait": 12})
            self.assertEqual(posted.status_code, 200, posted.text)
            job_id = posted.json()["id"]
            body = None
            for _ in range(40):
                body = self.client.get(f"/api/scrape/{job_id}").json()
                if body["status"] in ("done", "failed"):
                    break
                time.sleep(0.05)
        self.assertEqual(body["status"], "done", body.get("error"))
        self.assertTrue(body["ok"])

    def test_resolve_missing_id_http_offers_scrape(self):
        resolved = self.client.post("/api/resolve", json={"url": "1821295"})
        self.assertEqual(resolved.status_code, 200)
        body = resolved.json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["needs_scrape"])
        self.assertTrue(body["can_scrape"])


if __name__ == "__main__":
    unittest.main()
