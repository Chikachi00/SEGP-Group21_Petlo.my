"""Regression checks for original-pixel crops, class thresholds, and real BGR frames."""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from cv.detect_disc_video import Detection, crop_grid, detect_frame, merge_discs, convert_boxes
from cv.video_tools.media import Toolchain, iter_source_frames, scan_video


def box(label, confidence, bounds):
    return SimpleNamespace(cls=np.array([label]), conf=np.array([confidence]), xyxy=np.array([bounds], dtype=float))


class DiscDetectorContracts(unittest.TestCase):
    def test_overlapping_crops_cover_both_landscape_and_portrait(self):
        for width, height in ((201, 103), (73, 131)):
            covered = np.zeros((height, width), dtype=bool)
            for x1, y1, x2, y2 in crop_grid(width, height, 2, .2):
                self.assertTrue(0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height)
                covered[y1:y2, x1:x2] = True
            self.assertTrue(covered.all())
        with self.assertRaises(ValueError):
            crop_grid(100, 100, 2, float('nan'))

    def test_tile_boxes_return_to_full_coordinates_and_are_clipped(self):
        result = SimpleNamespace(boxes=[box(29, .8, [-5, 4, 60, 40])])
        detections = convert_boxes(result, {29: 'frisbee'}, (100, 80), (70, 50), 'tile')
        self.assertEqual(detections[0].bbox, [65., 54., 100., 80.])
        self.assertEqual(detections[0].origin, 'tile')

    def test_full_tile_duplicates_merge_without_removing_a_second_disc(self):
        detections = [Detection([10, 10, 30, 30], .4, 'frisbee', 'full'),
                      Detection([11, 10, 31, 30], .8, 'frisbee', 'tile'),
                      Detection([100, 100, 120, 120], .7, 'frisbee', 'tile'),
                      Detection([10, 10, 30, 30], .9, 'dog', 'full')]
        result = merge_discs(detections)
        self.assertEqual(len(result), 3)
        self.assertEqual(sum(d.label == 'frisbee' for d in result), 2)
        self.assertNotIn(detections[0], result)

    def test_disc_threshold_does_not_lower_dog_or_person_threshold(self):
        class Model:
            def predict(self, **kwargs):
                self.kwargs = kwargs
                return [SimpleNamespace(boxes=[box(29, .12, [1, 2, 5, 6]),
                                                box(16, .12, [20, 20, 30, 30]),
                                                box(0, .8, [40, 40, 50, 50])])]
        model = Model()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        before = frame.copy()
        detections = detect_frame(model, frame, {29: 'frisbee', 16: 'dog', 0: 'person'},
                                  confidence=.25, disc_confidence=.1, grid=0)
        self.assertEqual({d.label for d in detections}, {'frisbee', 'person'})
        self.assertEqual(model.kwargs['conf'], .1)
        self.assertTrue(np.array_equal(frame, before))


class OriginalBGRContracts(unittest.TestCase):
    def test_bgr_stream_selects_real_vfr_pts_without_inserted_frames(self):
        try:
            tools = Toolchain.discover(os.environ.get('VIDEO_TOOLS_FFMPEG_DIR'))
        except RuntimeError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory(prefix='disc-bgr-') as temporary:
            source = Path(temporary) / 'vfr.mkv'
            encoded = subprocess.run([tools.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                                      '-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=10:duration=1',
                                      '-vf', 'select=eq(n\\,0)+eq(n\\,1)+eq(n\\,4)+eq(n\\,9)',
                                      '-fps_mode', 'vfr', '-c:v', 'ffv1', str(source)], capture_output=True)
            self.assertEqual(encoded.returncode, 0, encoded.stderr)
            metadata, index, _ = scan_video(source, tools)
            decoded = list(iter_source_frames(source, [index[1], index[3]], metadata, tools))
            self.assertEqual([r['frame_id'] for r, frame in decoded], [1, 3])
            self.assertEqual([r['t_sec'] for r, frame in decoded], [.1, .9])
            self.assertTrue(all(frame.shape == (64, 96, 3) for r, frame in decoded))
            self.assertFalse(np.array_equal(decoded[0][1], decoded[1][1]))


if __name__ == '__main__':
    unittest.main()
