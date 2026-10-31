"""Compatibility adapter: invoke existing commands without editing algorithm code."""
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from cv.fuse_two_views import run as fuse_two_views, FusionSettings

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


def copy_verified(source, target, expected_sha256, control=None):
    """Copy and verify in one source read, keeping memory bounded by the chunk."""
    value = hashlib.sha256()
    created = False
    try:
        with Path(source).open('rb') as original, Path(target).open('xb') as copied:
            created = True
            while chunk := original.read(1024 * 1024):
                if control is not None:
                    control.checkpoint()
                value.update(chunk)
                copied.write(chunk)
        if value.hexdigest() != expected_sha256:
            raise ValueError('Stored source content changed')
    except BaseException:
        if created:
            Path(target).unlink(missing_ok=True)
        raise


def inside(root, key):
    path = (root / key).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Storage key outside root')
    return path


def validate_selection(mode, videos):
    if mode == 'single_view' and len(videos) == 1:
        return
    if mode not in ('sample_pair', 'paired_views') or len(videos) != 2 \
            or {v['camera_perspective'] for v in videos} != {'front', 'side'}:
        raise ValueError('Choose one video, or one front and one side video')
    if mode == 'sample_pair' and any(v['source_sha256'] != SAMPLES[v['camera_perspective']][1] for v in videos):
        raise ValueError('Sample-pair fusion supports only the original matching sample contents')


class PipelineRunner:
    supports_job_control = True
    def __init__(self, settings):
        self.settings = settings
        self._toolchain = None
        self._tools_lock = threading.Lock()

    def tools(self):
        from cv.video_tools.media import Toolchain
        # Discovery recursively searches for binaries and starts two version
        # subprocesses. The configured tools stay fixed for this server lifetime.
        with self._tools_lock:
            if self._toolchain is None:
                self._toolchain = Toolchain.discover(self.settings.ffmpeg_dir)
            return self._toolchain

    def probe(self, path):
        from cv.video_tools.media import probe_video
        return probe_video(path, self.tools())

    def check_ready(self):
        if not self.settings.model.is_file():
            raise ValueError('Local YOLO weights are missing. Configure PETLO_MODEL_PATH first.')
        self.tools()

    def run(self, job_id, mode, videos, update, control=None):
        """Keep expensive imports/model state in one controllable worker process."""
        from .process_control import ProcessControl
        validate_selection(mode, videos)
        self.check_ready()
        root = inside(self.settings.storage, f'jobs/{job_id}')
        root.mkdir(parents=True, exist_ok=False)
        request_path = root / 'request.json'
        progress_path = root / 'progress.jsonl'
        request_path.write_text(json.dumps({'job_id': job_id, 'mode': mode, 'videos': videos,
            'storage': str(self.settings.storage), 'model': str(self.settings.model),
            'ffmpeg_dir': str(Path(self.tools().ffmpeg).parent), 'stage_timeout': self.settings.stage_timeout,
            'device': self.settings.device, 'cpu_threads': self.settings.cpu_threads,
            'tile_batch_size': self.settings.tile_batch_size}), encoding='utf-8')
        position = 0

        def progress():
            nonlocal position
            changed = False
            if progress_path.is_file():
                with progress_path.open(encoding='utf-8') as stream:
                    stream.seek(position)
                    while line := stream.readline():
                        if not line.endswith('\n'):
                            break
                        update(json.loads(line)['stage'])
                        position = stream.tell()
                        changed = True
            return changed

        active_control = control or ProcessControl(lambda status: None)
        with (root / 'pipeline.log').open('ab') as output:
            active_control.command([sys.executable, '-m', 'backend.analysis_worker', request_path], cwd=ROOT,
                stdout=output, timeout=self.settings.stage_timeout, on_progress=progress)
        progress()
        return json.loads((root / 'result.json').read_text(encoding='utf-8'))

    def run_direct(self, job_id, mode, videos, update):
        """Worker-only orchestration; default standalone CV commands keep reviews."""
        from cv.build_throw_statistics import bucket_outcome, summarize
        from cv.video_tools.prepare import prepare
        from cv.detect_disc_video import run as detect
        from cv.track_dog_video import run as track_dog
        from cv.track_disc_recovered_video import run as track_disc
        from cv.analyze_dog_disc import run as analyze_joint
        from cv.analyze_throw_events_v3 import run as analyze_events
        from cv.fuse_throw_events_v3 import run as fuse_events
        from .preview import encode_preview
        validate_selection(mode, videos)
        self.check_ready()
        root = inside(self.settings.storage, f'jobs/{job_id}')
        source = root / 'source'
        source.mkdir(parents=True, exist_ok=False)
        tools = self.tools()
        timings = []

        def stage(name, operation, *args, **kwargs):
            update(name)
            started = time.perf_counter()
            result = operation(*args, **kwargs)
            timings.append({'stage': name, 'seconds': time.perf_counter() - started})
            (root / 'timings.json').write_text(json.dumps(timings, indent=2), encoding='utf-8')
            return result

        shared_model = None
        device = None

        def detection(args):
            nonlocal shared_model, device
            if shared_model is None:
                import torch
                from cv.detect_video import load_detection_model
                torch.set_num_threads(self.settings.cpu_threads)
                requested = self.settings.device
                device = ('0' if torch.cuda.is_available() else 'cpu') if requested == 'auto' else requested
                if device != 'cpu' and not torch.cuda.is_available():
                    raise ValueError('CUDA was requested but is unavailable in the installed PyTorch environment')
                shared_model = load_detection_model(str(self.settings.model))

                def inference_start(_predictor):
                    # Ultralytics selects its own CPU thread count during initial
                    # setup. Restore the configured value before inference.
                    if torch.get_num_threads() != self.settings.cpu_threads:
                        torch.set_num_threads(self.settings.cpu_threads)

                shared_model.add_callback('on_predict_start', inference_start)
                (root / 'runtime.json').write_text(json.dumps({'device': device, 'torch': torch.__version__,
                    'gpu': torch.cuda.get_device_name(int(device)) if device != 'cpu' else None,
                    'cpu_threads': self.settings.cpu_threads,
                    'tile_batch_size': self.settings.tile_batch_size}, indent=2), encoding='utf-8')
            args.device = device
            return detect(args, model=shared_model, render=False)

        paths = {}
        for video in videos:
            original = inside(self.settings.storage, video['storage_key'])
            view = video['camera_perspective']
            # The job directory provides uniqueness; short generated names avoid Windows path limits.
            stem = SAMPLES[view][0] if mode == 'sample_pair' else f'Tripod_{view}'
            copied = source / f'{stem}{original.suffix}'
            copy_verified(original, copied, video['source_sha256'])
            paths[video['video_id']] = copied
        pack = root / 'pack'
        manifest = stage('prepare', prepare, source, pack, tools, review_artifacts=False)
        if any(v['status'] != 'complete' for v in manifest['videos']):
            raise ValueError('Full source decoding failed')
        previews, metadata, single_rows, api_events = {}, {}, [], []
        preview_encoders = {}
        event_root = root / 'throw-events-v3'
        for video in videos:
            key, view = video['video_id'], video['camera_perspective']
            copied = paths[key]
            indexed = next(v for v in manifest['videos'] if v['id'] == copied.stem)
            if indexed['camera'] != 'tripod' or indexed['role'] != 'action':
                raise ValueError('Expected fixed-camera action metadata')
            preview = root / 'previews' / f'{key}.mp4'
            preview.parent.mkdir(exist_ok=True)
            preview_encoders[view] = stage(f'{view}:preview', encode_preview, copied, preview, tools,
                self.settings.stage_timeout, device=self.settings.device)
            (root / 'preview-encoders.json').write_text(json.dumps(preview_encoders), encoding='utf-8')
            previews[key] = preview.relative_to(self.settings.storage).as_posix()
            metadata[key] = dict(indexed['metadata'], duration=indexed['duration'], width=indexed['width'], height=indexed['height'])
            folder = root / view
            folder.mkdir()
            detector = folder / 'detected.mp4'
            detection_rows = detector.with_suffix('.jsonl')
            ffmpeg_dir = Path(tools.ffmpeg).parent
            stage(f'{view}:detect', detection, SimpleNamespace(video=copied, pack=pack, output=detector,
                model=str(self.settings.model), mode='enhanced', confidence=.25, disc_confidence=.25,
                imgsz=None, disc_grid=None, tile_imgsz=960, overlap=.2, start=0., end=None,
                cpu_threads=self.settings.cpu_threads, device='cpu', ffmpeg_dir=ffmpeg_dir,
                tile_batch_size=self.settings.tile_batch_size))
            dog, disc, joint = folder / 'dog', folder / 'disc', folder / 'joint'
            stage(f'{view}:dog_tracks', track_dog, detection_rows, pack, dog, ffmpeg_dir=ffmpeg_dir, render=False)
            stage(f'{view}:disc_tracks', track_disc, detection_rows, pack, disc, ffmpeg_dir=ffmpeg_dir,
                  model_path=self.settings.model, model=shared_model, device=device, render=False)
            stage(f'{view}:joint', analyze_joint, dog, disc, pack, joint, review=False)
            events_dir = event_root / f'{view}-v1'
            stage(f'{view}:events', analyze_events, joint, detection_rows, pack, events_dir,
                  ffmpeg_dir=ffmpeg_dir, review=False)
            raw = json.loads((events_dir / 'events-v3.json').read_text(encoding='utf-8'))
            if mode == 'single_view':
                for row in raw['event_candidates']:
                    event_id = f'{job_id}-{row["throw_id"]}'
                    interval = [float(row['start_sec']), float(row['end_sec'])]
                    api_events.append({'event_id': event_id, 'category': bucket_outcome(row['predicted_outcome']),
                        'conflict': False, 'source_intervals': [{'video_id': key, 'start_sec': interval[0], 'end_sec': interval[1]}]})
                    single_rows.append({'sample_throw_id': event_id, 'outcome': row['predicted_outcome'],
                                        f'{view}_source_time_sec': interval, f'{view}_outcome': row['predicted_outcome']})
        if mode in ('sample_pair', 'paired_views'):
            if mode == 'sample_pair':
                # Legacy sample-only path, unchanged. No --labels: reviewed answers must never generate machine results.
                stage('fusion', fuse_events, event_root)
                fused = json.loads((event_root / 'fused-results.json').read_text(encoding='utf-8'))
            else:
                fused = stage('fusion', fuse_two_views, event_root / 'front-v1', event_root / 'side-v1', root / 'two-view')
            ids = {v['camera_perspective']: v['video_id'] for v in videos}
            for row in fused['results']:
                intervals = [{'video_id': ids[view], 'start_sec': row[f'{view}_source_time_sec'][0],
                              'end_sec': row[f'{view}_source_time_sec'][1]}
                             for view in ('front', 'side') if row.get(f'{view}_source_time_sec')]
                api_events.append({'event_id': f'{job_id}-{row["sample_throw_id"]}',
                                   'category': bucket_outcome(row['outcome']),
                                   'conflict': row['conflict'], 'source_intervals': intervals})
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
