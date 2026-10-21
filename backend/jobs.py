from concurrent.futures import ThreadPoolExecutor
import logging
import threading

from .db import Event, Job, TrainingSession, Video, now
from .process_control import ACTIVE, TERMINAL, JobCancelled, ProcessControl

logger = logging.getLogger(__name__)


class JobManager:
    """One inference worker with owned-process pause/resume/cancel controls."""
    def __init__(self, sessions, runner):
        self.sessions, self.runner = sessions, runner
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='petlo-analysis')
        self.lock = threading.RLock()
        self.controls = {}
        self.futures = {}

    def publish(self, job_id, status, *, stage=None, error=None):
        with self.sessions.begin() as db:
            job = db.get(Job, job_id)
            if job.status in TERMINAL:
                return
            job.status = status
            if stage is not None:
                job.stage = stage
            if status in TERMINAL:
                job.finished_at = now()
                job.error_json = error
            parent = db.get(TrainingSession, job.session_id)
            if parent.current_job_id == job_id:
                parent.status = status

    def enqueue(self, job_id):
        with self.lock:
            control = ProcessControl(lambda status: self.publish(job_id, status))
            self.controls[job_id] = control
            self.futures[job_id] = self.executor.submit(self.execute, job_id, control)

    def request(self, job_id, action):
        with self.lock:
            control = self.controls.get(job_id)
            if control is None:
                raise ValueError('This task is not active in the current server process.')
            control.request(action)
            if action == 'cancel' and self.futures[job_id].cancel():
                with control.condition:
                    self.publish(job_id, 'cancelled')
                    control.finished = True

    def execute(self, job_id, control):
        def update(stage):
            control.checkpoint()
            with control.condition:
                if control.cancel_requested:
                    raise JobCancelled()
                self.publish(job_id, 'running', stage=stage)
        try:
            with control.condition:
                control.started = True
            control.checkpoint()
            with self.sessions() as db:
                job = db.get(Job, job_id)
                mode = job.mode
                videos = []
                for identity in job.video_ids:
                    value = db.get(Video, identity)
                    videos.append({name: getattr(value, name) for name in ('video_id', 'storage_key', 'camera_perspective', 'source_sha256')})
            if getattr(self.runner, 'supports_job_control', False):
                result = self.runner.run(job_id, mode, videos, update, control=control)
            else:
                result = self.runner.run(job_id, mode, videos, update)
            control.checkpoint()
            with control.condition:
                if control.cancel_requested:
                    raise JobCancelled()
                with self.sessions.begin() as db:
                    job = db.get(Job, job_id)
                    for value in result['events']:
                        db.add(Event(job_id=job_id, **value))
                    for identity, key in result['previews'].items():
                        video = db.get(Video, identity)
                        video.preview_key = key
                        video.metadata_json = result['metadata'][identity]
                    job.result_json = {key: result[key] for key in ('statistics', 'algorithm_version', 'limitations')}
                    job.status, job.stage, job.finished_at = 'completed', 'complete', now()
                    parent = db.get(TrainingSession, job.session_id)
                    if parent.current_job_id == job_id:
                        parent.status = 'completed'
                control.finished = True
        except JobCancelled:
            with control.condition:
                self.publish(job_id, 'cancelled')
                control.finished = True
        except Exception:
            logger.exception('Analysis failed for job %s', job_id)
            with control.condition:
                self.publish(job_id, 'failed', error={'code': 'ANALYSIS_FAILED', 'message': 'Analysis failed. Inspect the local server/job log for details.'})
                control.finished = True

    def close(self):
        # Paused tasks must not make server shutdown wait forever.
        with self.lock:
            identities = [identity for identity, control in self.controls.items() if not control.finished]
        for identity in identities:
            try:
                self.request(identity, 'cancel')
            except ValueError:
                pass
        self.executor.shutdown(wait=True)
