"""SFX pack, original music bed, ducking, limiter, and loudnorm for recap masters.

Hits and beds are synthesized (ffmpeg lavfi, numpy fallback). Nothing is pulled
from a trending-song catalog — those get muted on TikTok/Reels/Shorts.

SFX map (see ``cue_list``):
    impact  number slam (hook_claim, stat_slam, punch)
    whoosh  wipe cuts + live clip smash
    riser   into hook_punch / close / slam
    crowd   goal scenes (goal_timeline, goal_chain, goalmouth) and a scored close
    glass   robbery / xG shock (xg_robbery hook, xg_race, conversion_gauges)
    tick    micro-hook flash
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np

from . import music_beds, timing

RATE = 44100
SFX_DIR = Path(__file__).resolve().parent / "sfx"
PACK_VERSION = "2"
MAX_BEAT_SHIFT = 0.120
DEFAULT_BPM = music_beds.DEFAULT_BPM

# Peak gains on the SFX bus before the mix limiter. Keep these well under 1 so
# stacked hits cannot clip on their own.
SFX_GAIN = {
    "impact": 0.52,
    "whoosh": 0.38,
    "riser": 0.30,
    "tick": 0.32,
    "crowd": 0.40,
    "glass": 0.42,
}
SFX_BUS_CEILING = 0.70
MIX_LIMIT = 0.89

LOUDNORM_PROFILES = {
    "tiktok": {"I": -11.0, "TP": -1.2, "LRA": 9.0},   # slightly hotter social
    "youtube": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
}

GOAL_SCENES = {"goal_timeline", "goal_chain", "goalmouth"}
ROBBERY_KINDS = {"xg_robbery", "waste"}
ROBBERY_VIZ = {"xg_race", "conversion_gauges"}
NUMBER_SLAM_VIZ = {"hook_claim", "stat_slam"}

_PACK_NAMES = ("whoosh.wav", "impact.wav", "riser.wav", "tick.wav", "crowd.wav", "glass.wav")


def _ffmpeg_bin(explicit: str | None = None) -> str | None:
    return explicit or shutil.which("ffmpeg")


def _write_wav(path: Path, samples: np.ndarray, rate: int = RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.asarray(samples, dtype=float), -1.0, 1.0)
    data = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width == 2:
        samples = np.frombuffer(frames, dtype=np.int16).astype(float) / 32768.0
    else:
        samples = np.frombuffer(frames, dtype=np.uint8).astype(float)
        samples = (samples - 128.0) / 128.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != RATE and samples.size:
        duration = samples.size / float(rate)
        target = max(1, int(round(duration * RATE)))
        samples = np.interp(
            np.linspace(0, samples.size - 1, target),
            np.arange(samples.size),
            samples,
        )
    return samples.astype(float)


def _env(n: int, attack: float, release: float, rate: int = RATE) -> np.ndarray:
    attack_n = max(1, int(attack * rate))
    release_n = max(1, int(release * rate))
    env = np.ones(n, dtype=float)
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n)
    if release_n < n:
        env[-release_n:] = np.linspace(1.0, 0.0, release_n)
    return env


def _run_ffmpeg(ffmpeg: str, args: list[str]) -> bool:
    result = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _lavfi_wav(ffmpeg: str, path: Path, lavfi: str, duration: float, af: str) -> bool:
    ok = _run_ffmpeg(
        ffmpeg,
        ["-f", "lavfi", "-i", lavfi, "-t", f"{duration:.3f}", "-af", af,
         "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(path)],
    )
    return ok and path.exists() and path.stat().st_size > 200


def _synthesize_pack_numpy(directory: Path) -> None:
    rng = np.random.default_rng(7)
    t = lambda seconds: np.linspace(0, seconds, int(seconds * RATE), endpoint=False)

    whoosh_t = t(0.28)
    noise = rng.normal(0, 1, whoosh_t.size)
    sweep = np.sin(np.linspace(0.4, 0.95, whoosh_t.size) * math.pi)
    _write_wav(directory / "whoosh.wav", noise * sweep * _env(whoosh_t.size, 0.02, 0.12) * 0.35)

    impact_t = t(0.22)
    click = rng.normal(0, 1, impact_t.size) * np.exp(-impact_t * 55)
    body = np.sin(2 * math.pi * 70 * impact_t) * np.exp(-impact_t * 18)
    _write_wav(directory / "impact.wav", (click * 0.45 + body * 0.7) * 0.85)

    riser_t = t(0.55)
    freq = np.linspace(180, 720, riser_t.size)
    phase = np.cumsum(freq) / RATE * 2 * math.pi
    _write_wav(directory / "riser.wav", np.sin(phase) * _env(riser_t.size, 0.08, 0.12) * 0.28)

    tick_t = t(0.06)
    _write_wav(directory / "tick.wav", rng.normal(0, 1, tick_t.size) * np.exp(-tick_t * 90) * 0.5)

    crowd_t = t(1.0)
    crowd = rng.normal(0, 1, crowd_t.size)
    kernel = np.hanning(401)
    kernel /= kernel.sum()
    crowd = np.convolve(crowd, kernel, mode="same") * _env(crowd_t.size, 0.15, 0.25)
    _write_wav(directory / "crowd.wav", crowd * 0.22)

    glass_t = t(0.18)
    glass = (
        np.sin(2 * math.pi * 1760 * glass_t) * np.exp(-glass_t * 22)
        + np.sin(2 * math.pi * 2637 * glass_t) * np.exp(-glass_t * 28) * 0.4
    )
    _write_wav(directory / "glass.wav", glass * 0.4)


def _synthesize_pack_ffmpeg(directory: Path, ffmpeg: str) -> bool:
    """Short filtered sine/noise hits. Tiny wavs, no sample library."""
    directory.mkdir(parents=True, exist_ok=True)
    specs = {
        "whoosh": (
            "anoisesrc=color=white:sample_rate=44100:amplitude=0.65:duration=0.28",
            0.28,
            "highpass=f=280,lowpass=f=1600,afade=t=in:d=0.03,afade=t=out:st=0.11:d=0.17,volume=0.75",
        ),
        "tick": (
            "anoisesrc=color=white:sample_rate=44100:amplitude=0.7:duration=0.06",
            0.06,
            "highpass=f=5000,afade=t=out:st=0.008:d=0.05,volume=0.6",
        ),
        "crowd": (
            "anoisesrc=color=brown:sample_rate=44100:amplitude=0.55:duration=1.0",
            1.0,
            "highpass=f=200,lowpass=f=1400,afade=t=in:d=0.14,afade=t=out:st=0.72:d=0.28,volume=0.55",
        ),
        "riser": (
            "aevalsrc=exprs=sin(2*PI*(180+980*t)*t):s=44100:d=0.55",
            0.55,
            "afade=t=in:d=0.08,afade=t=out:st=0.42:d=0.13,volume=0.38",
        ),
        "glass": (
            "aevalsrc=exprs=sin(2*PI*1760*t)*exp(-22*t)+0.4*sin(2*PI*2637*t)*exp(-28*t):s=44100:d=0.18",
            0.18,
            "afade=t=out:st=0.02:d=0.16,volume=0.55",
        ),
    }
    for name, (lavfi, dur, af) in specs.items():
        if not _lavfi_wav(ffmpeg, directory / f"{name}.wav", lavfi, dur, af):
            return False

    impact = directory / "impact.wav"
    ok = _run_ffmpeg(
        ffmpeg,
        [
            "-f", "lavfi", "-i", "sine=frequency=68:sample_rate=44100:duration=0.22",
            "-f", "lavfi", "-i", "anoisesrc=color=white:sample_rate=44100:amplitude=0.9:duration=0.10",
            "-filter_complex",
            "[0]afade=t=out:st=0.04:d=0.18,volume=0.85[body];"
            "[1]highpass=f=1800,afade=t=out:st=0.012:d=0.07,volume=0.55[click];"
            "[click][body]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.90:attack=1:release=40[a]",
            "-map", "[a]", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le",
            str(impact),
        ],
    )
    return ok and impact.exists()


def ensure_pack() -> Path:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    marker = SFX_DIR / ".pack_version"
    ready = all((SFX_DIR / name).exists() for name in _PACK_NAMES)
    version_ok = marker.exists() and marker.read_text(encoding="utf-8").strip() == PACK_VERSION
    if ready and version_ok:
        return SFX_DIR
    ffmpeg = _ffmpeg_bin()
    if ffmpeg and _synthesize_pack_ffmpeg(SFX_DIR, ffmpeg):
        marker.write_text(PACK_VERSION, encoding="utf-8")
        return SFX_DIR
    _synthesize_pack_numpy(SFX_DIR)
    marker.write_text(PACK_VERSION, encoding="utf-8")
    return SFX_DIR


def cue_list(scenes: list[dict[str, Any]]) -> list[tuple[float, str]]:
    """(seconds, sfx stem) hits aligned to the assembled timeline."""
    cues: list[tuple[float, str]] = []
    pack = {path.stem for path in ensure_pack().glob("*.wav")}
    has_goal_scene = any(scene.get("visualization") in GOAL_SCENES for scene in scenes)
    for scene in scenes:
        start = float(scene.get("visible_start") or scene.get("clip_start") or 0.0)
        viz = str(scene.get("visualization") or "")
        kind = str(scene.get("hook_kind") or "")
        cut = str(scene.get("cut") or "")

        if cut == "wipe":
            cues.append((start, "whoosh"))

        if viz == "hook_claim":
            cues.append((start, "impact"))
        elif viz == "hook_punch":
            cues.append((max(0.0, start - 0.48), "riser"))
            cues.append((start, "impact"))
            if kind in ROBBERY_KINDS or "robbery" in kind:
                cues.append((start + 0.05, "glass"))
        elif viz == "micro_hook":
            cues.append((start, "tick"))
        elif viz == "stat_slam":
            cues.append((start, "riser"))
            cues.append((start + 0.22, "impact"))
        elif viz in GOAL_SCENES:
            cues.append((start + 0.18, "crowd"))
            cues.append((start + 0.35, "impact"))
        elif viz in ROBBERY_VIZ:
            cues.append((start + 0.12, "glass"))
            cues.append((start + 0.28, "impact"))
        elif viz == "close":
            cues.append((max(0.0, start - 0.20), "riser"))
            cues.append((start + 0.16, "impact"))
            if has_goal_scene:
                cues.append((start, "crowd"))
        elif viz == "live_clip":
            cues.append((start, "whoosh"))

    return [(when, name) for when, name in cues if name in pack and when >= 0]


def snap_wipes_to_beats(
    scenes: list[dict[str, Any]],
    bpm: float | None = DEFAULT_BPM,
    *,
    max_shift: float = MAX_BEAT_SHIFT,
) -> list[dict[str, Any]]:
    """Nudge the scene before each wipe so the cut lands on a beat.

    Scene length never moves more than ``max_shift`` seconds (default 120 ms).
    If the nearest beat is further than that, the wipe is left alone.
    """
    if not scenes or not bpm or bpm <= 0:
        return scenes
    period = 60.0 / float(bpm)
    out = [dict(scene) for scene in scenes]

    def wipe_time(index: int) -> float:
        cursor = 0.0
        for i in range(index):
            clip = float(out[i].get("clip") or out[i].get("on_screen") or 0.0)
            hard_out = i >= len(out) - 1 or out[i + 1].get("cut") == "hard"
            cursor += clip if hard_out else clip - timing.TRANSITION
        return cursor

    for index in range(1, len(out)):
        if out[index].get("cut") == "hard":
            continue
        now = wipe_time(index)
        nearest = round(now / period) * period
        shift = nearest - now
        if abs(shift) < 1e-4 or abs(shift) > max_shift:
            continue
        prev = out[index - 1]
        on_screen = float(prev.get("on_screen") or prev.get("clip") or 0.0) + shift
        if on_screen < 0.25:
            continue
        extra = 0.0 if out[index].get("cut") == "hard" else timing.TRANSITION
        prev["on_screen"] = round(on_screen, 3)
        prev["clip"] = round(on_screen + extra, 3)
        out[index - 1] = prev
    return out


def detect_bpm(path: Path, *, ffmpeg: str | None = None, default: float = DEFAULT_BPM) -> float:
    """Lightweight envelope autocorrelation. Falls back to 120."""
    ffmpeg = _ffmpeg_bin(ffmpeg)
    path = Path(path)
    if not ffmpeg or not path.exists():
        return default
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error",
         "-i", str(path), "-t", "24", "-ac", "1", "-ar", "22050",
         "-f", "f32le", "pipe:1"],
        capture_output=True,
    )
    if result.returncode != 0 or len(result.stdout) < 22050:
        return default
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    hop = 512
    if samples.size < hop * 8:
        return default
    windows = np.lib.stride_tricks.sliding_window_view(samples, hop)[::hop]
    env = np.sqrt(np.mean(windows * windows, axis=1))
    env = env - env.mean()
    if float(env.std()) < 1e-6:
        return default
    sr_env = 22050.0 / hop
    min_bpm, max_bpm = 80.0, 160.0
    min_lag = max(1, int(sr_env * 60.0 / max_bpm))
    max_lag = min(len(env) - 1, int(sr_env * 60.0 / min_bpm))
    best_v = -1.0
    best = default
    for lag in range(min_lag, max_lag + 1):
        value = float(np.dot(env[:-lag], env[lag:]))
        if value > best_v:
            best_v = value
            best = 60.0 * sr_env / lag
    return float(max(min_bpm, min(max_bpm, best)))


def normalize_loudnorm(value: str | None) -> str:
    text = str(value or "tiktok").strip().lower()
    if text in {"0", "false", "none", "off", "no"}:
        return "off"
    if text in {"youtube", "yt", "ytb", "-14"}:
        return "youtube"
    return "tiktok"


def loudnorm_available(ffmpeg: str | None = None) -> bool:
    ffmpeg = _ffmpeg_bin(ffmpeg)
    if not ffmpeg:
        return False
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True, text=True,
    )
    return "loudnorm" in (result.stdout or "")


def resolve_music_bed(
    spec: str,
    *,
    out_dir: Path,
    scenes: list[dict[str, Any]],
    music_file: str | Path | None = None,
    skip_audio: bool = False,
    ffmpeg: str | None = None,
) -> tuple[Path | None, float]:
    """Return ``(bed_path, bpm)``. ``spec`` is auto, none, or a file path."""
    if skip_audio:
        return None, DEFAULT_BPM
    ffmpeg = _ffmpeg_bin(ffmpeg)
    override = str(music_file or "").strip()
    spec = str(spec or "auto").strip()
    if override:
        path = Path(override)
        if path.exists():
            return path, detect_bpm(path, ffmpeg=ffmpeg)
        print(f"  [audio] --music-file not found: {path}")
    lowered = spec.lower()
    if lowered in {"none", "off", "no", ""}:
        return None, DEFAULT_BPM
    if lowered != "auto":
        path = Path(spec)
        if path.exists():
            return path, detect_bpm(path, ffmpeg=ffmpeg)
        print(f"  [audio] --music-bed path not found: {path}; generating an original bed")
    if not ffmpeg:
        return None, DEFAULT_BPM
    bed = music_beds.ensure_bed(out_dir, scenes, ffmpeg=ffmpeg)
    return bed, music_beds.bpm_for(scenes)


def _render_sfx_bus(scenes: list[dict[str, Any]], duration: float, dest: Path) -> Path | None:
    cues = cue_list(scenes)
    if not cues or duration <= 0:
        return None
    pack = ensure_pack()
    n = int(math.ceil(duration * RATE)) + RATE
    bus = np.zeros(n, dtype=float)
    cache: dict[str, np.ndarray] = {}
    for when, name in cues:
        src = pack / f"{name}.wav"
        if not src.exists():
            continue
        if name not in cache:
            cache[name] = _read_wav(src)
        wave_samples = cache[name]
        start = int(round(when * RATE))
        if start >= n or start < 0:
            continue
        end = min(n, start + wave_samples.size)
        bus[start:end] += wave_samples[: end - start] * SFX_GAIN.get(name, 0.35)
    peak = float(np.max(np.abs(bus))) if bus.size else 0.0
    if peak > SFX_BUS_CEILING:
        bus *= SFX_BUS_CEILING / peak
    if peak < 1e-6:
        return None
    _write_wav(dest, bus[: int(math.ceil(duration * RATE))])
    return dest if dest.exists() else None


def _parse_loudnorm_json(text: str) -> dict[str, str] | None:
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if "input_i" not in data:
        return None
    return {str(key): str(value) for key, value in data.items()}


def _limiter_filter() -> str:
    return f"alimiter=limit={MIX_LIMIT}:attack=5:release=50:level=false"


def _loudnorm_filter(profile: str, measured: dict[str, str] | None = None) -> str:
    cfg = LOUDNORM_PROFILES[profile]
    base = f"loudnorm=I={cfg['I']}:TP={cfg['TP']}:LRA={cfg['LRA']}"
    if not measured:
        return f"{base}:print_format=summary"
    return (
        f"{base}:measured_I={measured['input_i']}:measured_LRA={measured['input_lra']}:"
        f"measured_TP={measured['input_tp']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured.get('target_offset', '0')}:linear=true:print_format=summary"
    )


def _apply_loudness(
    ffmpeg: str,
    source: Path,
    dest: Path,
    profile: str,
) -> bool:
    """Limiter always. Dual-pass loudnorm when the filter exists and profile is on."""
    limiter = _limiter_filter()
    want = normalize_loudnorm(profile)
    use_loudnorm = want != "off" and loudnorm_available(ffmpeg)
    if not use_loudnorm:
        return _run_ffmpeg(
            ffmpeg,
            ["-i", str(source), "-af", limiter, "-c:a", "aac", "-b:a", "192k", str(dest)],
        ) and dest.exists()

    measure = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(source),
         "-af", _loudnorm_filter(want), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    measured = _parse_loudnorm_json((measure.stderr or "") + (measure.stdout or ""))
    af = f"{_loudnorm_filter(want, measured)},{limiter}" if measured else f"{_loudnorm_filter(want)},{limiter}"
    ok = _run_ffmpeg(
        ffmpeg,
        ["-i", str(source), "-af", af, "-c:a", "aac", "-b:a", "192k", str(dest)],
    )
    if ok and dest.exists():
        target = LOUDNORM_PROFILES[want]["I"]
        print(f"  [audio] loudnorm {want} (target {target:.0f} LUFS) + limiter")
        return True
    print("  [audio] loudnorm failed; exporting limiter-only mix")
    return _run_ffmpeg(
        ffmpeg,
        ["-i", str(source), "-af", limiter, "-c:a", "aac", "-b:a", "192k", str(dest)],
    ) and dest.exists()


def mix(
    out_dir: Path,
    scenes: list[dict[str, Any]],
    voiceover: Path | None,
    *,
    sfx: bool = True,
    music_file: str | Path | None = None,
    ffmpeg: str,
    duration: float,
    loudnorm: str = "tiktok",
    skip_audio: bool = False,
) -> Path | None:
    """Build a mixed AAC bed (VO + SFX + ducked original/optional music).

    ``skip_audio`` returns None immediately so the encoder can write a silent
    (but valid) mp4 without running loudnorm.
    """
    if skip_audio or duration <= 0:
        return None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mixed = out_dir / "mix.m4a"
    raw = out_dir / "mix_raw.wav"

    vo_path = Path(voiceover) if voiceover and Path(voiceover).exists() else None
    music_path = Path(music_file) if music_file and Path(music_file).exists() else None
    sfx_path = None
    if sfx:
        sfx_path = _render_sfx_bus(scenes, duration, out_dir / "sfx_bus.wav")

    if vo_path is None and sfx_path is None and music_path is None:
        return None

    inputs: list[str] = []
    filters: list[str] = []
    index = 0

    def add_input(path: Path, *, loop: bool = False) -> int:
        nonlocal index
        if loop:
            inputs.extend(["-stream_loop", "-1"])
        inputs.extend(["-i", str(path.resolve())])
        current = index
        index += 1
        return current

    fmt = f"aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo"

    vo_idx = add_input(vo_path) if vo_path is not None else None
    sfx_idx = add_input(sfx_path) if sfx_path is not None else None
    music_idx = add_input(music_path, loop=True) if music_path is not None else None

    fg_parts: list[str] = []
    if vo_idx is not None:
        filters.append(f"[{vo_idx}:a]{fmt},volume=1.0[vo]")
        fg_parts.append("[vo]")
    if sfx_idx is not None:
        filters.append(f"[{sfx_idx}:a]{fmt},volume=0.95[sfx]")
        fg_parts.append("[sfx]")

    if music_idx is not None:
        # Under VO the bed sits back; music-only / sfx+music can be hotter.
        music_vol = 0.16 if vo_idx is not None else 0.30
        filters.append(
            f"[{music_idx}:a]{fmt},volume={music_vol:.2f},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[bed]"
        )

    if len(fg_parts) == 2:
        filters.append(
            "".join(fg_parts)
            + "amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[fg]"
        )
        fg = "[fg]"
    elif len(fg_parts) == 1:
        filters.append(f"{fg_parts[0]}anull[fg]")
        fg = "[fg]"
    else:
        fg = None

    if music_idx is not None and fg is not None:
        filters.append(f"{fg}asplit=2[fg_main][sc]")
        filters.append(
            "[bed][sc]sidechaincompress=threshold=0.045:ratio=7:attack=15:release=220:makeup=1.4[ducked]"
        )
        filters.append(
            "[ducked][fg_main]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"atrim=0:{duration:.3f}[pre]"
        )
    elif music_idx is not None:
        filters.append(f"[bed]atrim=0:{duration:.3f}[pre]")
    else:
        filters.append(f"{fg}atrim=0:{duration:.3f}[pre]")

    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[pre]",
        "-t", f"{duration:.3f}",
        "-c:a", "pcm_f32le",
        str(raw),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not raw.exists():
        print(f"  [audio] mix failed: {(result.stderr or '').strip()[:400]}")
        return None

    if not _apply_loudness(ffmpeg, raw, mixed, loudnorm):
        raw.unlink(missing_ok=True)
        return None
    raw.unlink(missing_ok=True)

    bits = []
    if vo_path is not None:
        bits.append("voice")
    if sfx_path is not None:
        bits.append(f"sfx×{len(cue_list(scenes))}")
    if music_path is not None:
        bits.append("music")
    print(f"  [audio] mix: {' + '.join(bits) or 'empty'}")
    return mixed if mixed.exists() else None
