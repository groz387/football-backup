"""Mocked ElevenLabs v3 client: rotation, no secrets in status, approve/regen."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from recap import config as cfg
from recap import elevenlabs_tts as tts


def _clear_eleven() -> dict[str, str]:
    wiped = {key: "" for key in list(os.environ) if key.startswith("ELEVENLABS")}
    wiped.update({
        "ELEVENLABS_API_KEY": "",
        "ELEVENLABS_API_KEYS": "",
        "ELEVENLABS_PROXIES": "",
        "ELEVENLABS_VOICE_ID": "",
        "ELEVENLABS_MODEL": "eleven_v3",
        "ELEVENLABS_STYLE": "robust",
        "ELEVENLABS_VOICE_NAME": "Liam Callahan - Witty Media Person",
    })
    return wiped


class _Resp:
    def __init__(self, status: int, content: bytes = b"", payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = content
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class ConfiguredTests(unittest.TestCase):
    def test_configured_false_without_keys(self) -> None:
        with mock.patch.dict(os.environ, _clear_eleven(), clear=False):
            self.assertFalse(tts.configured())
            self.assertFalse(cfg.load_eleven_config().enabled)

    def test_configured_true_with_single_key(self) -> None:
        env = _clear_eleven()
        env["ELEVENLABS_API_KEY"] = "sk_test_only"
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertTrue(tts.configured())
            self.assertEqual(cfg.load_eleven_config().model, "eleven_v3")
            self.assertEqual(cfg.load_eleven_config().style, "robust")
            self.assertIn("Callahan", cfg.load_eleven_config().voice_name)


class SynthesizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.dest = self.tmp / "voiceover.mp3"
        self.env = _clear_eleven()
        self.env["ELEVENLABS_API_KEY"] = "sk_test_alpha"
        self.env["ELEVENLABS_API_KEYS"] = "sk_test_beta"
        self.env["ELEVENLABS_PROXIES"] = "http://user:hunter2@proxy.example:8080"

    def test_posts_eleven_v3_and_redacts_status(self) -> None:
        posts = []

        def fake_http(method, url, **kwargs):
            posts.append({"method": method, "url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")})
            return _Resp(200, content=b"ID3fake-mp3")

        with mock.patch.dict(os.environ, self.env, clear=False):
            with mock.patch.object(tts, "_http_request", side_effect=fake_http):
                path = tts.synthesize(
                    "[mischievously] Barcelona Elchenin Götünə Ağac Soxdu",
                    self.dest,
                    language="az",
                    style="robust",
                    voice_id=cfg.FALLBACK_VOICE_ID,
                )
        self.assertEqual(path, self.dest)
        self.assertTrue(self.dest.exists())
        self.assertEqual(posts[0]["method"], "POST")
        self.assertIn("/text-to-speech/", posts[0]["url"])
        self.assertEqual(posts[0]["json"]["model_id"], "eleven_v3")
        self.assertGreaterEqual(posts[0]["json"]["voice_settings"]["stability"], 0.8)
        status_path = self.tmp / "voiceover" / "az" / "status.json"
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        dumped = json.dumps(payload)
        self.assertNotIn("sk_test", dumped)
        self.assertNotIn("hunter2", dumped)
        self.assertNotIn("api_key", payload)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["model"], "eleven_v3")
        self.assertEqual(payload["style"], "robust")
        if payload.get("proxy_used"):
            self.assertNotIn("hunter2", payload["proxy_used"])
            self.assertIn("***@", payload["proxy_used"])

    def test_rotates_key_after_401(self) -> None:
        keys_seen = []

        def fake_http(method, url, **kwargs):
            key = (kwargs.get("headers") or {}).get("xi-api-key")
            keys_seen.append(key)
            if len(keys_seen) == 1:
                return _Resp(401)
            return _Resp(200, content=b"ID3ok")

        with mock.patch.dict(os.environ, self.env, clear=False):
            with mock.patch.object(tts, "_http_request", side_effect=fake_http):
                tts.synthesize("go", self.dest, language="en", voice_id=cfg.FALLBACK_VOICE_ID)
        self.assertEqual(len(keys_seen), 2)
        self.assertNotEqual(keys_seen[0], keys_seen[1])

    def test_rotates_after_429(self) -> None:
        hits = []

        def fake_http(method, url, **kwargs):
            hits.append(1)
            if len(hits) == 1:
                return _Resp(429)
            return _Resp(200, content=b"ID3ok")

        with mock.patch.dict(os.environ, self.env, clear=False):
            with mock.patch.object(tts, "_http_request", side_effect=fake_http):
                with mock.patch.object(tts.time, "sleep"):
                    tts.synthesize("go", self.dest, language="en", voice_id=cfg.FALLBACK_VOICE_ID)
        self.assertGreaterEqual(len(hits), 2)

    def test_approve_and_regenerate(self) -> None:
        self.dest.write_bytes(b"ID3take1")

        def fake_http(method, url, **kwargs):
            return _Resp(200, content=b"ID3take2")

        with mock.patch.dict(os.environ, self.env, clear=False):
            approved = tts.approve_voiceover(self.tmp, "en")
            self.assertEqual(approved["status"], "approved")
            self.assertTrue(Path(approved["approved_path"]).exists())
            with mock.patch.object(tts, "_http_request", side_effect=fake_http):
                path = tts.regenerate_voiceover(
                    "again", "en", self.dest, voice_id=cfg.FALLBACK_VOICE_ID,
                )
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), b"ID3take2")
            # Studio aliases
            self.assertIs(tts.approve_voice, tts.approve_voiceover)
            self.assertIs(tts.regenerate_voice, tts.regenerate_voiceover)

    def test_public_env_has_no_secrets(self) -> None:
        with mock.patch.dict(os.environ, self.env, clear=False):
            snap = cfg.public_env()
        blob = json.dumps(snap)
        self.assertNotIn("sk_test", blob)
        self.assertNotIn("hunter2", blob)
        self.assertTrue(snap["elevenlabs"])
        self.assertEqual(snap["elevenlabs_model"], "eleven_v3")


if __name__ == "__main__":
    unittest.main()
