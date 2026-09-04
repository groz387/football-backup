"""Frame-timebase contract for artifact-free ffmpeg assembly."""

from __future__ import annotations

import unittest

from recap import video


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


if __name__ == "__main__":
    unittest.main()
