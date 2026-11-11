"""Run an actual upload/API/database/CV/playback check in an isolated local output folder."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

from fastapi.testclient import TestClient

from .config import ROOT, Settings
from .main import create_app
from .pipeline import PipelineRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--view', choices=['front', 'side'], default='front')
    parser.add_argument('--seconds', type=float, help='Create a short resized smoke-test input, not an accuracy benchmark')
    args = parser.parse_args()
    if not args.video.is_file() or args.seconds is not None and args.seconds <= 0:
        parser.error('Choose an existing video and positive clip duration')
    output = ROOT / 'outputs' / f'backend-smoke-{uuid.uuid4().hex[:12]}'
    output.mkdir(parents=True)
    settings = Settings(database_url=f'sqlite:///{(output / "service.sqlite3").as_posix()}', storage=output / 'storage', seed_demo=True)
    runner = PipelineRunner(settings)
    video = args.video.resolve()
    if args.seconds is not None:
        video = output / 'smoke-input.mp4'
        subprocess.run([runner.tools().ffmpeg, '-nostdin', '-y', '-v', 'error', '-i', str(args.video.resolve()),
            '-t', str(args.seconds), '-an', '-vf', 'scale=640:-2', '-c:v', 'libx264', '-threads', '2',
            '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(video)], check=True)
    started = time.perf_counter()
    with TestClient(create_app(settings), client=('127.0.0.1', 50000)) as client:
        dog = client.get('/api/v1/dogs').json()['items'][0]
        created = client.post('/api/v1/sessions', json={'dog_id': dog['dog_id']})
        created.raise_for_status()
        session_id = created.json()['session_id']
        with video.open('rb') as stream:
            uploaded = client.post(f'/api/v1/sessions/{session_id}/videos', files={'file': (video.name, stream, 'video/mp4')}, data={'camera_perspective': args.view})
        uploaded.raise_for_status()
        accepted = client.post(f'/api/v1/sessions/{session_id}/analysis', json={'mode': 'single_view', 'video_ids': [uploaded.json()['video_id']]})
        accepted.raise_for_status()
        job_id = accepted.json()['job_id']
        previous = None
        while True:
            job = client.get(f'/api/v1/jobs/{job_id}').json()
            if (job['status'], job['stage']) != previous:
                print(json.dumps(job), flush=True)
                previous = job['status'], job['stage']
            if job['status'] in ('completed', 'failed', 'cancelled'):
                break
            time.sleep(1)
        if job['status'] != 'completed':
            raise RuntimeError(f'Actual pipeline failed. Inspect {settings.storage / "jobs" / job_id / "pipeline.log"}')
        detail = client.get(f'/api/v1/sessions/{session_id}').json()
        media = client.get(detail['videos'][0]['playback_url'], headers={'Range': 'bytes=0-99'})
        assert media.status_code == 206 and len(media.content) == 100
    with TestClient(create_app(settings), client=('127.0.0.1', 50000)) as restarted:
        assert restarted.get(f'/api/v1/sessions/{session_id}').json()['status'] == 'completed'
    report = {'status': 'complete', 'kind': 'actual_pipeline_smoke_not_accuracy', 'session_id': session_id,
              'job_id': job_id, 'clip_seconds_requested': args.seconds, 'elapsed_seconds': time.perf_counter() - started,
              'source_input': str(video), 'statistics': detail['statistics'], 'playback_range_status': media.status_code,
              'persistence_after_restart': True}
    (output / 'smoke-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output / 'smoke-report.json'), **report}), flush=True)


if __name__ == '__main__':
    main()
