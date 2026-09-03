"""ElevenLabs v3 TTS for recap voiceovers.

Voice: Liam Callahan / Witty Media Person. Model: eleven_v3.
Style: robust | normal (v3 stability).

Contracts:

    configured() -> bool
    synthesize(text, dest, language=..., style=..., regenerate=..., voice_id=...) -> Path

Studio also calls synthesize via kwargs (text, language, dest, voice_id).

    approve_voiceover(out_dir, language) -> dict
    regenerate_voiceover(text, language, dest, voice_id=None) -> Path

Keys: ELEVENLABS_API_KEY, ELEVENLABS_API_KEYS, ELEVENLABS_PROXIES.
Never log secret values.
"""

from __future__ import annotations

import json
import random
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from . import config as cfg

API_ROOT = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = cfg.DEFAULT_MODEL
DEFAULT_VOICE_NAME = cfg.DEFAULT_VOICE_NAME
DEFAULT_VOICE_ID = cfg.FALLBACK_VOICE_ID

_VOICE_CACHE: dict[str, str] = {}
_MODEL_CACHE: str | None = None


def reset_caches() -> None:
    """Tests call this between mocked runs."""
    global _VOICE_CACHE, _MODEL_CACHE
    _VOICE_CACHE = {}
    _MODEL_CACHE = None


def detect_model(session: Any | None = None, conf: Any | None = None) -> str:
    """Prefer eleven_v3; list GET /v1/models and fall back if the account lacks it.

    Documented name is ``eleven_v3``. If the API catalogue uses another id the
    first matching candidate in ``cfg.MODEL_CANDIDATES`` wins.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    conf = conf or cfg.load_eleven_config()
    preferred = str(getattr(conf, "model", None) or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    ids: list[str] = []
    for slot in getattr(conf, "slots", None) or ():
        try:
            headers = {**_headers(slot.api_key), "Accept": "application/json"}
            if session is not None:
                response = session.get(f"{API_ROOT}/models", headers=headers, timeout=20)
            else:
                response = _http_request(
                    "GET", f"{API_ROOT}/models", headers=headers,
                    proxies=_proxy_map(getattr(slot, "proxy", None)), timeout=20,
                )
        except Exception:
            continue
        if not getattr(response, "ok", False):
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        rows = payload if isinstance(payload, list) else (payload.get("models") if isinstance(payload, dict) else [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                mid = str(item.get("model_id") or item.get("id") or "").strip()
            else:
                mid = str(item).strip()
            if mid:
                ids.append(mid)
        if ids:
            break
    chosen = preferred
    if ids:
        if preferred in ids:
            chosen = preferred
        else:
            for candidate in cfg.MODEL_CANDIDATES:
                if candidate in ids:
                    chosen = candidate
                    break
    _MODEL_CACHE = chosen
    return chosen


class ElevenLabsError(RuntimeError):
    """Raised when synthesis cannot complete."""


def configured() -> bool:
    return bool(cfg.load_eleven_config().slots)


def available() -> bool:
    return configured()


def redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}…{value[-4:]}"


def redact_proxy(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    host = parsed.hostname or "proxy"
    port = f":{parsed.port}" if parsed.port else ""
    auth = "***@" if parsed.username or parsed.password else ""
    scheme = f"{parsed.scheme}://" if parsed.scheme else ""
    return f"{scheme}{auth}{host}{port}"


def _proxy_map(url: str | None) -> dict[str, str] | None:
    if not url:
        return None
    return {"http": url, "https": url}


def _http_request(method: str, url: str, **kwargs: Any) -> requests.Response:
    timeout = kwargs.pop("timeout", 60)
    return requests.request(method, url, timeout=timeout, **kwargs)


def _headers(key: str) -> dict[str, str]:
    return {
        "xi-api-key": key,
        "Accept": "application/octet-stream",
        "Content-Type": "application/json",
    }


def resolve_voice_id(
    explicit: str | None = None,
    *,
    session: Any | None = None,
    conf: Any | None = None,
) -> str:
    conf = conf or cfg.load_eleven_config()
    chosen = (explicit or getattr(conf, "voice_id", "") or "").strip()
    cache_key = f"{chosen}|{getattr(conf, 'voice_name', '')}"
    if cache_key in _VOICE_CACHE:
        return _VOICE_CACHE[cache_key]
    if chosen and " " not in chosen and len(chosen) >= 16:
        _VOICE_CACHE[cache_key] = chosen
        return chosen
    target = (getattr(conf, "voice_name", None) or DEFAULT_VOICE_NAME).strip().lower()
    for slot in getattr(conf, "slots", None) or ():
        try:
            headers = {**_headers(slot.api_key), "Accept": "application/json"}
            if session is not None:
                response = session.get(f"{API_ROOT}/voices", headers=headers, timeout=20)
            else:
                response = _http_request(
                    "GET",
                    f"{API_ROOT}/voices",
                    headers=headers,
                    proxies=_proxy_map(getattr(slot, "proxy", None)),
                    timeout=20,
                )
        except (requests.RequestException, TypeError, AttributeError):
            continue
        if getattr(response, "status_code", 200) in {401, 403, 429} or not getattr(response, "ok", True):
            continue
        try:
            payload = response.json()
        except (ValueError, TypeError, AttributeError):
            continue
        voices = payload.get("voices") if isinstance(payload, dict) else payload
        if not isinstance(voices, list):
            continue
        for item in voices:
            if not isinstance(item, dict):
                continue
            label = str(item.get("name") or "").strip().lower()
            vid = str(item.get("voice_id") or item.get("id") or "")
            if not vid:
                continue
            if target and target in label:
                _VOICE_CACHE[cache_key] = vid
                return vid
            if "liam" in label and any(bit in label for bit in ("callahan", "witty", "media", "social")):
                _VOICE_CACHE[cache_key] = vid
                return vid
            if label == "liam":
                _VOICE_CACHE[cache_key] = vid
                return vid
    found = chosen or DEFAULT_VOICE_ID
    _VOICE_CACHE[cache_key] = found
    return found


search_voice_id = resolve_voice_id


def _pcm_to_wav(pcm: bytes, dest: Path, rate: int = 24000) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


def _status_path(out_dir: Path, language: str) -> Path:
    folder = Path(out_dir) / "voiceover" / language
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "status.json"


def _load_status(out_dir: Path, language: str) -> dict[str, Any]:
    path = _status_path(out_dir, language)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return {"language": language, "status": "none", "attempt": 0, "path": ""}


def _save_status(out_dir: Path, language: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = _status_path(out_dir, language)
    safe = {k: v for k, v in payload.items() if k not in {"api_key", "proxy"}}
    if "proxy_used" in safe:
        safe["proxy_used"] = redact_proxy(str(safe.get("proxy_used") or ""))
    path.write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return safe


def synthesize(
    text: str,
    dest: str | Path | None = None,
    language: str = "en",
    voice_id: str | None = None,
    *,
    out_path: str | Path | None = None,
    path: str | Path | None = None,
    style: str | None = None,
    model: str | None = None,
    regenerate: bool = False,
    conf: Any | None = None,
    session: Any | None = None,
    **_ignored: Any,
) -> Path:
    """Generate speech to ``dest``.

    ``voice.prepare`` calls ``synthesize(text, dest, language=..., style=..., regenerate=...)``.
    Studio passes the same fields as kwargs.
    """
    # Studio sometimes used to pass language as the second positional. If dest
    # looks like a language code and out_path/path is the file, swap.
    if isinstance(dest, str) and dest.lower() in {
        "en", "az", "es", "ru", "tr", "fr", "de", "it", "ar", "uk", "pl", "nl",
        "ja", "ko", "hi", "pt-br", "pt-pt", "pt-BR", "pt-PT",
    } and (out_path or path):
        language = dest
        dest = out_path or path
    target = Path(dest or out_path or path or "voiceover.mp3")
    spoken = (text or "").strip()
    if not spoken:
        raise ElevenLabsError("No voiceover text to synthesise.")
    if target.exists() and target.stat().st_size > 0 and not regenerate:
        return target

    conf = conf or cfg.load_eleven_config()
    if not getattr(conf, "slots", None):
        raise ElevenLabsError(
            "No ElevenLabs key. Set ELEVENLABS_API_KEY or ELEVENLABS_API_KEYS."
        )
    model_id = (model or detect_model(session=session, conf=conf) or getattr(conf, "model", None) or DEFAULT_MODEL)
    model_id = str(model_id).strip() or DEFAULT_MODEL
    try:
        settings = cfg.style_voice_settings(style or getattr(conf, "style", None) or "robust")
        style_name = cfg.eleven_style(style or getattr(conf, "style", None) or "robust")
    except ValueError:
        settings = cfg.style_voice_settings("robust")
        style_name = "robust"
    vid = resolve_voice_id(voice_id, session=session, conf=conf)
    want_wav = target.suffix.lower() in {".wav", ".wave"}
    output_format = "pcm_24000" if want_wav else "mp3_44100_128"
    payload = {
        "text": spoken,
        "model_id": model_id,
        "voice_settings": settings,
    }
    url = f"{API_ROOT}/text-to-speech/{vid}?output_format={output_format}"
    last_error = "no attempts"
    delay = 1.0
    for slot in conf.slots:
        try:
            if session is not None:
                response = session.post(
                    url,
                    headers=_headers(slot.api_key),
                    json=payload,
                    timeout=90,
                )
            else:
                response = _http_request(
                    "POST",
                    url,
                    headers=_headers(slot.api_key),
                    json=payload,
                    proxies=_proxy_map(getattr(slot, "proxy", None)),
                    timeout=90,
                )
        except requests.RequestException as exc:
            last_error = type(exc).__name__
            time.sleep(delay + random.uniform(0, 0.3))
            delay = min(8.0, delay * 2)
            continue
        if response.status_code in {401, 403}:
            last_error = f"auth {response.status_code}"
            continue
        if response.status_code == 429:
            last_error = "rate limited"
            time.sleep(delay)
            delay = min(8.0, delay * 2)
            continue
        if not response.ok:
            last_error = f"http {response.status_code}"
            continue
        body = response.content or b""
        target.parent.mkdir(parents=True, exist_ok=True)
        if want_wav:
            _pcm_to_wav(body, target)
        else:
            target.write_bytes(body)
        _save_status(target.parent, language, {
            "language": language,
            "status": "ready",
            "attempt": int(_load_status(target.parent, language).get("attempt") or 0) + 1,
            "path": str(target),
            "model": model_id,
            "voice_id": vid,
            "voice_name": getattr(conf, "voice_name", DEFAULT_VOICE_NAME),
            "stability": style_name,
            "style": style_name,
            "proxy_used": redact_proxy(getattr(slot, "proxy", None) or ""),
            "bytes": len(body),
        })
        return target
    raise ElevenLabsError(f"ElevenLabs synthesis failed ({last_error}).")


def regenerate_voiceover(
    text: str,
    language: str,
    dest: str | Path,
    voice_id: str | None = None,
    **kwargs: Any,
) -> Path:
    """Fresh take. Studio and the CLI regen gate both call this."""
    dest_path = Path(dest)
    status = _load_status(dest_path.parent, language)
    status["status"] = "regenerating"
    status["attempt"] = int(status.get("attempt") or 0) + 1
    _save_status(dest_path.parent, language, status)
    path = synthesize(
        text, dest_path, language=language, voice_id=voice_id, regenerate=True, **kwargs,
    )
    _save_status(dest_path.parent, language, {
        **_load_status(dest_path.parent, language),
        "status": "ready",
        "path": str(path),
    })
    return path


def approve_voiceover(out_dir: str | Path, language: str) -> dict[str, Any]:
    """Mark the current take approved. Studio can call this per language."""
    root = Path(out_dir)
    status = _load_status(root, language)
    raw_path = str(status.get("path") or "").strip()
    path = Path(raw_path) if raw_path else None
    if path is None or not path.exists():
        for candidate in (
            root / "voiceover.mp3",
            root / "narration.mp3",
            root / "narration.wav",
            root / "voiceover" / language / "take.mp3",
            root / f"voice_{language}.wav",
            root / f"voice_{language}.mp3",
        ):
            if candidate.exists():
                path = candidate
                break
    if path is None or not path.exists() or not path.name:
        raise ElevenLabsError(f"No voiceover file to approve for {language}.")
    approved = path.with_name("approved" + path.suffix.lower())
    try:
        if path.resolve() != approved.resolve():
            approved.write_bytes(path.read_bytes())
    except OSError:
        approved = path
    return _save_status(root, language, {
        **status,
        "language": language,
        "status": "approved",
        "path": str(path),
        "approved_path": str(approved),
    })


# Names the studio console can import without reaching past this module.
approve_voice = approve_voiceover
regenerate_voice = regenerate_voiceover
regenerate = regenerate_voiceover
