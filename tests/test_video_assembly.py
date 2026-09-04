"""Frame-timebase contract for artifact-free ffmpeg assembly."""

from __future__ import annotations

import unittest

from recap import timing, video


class AssemblyFilterTests(unittest.TestCase):
    def test_every_join_is_normalized_to_frame_timebase(self):
        scenes = [
            {"clip": 0.8, "cut": "hard"},
            {"clip": 5.5, "cut": "hard"},
            {"clip": 6.0, "cut": "fade"},
            {"clip": 5.0, "cut": "fade"},
        ]
        graph, label = video._assembly_filter(scenes, 24)
        self.assertNotIn("settb=AVTB", graph)
        self.assertIn("settb=1/24", graph)
        self.assertIn("setpts=N/24/TB", graph)
        self.assertIn("xfade=transition=fade", graph)
        self.assertIn("[raw2]fps=24,settb=1/24", graph)
        self.assertIn("[raw3]fps=24,settb=1/24", graph)
        self.assertEqual(label, "x3")

    def test_subtitles_do_not_split_at_club_abbreviation(self):
        chunks = timing._split_for_subtitles(
            "Atl. Madrid won 0-2; Barcelona led shots 18-5. Who was best?"
        )
        self.assertFalse(any(chunk == "Atl." for chunk in chunks))
        self.assertTrue(chunks[0].startswith("Atl. Madrid"))

    def test_audio_encode_uses_explicit_duration_not_shortest(self):
        args = video._audio_encode_args(17.5)
        self.assertNotIn("-shortest", args)
        self.assertIn("apad", args)
        self.assertIn("-t", args)
        self.assertIn("17.500", args)
        self.assertIn("settb=1/24", video._assembly_filter(
            [{"clip": 2.0, "cut": "hard"}, {"clip": 5.0, "cut": "fade"}], 24
        )[0])


if __name__ == "__main__":
    unittest.main()
