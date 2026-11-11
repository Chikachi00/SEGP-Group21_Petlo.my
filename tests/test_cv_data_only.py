"""Real-frame equivalence and skipped rendering for backend data-only stages."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from cv import detect_disc_video, track_dog_video, track_disc_recovered_video
from cv.track_dog_video import read_json, sha256, write_json
from cv.video_tools.media import Toolchain, scan_video


class SavedModel:
    names = {0: 'person', 16: 'dog', 29: 'frisbee'}

    def __init__(self):
        self.calls = 0

    def predict(self, **kwargs):
        self.calls += 1
        return [SimpleNamespace(boxes=[SimpleNamespace(cls=[29], conf=[.8],
                xyxy=np.array([[40., 100., 64., 112.]]))])]


class DataOnlyMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.tools = Toolchain.discover()
        except (ValueError, OSError, RuntimeError) as exc:
            raise unittest.SkipTest(str(exc))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cv-data-only-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = self.root / 'raw'
        raw.mkdir()
        images = self.root / 'images'
        images.mkdir()
        for i in range(14):
            frame = np.zeros((240, 400, 3), dtype=np.uint8)
            frame[100:112, 40 + 8 * i:64 + 8 * i] = (220, 140, 40)
            cv2.imwrite(str(images / f'{i:03d}.png'), frame)
        self.source = raw / 'disc.mkv'
        subprocess.run([self.tools.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-framerate', '50', '-i', str(images / '%03d.png'),
                        '-vf', 'select=lte(n\\,6)+eq(n\\,8)+eq(n\\,10)+gte(n\\,12)',
                        '-fps_mode', 'vfr', '-c:v', 'ffv1', str(self.source)], capture_output=True, check=True)
        metadata, self.index, _ = scan_video(self.source, self.tools)
        self.pack = self.root / 'pack'
        self.pack.mkdir()
        write_json(self.pack / 'frames.json', self.index)
        video = {'id': 'disc', 'source': str(self.source), 'source_sha256': sha256(self.source),
                 'status': 'complete', 'role': 'action', 'width': 400, 'height': 240,
                 'frames_count': len(self.index), 'duration': metadata['duration'], 'metadata': metadata,
                 'paths': {'frame_index': 'frames.json'}}
        write_json(self.pack / 'manifest.json', {'videos': [video]})
        self.det = self.root / 'detections.jsonl'
        rows = []
        for record in self.index:
            x = 40 + 8 * round(record['t_sec'] * 50)
            discs = [{'label': 'disc', 'bbox': [float(x), 100., float(x + 24), 112.], 'confidence': .8}]
            if .12 <= record['t_sec'] < .24:
                discs = []
            rows.append({'video_id': 'disc', **record, 'detections': discs + [
                {'label': 'dog', 'bbox': [200., 100., 250., 180.], 'confidence': .9}]})
        self.det.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        write_json(self.det.with_suffix('.json'), {'status': 'complete', 'video_id': 'disc',
                   'source': str(self.source), 'source_sha256': video['source_sha256'],
                   'first_frame': self.index[0], 'last_frame': self.index[-1],
                   'counts': {'processed_frames': 11, 'disc_frames': 8, 'dog_frames': 11, 'person_frames': 0}})
        self.weights = self.root / 'fake-model.pt'
        self.weights.write_bytes(b'local weights provenance fixture; shared model injected')

    def run_tracking(self, module, output, **kwargs):
        return module.run(self.det, self.pack, output, ffmpeg_dir=Path(self.tools.ffmpeg).parent, **kwargs)

    def test_dog_data_matches_rendered_evidence_without_source_decode(self):
        module = track_dog_video
        rendered, data = self.root / 'dog-review', self.root / 'dog-data'
        self.run_tracking(module, rendered)
        with (patch.object(module, 'iter_source_frames', side_effect=AssertionError('source decoded')),
             patch.object(module, 'annotate', side_effect=AssertionError('frame annotated')),
             patch.object(cv2, 'VideoWriter', side_effect=AssertionError('video encoded'))):
            summary = self.run_tracking(module, data, render=False)
        self.assert_data_equivalent(rendered, data, summary)

    def test_recovery_data_matches_rendered_visual_measurements_and_reuses_model(self):
        module = track_disc_recovered_video
        rendered, data = self.root / 'disc-review', self.root / 'disc-data'
        options = {'model': SavedModel(), 'model_path': self.weights}
        self.run_tracking(module, rendered, **options)
        with (patch.object(module, 'load_detection_model', side_effect=AssertionError('model reloaded')),
             patch.object(module, 'annotate', side_effect=AssertionError('frame annotated')),
             patch.object(cv2, 'VideoWriter', side_effect=AssertionError('video encoded')),
             patch.object(cv2, 'imwrite', side_effect=AssertionError('audit image written'))):
            summary = self.run_tracking(module, data, render=False, **options)
        self.assert_data_equivalent(rendered, data, summary)
        self.assertEqual(summary['recovery_counts']['colour_accepted'], 3)

    def assert_data_equivalent(self, rendered, data, summary):
        for name in ('tracks.jsonl', 'states.jsonl', 'trajectory.csv'):
            self.assertEqual((rendered / name).read_bytes(), (data / name).read_bytes(), name)
        self.assertEqual(summary['processed_frames'], len(self.index))
        self.assertFalse(summary['provenance']['render_review'])
        self.assertIsNone(summary['validated']['output_frame_count'])
        self.assertEqual(set(summary['artifact_sha256']), {'tracks.jsonl', 'states.jsonl', 'trajectory.csv'})
        self.assertEqual({p.suffix for p in data.iterdir()}, {'.json', '.jsonl', '.csv'})

    def test_tracking_cache_separates_modes_and_requires_evidence_artifacts(self):
        for module in (track_dog_video, track_disc_recovered_video):
            with self.subTest(module=module.__name__):
                output = self.root / module.__name__.split('.')[-1]
                summary = self.run_tracking(module, output, render=False)
                self.assertEqual(self.run_tracking(module, output, render=False)['cache_key'], summary['cache_key'])
                with self.assertRaisesRegex(ValueError, 'different'):
                    self.run_tracking(module, output, render=True)
                del summary['artifact_sha256']['states.jsonl']
                write_json(output / 'summary.json', summary)
                with self.assertRaisesRegex(ValueError, 'Invalid cached output manifest'):
                    self.run_tracking(module, output, render=False)

    def test_detection_runs_every_frame_with_identical_data_and_no_writer(self):
        args = argparse.Namespace(video=self.source, pack=self.pack, output=self.root / 'review.mp4',
            mode='baseline', imgsz=None, confidence=.25, disc_confidence=.25, disc_grid=0,
            tile_imgsz=960, overlap=.2, device='cpu', model=str(self.weights), cpu_threads=1,
            ffmpeg_dir=Path(self.tools.ffmpeg).parent, start=0., end=None)
        rendered_model = SavedModel()
        detect_disc_video.run(args, model=rendered_model)
        args.output = self.root / 'data.mp4'
        args.tile_batch_size = 4
        data_model = SavedModel()
        with (patch.object(detect_disc_video, 'load_detection_model', side_effect=AssertionError('model reloaded')),
             patch.object(detect_disc_video, 'draw_detection', side_effect=AssertionError('frame annotated')),
             patch.object(cv2, 'VideoWriter', side_effect=AssertionError('video encoded'))):
            report = detect_disc_video.run(args, model=data_model, render=False)
        self.assertEqual(rendered_model.calls, len(self.index))
        self.assertEqual(data_model.calls, len(self.index))
        self.assertEqual((self.root / 'review.jsonl').read_bytes(), (self.root / 'data.jsonl').read_bytes())
        self.assertFalse(args.output.exists())
        self.assertIsNone(report['video'])
        self.assertFalse(report['render_review'])
        self.assertEqual(report['settings']['tile_batch_size'],4)
        self.assertEqual(report['counts']['processed_frames'], len(self.index))

    def test_data_only_tracking_still_rejects_invalid_timestamp_index(self):
        rows = [json.loads(line) for line in self.det.read_text().splitlines()]
        rows[1]['t_sec'] += .005
        self.det.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        for module in (track_dog_video, track_disc_recovered_video):
            with self.subTest(module=module.__name__), self.assertRaisesRegex(ValueError, 'Detector time'):
                self.run_tracking(module, self.root / module.__name__.split('.')[-1], render=False)

    def test_recovery_records_device_and_rejects_cache_for_another_device(self):
        module=track_disc_recovered_video
        output=self.root/'device-data'
        with patch.object(module,'RecoveryTracker',wraps=module.RecoveryTracker) as tracker:
            summary=self.run_tracking(module,output,render=False,model=SavedModel(),model_path=self.weights,device='0')
        self.assertEqual(tracker.call_args.kwargs['device'],'0')
        self.assertEqual(summary['provenance']['device'],'0')
        with self.assertRaisesRegex(ValueError,'different input/settings'):
            self.run_tracking(module,output,render=False,model=SavedModel(),model_path=self.weights,device='cpu')


if __name__ == '__main__':
    unittest.main()
