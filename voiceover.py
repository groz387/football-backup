from __future__ import annotations

import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class VoiceoverConfig:
    voiceover_file: str = ""
    provider: str = "human"
    skip_audio: bool = False


def prepare_voiceover(out_dir: Path, text: str, config: VoiceoverConfig) -> Path | None:
    if config.skip_audio:
        return None

    if config.voiceover_file:
        return attach_human_voiceover(out_dir, Path(config.voiceover_file))

    if config.provider == "sapi":
        return synthesize_sapi_voiceover(out_dir, text)

    recording_path = out_dir / "voiceover_recording_script.txt"
    print(f"[audio] No voiceover attached. Record a human VO from {recording_path} and rerun with --voiceover-file PATH.")
    return None


def attach_human_voiceover(out_dir: Path, source: Path) -> Path | None:
    if not source.exists():
        print(f"[audio] Human voiceover file not found: {source}")
        return None

    suffix = source.suffix.lower() or ".wav"
    dest = out_dir / f"human_voiceover{suffix}"
    try:
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        print(f"[audio] Using human voiceover: {dest}")
        return dest
    except Exception as exc:
        print(f"[audio] Could not copy human voiceover: {exc}")
        return source


def synthesize_sapi_voiceover(out_dir: Path, text: str) -> Path | None:
    wav_path = out_dir / "voiceover.wav"
    text_path = out_dir / "voiceover_for_tts.txt"
    text_path.write_text(text, encoding="utf-8")
    if sys.platform != "win32":
        print("[audio] Windows SAPI text-to-speech is only available on Windows.")
        return None

    ps_text = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$speak.Rate = 5;"
        "$speak.Volume = 100;"
        f"$text = Get-Content -Raw -Encoding UTF8 '{ps_quote(text_path)}';"
        f"$speak.SetOutputToWaveFile('{ps_quote(wav_path)}');"
        "$speak.Speak($text);"
        "$speak.Dispose();"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_text], check=True, capture_output=True, text=True)
        print("[audio] Generated rough-draft SAPI narration. Use human VO for publication.")
        return wav_path if wav_path.exists() else None
    except Exception as exc:
        print(f"[audio] Windows speech synthesis failed: {exc}")
        return None


def audio_duration(path: Path | None) -> float | None:
    if not path or not path.exists():
        return None

    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate()
                return frames / float(rate) if rate else None
        except Exception:
            return None

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def fit_scene_durations_to_audio(scenes: list[dict[str, Any]], audio_path: Path | None, pad: float = 0.20) -> list[dict[str, Any]]:
    duration = audio_duration(audio_path)
    if duration is None or not scenes:
        return scenes

    current_total = sum(float(scene.get("duration", 6.0)) for scene in scenes)
    if current_total <= 0:
        return scenes

    target_total = max(12.0, min(45.0, duration + pad))
    scale = target_total / current_total
    for scene in scenes:
        scene["duration"] = round(max(1.2, float(scene.get("duration", 6.0)) * scale), 2)
    return scenes


def ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")
