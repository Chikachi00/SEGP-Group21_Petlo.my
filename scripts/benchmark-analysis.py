"""Time real analysis stages in isolated storage, without changing saved sessions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--view', choices=('front', 'side'), default='front')
    parser.add_argument('--source-root', type=Path, default=PROJECT,
                        help='Optional saved source tree for before/after comparisons')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--device', default='cpu', help='cpu, auto or a CUDA device index')
    parser.add_argument('--cpu-threads', type=int)
    parser.add_argument('--tile-batch-size', type=int)
    args = parser.parse_args()
    video = args.video.resolve()
    if not video.is_file():
        parser.error('Choose an existing video')
    if any(value is not None and value < 1 for value in (args.cpu_threads, args.tile_batch_size)):
        parser.error('Thread and batch counts must be positive')
    sys.path.insert(0, str(args.source_root.resolve()))
    from backend.config import Settings
    from backend.pipeline import PipelineRunner, digest
    output = (args.output or PROJECT / 'outputs' / f'runtime-benchmark-{uuid.uuid4().hex[:10]}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = Settings(storage=output / 'storage', model=PROJECT / 'yolo11n.pt')
    if hasattr(settings, 'device'):
        settings.device = args.device
    if args.cpu_threads is not None and hasattr(settings, 'cpu_threads'):
        settings.cpu_threads = args.cpu_threads
    if args.tile_batch_size is not None and hasattr(settings, 'tile_batch_size'):
        settings.tile_batch_size = args.tile_batch_size
    runner = PipelineRunner(settings)
    runner.check_ready()
    uploads = settings.storage / 'uploads'
    uploads.mkdir(parents=True)
    copied = uploads / f'input{video.suffix}'
    shutil.copyfile(video, copied)
    stages = []
    started = time.perf_counter()

    def update(stage):
        elapsed = time.perf_counter() - started
        if stages:
            stages[-1]['seconds'] = elapsed - stages[-1]['started_seconds']
        stages.append({'stage': stage, 'started_seconds': elapsed})
        print(f'{elapsed:.3f}s: {stage}', flush=True)

    result = runner.run('benchmark', 'single_view', [{'video_id': 'benchmark-video',
        'storage_key': copied.relative_to(settings.storage).as_posix(),
        'source_sha256': digest(copied), 'camera_perspective': args.view}], update)
    elapsed = time.perf_counter() - started
    stages[-1]['seconds'] = elapsed - stages[-1]['started_seconds']
    job_root = settings.storage / 'jobs' / 'benchmark'
    runtime_path = job_root / 'runtime.json'
    worker_timings_path = job_root / 'timings.json'
    report = {'kind': 'real_pipeline_runtime_not_accuracy', 'elapsed_seconds': elapsed,
              'source': str(video), 'source_root': str(args.source_root.resolve()),
              'requested_device': args.device, 'stages': stages,
              'statistics': result['statistics'], 'events': result['events'],
              'runtime': json.loads(runtime_path.read_text(encoding='utf-8')) if runtime_path.is_file() else None,
              'worker_timings': json.loads(worker_timings_path.read_text(encoding='utf-8')) if worker_timings_path.is_file() else None}
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'elapsed_seconds': elapsed, 'report': str(output / 'report.json')}), flush=True)


if __name__ == '__main__':
    main()
