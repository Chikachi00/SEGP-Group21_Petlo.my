import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import psutil
from sqlalchemy import select

from backend.tests import test_api as helpers
from backend.db import Event, Job, TrainingSession, User
from backend.process_control import JobCancelled, ProcessControl


def until(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('Expected state was not reached.')


class ControlledRunner(helpers.TestRunner):
    supports_job_control = True

    def run(self, job_id, mode, videos, update, control=None):
        update('controlled')
        target = self.settings.storage / 'controlled.log'
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('ab') as output:
            control.command([sys.executable, '-c', 'import time; time.sleep(1)'],
                            cwd=self.settings.storage, stdout=output, timeout=10)
        return super().run(job_id, mode, videos, update)


class SessionManagementTests(unittest.TestCase):
    setUp = helpers.ApiTests.setUp
    tearDown = helpers.ApiTests.tearDown
    client = helpers.ApiTests.client
    session = helpers.ApiTests.session
    upload = helpers.ApiTests.upload
    wait = helpers.ApiTests.wait

    def test_names_trash_restore_and_original_report_survive_restart(self):
        with self.client(helpers.TestRunner(self.settings, with_events=True)) as client:
            identity = self.session(client)
            video = self.upload(client, identity).json()['video_id']
            job = client.post(f'/api/v1/sessions/{identity}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
            self.wait(client, job['job_id'])
            original = client.get(f'/api/v1/sessions/{identity}').json()
            self.assertEqual(original['name'], 'Front view session')
            renamed = client.patch(f'/api/v1/sessions/{identity}', json={'name': '  Sample training — Front  '})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(renamed.json()['name'], 'Sample training — Front')
            self.assertEqual(client.patch(f'/api/v1/sessions/{identity}', json={'name': '   '}).status_code, 422)
            self.assertEqual(client.patch(f'/api/v1/sessions/{identity}', json={'name': 'x' * 121}).status_code, 422)
            self.assertEqual(client.delete(f'/api/v1/sessions/{identity}').status_code, 200)
            self.assertEqual(client.get('/api/v1/sessions').json()['total'], 0)
            self.assertEqual(client.get('/api/v1/sessions?trash=true').json()['total'], 1)
            self.assertEqual(client.get(f'/api/v1/sessions/{identity}').status_code, 404)
            self.assertEqual(client.get(original['videos'][0]['playback_url']).status_code, 404)
            with client.app.state.sessions() as db:
                self.assertEqual(len(list(db.scalars(select(Event).where(Event.job_id == job['job_id'])))), 2)
            self.assertTrue(any(self.settings.storage.rglob('preview.mp4')))
        with self.client() as client:
            restored = client.post(f'/api/v1/sessions/{identity}/restore')
            self.assertEqual(restored.status_code, 200, restored.text)
            detail = client.get(f'/api/v1/sessions/{identity}').json()
            self.assertEqual(detail['name'], 'Sample training — Front')
            self.assertEqual(detail['events'], original['events'])
            self.assertEqual(detail['statistics'], original['statistics'])
            self.assertEqual(client.get(detail['videos'][0]['playback_url'], headers={'Range': 'bytes=0-2'}).status_code, 206)

    def test_create_custom_name_and_control_other_users_are_rejected(self):
        with self.client() as client:
            created = client.post('/api/v1/sessions', json={'dog_id': '1', 'name': 'My first training'})
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()['name'], 'My first training')
            with client.app.state.sessions.begin() as db:
                db.add(User(user_id=2, email='other@invalid.test', password_hash='disabled', system_role='Trainer', name='Other'))
                db.flush()
                db.add(TrainingSession(session_id='other-session', dog_id=1, trainer_id=2, status='ready'))
                db.flush()
                db.add(Job(job_id='other-job', session_id='other-session', status='queued', mode='single_view', video_ids=[]))
            self.assertEqual(client.patch('/api/v1/sessions/other-session', json={'name': 'Changed'}).status_code, 404)
            self.assertEqual(client.delete('/api/v1/sessions/other-session').status_code, 404)
            self.assertEqual(client.post('/api/v1/sessions/other-session/restore').status_code, 404)
            self.assertEqual(client.post('/api/v1/jobs/other-job/control', json={'action': 'pause'}).status_code, 404)

    def test_pause_resume_preserve_job_and_cancel_is_terminal(self):
        with self.client(ControlledRunner(self.settings)) as client:
            identity = self.session(client)
            video = self.upload(client, identity).json()['video_id']
            job = client.post(f'/api/v1/sessions/{identity}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
            url = f'/api/v1/jobs/{job["job_id"]}'
            until(lambda: client.get(url).json()['stage'] == 'controlled')
            self.assertEqual(client.post(url + '/control', json={'action': 'pause'}).status_code, 200)
            until(lambda: client.get(url).json()['status'] == 'paused')
            self.assertEqual(client.post(url + '/control', json={'action': 'pause'}).json()['status'], 'paused')
            self.assertEqual(client.get(f'/api/v1/sessions/{identity}').json()['status'], 'paused')
            self.assertEqual(client.post(f'/api/v1/sessions/{identity}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).status_code, 409)
            self.assertEqual(client.post(url + '/control', json={'action': 'resume'}).status_code, 200)
            time.sleep(.05)
            self.assertEqual(client.post(url + '/control', json={'action': 'cancel'}).status_code, 200)
            until(lambda: client.get(url).json()['status'] == 'cancelled')
            self.assertEqual(client.get(f'/api/v1/sessions/{identity}').json()['current_job_id'], job['job_id'])
            self.assertEqual(client.post(url + '/control', json={'action': 'resume'}).status_code, 409)

    def test_delete_active_task_cancels_it_and_restore_keeps_inputs(self):
        with self.client(ControlledRunner(self.settings)) as client:
            identity = self.session(client)
            video = self.upload(client, identity).json()['video_id']
            job = client.post(f'/api/v1/sessions/{identity}/analysis', json={'mode': 'single_view', 'video_ids': [video]}).json()
            self.assertEqual(client.delete(f'/api/v1/sessions/{identity}').status_code, 200)
            def cancelled():
                with client.app.state.sessions() as db:
                    return db.get(Job, job['job_id']).status == 'cancelled'
            until(cancelled)
            self.assertEqual(client.get('/api/v1/sessions').json()['total'], 0)
            restored = client.post(f'/api/v1/sessions/{identity}/restore').json()
            self.assertEqual(restored['status'], 'cancelled')
            self.assertEqual(len(client.get(f'/api/v1/sessions/{identity}').json()['videos']), 1)


class RealProcessControlTests(unittest.TestCase):
    def test_pause_freezes_parent_and_child_and_cancel_terminates_both(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = root / 'child.py'
            child.write_text("import pathlib,time\np=pathlib.Path('child-ticks')\nwhile True:\n with p.open('a') as f: f.write('tick\\n'); f.flush()\n time.sleep(.02)\n", encoding='utf-8')
            parent = root / 'parent.py'
            parent.write_text("import pathlib,subprocess,sys,time\np=subprocess.Popen([sys.executable,'-u','child.py'])\npathlib.Path('child-pid').write_text(str(p.pid))\np=pathlib.Path('parent-ticks')\nwhile True:\n with p.open('a') as f: f.write('tick\\n'); f.flush()\n time.sleep(.02)\n", encoding='utf-8')
            states, failures = [], []
            control = ProcessControl(states.append)
            control.started = True
            def run():
                try:
                    with (root / 'process.log').open('wb') as log:
                        control.command([sys.executable, '-u', parent], cwd=root, stdout=log, timeout=15)
                except Exception as exc:
                    failures.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            try:
                until(lambda: (root / 'child-ticks').exists())
                child_pid = int((root / 'child-pid').read_text())
                control.request('pause')
                until(lambda: states and states[-1] == 'paused')
                time.sleep(.1)
                before = [(root / name).read_bytes() for name in ['parent-ticks', 'child-ticks']]
                time.sleep(.35)
                self.assertEqual(before, [(root / name).read_bytes() for name in ['parent-ticks', 'child-ticks']])
                control.request('resume')
                until(lambda: (root / 'child-ticks').read_bytes() != before[1])
                parent_pid = control.process.pid
                control.request('cancel')
                thread.join(6)
                self.assertFalse(thread.is_alive())
                self.assertTrue(failures and isinstance(failures[0], JobCancelled), failures)
                self.assertFalse(psutil.pid_exists(parent_pid))
                self.assertFalse(psutil.pid_exists(child_pid))
            finally:
                if thread.is_alive():
                    control.request('cancel')
                    thread.join(6)

    def test_paused_time_does_not_consume_subprocess_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            states, failures = [], []
            control = ProcessControl(states.append)
            control.started = True
            def run():
                try:
                    with (root / 'process.log').open('wb') as log:
                        control.command([sys.executable, '-c', "from pathlib import Path; import time; Path('ready').touch(); time.sleep(1)"], cwd=root, stdout=log, timeout=2)
                except Exception as exc:
                    failures.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            try:
                until(lambda: (root / 'ready').exists())
                control.request('pause')
                until(lambda: states and states[-1] == 'paused')
                time.sleep(2.2)
                control.request('resume')
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
            finally:
                if thread.is_alive():
                    control.request('cancel')
                    thread.join(6)
