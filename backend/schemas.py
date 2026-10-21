from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dog_id: str = Field(min_length=1)
    recorded_at: datetime | None = None

    @field_validator('recorded_at')
    @classmethod
    def timezone_required(cls, value):
        if value and value.tzinfo is None:
            raise ValueError('recorded_at requires a timezone')
        return value


class CreateDog(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    breed: str = Field(min_length=1, max_length=255)
    date_of_birth: date


class StartAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    video_ids: list[str] = Field(min_length=1, max_length=2)
    mode: Literal['single_view', 'sample_pair']

    @field_validator('video_ids')
    @classmethod
    def unique_ids(cls, value):
        if any(not v.strip() for v in value) or len(set(value)) != len(value):
            raise ValueError('Video IDs must be non-empty and unique')
        return value


Category = Literal['in_air_catch_candidate', 'ground_pickup_candidate', 'miss_candidate', 'uncertain']


class StatisticsOut(BaseModel):
    report_type: Literal['unverified_candidate_statistics']
    total_throw_candidates: int = Field(ge=0)
    classified_candidate_events: int = Field(ge=0)
    uncertain_events: int = Field(ge=0)
    candidate_counts: dict[Category, int]
    candidate_coverage: float | None = Field(ge=0, le=1)
    in_air_catch_candidate_rate: float | None = Field(ge=0, le=1)
    retrieval_candidate_rate: float | None = Field(ge=0, le=1)
    denominator_definition: str
    human_labels_used_for_statistics: Literal[False]


class SessionOut(BaseModel):
    session_id: str
    dog_id: str
    date: str
    status: Literal['draft', 'ready', 'queued', 'running', 'completed', 'failed']
    statistics: StatisticsOut | None


class VideoOut(BaseModel):
    video_id: str
    session_id: str
    camera_perspective: Literal['front', 'side']
    duration_sec: float | None
    width: int | None
    height: int | None
    playback_url: str | None
    preview_url: str | None


class IntervalOut(BaseModel):
    video_id: str
    start_sec: float = Field(ge=0)
    end_sec: float = Field(ge=0)


class EventOut(BaseModel):
    event_id: str
    category: Category
    conflict: bool
    source_intervals: list[IntervalOut]


class DetailOut(SessionOut):
    current_job_id: str | None
    videos: list[VideoOut]
    events: list[EventOut]
    algorithm_version: str | None
    limitations: list[str]


class SessionListOut(BaseModel):
    items: list[SessionOut]
    page: int
    page_size: int
    total: int


class JobErrorOut(BaseModel):
    code: str
    message: str


class JobOut(BaseModel):
    job_id: str
    session_id: str
    status: Literal['queued', 'running', 'completed', 'failed']
    progress_percent: float | None = Field(ge=0, le=100)
    stage: str | None
    error: JobErrorOut | None
    created_at: str
    finished_at: str | None
