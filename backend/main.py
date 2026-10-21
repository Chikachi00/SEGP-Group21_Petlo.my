"""Loopback-only local service. Authentication/public deployment is a separate step."""
from contextlib import asynccontextmanager
from datetime import timezone
import hashlib
import ipaddress
import logging
import math
import threading
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, update
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .db import Dog, Event, Job, LegacyVideo, TrainingSession, Video, database, initialize, now
from .jobs import JobManager
from .pipeline import PipelineRunner, inside, validate_selection
from .schemas import CreateDog, CreateSession, DetailOut, JobOut, SessionListOut, SessionOut, StartAnalysis, VideoOut

log = logging.getLogger(__name__)


def problem(status, code, message):
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})


def response_error(status, code, message, request_id, details=None):
    return JSONResponse(status_code=status, content={'error': {
        'code': code, 'message': message, 'details': details, 'request_id': request_id,
    }})


class UploadBodyLimit:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        limited = scope['type'] == 'http' and scope['method'] == 'POST' and scope['path'].endswith('/videos')
        size = 0

        async def counted_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > self.max_bytes:
                raise HTTPException(413, detail={'code': 'UPLOAD_TOO_LARGE', 'message': 'Upload exceeds the configured limit.'})
            return message
        await self.app(scope, counted_receive if limited else receive, send)


def create_app(settings=None, runner=None):
    config = settings or Settings()
    config.validate()
    engine, sessions = database(config)
    worker = runner or PipelineRunner(config)
    lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        config.storage.mkdir(parents=True, exist_ok=True)
        initialize(engine, sessions, config)
        app.state.jobs = JobManager(sessions, worker)
        yield
        app.state.jobs.close()
        engine.dispose()

    app = FastAPI(title='Petlo local integration API', version='1.0.0', lifespan=lifespan)
    app.state.sessions, app.state.settings, app.state.runner = sessions, config, worker
    app.add_middleware(UploadBodyLimit, max_bytes=config.max_upload_bytes + 65536)
    app.add_middleware(CORSMiddleware, allow_origins=list(config.origins), allow_methods=['GET', 'POST', 'OPTIONS'],
                       allow_headers=['Content-Type'], expose_headers=['X-Request-ID'], allow_credentials=False)

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        try:
            local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not local:
            return response_error(403, 'LOCAL_ONLY', 'This development service only accepts loopback clients.', request_id)
        origin = request.headers.get('origin')
        if origin and origin not in config.origins:
            return response_error(403, 'ORIGIN_NOT_ALLOWED', 'Origin is not allowed.', request_id)
        try:
            response = await call_next(request)
        except Exception:
            log.exception('Request failed: %s', request_id)
            return response_error(500, 'SERVER_ERROR', 'The server could not complete this request.', request_id)
        response.headers['X-Request-ID'] = request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return response_error(exc.status_code, detail.get('code', 'HTTP_ERROR'),
                              detail.get('message', str(exc.detail)), request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return response_error(422, 'INVALID_REQUEST', 'Request validation failed.', request.state.request_id,
                              [{'field': list(e['loc']), 'message': e['msg']} for e in exc.errors()])

    def owned(db, identity):
        value = db.get(TrainingSession, identity)
        if not value or value.trainer_id != config.local_user_id:
            problem(404, 'SESSION_NOT_FOUND', 'Session not found.')
        return value

    def summary(db, value):
        job = db.get(Job, value.current_job_id) if value.current_job_id else None
        result = job.result_json if job and job.status == 'completed' else None
        return {'session_id': value.session_id, 'dog_id': str(value.dog_id), 'date': value.recorded_at,
                'status': value.status, 'statistics': result['statistics'] if result else None}

    def video_json(value, request):
        url = str(request.url_for('playback', video_id=value.video_id)) if value.preview_key else None
        return {'video_id': value.video_id, 'session_id': value.session_id, 'camera_perspective': value.camera_perspective,
                'duration_sec': value.metadata_json.get('duration'), 'width': value.metadata_json.get('width'),
                'height': value.metadata_json.get('height'), 'playback_url': url, 'preview_url': url}

    def job_json(value):
        return {'job_id': value.job_id, 'session_id': value.session_id, 'status': value.status,
                'progress_percent': 100 if value.status == 'completed' else None,
                'stage': value.stage, 'error': value.error_json,
                'created_at': value.created_at, 'finished_at': value.finished_at}

    @app.get('/api/v1/health')
    def health():
        return {'status': 'ok', 'mode': 'local_single_user', 'max_upload_bytes': config.max_upload_bytes}

    @app.get('/api/v1/dogs')
    def dogs():
        with sessions() as db:
            return {'items': [{'dog_id': str(d.dog_id), 'name': d.name, 'breed': d.breed,
                               'date_of_birth': d.date_of_birth.isoformat()}
                              for d in db.scalars(select(Dog).where(Dog.owner_id == config.local_user_id).order_by(Dog.dog_id))]}

    @app.post('/api/v1/dogs', status_code=201)
    def create_dog(body: CreateDog):
        with sessions.begin() as db:
            value = Dog(owner_id=config.local_user_id, **body.model_dump())
            db.add(value)
            db.flush()
            return {'dog_id': str(value.dog_id), **body.model_dump(mode='json')}

    @app.post('/api/v1/sessions', status_code=201, response_model=SessionOut)
    def create_session(body: CreateSession):
        try:
            dog_id = int(body.dog_id)
        except ValueError:
            problem(422, 'INVALID_DOG', 'Choose a dog returned by /dogs.')
        with sessions.begin() as db:
            dog = db.get(Dog, dog_id)
            if not dog or dog.owner_id != config.local_user_id:
                problem(404, 'DOG_NOT_FOUND', 'Dog not found.')
            value = TrainingSession(session_id=uuid.uuid4().hex, dog_id=dog_id, trainer_id=config.local_user_id,
                                    recorded_at=body.recorded_at.astimezone(timezone.utc).isoformat() if body.recorded_at else now(), status='draft')
            db.add(value)
            db.flush()
            return summary(db, value)

    @app.post('/api/v1/sessions/{session_id}/videos', status_code=201, response_model=VideoOut)
    def upload(session_id: str, request: Request, file: UploadFile = File(...), camera_perspective: str = Form(...)):
        from pathlib import Path
        suffix = Path(file.filename or '').suffix.lower()
        if camera_perspective not in ('front', 'side'):
            problem(422, 'INVALID_VIEW', 'Choose front or side.')
        if suffix not in ('.mp4', '.mov', '.mkv', '.avi', '.webm'):
            problem(415, 'VIDEO_UNSUPPORTED', 'Choose an MP4, MOV, MKV, AVI or WebM file.')
        identity = uuid.uuid4().hex
        storage_key = f'uploads/{identity}{suffix}'
        target = inside(config.storage, storage_key)
        saved = False
        try:
            with lock, sessions.begin() as db:
                parent = owned(db, session_id)
                if parent.current_job_id:
                    problem(409, 'SESSION_LOCKED', 'Videos cannot be added after analysis starts.')
                if db.scalar(select(Video.video_id).where(Video.session_id == session_id, Video.camera_perspective == camera_perspective)):
                    problem(409, 'DUPLICATE_VIEW', 'This session already has that camera view.')
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with target.open('xb') as stream:
                    while chunk := file.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > config.max_upload_bytes:
                            problem(413, 'UPLOAD_TOO_LARGE', 'Video exceeds the configured limit.')
                        digest.update(chunk)
                        stream.write(chunk)
                if size == 0:
                    problem(422, 'VIDEO_EMPTY', 'Video is empty.')
                try:
                    metadata = worker.probe(target)
                    if not math.isfinite(metadata['duration']) or metadata['duration'] <= 0 or metadata['width'] <= 0 or metadata['height'] <= 0:
                        raise ValueError('Invalid dimensions/duration')
                except Exception:
                    log.exception('Video metadata validation failed')
                    problem(422, 'VIDEO_INVALID', 'Video could not be validated by the local decoder. Check the media and FFmpeg configuration.')
                legacy = LegacyVideo(file_path=storage_key, camera_perspective=camera_perspective, video_length=math.ceil(metadata['duration']))
                db.add(legacy)
                db.flush()
                value = Video(video_id=identity, session_id=session_id, legacy_video_id=legacy.video_id,
                              camera_perspective=camera_perspective, storage_key=storage_key,
                              source_sha256=digest.hexdigest(), metadata_json=metadata)
                db.add(value)
                parent.status = 'ready'
                db.flush()
                result = video_json(value, request)
            saved = True
            return result
        finally:
            file.file.close()
            if not saved and target.is_file():
                target.unlink()

    @app.post('/api/v1/sessions/{session_id}/analysis', status_code=202, response_model=JobOut)
    def analyze(session_id: str, body: StartAnalysis, request: Request):
        with lock, sessions.begin() as db:
            parent = owned(db, session_id)
            if parent.status in ('queued', 'running'):
                problem(409, 'JOB_ALREADY_RUNNING', 'This session already has an active analysis job.')
            videos = [db.get(Video, identity) for identity in body.video_ids]
            if any(not value or value.session_id != session_id for value in videos):
                problem(404, 'VIDEO_NOT_FOUND', 'A selected video does not belong to this session.')
            try:
                validate_selection(body.mode, [{'camera_perspective': v.camera_perspective, 'source_sha256': v.source_sha256} for v in videos])
            except ValueError as exc:
                problem(422, 'ANALYSIS_MODE_UNSUPPORTED', str(exc))
            try:
                worker.check_ready()
            except Exception:
                problem(503, 'ANALYZER_UNAVAILABLE', 'Configure the local YOLO model and FFmpeg before starting analysis.')
            changed = db.execute(update(TrainingSession).where(TrainingSession.session_id == session_id,
                TrainingSession.status.not_in(['queued', 'running'])).values(status='queued'))
            if changed.rowcount != 1:
                problem(409, 'JOB_ALREADY_RUNNING', 'Another request already started analysis.')
            value = Job(job_id=uuid.uuid4().hex, session_id=session_id, status='queued', stage='queued',
                        mode=body.mode, video_ids=body.video_ids)
            db.add(value)
            parent.current_job_id = value.job_id
            db.flush()  # Resolve the persisted submission timestamp before serializing.
            result = job_json(value)
        try:
            request.app.state.jobs.enqueue(value.job_id)
        except Exception:
            with sessions.begin() as db:
                failed = db.get(Job, value.job_id)
                failed.status, failed.finished_at = 'failed', now()
                failed.error_json = {'code': 'QUEUE_UNAVAILABLE', 'message': 'Could not submit analysis.'}
                db.get(TrainingSession, session_id).status = 'failed'
            problem(503, 'QUEUE_UNAVAILABLE', 'Could not submit analysis.')
        return result

    @app.get('/api/v1/jobs/{job_id}', response_model=JobOut)
    def get_job(job_id: str):
        with sessions() as db:
            value = db.get(Job, job_id)
            if not value:
                problem(404, 'JOB_NOT_FOUND', 'Job not found.')
            owned(db, value.session_id)
            return job_json(value)

    @app.get('/api/v1/sessions', response_model=SessionListOut)
    def list_sessions(page: int = 1, page_size: int = 20):
        if page < 1 or not 1 <= page_size <= 100:
            problem(422, 'INVALID_PAGE', 'Use page >= 1 and page_size from 1 to 100.')
        with sessions() as db:
            query = select(TrainingSession).where(TrainingSession.trainer_id == config.local_user_id)
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            values = db.scalars(query.order_by(TrainingSession.recorded_at.desc(), TrainingSession.session_id.desc()).offset((page - 1) * page_size).limit(page_size))
            return {'items': [summary(db, value) for value in values], 'page': page, 'page_size': page_size, 'total': total}

    @app.get('/api/v1/sessions/{session_id}', response_model=DetailOut)
    def detail(session_id: str, request: Request):
        with sessions() as db:
            parent = owned(db, session_id)
            value = summary(db, parent)
            job = db.get(Job, parent.current_job_id) if parent.current_job_id else None
            result = job.result_json if job and job.status == 'completed' else None
            events = db.scalars(select(Event).where(Event.job_id == job.job_id).order_by(Event.event_id)) if result else []
            value.update(videos=[video_json(v, request) for v in db.scalars(select(Video).where(Video.session_id == session_id))],
                events=[{'event_id': e.event_id, 'category': e.category, 'conflict': e.conflict, 'source_intervals': e.source_intervals} for e in events],
                algorithm_version=result['algorithm_version'] if result else None,
                limitations=result['limitations'] if result else [], current_job_id=parent.current_job_id)
            return value

    @app.get('/api/v1/videos/{video_id}/playback', name='playback')
    def playback(video_id: str):
        with sessions() as db:
            value = db.get(Video, video_id)
            if not value:
                problem(404, 'VIDEO_NOT_FOUND', 'Video not found.')
            owned(db, value.session_id)
            if not value.preview_key:
                problem(404, 'PREVIEW_PENDING', 'Playback will be available after analysis completes.')
            path = inside(config.storage, value.preview_key)
            if not path.is_file():
                problem(404, 'MEDIA_NOT_FOUND', 'Playback media is unavailable.')
            return FileResponse(path, media_type='video/mp4', filename=f'{video_id}.mp4', content_disposition_type='inline')

    return app


app = create_app()
