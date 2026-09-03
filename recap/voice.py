"""Narration audio.

A human recording is the intended path. Windows SAPI exists only so a rough
cut can be timed end to end, and it says so in the console when it is used.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VoiceConfig:
    voiceover_file: str = ""
    use_sapi: bool = False
    skip_audio: bool = False
    language: str = "en"
    eleven_style: str = "robust"
    eleven_voice: str = ""
    eleven_model: str = ""
    regenerate: bool = False
    no_elevenlabs: bool = False


def prepare(out_dir: Path, narration: str, config: VoiceConfig) -> Path | None:
    out_dir = Path(out_dir)
    if config.skip_audio:
        return None
    if config.voiceover_file:
        return _attach(out_dir, Path(config.voiceover_file))
    if not config.no_elevenlabs:
        eleven = _synthesize_eleven(out_dir, narration, config)
        if eleven is not None:
            return eleven
    if config.use_sapi:
        return _synthesize_sapi(out_dir, narration)
    print(
        "  [audio] no narration attached. Record the lines in "
        "voiceover_recording_script.txt and rerun with --voiceover-file PATH, "
        "or set ELEVENLABS_API_KEY for v3 TTS."
    )
    return None


def _synthesize_eleven(out_dir: Path, narration: str, config: VoiceConfig) -> Path | None:
    try:
        from . import elevenlabs_tts
    except Exception:
        return None
    if not elevenlabs_tts.configured():
        return None
    dest = out_dir / "voiceover.mp3"
    try:
        path = elevenlabs_tts.synthesize(
            narration,
            dest,
            language=config.language,
            style=config.eleven_style,
            regenerate=config.regenerate,
            voice_id=config.eleven_voice or None,
            model=config.eleven_model or None,
        )
    except elevenlabs_tts.ElevenLabsError as exc:
        print(f"  [audio] ElevenLabs failed ({exc}); falling back.")
        return None
    if path and path.exists():
        print(f"  [audio] ElevenLabs v3 voiceover: {path.name}")
        return path
    return None


def _attach(out_dir: Path, source: Path) -> Path | None:
    if not source.exists():
        print(f"  [audio] narration file not found: {source}")
        return None
    destination = out_dir / f"narration{source.suffix.lower() or '.wav'}"
    try:
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    except Exception as exc:  # noqa: BLE001
        print(f"  [audio] could not copy the narration file ({exc}); using it in place.")
        return source
    print(f"  [audio] using narration: {destination.name}")
    return destination


def _synthesize_sapi(out_dir: Path, narration: str) -> Path | None:
    if sys.platform != "win32":
        print("  [audio] SAPI narration is only available on Windows.")
        return None

    text_path = out_dir / "narration_for_tts.txt"
    wav_path = out_dir / "narration.wav"
    text_path.write_text(narration, encoding="utf-8")

    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$speak.Rate = 2;"
        "$speak.Volume = 100;"
        f"$text = Get-Content -Raw -Encoding UTF8 '{_ps_quote(text_path)}';"
        f"$speak.SetOutputToWaveFile('{_ps_quote(wav_path)}');"
        "$speak.Speak($text);"
        "$speak.Dispose();"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not wav_path.exists():
        print(f"  [audio] SAPI synthesis failed: {result.stderr.strip()[:200]}")
        return None
    print("  [audio] synthetic narration generated. Replace it with a human recording before publishing.")
    return wav_path


def duration(path: Path | None) -> float | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None

    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                rate = handle.getframerate()
                return handle.getnframes() / float(rate) if rate else None
        except Exception:  # noqa: BLE001 - fall through to ffprobe
            pass

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")
