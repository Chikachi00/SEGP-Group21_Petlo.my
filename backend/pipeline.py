"""Compatibility adapter: invoke existing commands without editing algorithm code."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ROOT

SAMPLES = {
    'front': ('Landscape_Tripod_FrontView', 'd29fdcda04dae936ced2b300e0d1328fb5b1524343b58ae4e2551da2191ab801'),
    'side': ('Landscape_Tripod_SideView', '505a974f330df5161444649f2d41f3eb4ea07f6ab7bd4012604dbd42f86366e5'),
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def inside(root, key):
    path = (root / key).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Storage key outside root')
    return path


def validate_selection(mode, videos):
    if mode == 'single_view' and len(videos) == 1:
        return
    if mode != 'sample_pair' or len(videos) != 2 or {v['camera_perspective'] for v in videos} != {'front', 'side'}:
        raise ValueError('Choose one video, or the matching front and side samples')
    if any(v['source_sha256'] != SAMPLES[v['camera_perspective']][1] for v in videos):
        raise ValueError('Sample-pair fusion supports only the original matching sample contents')


class PipelineRunner:
    def __init__(self, settings):
        self.settings = settings

    def tools(self):
        from cv.video_tools.media import Toolchain
        return Toolchain.discover(self.settings.ffmpeg_dir)

    def probe(self, path):
        from cv.video_tools.media import probe_video
        return probe_video(path, self.tools())

    def check_ready(self):
        if not self.settings.model.is_file():
            raise ValueError('Local YOLO weights are missing. Configure PETLO_MODEL_PATH first.')
        self.tools()

    def run(self, job_id, mode, videos, update):
        from cv.build_throw_statistics import bucket_outcome, summarize
        validate_selection(mode, videos)
        self.check_ready()
        root = inside(self.settings.storage, f'jobs/{job_id}')
        source = root / 'source'
        source.mkdir(parents=True, exist_ok=False)
        tools = self.tools()
        log = root / 'pipeline.log'

        def command(stage, args):
            update(stage)
            with log.open('ab') as output:
                subprocess.run([str(a) for a in args], cwd=ROOT, shell=False, stdout=output,
                               stderr=subprocess.STDOUT, check=True, timeout=self.settings.stage_timeout)

        def script(stage, name, *args):
            command(stage, [sys.executable, ROOT / 'cv' / name, *args])

        paths = {}
        for video in videos:
            original = inside(self.settings.storage, video['storage_key'])
            if digest(original) != video['source_sha256']:
                raise ValueError('Stored source content changed')
            view = video['camera_perspective']
            # The job directory provides uniqueness; short generated names avoid Windows path limits.
            stem = SAMPLES[view][0] if mode == 'sample_pair' else f'Tripod_{view}'
            copied = source / f'{stem}{original.suffix}'
            shutil.copyfile(original, copied)
            paths[video['video_id']] = copied
        pack = root / 'pack'
        command('prepare', [sys.executable, '-m', 'cv.video_tools', 'prepare', '--source', source,
                            '--output', pack, '--ffmpeg-dir', Path(tools.ffmpeg).parent])
        manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
        if any(v['status'] != 'complete' for v in manifest['videos']):
            raise ValueError('Full source decoding failed')
        # Algorithms require the existing frame-preserving CFR preview and its verified sidecar.
        # Browser playback is generated separately below with original relative source timing.
        evidence_previews = root / 'evidence-previews'
        script('evidence_previews', 'prepare_joint_previews.py', '--pack', pack,
               '--output-dir', evidence_previews, '--ffmpeg-dir', Path(tools.ffmpeg).parent)
        previews, metadata, single_rows, api_events = {}, {}, [], []
        event_root = root / 'throw-events-v3'
        for video in videos:
            key, view = video['video_id'], video['camera_perspective']
            copied = paths[key]
            evidence_preview = evidence_previews / f'{copied.stem}.mp4'
            indexed = next(v for v in manifest['videos'] if v['id'] == copied.stem)
            if indexed['camera'] != 'tripod' or indexed['role'] != 'action':
                raise ValueError('Expected fixed-camera action metadata')
            preview = root / 'previews' / f'{key}.mp4'
            preview.parent.mkdir(exist_ok=True)
            command(f'{view}:preview', [tools.ffmpeg, '-nostdin', '-y', '-v', 'error', '-i', copied,
                '-map', '0:v:0', '-vf', 'setpts=PTS-STARTPTS,scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2',
                '-fps_mode', 'passthrough', '-an', '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast',
                '-crf', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', preview])
            previews[key] = preview.relative_to(self.settings.storage).as_posix()
            metadata[key] = dict(indexed['metadata'], duration=indexed['duration'], width=indexed['width'], height=indexed['height'])
            folder = root / view
            folder.mkdir()
            detector = folder / 'detected.mp4'
            detection_rows = detector.with_suffix('.jsonl')
            ffmpeg_flags = ['--ffmpeg-dir', Path(tools.ffmpeg).parent]
            script(f'{view}:detect', 'detect_disc_video.py', copied, '--pack', pack, '--output', detector,
                   '--model', self.settings.model, *ffmpeg_flags)
            dog, disc, joint = folder / 'dog', folder / 'disc', folder / 'joint'
            script(f'{view}:dog_tracks', 'track_dog_video.py', '--detections', detection_rows, '--pack', pack,
                   '--output-dir', dog, *ffmpeg_flags)
            script(f'{view}:disc_tracks', 'track_disc_recovered_video.py', '--detections', detection_rows,
                   '--pack', pack, '--output-dir', disc, '--model', self.settings.model, *ffmpeg_flags)
            script(f'{view}:joint', 'analyze_dog_disc.py', '--dog-dir', dog, '--disc-dir', disc,
                   '--pack', pack, '--output-dir', joint, '--preview', evidence_preview)
            events_dir = event_root / f'{view}-v1'
            script(f'{view}:events', 'analyze_throw_events_v3.py', '--joint-dir', joint,
                   '--detections', detection_rows, '--pack', pack, '--output-dir', events_dir,
                   '--preview', evidence_preview, *ffmpeg_flags)
            raw = json.loads((events_dir / 'events-v3.json').read_text(encoding='utf-8'))
            if mode == 'single_view':
                for row in raw['event_candidates']:
                    event_id = f'{job_id}-{row["throw_id"]}'
                    interval = [float(row['start_sec']), float(row['end_sec'])]
                    api_events.append({'event_id': event_id, 'category': bucket_outcome(row['predicted_outcome']),
                        'conflict': False, 'source_intervals': [{'video_id': key, 'start_sec': interval[0], 'end_sec': interval[1]}]})
                    single_rows.append({'sample_throw_id': event_id, 'outcome': row['predicted_outcome'],
                                        f'{view}_source_time_sec': interval, f'{view}_outcome': row['predicted_outcome']})
        if mode == 'sample_pair':
            # No --labels argument: reviewed answers must never generate machine results.
            script('fusion', 'fuse_throw_events_v3.py', '--root', event_root)
            fused = json.loads((event_root / 'fused-results.json').read_text(encoding='utf-8'))
            for row in fused['results']:
                api_events.append({'event_id': f'{job_id}-{row["sample_throw_id"]}', 'category': bucket_outcome(row['outcome']),
                    'conflict': row['conflict'], 'source_intervals': [
                        {'video_id': v['video_id'], 'start_sec': row[f'{v["camera_perspective"]}_source_time_sec'][0],
                         'end_sec': row[f'{v["camera_perspective"]}_source_time_sec'][1]} for v in videos]})
        else:
            fused = {'schema_version': 1, 'algorithm': 'throw-events-v3 single-view adapter',
                     'source_sha256': {v['video_id']: v['source_sha256'] for v in videos}, 'results': single_rows}
        update('statistics')
        stats = summarize(fused)
        (root / 'statistics.json').write_text(json.dumps(stats, indent=2, allow_nan=False), encoding='utf-8')
        code_hash = hashlib.sha256(''.join(digest(p) for p in sorted((ROOT / 'cv').rglob('*.py'))).encode()).hexdigest()[:16]
        for event in api_events:
            for interval in event['source_intervals']:
                if not 0 <= interval['start_sec'] <= interval['end_sec'] <= metadata[interval['video_id']]['duration'] + .05:
                    raise ValueError('Algorithm interval outside source duration')
        return {'statistics': {k: v for k, v in stats.items() if k not in ('events', 'source_sha256', 'algorithm', 'schema_version', 'limitations')},
                'events': api_events, 'previews': previews, 'metadata': metadata,
                'algorithm_version': f'throw-events-v3/api-adapter-v1:{code_hash}',
                'limitations': ['Unverified algorithm candidates, not independent accuracy measurements.',
                                'Fixed front/side cameras only; single-view results may remain uncertain.',
                                'No calibrated physical distance, height or speed.',
                                'Paired sample views use event order, not a shared source clock.']}
