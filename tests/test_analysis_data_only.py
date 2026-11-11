"""Analysis data stays identical when API runs omit offline review artifacts."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cv.analyze_dog_disc import run as run_joint, sha256, write_json
from cv.analyze_throw_events import make_link_features
from cv.analyze_throw_events_v3 import run as run_events
from cv.video_tools.media import Toolchain, scan_video


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row, allow_nan=False) + '\n' for row in rows), encoding='utf-8')


class JointDataOnlyTests(unittest.TestCase):
    def test_data_matches_review_and_cache_checks_mode_and_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, pack = root / 'raw', root / 'pack'
            raw.mkdir()
            pack.mkdir()
            source = raw / 'sample.mp4'
            source.write_bytes(b'source provenance fixture')
            records = [{'frame_id': index, 't_sec': index * .04, 'pts_sec': index * .04 + 2,
                        'timestamp_source': 'pts_time'} for index in range(30)]
            write_json(pack / 'frames.json', records)
            write_json(pack / 'manifest.json', {'videos': [{'id': 'test', 'source': str(source), 'source_sha256': sha256(source),
                'status': 'complete', 'role': 'action', 'camera': 'tripod', 'width': 1000, 'height': 600, 'frames_count': len(records),
                'paths': {'frame_index': 'frames.json'}, 'metadata': {'avg_frame_rate': 25.}}]})
            for kind in ('dog', 'disc'):
                tracking = root / kind
                tracking.mkdir()
                rows = []
                for index, record in enumerate(records):
                    observation = {'track_id': f'{kind}-001', 'state': 'detected', 'confidence': .9, 'prediction_bbox': None,
                        'bbox': [350., 170., 430., 280.] if kind == 'dog' else [50. + index * 16, 200., 70. + index * 16, 210.]}
                    if kind == 'disc':
                        observation['measurement_source'] = 'saved_detector'
                    rows.append({**record, **observation} if kind == 'dog' else {**record, 'tracks': [observation]})
                write_rows(tracking / 'states.jsonl', rows)
                write_json(tracking / 'summary.json', {'status': 'complete', 'video_id': 'test', 'source': str(source),
                    'processed_frames': len(records), 'artifact_sha256': {'states.jsonl': sha256(tracking / 'states.jsonl')},
                    'provenance': {'source_sha256': sha256(source), 'detections_sha256': 'same detector', 'display_size': [1000, 600]}})
            args = (root / 'dog', root / 'disc', pack)
            review = run_joint(*args, root / 'review')
            with patch('cv.analyze_dog_disc.review_page', side_effect=AssertionError('Review rendering must be skipped')):
                data = run_joint(*args, root / 'data', preview=root / 'missing.mp4', review=False)
            self.assertEqual(review['metrics'], data['metrics'])
            self.assertFalse(data['provenance']['review'])
            self.assertNotEqual(review['cache_key'], data['cache_key'])
            for name in ('joint-states.jsonl', 'events.json'):
                self.assertEqual((root / 'review' / name).read_bytes(), (root / 'data' / name).read_bytes())
            self.assertEqual(set(data['artifact_sha256']), {'joint-states.jsonl', 'events.json'})
            self.assertEqual({path.name for path in (root / 'data').iterdir()}, {'joint-states.jsonl', 'events.json', 'summary.json'})
            self.assertEqual(data, run_joint(*args, root / 'data', review=False))
            with self.assertRaisesRegex(ValueError, 'Existing output differs'):
                run_joint(*args, root / 'data')
            (root / 'data' / 'events.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Output cache changed'):
                run_joint(*args, root / 'data', review=False)


class EventDataOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = Toolchain.discover()

    def create_inputs(self, root):
        raw, pack, joint = root / 'raw', root / 'pack', root / 'joint'
        for path in (raw, pack, joint):
            path.mkdir()
        source = raw / 'sample.mkv'
        subprocess.run([self.tools.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=1000x600:rate=25:duration=3',
                        '-c:v', 'ffv1', str(source)], capture_output=True, check=True)
        metadata, records, _ = scan_video(source, self.tools)
        video = {'id': 'test', 'source': str(source), 'source_sha256': sha256(source), 'status': 'complete', 'role': 'action',
            'camera': 'tripod', 'width': 1000, 'height': 600, 'frames_count': len(records), 'duration': metadata['duration'],
            'paths': {'frame_index': 'frames.json'}, 'metadata': metadata}
        write_json(pack / 'manifest.json', {'videos': [video]})
        write_json(pack / 'frames.json', records)
        frames, detector_rows = [], []
        for record in records:
            second = record['t_sec']
            dog_x = 400 if second < .8 else 400 + (second - .8) * 100
            disc_x = 50 + 450 * second if second < .8 else 410 + (second - .8) * 100
            frames.append({**record, 'dog': {'track_id': 'dog-001', 'state': 'detected', 'bbox': [dog_x, 170., dog_x + 70, 280.],
                'confidence': .9, 'prediction_bbox': None}, 'discs': [{'disc_id': 'disc-001', 'state': 'detected',
                'bbox': [disc_x, 200., disc_x + 20, 210.], 'confidence': .9, 'prediction_bbox': None,
                'measurement_source': 'saved_detector', 'moving': second < .8, 'approaching': second < .8}]})
            detector_rows.append({**record, 'video_id': 'test', 'detections': [{'label': 'person', 'bbox': [20., 140., 90., 300.], 'confidence': .9}]})
        detections = root / 'detections.jsonl'
        write_rows(detections, detector_rows)
        write_json(detections.with_suffix('.json'), {'status': 'complete', 'source': str(source), 'source_sha256': video['source_sha256'],
            'video_id': 'test', 'first_frame': records[0], 'last_frame': records[-1],
            'counts': {'processed_frames': len(records), 'dog_frames': 0, 'disc_frames': 0, 'person_frames': len(records)}})
        tracker = root / 'tracking-summary.json'
        write_json(tracker, {'provenance': {'detections_sha256': sha256(detections)}})
        write_rows(joint / 'joint-states.jsonl', frames)
        write_json(joint / 'summary.json', {'status': 'complete', 'video_id': 'test', 'metrics': {'processed_frames': len(records)},
            'artifact_sha256': {'joint-states.jsonl': sha256(joint / 'joint-states.jsonl')},
            'provenance': {'source_sha256': video['source_sha256'], 'inputs': {str(tracker): sha256(tracker)}}})
        return video, records, (joint, detections, pack)

    def test_events_states_and_diagnostics_match_review_without_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, records, args = self.create_inputs(root)
            preview = root / 'preview.mp4'
            preview.write_bytes(b'preview sidecar fixture; not used for frame decoding')
            write_json(preview.with_suffix('.json'), {'status': 'complete', 'signature': {'source_sha256': video['source_sha256'],
                'source_frames': len(records)}, 'sha256': sha256(preview)})
            review = run_events(*args, root / 'review', preview, ffmpeg_dir=Path(self.tools.ffmpeg).parent)
            self.assertGreater(review['contact_crop_frames'], 0)
            preview.unlink()
            preview.with_suffix('.json').unlink()
            with patch('cv.analyze_throw_events.make_contact_crops', side_effect=AssertionError('Contact crops must be skipped')), \
                 patch('cv.analyze_throw_events.review_page', side_effect=AssertionError('HTML must be skipped')), \
                 patch('cv.analyze_throw_events.cv2.imwrite', side_effect=AssertionError('Images must be skipped')):
                data = run_events(*args, root / 'data', ffmpeg_dir=Path(self.tools.ffmpeg).parent, review=False)
            self.assertEqual(data['outcome_candidates'], {'catch_candidate': 1})
            self.assertFalse(data['provenance']['review'])
            self.assertEqual(data['contact_crop_frames'], 0)
            artifacts = {'events-v3.json', 'event-states.jsonl', 'diagnostics.json'}
            self.assertEqual(set(data['artifact_sha256']), artifacts)
            self.assertEqual({path.name for path in (root / 'data').iterdir()}, artifacts | {'summary.json'})
            for name in artifacts:
                self.assertEqual((root / 'review' / name).read_bytes(), (root / 'data' / name).read_bytes())
            self.assertEqual(data, run_events(*args, root / 'data', ffmpeg_dir=Path(self.tools.ffmpeg).parent, review=False))
            with self.assertRaisesRegex(ValueError, 'Verified clean source preview required'):
                run_events(*args, root / 'data', ffmpeg_dir=Path(self.tools.ffmpeg).parent)
            preview.write_bytes(b'preview sidecar fixture; not used for frame decoding')
            write_json(preview.with_suffix('.json'), {'status': 'complete', 'signature': {'source_sha256': video['source_sha256'],
                'source_frames': len(records)}, 'sha256': sha256(preview)})
            with self.assertRaisesRegex(ValueError, 'Existing event output differs'):
                run_events(*args, root / 'data', preview, ffmpeg_dir=Path(self.tools.ffmpeg).parent)
            (root / 'data' / 'event-states.jsonl').write_text('{}\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Event cache modified'):
                run_events(*args, root / 'data', ffmpeg_dir=Path(self.tools.ffmpeg).parent, review=False)

    def test_endpoint_colour_features_identical_without_saved_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, records, _ = self.create_inputs(root)
            points = {'disc-001': [{'frame_id': 8, 'bbox': [30., 20., 50., 30.], 'measurement_source': 'saved_detector'}],
                      'disc-002': [{'frame_id': 12, 'bbox': [30., 20., 50., 30.], 'measurement_source': 'saved_detector'}]}
            proposals = [{'from_frame': 8, 'from_disc_id': 'disc-001', 'to_frame': 12, 'to_disc_id': 'disc-002'}]
            review_dir, data_dir = root / 'review', root / 'data'
            review_dir.mkdir()
            data_dir.mkdir()
            features, images = make_link_features(video, records, points, proposals, self.tools, review_dir)
            with patch('cv.analyze_throw_events.cv2.imwrite', side_effect=AssertionError('Audit images must be skipped')):
                data_features, data_images = make_link_features(video, records, points, proposals, self.tools, data_dir, save_images=False)
            self.assertEqual(features, data_features)
            self.assertEqual(set(features), {(8, 'disc-001'), (12, 'disc-002')})
            self.assertEqual(len(images), 2)
            self.assertEqual(data_images, [])
            self.assertEqual(list(data_dir.iterdir()), [])
