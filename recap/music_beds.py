"""Original recap music beds, built with ffmpeg lavfi.

Nothing is downloaded. Nothing is ripped from a catalog or a trending sound.
Each bed is a short original loop (sine + noise + envelopes) at a known BPM
so wipe cuts can snap to the grid. The loop is tiled under the master and
ducked against voice/SFX in ``recap.audio``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

RATE = 44100
LOOP_SECONDS = 8.0  # 4 bars of 4/4 at 120 BPM
DEFAULT_BPM = 120.0
CACHE_DIR = Path(__file__).resolve().parent / "sfx" / "beds"

# Original, non-melodic pulse beds. Frequencies are fundamentals / fifths, not
# a recognizable riff — sports-recap texture, not a song.
STYLES: dict[str, dict[str, float | str]] = {
    "pulse": {
        "bpm": DEFAULT_BPM,
        "kick_hz": 62.0,
        "sub_hz": 49.0,
        "pulse_hz": 110.0,
        "stab_hz": 164.81,
        "noise": 0.030,
        "kick_drive": 0.90,
        "hat_drive": 0.14,
    },
    "shock": {
        "bpm": DEFAULT_BPM,
        "kick_hz": 48.0,
        "sub_hz": 41.0,
        "pulse_hz": 98.0,
        "stab_hz": 146.83,
        "noise": 0.018,
        "kick_drive": 0.78,
        "hat_drive": 0.08,
    },
    "riot": {
        "bpm": DEFAULT_BPM,
        "kick_hz": 68.0,
        "sub_hz": 55.0,
        "pulse_hz": 123.47,
        "stab_hz": 185.0,
        "noise": 0.045,
        "kick_drive": 1.00,
        "hat_drive": 0.18,
    },
}

_ROBBERY = {"xg_robbery", "waste", "volume_upset", "sterile_upset"}
_RIOT = {"blowout", "comeback", "late_turn", "stoppage"}
_GOAL_VIZ = {"goal_timeline", "goal_chain", "goalmouth"}


def style_for_scenes(scenes: list[dict[str, Any]] | None) -> str:
    kinds = {str(scene.get("hook_kind") or "") for scene in scenes or []}
    viz = {str(scene.get("visualization") or "") for scene in scenes or []}
    if kinds & _ROBBERY or "xg_race" in viz:
        return "shock"
    if kinds & _RIOT or viz & _GOAL_VIZ:
        return "riot"
    return "pulse"


def bpm_for(scenes: list[dict[str, Any]] | None, style: str | None = None) -> float:
    chosen = style or style_for_scenes(scenes)
    return float(STYLES.get(chosen, STYLES["pulse"])["bpm"])


def ensure_bed(
    out_dir: Path,
    scenes: list[dict[str, Any]] | None = None,
    *,
    ffmpeg: str | None = None,
    style: str | None = None,
    seconds: float = LOOP_SECONDS,
) -> Path | None:
    """Write ``out_dir/music_bed.wav``, generating a cached lavfi loop if needed."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    chosen = style or style_for_scenes(scenes)
    if chosen not in STYLES:
        chosen = "pulse"
    cache = _cached_loop(chosen, ffmpeg=ffmpeg, seconds=seconds)
    if cache is None:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / "music_bed.wav"
    if destination.resolve() != cache.resolve():
        shutil.copy2(cache, destination)
    print(f"  [audio] original music bed: {chosen} {bpm_for(scenes, chosen):.0f} bpm (ffmpeg lavfi, not a catalog track)")
    return destination if destination.exists() else cache


def _cached_loop(style: str, *, ffmpeg: str | None, seconds: float) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{style}_{int(seconds)}s.wav"
    if path.exists() and path.stat().st_size > 1000:
        return path
    if not ffmpeg:
        print("  [audio] ffmpeg not on PATH; cannot generate a music bed")
        return None
    if _render_lavfi_loop(path, style, ffmpeg=ffmpeg, seconds=seconds):
        return path
    print(f"  [audio] lavfi bed ({style}) failed")
    return None


def _render_lavfi_loop(path: Path, style: str, *, ffmpeg: str, seconds: float) -> bool:
    cfg = STYLES[style]
    beat = 60.0 / float(cfg["bpm"])
    # Kick on every beat, hat on every 8th, snare on 2 and 4. Commas inside
    # aevalsrc expressions have to be escaped so lavfi does not split filters.
    kick = (
        f"aevalsrc=exprs="
        f"{float(cfg['kick_drive'])}*(sin(2*PI*{float(cfg['kick_hz'])}*t)"
        f"+0.35*sin(2*PI*{float(cfg['kick_hz'])*2}*t))"
        f"*exp(-13*mod(t\\,{beat:.4f})):s={RATE}:d={seconds:.3f}"
    )
    hat = (
        f"aevalsrc=exprs="
        f"{float(cfg['hat_drive'])}*sin(2*PI*7800*t)*exp(-48*mod(t\\,{beat/2:.4f}))"
        f":s={RATE}:d={seconds:.3f}"
    )
    snare = (
        f"aevalsrc=exprs="
        f"0.22*sin(2*PI*190*t)*exp(-18*mod(t+{beat:.4f}\\,{beat*2:.4f}))"
        f":s={RATE}:d={seconds:.3f}"
    )
    sub = f"sine=frequency={float(cfg['sub_hz'])}:sample_rate={RATE}:duration={seconds:.3f}"
    pulse = f"sine=frequency={float(cfg['pulse_hz'])}:sample_rate={RATE}:duration={seconds:.3f}"
    stab = f"sine=frequency={float(cfg['stab_hz'])}:sample_rate={RATE}:duration={seconds:.3f}"
    air = f"anoisesrc=color=brown:sample_rate={RATE}:amplitude={float(cfg['noise'])}:duration={seconds:.3f}"

    filters = (
        f"[0]highpass=f=20,lowpass=f=180,volume=0.85[kick];"
        f"[1]highpass=f=6000,volume=0.9[hat];"
        f"[2]bandpass=f=1800:width_type=h:w=1600,volume=0.55[snare];"
        f"[3]lowpass=f=90,volume=0.42[sub];"
        f"[4]tremolo=f=2:d=0.72,lowpass=f=420,volume=0.22[pulse];"
        f"[5]tremolo=f=1:d=0.45,chorus=0.4:0.6:40:0.25:0.18:1.5,volume=0.10[stab];"
        f"[6]lowpass=f=650,highpass=f=80,volume=0.55[air];"
        f"[kick][hat][snare][sub][pulse][stab][air]"
        f"amix=inputs=7:duration=first:dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.90:attack=5:release=60:level=false,"
        f"aformat=sample_fmts=s16:sample_rates={RATE}:channel_layouts=stereo[a]"
    )
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", kick,
        "-f", "lavfi", "-i", hat,
        "-f", "lavfi", "-i", snare,
        "-f", "lavfi", "-i", sub,
        "-f", "lavfi", "-i", pulse,
        "-f", "lavfi", "-i", stab,
        "-f", "lavfi", "-i", air,
        "-filter_complex", filters,
        "-map", "[a]",
        "-t", f"{seconds:.3f}",
        "-c:a", "pcm_s16le",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not path.exists() or path.stat().st_size < 1000:
        err = (result.stderr or result.stdout or "").strip()[:400]
        if err:
            print(f"  [audio] lavfi bed failed: {err}")
        if path.exists():
            path.unlink(missing_ok=True)
        return False
    return True
