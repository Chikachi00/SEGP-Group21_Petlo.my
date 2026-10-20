"""Additive tables; create_all never alters or drops existing MySQL tables."""
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, UniqueConstraint, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'user_login'
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    system_role: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255))


class Dog(Base):
    __tablename__ = 'dogs'
    dog_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('user_login.user_id'))
    name: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[date] = mapped_column(Date)
    breed: Mapped[str] = mapped_column(String(255))


class LegacyVideo(Base):
    __tablename__ = 'video'
    video_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1023))
    camera_perspective: Mapped[str] = mapped_column(String(127))
    video_length: Mapped[int] = mapped_column(Integer)


class TrainingSession(Base):
    __tablename__ = 'analysis_sessions'
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dog_id: Mapped[int] = mapped_column(ForeignKey('dogs.dog_id'))
    trainer_id: Mapped[int] = mapped_column(ForeignKey('user_login.user_id'))
    recorded_at: Mapped[str] = mapped_column(String(40), default=now)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    status: Mapped[str] = mapped_column(String(16), default='draft')
    current_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Video(Base):
    __tablename__ = 'analysis_videos'
    __table_args__ = (UniqueConstraint('session_id', 'camera_perspective'),)
    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('analysis_sessions.session_id'), index=True)
    legacy_video_id: Mapped[int] = mapped_column(ForeignKey('video.video_id'))
    camera_perspective: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(1023))
    preview_key: Mapped[str | None] = mapped_column(String(1023), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON)


class Job(Base):
    __tablename__ = 'analysis_jobs'
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('analysis_sessions.session_id'), index=True)
    status: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    video_ids: Mapped[list] = mapped_column(JSON)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Event(Base):
    __tablename__ = 'analysis_events'
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('analysis_jobs.job_id'), index=True)
    category: Mapped[str] = mapped_column(String(40))
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    source_intervals: Mapped[list] = mapped_column(JSON)


def database(settings):
    if settings.database_url.startswith('sqlite:///'):
        Path(settings.database_url[len('sqlite:///'):]).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, connect_args={'check_same_thread': False, 'timeout': 30} if settings.database_url.startswith('sqlite:') else {}, pool_pre_ping=True)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def enable_foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize(engine, sessions, settings):
    Base.metadata.create_all(engine)
    with sessions.begin() as db:
        if settings.seed_demo and not db.get(User, settings.local_user_id):
            db.add(User(user_id=settings.local_user_id, email='local-demo@localhost.invalid', password_hash='!login-disabled', system_role='Trainer', name='Local development user'))
            db.flush()
            db.add(Dog(owner_id=settings.local_user_id, name='Local demo dog', date_of_birth=date(2020, 1, 1), breed='Development placeholder'))
        if not db.get(User, settings.local_user_id):
            raise ValueError('PETLO_LOCAL_USER_ID must reference an existing user_login record')
        # Interrupted jobs are explicit failures; never replay work invisibly on restart.
        for job in db.scalars(select(Job).where(Job.status.in_(['queued', 'running']))):
            job.status, job.stage = 'failed', 'interrupted'
            job.error_json = {'code': 'SERVER_RESTARTED', 'message': 'Analysis was interrupted. Start a new job.'}
            job.finished_at = now()
            parent = db.get(TrainingSession, job.session_id)
            if parent and parent.current_job_id == job.job_id:
                parent.status = 'failed'
