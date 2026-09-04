"""SFX pack, optional music duck, and mix for recap masters.

Hits are synthesized (no copyrighted samples). Music is opt-in via --music-file
so the pipeline never ships a copyrighted bed by default.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any

import numpy as np

RATE = 44100
SFX_DIR = Path(__file__).resolve().parent / "sfx"


def _write_wav(path: Path, samples: np.ndarray, rate: int = RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(samples, -1.0, 1.0)
    data = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())


def _env(n: int, attack: float, release: float, rate: int = RATE) -> np.ndarray:
    attack_n = max(1, int(attack * rate))
    release_n = max(1, int(release * rate))
    env = np.ones(n, dtype=float)
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n)
    if release_n < n:
        env[-release_n:] = np.linspace(1.0, 0.0, release_n)
    return env


def _synthesize_pack(directory: Path) -> None:
    rng = np.random.default_rng(7)
    t = lambda seconds: np.linspace(0, seconds, int(seconds * RATE), endpoint=False)

    # whoosh: noise through a rising low-pass
    whoosh_t = t(0.28)
    noise = rng.normal(0, 1, whoosh_t.size)
    sweep = np.sin(np.linspace(0.4, 0.95, whoosh_t.size) * math.pi)
    whoosh = noise * sweep * _env(whoosh_t.size, 0.02, 0.12)
    _write_wav(directory / "whoosh.wav", whoosh * 0.35)

    # impact: decaying click + body
    impact_t = t(0.22)
    click = rng.normal(0, 1, impact_t.size) * np.exp(-impact_t * 55)
    body = np.sin(2 * math.pi * 70 * impact_t) * np.exp(-impact_t * 18)
    _write_wav(directory / "impact.wav", (click * 0.45 + body * 0.7) * 0.85)

    # riser: rising sine
    riser_t = t(0.55)
    freq = np.linspace(180, 720, riser_t.size)
    phase = np.cumsum(freq) / RATE * 2 * math.pi
    riser = np.sin(phase) * _env(riser_t.size, 0.08, 0.12)
    _write_wav(directory / "riser.wav", riser * 0.28)

    # tick
    tick_t = t(0.06)
    tick = rng.normal(0, 1, tick_t.size) * np.exp(-tick_t * 90)
    _write_wav(directory / "tick.wav", tick * 0.5)

    # crowd swell, 1s filtered noise
    crowd_t = t(1.0)
    crowd = rng.normal(0, 1, crowd_t.size)
    kernel = np.hanning(401)
    kernel /= kernel.sum()
    crowd = np.convolve(crowd, kernel, mode="same") * _env(crowd_t.size, 0.15, 0.25)
    _write_wav(directory / "crowd.wav", crowd * 0.22)

    # glass / ping
    glass_t = t(0.18)
    glass = (
        np.sin(2 * math.pi * 1760 * glass_t) * np.exp(-glass_t * 22)
        + np.sin(2 * math.pi * 2637 * glass_t) * np.exp(-glass_t * 28) * 0.4
    )
    _write_wav(directory / "glass.wav", glass * 0.4)


def ensure_pack() -> Path:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    needed = ("whoosh.wav", "impact.wav", "riser.wav", "tick.wav", "crowd.wav", "glass.wav")
    if not all((SFX_DIR / name).exists() for name in needed):
        _synthesize_pack(SFX_DIR)
    return SFX_DIR


def cue_list(scenes: list[dict[str, Any]]) -> list[tuple[float, str]]:
    """(seconds, sfx stem) hits aligned to the assembled timeline."""
    cues: list[tuple[float, str]] = []
    pack = {path.stem for path in ensure_pack().glob("*.wav")}
    for scene in scenes:
        start = float(scene.get("visible_start") or scene.get("clip_start") or 0.0)
        viz = scene.get("visualization")
        if viz in {"hook_claim", "hook_punch"}:
            cues.append((start, "impact"))
            if viz == "hook_punch":
                cues.append((start + 0.04, "glass"))
        elif viz == "micro_hook":
            cues.append((start, "tick"))
            cues.append((start, "whoosh"))
        elif viz == "stat_slam":
            cues.append((start + 0.22, "impact"))
            cues.append((start, "riser"))
        elif viz in {"shot_map", "goal_timeline", "goal_chain"}:
            cues.append((start + 0.35, "impact"))
        elif viz == "close":
            cues.append((start, "riser"))
            cues.append((start + 0.18, "impact"))
            cues.append((start, "crowd"))
        elif viz == "live_clip":
            cues.append((start, "whoosh"))
    return [(when, name) for when, name in cues if name in pack and when >= 0]


def mix(
    out_dir: Path,
    scenes: list[dict[str, Any]],
    voiceover: Path | None,
    *,
    sfx: bool = True,
    music_file: str | Path | None = None,
    ffmpeg: str,
    duration: float,
) -> Path | None:
    """Build a mixed AAC bed (VO + SFX + optional ducked music)."""
    import subprocess

    out_dir = Path(out_dir)
    mixed = out_dir / "mix.m4a"
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    index = 0

    def add_input(path: Path) -> int:
        nonlocal index
        inputs.extend(["-i", str(path.resolve())])
        current = index
        index += 1
        return current

    vo_idx = None
    if voiceover and Path(voiceover).exists():
        vo_idx = add_input(Path(voiceover))
        filters.append(f"[{vo_idx}:a]aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo[vo]")
        labels.append("[vo]")

    if sfx:
        pack = ensure_pack()
        for when, name in cue_list(scenes):
            delay_ms = max(0, int(round(when * 1000)))
            src = pack / f"{name}.wav"
            if not src.exists():
                continue
            idx = add_input(src)
            tag = f"s{idx}"
            filters.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo,"
                f"adelay={delay_ms}|{delay_ms},volume=0.55[{tag}]"
            )
            labels.append(f"[{tag}]")

    music_idx = None
    music_path = Path(music_file) if music_file else None
    if music_path and music_path.exists():
        music_idx = add_input(music_path)
        filters.append(
            f"[{music_idx}:a]aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo,"
            f"volume=0.16,atrim=0:{duration:.3f}[bed]"
        )

    if not labels and music_idx is None:
        return None

    if music_idx is not None and vo_idx is not None:
        filters.append("[vo]asplit=2[vo_main][sc]")
        filters.append(
            "[bed][sc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=250:makeup=2[ducked]"
        )
        mix_in = ["[ducked]", "[vo_main]", *labels[1:]]
        filters.append(
            "".join(mix_in) + f"amix=inputs={len(mix_in)}:duration=longest:dropout_transition=0:normalize=0[aout]"
        )
    elif music_idx is not None:
        mix_in = ["[bed]", *labels]
        filters.append(
            "".join(mix_in) + f"amix=inputs={len(mix_in)}:duration=longest:dropout_transition=0:normalize=0[aout]"
        )
    else:
        filters.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[aout]"
        )

    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[aout]",
        "-t", f"{duration:.3f}",
        "-c:a", "aac", "-b:a", "192k",
        str(mixed),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [audio] mix failed: {result.stderr.strip()[:400]}")
        return None
    return mixed if mixed.exists() else None
