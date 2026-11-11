"""Regression checks for bounded queries, upload concurrency and job resources."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from sqlalchemy import event, func, select

from backend.db import Job, LegacyVideo, SessionPreferences, TrainingSession, Video, now
from backend.pipeline import PipelineRunner, copy_verified
from backend.process_control import JobCancelled
from backend.tests import test_api as helpers
from cv.build_throw_statistics import summarize


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Expected state was not reached.')


class BackendOptimizationTests(unittest.TestCase):
    setUp = helpers.ApiTests.setUp
    tearDown = helpers.ApiTests.tearDown
    client = helpers.ApiTests.client
    session = helpers.ApiTests.session
    upload = helpers.ApiTests.upload
    wait = helpers.ApiTests.wait

    def test_session_list_has_constant_query_count_and_preserves_summaries(self):
        with self.client() as client:
            stats = summarize({'schema_version': 1, 'results': []})
            with client.app.state.sessions.begin() as db:
                for index in range(25):
                    identity = f'session-{index:02}'
                    parent = TrainingSession(session_id=identity, dog_id=1, trainer_id=1,
                        recorded_at=f'2026-01-01T00:00:{index:02}+00:00', status='completed' if index == 20 else 'ready')
                    db.add(parent)
                    db.flush()
                    if index in (10, 24):
                        db.add(SessionPreferences(session_id=identity, display_name='Custom name' if index == 10 else None,
                            deleted_at=now() if index == 24 else None))
                    if index == 20:
                        job = Job(job_id='completed-job', session_id=identity, status='completed', mode='single_view', video_ids=[],
                            result_json={'statistics': stats, 'algorithm_version': 'test-only', 'limitations': []})
                        db.add(job)
                        parent.current_job_id = job.job_id
                    views = ('front', 'side') if index == 5 else ('front',) if index % 3 == 1 else ('side',) if index % 3 == 2 else ()
                    for view in views:
                        legacy = LegacyVideo(file_path=f'{identity}-{view}.mp4', camera_perspective=view, video_length=1)
                        db.add(legacy)
                        db.flush()
                        db.add(Video(video_id=f'{identity}-{view}', session_id=identity, legacy_video_id=legacy.video_id,
                            camera_perspective=view, storage_key=legacy.file_path, source_sha256='test-only', metadata_json={}))

            engine = client.app.state.sessions.kw['bind']
            queries = []

            def record(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith('SELECT'):
                    queries.append(statement)

            event.listen(engine, 'before_cursor_execute', record)
            try:
                response = client.get('/api/v1/sessions?page_size=20')
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(len(queries), 3)
                queries.clear()
                small_page = client.get('/api/v1/sessions?page_size=1')
                self.assertEqual(small_page.status_code, 200, small_page.text)
                self.assertEqual(len(queries), 3)
                queries.clear()
                trash = client.get('/api/v1/sessions?trash=true').json()
                self.assertEqual(len(queries), 3)
            finally:
                event.remove(engine, 'before_cursor_execute', record)
            self.assertEqual(result['total'], 24)
            self.assertEqual([row['session_id'] for row in result['items']], [f'session-{index:02}' for index in range(23, 3, -1)])
            by_id = {row['session_id']: row for row in result['items']}
            self.assertEqual(by_id['session-10']['name'], 'Custom name')
            self.assertEqual(by_id['session-05']['name'], 'Front + Side session')
            self.assertEqual(by_id['session-22']['name'], 'Front view session')
            self.assertEqual(by_id['session-23']['name'], 'Side view session')
            self.assertEqual(by_id['session-21']['name'], 'Training session')
            detail = client.get('/api/v1/sessions/session-20').json()
            self.assertEqual(by_id['session-20']['statistics'], detail['statistics'])
            self.assertEqual(trash['total'], 1)
            self.assertEqual(trash['items'][0]['session_id'], 'session-24')

    def test_slow_upload_does_not_block_other_sessions_or_commit_after_trash(self):
        entered, release = threading.Event(), threading.Event()

        class SlowProbe(helpers.TestRunner):
            def probe(self, path):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test probe timed out')
                return super().probe(path)

        with self.client(SlowProbe(self.settings)) as client, ThreadPoolExecutor(max_workers=2) as executor:
            identity = self.session(client)
            other = self.session(client)
            pending = executor.submit(self.upload, client, identity)
            try:
                self.assertTrue(entered.wait(2))
                # Both writes need the API write lock. They must complete while
                # the first upload is still deliberately blocked in its probe.
                renamed = executor.submit(client.patch, f'/api/v1/sessions/{other}', json={'name': 'Still responsive'})
                response = renamed.result(timeout=2)
                self.assertEqual(response.status_code, 200, response.text)
                trashed = executor.submit(client.delete, f'/api/v1/sessions/{identity}').result(timeout=2)
                self.assertEqual(trashed.status_code, 200, trashed.text)
            finally:
                release.set()
                response = pending.result(timeout=5)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(list((self.settings.storage / 'uploads').iterdir()), [])
            client.post(f'/api/v1/sessions/{identity}/restore')
            self.assertEqual(client.get(f'/api/v1/sessions/{identity}').json()['videos'], [])

    def test_concurrent_duplicate_uploads_commit_one_video_and_clean_up_loser(self):
        probing = threading.Barrier(2)

        class ConcurrentProbe(helpers.TestRunner):
            def probe(self, path):
                probing.wait(timeout=5)
                return super().probe(path)

        with self.client(ConcurrentProbe(self.settings)) as client, ThreadPoolExecutor(max_workers=2) as executor:
            identity = self.session(client)
            uploads = [executor.submit(self.upload, client, identity) for _ in range(2)]
            responses = [upload.result(timeout=6) for upload in uploads]
            self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
            duplicate = next(response for response in responses if response.status_code == 409)
            self.assertEqual(duplicate.json()['error']['code'], 'DUPLICATE_VIEW')
            self.assertEqual(len(client.get(f'/api/v1/sessions/{identity}').json()['videos']), 1)
            self.assertEqual(len(list((self.settings.storage / 'uploads').iterdir())), 1)

    def test_upload_started_before_analysis_is_rejected_without_orphans(self):
        entered, release = threading.Event(), threading.Event()

        class SlowSecondProbe(helpers.TestRunner):
            def probe(self, path):
                if path.read_bytes() == b'second-camera':
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError('Test probe timed out')
                return super().probe(path)

        with self.client(SlowSecondProbe(self.settings)) as client, ThreadPoolExecutor(max_workers=2) as executor:
            identity = self.session(client)
            first = self.upload(client, identity)
            self.assertEqual(first.status_code, 201, first.text)
            video_id = first.json()['video_id']
            uploads_before = set((self.settings.storage / 'uploads').iterdir())
            pending = executor.submit(self.upload, client, identity, b'second-camera', 'side')
            try:
                self.assertTrue(entered.wait(2))
                accepted = executor.submit(client.post, f'/api/v1/sessions/{identity}/analysis',
                    json={'mode': 'single_view', 'video_ids': [video_id]}).result(timeout=2)
                self.assertEqual(accepted.status_code, 202, accepted.text)
            finally:
                release.set()
                response = pending.result(timeout=5)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['error']['code'], 'SESSION_LOCKED')
            self.assertEqual(set((self.settings.storage / 'uploads').iterdir()), uploads_before)
            self.assertEqual(self.wait(client, accepted.json()['job_id'])['status'], 'completed')
            detail = client.get(f'/api/v1/sessions/{identity}').json()
            self.assertEqual([video['video_id'] for video in detail['videos']], [video_id])
            with client.app.state.sessions() as db:
                self.assertEqual(db.scalar(select(func.count()).select_from(Video)), 1)
                self.assertEqual(db.scalar(select(func.count()).select_from(LegacyVideo)), 1)
                self.assertEqual(db.scalar(select(LegacyVideo.file_path)), db.get(Video, video_id).storage_key)

    def test_completed_and_queued_cancelled_jobs_release_runtime_controls(self):
        release = threading.Event()
        try:
            with self.client(helpers.TestRunner(self.settings, gate=release)) as client:
                first = self.session(client)
                video = self.upload(client, first).json()['video_id']
                running = client.post(f'/api/v1/sessions/{first}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
                until(lambda: client.get(f'/api/v1/jobs/{running["job_id"]}').json()['stage'] == 'test')
                second = self.session(client)
                video = self.upload(client, second).json()['video_id']
                queued = client.post(f'/api/v1/sessions/{second}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
                response = client.post(f'/api/v1/jobs/{queued["job_id"]}/control', json={'action': 'cancel'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(client.get(f'/api/v1/jobs/{queued["job_id"]}').json()['status'], 'cancelled')
                release.set()
                self.assertEqual(self.wait(client, running['job_id'])['status'], 'completed')
                manager = client.app.state.jobs

                def released():
                    with manager.lock:
                        return not manager.controls and not manager.futures

                until(released)
                self.assertEqual(client.post(f'/api/v1/jobs/{running["job_id"]}/control', json={'action': 'resume'}).status_code, 409)
                self.assertEqual(client.get(f'/api/v1/sessions/{first}').json()['status'], 'completed')
                client.app.state.runner.fail = True
                third = self.session(client)
                video = self.upload(client, third).json()['video_id']
                failed = client.post(f'/api/v1/sessions/{third}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
                self.assertEqual(self.wait(client, failed['job_id'])['status'], 'failed')
                until(released)
        finally:
            release.set()


class PipelineIOTests(unittest.TestCase):
    def test_verified_copy_preserves_content_and_removes_corrupt_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source.mp4', root / 'copy.mp4'
            content = b'video-data' * 300000
            source.write_bytes(content)
            copy_verified(source, target, hashlib.sha256(content).hexdigest())
            self.assertEqual(target.read_bytes(), content)
            with self.assertRaises(FileExistsError):
                copy_verified(source, target, 'wrong-hash')
            self.assertEqual(target.read_bytes(), content)
            target.unlink()
            with self.assertRaisesRegex(ValueError, 'Stored source content changed'):
                copy_verified(source, target, 'wrong-hash')
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), content)

    def test_verified_copy_observes_cancellation_and_removes_partial_output(self):
        class CancelledControl:
            def checkpoint(self):
                raise JobCancelled()

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source.mp4', root / 'copy.mp4'
            source.write_bytes(b'video')
            with self.assertRaises(JobCancelled):
                copy_verified(source, target, 'unused', CancelledControl())
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), b'video')

    def test_toolchain_discovery_is_reused_and_failures_can_be_retried(self):
        runner = PipelineRunner(helpers.Settings())
        tools = object()
        with patch('cv.video_tools.media.Toolchain.discover', side_effect=[ValueError('Not installed yet'), tools]) as discover:
            with self.assertRaises(ValueError):
                runner.tools()
            self.assertIs(runner.tools(), tools)
            self.assertIs(runner.tools(), tools)
            self.assertEqual(discover.call_count, 2)
