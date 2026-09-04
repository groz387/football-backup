"""ElevenLabs 402 must not be guessed as 'credits exhausted'."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from recap import elevenlabs_tts as el


class _Resp:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}
        self.text = text or str(payload or "")
        self.content = b"ID3fake-mp3"

    def json(self):
        return self._payload


class ElevenLabsErrorTests(unittest.TestCase):
    def test_bare_402_is_payment_required_not_exhausted(self):
        error = el._response_error(_Resp(402, {"detail": {"status": "payment_required"}}), "eleven_v3")
        self.assertEqual(error.code, "payment_required")
        self.assertNotIn("credits are exhausted", str(error).lower())

    def test_v3_quota_is_model_block(self):
        error = el._response_error(_Resp(402, {
            "detail": {
                "status": "quota_exceeded",
                "message": "This request exceeds your quota of eleven_v3.",
            }
        }), "eleven_v3")
        self.assertEqual(error.code, "model_access_denied")

    def test_monthly_character_quota_is_account_quota(self):
        error = el._response_error(_Resp(402, {
            "detail": {
                "status": "quota_exceeded",
                "message": "You have exceeded your monthly character quota.",
            }
        }), "eleven_v3")
        self.assertEqual(error.code, "quota_exceeded")

    def test_remaining_balance_downgrades_false_quota(self):
        error = el.ElevenLabsError(
            "ElevenLabs account quota: monthly limit.",
            code="quota_exceeded", http=402, model="eleven_v3",
            fallback_tried=["eleven_v3"],
        )
        conf = SimpleNamespace(slots=[SimpleNamespace(api_key="sk_test", proxy=None)], model="eleven_v3")
        session = mock.Mock()
        session.get.return_value = _Resp(200, {
            "tier": "creator", "character_count": 1200, "character_limit": 100000,
        })
        # check_account uses Accept json headers; reuse the fake 200 body.
        enriched = el._enrich_with_account(error, conf, session)
        self.assertEqual(enriched.code, "payment_required")
        self.assertIn("98,800", str(enriched))

    def test_v3_402_falls_back_to_multilingual(self):
        el.reset_caches()
        conf = SimpleNamespace(
            slots=[SimpleNamespace(api_key="sk_test", proxy=None)],
            model="eleven_v3", voice_id="TX3LPaxmHKxFdv7VOQHJ", voice_name="Liam",
            style="robust",
        )
        calls = []

        class Session:
            def post(self, url, **kwargs):
                model = kwargs["json"]["model_id"]
                calls.append(model)
                if model == "eleven_v3":
                    return _Resp(402, {
                        "detail": {"status": "payment_required", "message": "eleven_v3 requires a higher tier."}
                    })
                return _Resp(200, {})

            def get(self, url, **kwargs):
                if url.endswith("/models"):
                    return _Resp(200, [{"model_id": "eleven_v3"}, {"model_id": "eleven_multilingual_v2"}])
                if url.endswith("/voices"):
                    return _Resp(200, {"voices": [{"name": "Liam Callahan", "voice_id": "TX3LPaxmHKxFdv7VOQHJ"}]})
                return _Resp(200, {"character_count": 10, "character_limit": 100000})

        dest = el.synthesize(
            "Barcelona won 5-1.", dest="/tmp/el-fallback.mp3",
            regenerate=True, conf=conf, session=Session(),
        )
        self.assertTrue(dest.exists())
        self.assertIn("eleven_v3", calls)
        self.assertIn("eleven_multilingual_v2", calls)


if __name__ == "__main__":
    unittest.main()
