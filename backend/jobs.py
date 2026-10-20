from concurrent.futures import ThreadPoolExecutor
import logging
from sqlalchemy import select

from .db import Event, Job, TrainingSession, Video, now

logger = logging.getLogger(__name__)


class JobManager:
    """One local inference worker. Persistence comes from the database, not browser state."""
    def __init__(self, sessions, runner):
        self.sessions, self.runner = sessions, runner
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='petlo-analysis')

    def enqueue(self, job_id):
        self.executor.submit(self.execute, job_id)

    def execute(self, job_id):
        def update(stage):
            with self.sessions.begin() as db:
                job = db.get(Job, job_id)
                job.status, job.stage = 'running', stage
                db.get(TrainingSession, job.session_id).status = 'running'
        try:
            with self.sessions() as db:
                job = db.get(Job, job_id)
                mode = job.mode
                videos = []
                for identity in job.video_ids:
                    value = db.get(Video, identity)
                    videos.append({name: getattr(value, name) for name in ('video_id', 'storage_key', 'camera_perspective', 'source_sha256')})
            result = self.runner.run(job_id, mode, videos, update)
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
                db.get(TrainingSession, job.session_id).status = 'completed'
        except Exception:
            logger.exception('Analysis failed for job %s', job_id)
            with self.sessions.begin() as db:
                job = db.get(Job, job_id)
                job.status, job.finished_at = 'failed', now()
                job.error_json = {'code': 'ANALYSIS_FAILED', 'message': 'Analysis failed. Inspect the local server/job log for details.'}
                db.get(TrainingSession, job.session_id).status = 'failed'

    def close(self):
        # Graceful shutdown lets current subprocess stages finish; do not start a second API worker.
        self.executor.shutdown(wait=True)
