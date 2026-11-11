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
from unittest.mock import patch

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

    def test_tile_batches_preserve_order_offsets_thresholds_and_class_filters(self):
        class Model:
            def __init__(self):
                self.calls=[]

            def predict(self, **kwargs):
                self.calls.append(kwargs)
                source=kwargs['source']
                images=source if isinstance(source,list) else [source]
                results=[]
                for image in images:
                    confidence=.6+int(image[0,0,0])/1000
                    candidates=[box(29,confidence,[2,3,20,12]),box(16,.9,[25,20,45,40]),box(0,.8,[50,20,65,40])]
                    results.append(SimpleNamespace(boxes=[b for b in candidates if int(b.cls[0]) in kwargs['classes']]))
                return results

        names={29:'frisbee',16:'dog',0:'person'}
        for width,height in ((201,103),(73,131)):
            frame=np.zeros((height,width,3),dtype=np.uint8)
            frame[:,:,0]=np.arange(width,dtype=np.uint8)
            before=frame.copy()
            for grid in (2,3):
                expected=detect_frame(Model(),frame,names,grid=grid,disc_confidence=.5)
                for batch_size in (2,4,9):
                    with self.subTest(width=width,height=height,grid=grid,batch_size=batch_size):
                        model=Model()
                        actual=detect_frame(model,frame,names,grid=grid,disc_confidence=.5,tile_batch_size=batch_size)
                        self.assertEqual(actual,expected)
                        tiles=crop_grid(width,height,grid)
                        self.assertEqual(len(model.calls),1+(len(tiles)+batch_size-1)//batch_size)
                        self.assertEqual(model.calls[0]['classes'],[29,16,0])
                        for call in model.calls[1:]:
                            self.assertEqual(call['classes'],[29])
                            self.assertEqual(call['conf'],.5)
                            self.assertEqual(call['imgsz'],960)
                            if isinstance(call['source'],list):
                                self.assertTrue(call['rect'])
                                self.assertEqual(len({image.shape for image in call['source']}),1)
                        self.assertTrue(np.array_equal(frame,before))

    def test_unequal_tile_shapes_use_individual_rectangular_inference(self):
        class Model:
            def __init__(self):self.calls=[]
            def predict(self, **kwargs):
                self.calls.append(kwargs)
                return [SimpleNamespace(boxes=[])]
        model=Model()
        with patch('cv.detect_disc_video.crop_grid',return_value=[(0,0,40,30),(40,0,90,40)]):
            detect_frame(model,np.zeros((100,100,3),dtype=np.uint8),{29:'frisbee'},tile_batch_size=4)
        self.assertEqual(len(model.calls),3)
        self.assertTrue(all(isinstance(call['source'],np.ndarray) for call in model.calls))

    def test_invalid_batch_size_and_incomplete_batch_predictions_are_rejected(self):
        class Model:
            def predict(self, **kwargs):return [SimpleNamespace(boxes=[])]
        frame=np.zeros((100,100,3),dtype=np.uint8)
        for batch_size in (0,-1,True,1.5):
            with self.subTest(batch_size=batch_size),self.assertRaisesRegex(ValueError,'positive integer'):
                detect_frame(Model(),frame,{29:'frisbee'},tile_batch_size=batch_size)
        with self.assertRaisesRegex(RuntimeError,'prediction count'):
            detect_frame(Model(),frame,{29:'frisbee'},tile_batch_size=4)


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
            readonly=list(iter_source_frames(source,[index[1],index[3]],metadata,tools,mutable=False))
            self.assertEqual([record for record,frame in readonly],[record for record,frame in decoded])
            # Compare after exhausting the generator: retained byte-backed frames
            # must keep their own pixels when the next source frame is read.
            for (record,frame),(readonly_record,readonly_frame) in zip(decoded,readonly):
                self.assertTrue(frame.flags.writeable)
                self.assertFalse(readonly_frame.flags.writeable)
                self.assertTrue(np.array_equal(frame,readonly_frame))


if __name__ == '__main__':
    unittest.main()
