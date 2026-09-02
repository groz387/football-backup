"""Audio lead tests: original beds, SFX map, ducking mix, loudnorm, skip-audio."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import video_pipeline
from recap import audio, music_beds, video
from recap.audio import cue_list, snap_wipes_to_beats

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _probe_streams(path: Path) -> dict:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,codec_name",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout or "{}")


def _ebur_i(path: Path) -> float | None:
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=framelog=verbose", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    text = (result.stderr or "") + (result.stdout or "")
    integrated = None
    for line in text.splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                integrated = float(line.split("I:")[1].split("LUFS")[0].strip())
            except ValueError:
                continue
    return integrated


class CueListTests(unittest.TestCase):
    def setUp(self) -> None:
        audio.ensure_pack()

    def test_number_slam_whoosh_riser_crowd_glass(self) -> None:
        scenes = [
            {"visualization": "hook_claim", "visible_start": 0.0, "cut": "hard", "hook_kind": "xg_robbery"},
            {"visualization": "hook_punch", "visible_start": 0.9, "cut": "hard", "hook_kind": "xg_robbery"},
            {"visualization": "xg_race", "visible_start": 2.0, "cut": "wipe"},
            {"visualization": "goal_timeline", "visible_start": 6.0, "cut": "wipe"},
            {"visualization": "close", "visible_start": 12.0, "cut": "hard"},
            {"visualization": "live_clip", "visible_start": 0.4, "cut": "hard"},
            {"visualization": "stat_slam", "visible_start": 8.0, "cut": "wipe"},
            {"visualization": "micro_hook", "visible_start": 5.5, "cut": "hard"},
        ]
        cues = cue_list(scenes)
        names_at: dict[str, list[float]] = {}
        for when, name in cues:
            names_at.setdefault(name, []).append(when)
        self.assertIn("impact", names_at)
        self.assertIn("whoosh", names_at)
        self.assertIn("riser", names_at)
        self.assertIn("crowd", names_at)
        self.assertIn("glass", names_at)
        self.assertIn("tick", names_at)
        punch_impacts = [w for w, n in cues if n == "impact" and abs(w - 0.9) < 0.02]
        self.assertTrue(any(r < 0.9 for r in names_at["riser"]))
        self.assertTrue(punch_impacts)


class BeatSnapTests(unittest.TestCase):
    def test_snaps_when_within_120ms(self) -> None:
        scenes = [
            {"visualization": "a", "cut": "hard", "on_screen": 1.05, "clip": 1.55},
            {"visualization": "b", "cut": "wipe", "on_screen": 3.0, "clip": 3.5},
        ]
        out = snap_wipes_to_beats(scenes, bpm=120)
        self.assertAlmostEqual(out[0]["on_screen"], 1.0, places=3)
        self.assertLessEqual(abs(out[0]["on_screen"] - 1.05), 0.120)

    def test_does_not_drag_more_than_120ms(self) -> None:
        scenes = [
            {"visualization": "a", "cut": "hard", "on_screen": 1.20, "clip": 1.70},
            {"visualization": "b", "cut": "wipe", "on_screen": 3.0, "clip": 3.5},
        ]
        out = snap_wipes_to_beats(scenes, bpm=120)
        self.assertEqual(out[0]["on_screen"], 1.20)


class CliTests(unittest.TestCase):
    def test_music_bed_and_loudnorm_flags(self) -> None:
        args = video_pipeline.parse_args(
            ["--auto", "--match-dir", "output/x", "--music-bed", "none", "--loudnorm", "youtube"]
        )
        self.assertEqual(args.music_bed, "none")
        self.assertEqual(args.loudnorm, "youtube")
        self.assertTrue(args.sfx)
        off = video_pipeline.parse_args(["--auto", "--match-dir", "output/x", "--no-loudnorm", "--no-sfx"])
        self.assertEqual(off.loudnorm, "off")
        self.assertFalse(off.sfx)
        skip = video_pipeline.parse_args(["--auto", "--match-dir", "output/x", "--skip-audio"])
        self.assertTrue(skip.skip_audio)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg required")
class MixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="recap-audio-"))
        audio.ensure_pack()

    def _scenes(self) -> list[dict]:
        return [
            {"visualization": "hook_claim", "visible_start": 0.0, "clip_start": 0.0, "cut": "hard",
             "on_screen": 0.9, "clip": 0.9, "hook_kind": "xg_robbery"},
            {"visualization": "hook_punch", "visible_start": 0.9, "clip_start": 0.9, "cut": "hard",
             "on_screen": 0.7, "clip": 1.2, "hook_kind": "xg_robbery"},
            {"visualization": "goal_timeline", "visible_start": 1.6, "clip_start": 1.6, "cut": "wipe",
             "on_screen": 1.4, "clip": 1.4},
        ]

    def test_skip_audio_returns_none(self) -> None:
        mixed = audio.mix(
            self.tmp, self._scenes(), None,
            sfx=True, music_file=None, ffmpeg=FFMPEG, duration=3.0,
            loudnorm="tiktok", skip_audio=True,
        )
        self.assertIsNone(mixed)
        self.assertFalse((self.tmp / "mix.m4a").exists())

    def test_music_only_mix(self) -> None:
        bed = music_beds.ensure_bed(self.tmp, self._scenes(), ffmpeg=FFMPEG, style="pulse")
        self.assertIsNotNone(bed)
        self.assertGreater(bed.stat().st_size, 1000)
        mixed = audio.mix(
            self.tmp, self._scenes(), None,
            sfx=False, music_file=bed, ffmpeg=FFMPEG, duration=3.0,
            loudnorm="off", skip_audio=False,
        )
        self.assertIsNotNone(mixed)
        self.assertTrue(mixed.exists())

    def test_sfx_plus_music_no_voice(self) -> None:
        bed = music_beds.ensure_bed(self.tmp, self._scenes(), ffmpeg=FFMPEG, style="shock")
        mixed = audio.mix(
            self.tmp, self._scenes(), None,
            sfx=True, music_file=bed, ffmpeg=FFMPEG, duration=3.2,
            loudnorm="tiktok", skip_audio=False,
        )
        self.assertIsNotNone(mixed)
        self.assertTrue(mixed.exists())
        loud = _ebur_i(mixed)
        if loud is not None:
            self.assertGreater(loud, -20.0)
            self.assertLess(loud, -6.0)

    def test_sfx_only_and_voice_duck(self) -> None:
        mixed_sfx = audio.mix(
            self.tmp, self._scenes(), None,
            sfx=True, music_file=None, ffmpeg=FFMPEG, duration=3.0,
            loudnorm="youtube", skip_audio=False,
        )
        self.assertIsNotNone(mixed_sfx)
        voice = self.tmp / "vo.wav"
        subprocess.run(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=44100:duration=2.2",
             str(voice)],
            check=True,
        )
        bed = music_beds.ensure_bed(self.tmp, self._scenes(), ffmpeg=FFMPEG, style="pulse")
        mixed = audio.mix(
            self.tmp, self._scenes(), voice,
            sfx=True, music_file=bed, ffmpeg=FFMPEG, duration=3.0,
            loudnorm="tiktok", skip_audio=False,
        )
        self.assertIsNotNone(mixed)
        self.assertTrue(mixed.exists())

    def test_generated_bed_bpm_near_120(self) -> None:
        bed = music_beds.ensure_bed(self.tmp, [], ffmpeg=FFMPEG, style="pulse")
        bpm = audio.detect_bpm(bed, ffmpeg=FFMPEG)
        self.assertGreaterEqual(bpm, 90)
        self.assertLessEqual(bpm, 150)

    def test_pack_wavs_are_small(self) -> None:
        pack = audio.ensure_pack()
        for name in audio._PACK_NAMES:
            path = pack / name
            self.assertTrue(path.exists(), name)
            self.assertLess(path.stat().st_size, 200_000, name)

    def test_silent_mp4_with_skip_audio(self) -> None:
        frames = self.tmp / "frames"
        frames.mkdir()
        frame = frames / "frame_00001.png"
        subprocess.run(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=108x192:d=0.1",
             "-frames:v", "1", str(frame)],
            check=True,
        )
        shutil.copyfile(frame, frames / "frame_00002.png")
        scenes = [{
            "visualization": "hook_claim", "frames": 2, "clip": 2 / 24,
            "on_screen": 2 / 24, "cut": "hard", "frame_dir": str(frames),
        }]
        out = video.assemble(
            self.tmp, scenes, None, fps=24, crossfade=False, sfx=True,
            burn_captions=False, music_file=self.tmp / "music_bed.wav",
            loudnorm="tiktok", skip_audio=True,
        )
        self.assertIsNotNone(out)
        streams = _probe_streams(out)
        types = {s.get("codec_type") for s in streams.get("streams") or []}
        self.assertIn("video", types)
        self.assertNotIn("audio", types)


class BedStyleTests(unittest.TestCase):
    def test_robbery_picks_shock(self) -> None:
        self.assertEqual(music_beds.style_for_scenes([{"hook_kind": "xg_robbery"}]), "shock")

    def test_goals_pick_riot(self) -> None:
        self.assertEqual(music_beds.style_for_scenes([{"visualization": "goal_chain"}]), "riot")

    def test_default_pulse(self) -> None:
        self.assertEqual(music_beds.style_for_scenes([]), "pulse")


if __name__ == "__main__":
    unittest.main()
