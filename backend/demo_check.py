"""Verify both original samples through the running local API; preserve the saved report."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import httpx

from .config import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--timeout-minutes', type=float, default=120)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.timeout_minutes <= 0:
        parser.error('Choose a valid local port and positive timeout.')
    sources = [(view, args.sample_dir / name) for view, name in [
        ('front', 'Landscape_Tripod_FrontView.mp4'), ('side', 'Landscape_Tripod_SideView.mp4')]]
    if any(not path.is_file() for _, path in sources):
        parser.error('Both original front and side samples must exist.')
    output = ROOT / 'outputs' / f'demo-check-{uuid.uuid4().hex[:10]}'
    output.mkdir(parents=True)
    started = time.perf_counter()
    report = {'kind': 'full_original_sample_pair_api_check', 'started_at': datetime.now(timezone.utc).isoformat(),
              'status': 'running', 'output': str(output), 'stages': []}

    def save():
        report['elapsed_seconds'] = round(time.perf_counter() - started, 2)
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', timeout=600, trust_env=False) as client:
            def checked(response):
                response.raise_for_status()
                return response.json()

            health = checked(client.get('/api/v1/health'))
            if health['mode'] != 'local_single_user':
                raise ValueError('This verifier is for the local single-user API only.')
            dogs = checked(client.get('/api/v1/dogs'))['items']
            if not dogs:
                raise ValueError('Create a local dog before running the check.')
            session = checked(client.post('/api/v1/sessions', json={'dog_id': dogs[0]['dog_id']}))
            report['session_id'] = session['session_id']
            print('Saved session:', session['session_id'], flush=True)
            save()
            ids = []
            for view, path in sources:
                print('Uploading original', view, path.stat().st_size, 'bytes', flush=True)
                with path.open('rb') as stream:
                    video = checked(client.post(f'/api/v1/sessions/{session["session_id"]}/videos',
                        files={'file': (path.name, stream, 'video/mp4')}, data={'camera_perspective': view}))
                ids.append(video['video_id'])
            report['upload_seconds'] = round(time.perf_counter() - started, 2)
            job = checked(client.post(f'/api/v1/sessions/{session["session_id"]}/analysis',
                json={'mode': 'sample_pair', 'video_ids': ids}))
            report['job_id'] = job['job_id']
            deadline = time.monotonic() + args.timeout_minutes * 60
            last = None
            while True:
                job = checked(client.get(f'/api/v1/jobs/{job["job_id"]}'))
                state = (job['status'], job['stage'])
                if state != last:
                    report['stages'].append({'status': state[0], 'stage': state[1],
                                             'elapsed_seconds': round(time.perf_counter() - started, 2)})
                    print(state, report['stages'][-1]['elapsed_seconds'], 'seconds', flush=True)
                    last = state
                    save()
                if job['status'] in ('completed', 'failed'):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('Stopped observing; the accepted server task may still be running.')
                time.sleep(3)
            report['job'] = job
            if job['status'] != 'completed':
                raise RuntimeError(str(job.get('error')))
            detail = checked(client.get(f'/api/v1/sessions/{session["session_id"]}'))
            report['detail'] = detail
            report['playback'] = []
            for video in detail['videos']:
                response = client.get(video['playback_url'], headers={'Range': 'bytes=0-1023'})
                if response.status_code != 206:
                    raise ValueError('Playback did not return HTTP 206.')
                report['playback'].append({'view': video['camera_perspective'], 'status': response.status_code,
                                           'content_range': response.headers.get('content-range')})
            report['status'] = 'completed'
            print(json.dumps(detail['statistics'], indent=2), flush=True)
    except Exception as exc:
        report['status'], report['error'] = 'failed', str(exc)
        raise
    finally:
        save()
        print('Verification record:', output / 'report.json', flush=True)


if __name__ == '__main__':
    main()
