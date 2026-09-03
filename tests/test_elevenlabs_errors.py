"""Actionable ElevenLabs failures and safe subscription preflight."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from recap import config as cfg
from recap import elevenlabs_tts as tts


class Resp:
    def __init__(self, status: int, payload=None, content: bytes = b""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def conf(keys=("sk_test_one",), model="eleven_v3"):
    return cfg.ElevenConfig(
        slots=[cfg.ElevenSlot(key, index=i) for i, key in enumerate(keys)],
        voice_id=cfg.FALLBACK_VOICE_ID,
        voice_name=cfg.DEFAULT_VOICE_NAME,
        model=model,
        style="robust",
    )


class ErrorTests(unittest.TestCase):
    def setUp(self):
        tts.reset_caches()
        self.dest = Path(tempfile.mkdtemp()) / "voice.mp3"

    def test_402_quota_message_and_payload(self):
        original = tts._http_request
        tts._http_request = lambda *a, **k: Resp(402, {"detail": {"status": "quota_exceeded"}})
        try:
            with self.assertRaises(tts.ElevenLabsError) as raised:
                tts.synthesize(
                    "hello", self.dest, conf=conf(), model="eleven_v3",
                    voice_id=cfg.FALLBACK_VOICE_ID,
                )
        finally:
            tts._http_request = original
        error = raised.exception
        self.assertEqual(error.code, "quota_exceeded")
        self.assertEqual(error.http, 402)
        self.assertIn("credits", str(error).lower())
        self.assertIn("top up", str(error).lower())
        self.assertNotIn("sk_test", str(error.as_dict()))

    def test_model_access_falls_back(self):
        seen = []

        def request(method, url, **kwargs):
            model = kwargs["json"]["model_id"]
            seen.append(model)
            if model == "eleven_v3":
                return Resp(402, {"detail": {
                    "status": "model_access_denied",
                    "message": "Your plan cannot access this model",
                }})
            return Resp(200, content=b"ID3fallback")

        original = tts._http_request
        tts._http_request = request
        try:
            path = tts.synthesize(
                "hello", self.dest, conf=conf(), model="eleven_v3",
                voice_id=cfg.FALLBACK_VOICE_ID,
            )
        finally:
            tts._http_request = original
        self.assertTrue(path.exists())
        self.assertEqual(seen[:2], ["eleven_v3", "eleven_multilingual_v2"])

    def test_quota_rotates_to_second_key(self):
        keys = []

        def request(method, url, **kwargs):
            key = kwargs["headers"]["xi-api-key"]
            keys.append(key)
            if key == "sk_test_one":
                return Resp(402, {"detail": {"status": "quota_exceeded"}})
            return Resp(200, content=b"ID3second")

        original = tts._http_request
        tts._http_request = request
        try:
            tts.synthesize(
                "hello", self.dest, conf=conf(("sk_test_one", "sk_test_two")),
                model="eleven_v3", voice_id=cfg.FALLBACK_VOICE_ID,
            )
        finally:
            tts._http_request = original
        self.assertEqual(keys, ["sk_test_one", "sk_test_two"])

    def test_account_health_and_preflight_are_safe(self):
        class Session:
            @staticmethod
            def get(url, **kwargs):
                return Resp(200, {
                    "tier": "creator",
                    "character_count": 3420,
                    "character_limit": 100000,
                })

        account = tts.check_account(conf=conf(), session=Session())
        self.assertTrue(account["ok"])
        self.assertEqual(account["remaining"], 96580)
        self.assertNotIn("sk_test", str(account))
        preflight = tts.preflight_characters(["abc", "12345"], account)
        self.assertEqual(preflight["characters_needed"], 8)
        self.assertTrue(preflight["enough"])


if __name__ == "__main__":
    unittest.main()
