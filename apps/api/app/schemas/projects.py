import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.db.models import JobStatus, JobType, ProjectStatus, SourceType


class UploadSource(BaseModel):
    type: Literal["upload"]
    key: str = Field(min_length=1, max_length=1024)


class UrlSource(BaseModel):
    type: Literal["url"]
    url: HttpUrl


ProjectSource = Annotated[UploadSource | UrlSource, Field(discriminator="type")]


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source: ProjectSource


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: JobType
    status: JobStatus
    progress: int
    error: str | None
    clip_id: uuid.UUID | None
    started_at: datetime | None
    finished_at: datetime | None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    source_url: str | None
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    status: ProjectStatus
    error: str | None
    progress: int = Field(ge=0, le=100, description="Progress of the active pipeline stage")
    created_at: datetime
    updated_at: datetime
