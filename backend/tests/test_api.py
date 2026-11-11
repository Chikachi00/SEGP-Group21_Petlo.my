from pathlib import Path
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.config import Settings
from backend.db import Job, TrainingSession
from backend.main import create_app
from backend.pipeline import validate_selection
from cv.build_throw_statistics import summarize


class TestRunner:
    """No inference in unit tests. A separate smoke check exercises the real runner."""
    def __init__(self, settings, fail=False, gate=None, with_events=False):
        self.settings, self.fail, self.gate = settings, fail, gate
        self.with_events = with_events

    def check_ready(self):
        pass

    def probe(self, path):
        if path.read_bytes().startswith(b'bad'):
            raise ValueError('Invalid media')
        return {'duration': .5, 'width': 640, 'height': 360}

    def run(self, job_id, mode, videos, update):
        update('test')
        if self.gate:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError('Test-only failure')
        key = f'jobs/{job_id}/preview.mp4'
        path = self.settings.storage / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'0123456789')
        rows = [{'sample_throw_id': 'first', 'outcome': 'ground_pickup_candidate'}, {'sample_throw_id': 'second', 'outcome': 'uncertain'}] if self.with_events else []
        stats = summarize({'schema_version': 1, 'results': rows})
        events = [{'event_id': f'{job_id}-{row["sample_throw_id"]}', 'category': 'ground_pickup_candidate' if i == 0 else 'uncertain',
                   'conflict': False, 'source_intervals': [{'video_id': videos[0]['video_id'], 'start_sec': .1, 'end_sec': .3}]} for i, row in enumerate(rows)]
        return {'statistics': stats, 'events': events, 'algorithm_version': 'test-only',
                'limitations': ['Test runner only'], 'previews': {v['video_id']: key for v in videos},
                'metadata': {v['video_id']: self.probe(path) for v in videos}}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(database_url=f'sqlite:///{(self.root / "db.sqlite3").as_posix()}', storage=self.root / 'storage')

    def tearDown(self):
        self.temp.cleanup()

    def client(self, runner=None):
        app = create_app(self.settings, runner or TestRunner(self.settings))
        return TestClient(app, client=('127.0.0.1', 50000))

    def session(self, client):
        dog_id = client.get('/api/v1/dogs').json()['items'][0]['dog_id']
        result = client.post('/api/v1/sessions', json={'dog_id': dog_id})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()['session_id']

    def upload(self, client, session, content=b'video', view='front'):
        return client.post(f'/api/v1/sessions/{session}/videos', files={'file': ('../../sample.mp4', content, 'video/mp4')}, data={'camera_perspective': view})

    def wait(self, client, job_id):
        for _ in range(200):
            result = client.get(f'/api/v1/jobs/{job_id}').json()
            if result['status'] in ('completed', 'failed'):
                return result
            time.sleep(.01)
        self.fail('Job did not terminate')

    def test_upload_job_playback_and_persistence(self):
        with self.client() as client:
            session = self.session(client)
            result = self.upload(client, session)
            self.assertEqual(result.status_code, 201, result.text)
            video = result.json()
            self.assertIsNone(video['playback_url'])
            result = client.post(f'/api/v1/sessions/{session}/analysis', json={'mode': 'single_view', 'video_ids': [video['video_id']]})
            self.assertEqual(result.status_code, 202, result.text)
            self.assertEqual(self.wait(client, result.json()['job_id'])['status'], 'completed')
            detail = client.get(f'/api/v1/sessions/{session}').json()
            self.assertEqual(detail['status'], 'completed')
            self.assertIsNone(detail['statistics']['in_air_catch_candidate_rate'])
            media = client.get(detail['videos'][0]['playback_url'], headers={'Range': 'bytes=2-5'})
            self.assertEqual(media.status_code, 206)
            self.assertEqual(media.content, b'2345')
        with self.client() as restarted:
            self.assertEqual(restarted.get(f'/api/v1/sessions/{session}').json()['status'], 'completed')
            self.assertEqual(restarted.get('/api/v1/sessions').json()['total'], 1)
        self.assertFalse((self.root / 'sample.mp4').exists())

    def test_invalid_media_and_duplicate_views_cleanup(self):
        with self.client() as client:
            session = self.session(client)
            self.assertEqual(self.upload(client, session, b'bad').status_code, 422)
            self.assertEqual(list((self.settings.storage / 'uploads').glob('*')), [])
            self.assertEqual(self.upload(client, session).status_code, 201)
            self.assertEqual(self.upload(client, session).status_code, 409)
            self.assertEqual(len(list((self.settings.storage / 'uploads').glob('*'))), 1)

    def test_event_categories_intervals_and_denominators_are_preserved(self):
        with self.client(TestRunner(self.settings, with_events=True)) as client:
            session = self.session(client)
            video = self.upload(client, session).json()['video_id']
            accepted = client.post(f'/api/v1/sessions/{session}/analysis', json={'mode': 'single_view', 'video_ids': [video]})
            self.wait(client, accepted.json()['job_id'])
            detail = client.get(f'/api/v1/sessions/{session}').json()
            self.assertEqual(detail['events'][0]['source_intervals'], [{'video_id': video, 'start_sec': .1, 'end_sec': .3}])
            self.assertEqual(detail['events'][0]['category'], 'ground_pickup_candidate')
            self.assertEqual(detail['statistics']['classified_candidate_events'], 1)
            self.assertEqual(detail['statistics']['uncertain_events'], 1)
            self.assertEqual(detail['statistics']['in_air_catch_candidate_rate'], 0)
            self.assertEqual(detail['statistics']['retrieval_candidate_rate'], 1)
            self.assertEqual(detail['statistics']['candidate_coverage'], .5)

    def test_limits_and_structured_errors(self):
        self.settings.max_upload_bytes = 3
        with self.client() as client:
            session = self.session(client)
            result = self.upload(client, session, b'oversized')
            self.assertEqual(result.status_code, 413, result.text)
            self.assertEqual(result.json()['error']['code'], 'UPLOAD_TOO_LARGE')
            self.assertEqual(client.get('/api/v1/sessions?page=0').status_code, 422)
            result = client.get('/api/v1/jobs/missing')
            self.assertEqual(result.status_code, 404)
            self.assertTrue(result.json()['error']['request_id'])

    def test_request_body_limit_precedes_media_probe(self):
        self.settings.max_upload_bytes = 3
        with self.client() as client:
            session = self.session(client)
            response = self.upload(client, session, b'x' * 70000)
            self.assertEqual(response.status_code, 413, response.text)

    def test_duplicate_job_rejected_and_failed_job_is_persisted(self):
        gate = threading.Event()
        try:
            with self.client(TestRunner(self.settings, fail=True, gate=gate)) as client:
                session = self.session(client)
                video = self.upload(client, session).json()['video_id']
                body = {'mode': 'single_view', 'video_ids': [video]}
                result = client.post(f'/api/v1/sessions/{session}/analysis', json=body)
                self.assertEqual(result.status_code, 202, result.text)
                second = client.post(f'/api/v1/sessions/{session}/analysis', json=body)
                self.assertEqual(second.status_code, 409)
                gate.set()
                self.assertEqual(self.wait(client, result.json()['job_id'])['status'], 'failed')
                self.assertIsNone(client.get(f'/api/v1/sessions/{session}').json()['statistics'])
        finally:
            gate.set()

    def test_sample_pair_rejects_arbitrary_inputs(self):
        with self.client() as client:
            session = self.session(client)
            front = self.upload(client, session).json()['video_id']
            side = self.upload(client, session, view='side').json()['video_id']
            result = client.post(f'/api/v1/sessions/{session}/analysis', json={'mode': 'sample_pair', 'video_ids': [front, side]})
            self.assertEqual(result.status_code, 422)
            with self.assertRaises(ValueError):
                validate_selection('sample_pair', [{'camera_perspective': 'front', 'source_sha256': 'unknown'}, {'camera_perspective': 'side', 'source_sha256': 'unknown'}])

    def test_restart_marks_interrupted_job_failed(self):
        with self.client() as client:
            session = self.session(client)
            with client.app.state.sessions.begin() as db:
                db.add(Job(job_id='interrupted', session_id=session, status='running', mode='single_view', video_ids=[]))
                parent = db.get(TrainingSession, session)
                parent.current_job_id, parent.status = 'interrupted', 'running'
        with self.client() as client:
            result = client.get('/api/v1/jobs/interrupted').json()
            self.assertEqual(result['error']['code'], 'SERVER_RESTARTED')
            self.assertEqual(client.get(f'/api/v1/sessions/{session}').json()['status'], 'failed')

    def test_local_origin_and_owned_resources(self):
        with self.client() as client:
            self.assertEqual(client.get('/api/v1/dogs', headers={'Origin': 'https://untrusted.invalid'}).status_code, 403)
            result = client.options('/api/v1/sessions', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
            self.assertEqual(result.headers['access-control-allow-origin'], 'http://localhost:5173')
            self.assertEqual(client.post('/api/v1/sessions', json={'dog_id': '999'}).status_code, 404)
            self.assertEqual(client.post('/api/v1/sessions', json={'dog_id': '1', 'trainer_id': 2}).status_code, 422)
        with TestClient(create_app(self.settings, TestRunner(self.settings)), client=('192.0.2.5', 50000)) as remote:
            self.assertEqual(remote.get('/api/v1/health').status_code, 403)


    def test_status_refresh_preserves_submission_time_and_does_not_enqueue_again(self):
        from datetime import datetime
        gate = threading.Event()
        try:
            with self.client(TestRunner(self.settings, gate=gate)) as client:
                session = self.session(client)
                video = self.upload(client, session).json()['video_id']
                submitted = client.post(f'/api/v1/sessions/{session}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
                job_id = submitted['job_id']
                self.assertIsNotNone(datetime.fromisoformat(submitted['created_at']).tzinfo)
                self.assertIsNone(submitted['finished_at'])
                for _ in range(3):
                    detail = client.get(f'/api/v1/sessions/{session}').json()
                    observed = client.get(f'/api/v1/jobs/{job_id}').json()
                    self.assertEqual(detail['current_job_id'], job_id)
                    self.assertEqual(observed['created_at'], submitted['created_at'])
                with client.app.state.sessions() as db:
                    self.assertEqual(len(list(db.scalars(select(Job).where(Job.session_id == session)))), 1)
                gate.set()
                completed = self.wait(client, job_id)
                self.assertEqual(completed['status'], 'completed')
                self.assertGreaterEqual(datetime.fromisoformat(completed['finished_at']), datetime.fromisoformat(completed['created_at']))
        finally:
            gate.set()


if __name__ == '__main__':
    unittest.main()
