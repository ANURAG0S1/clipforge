import asyncio
import logging
import uuid
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, RateLimiterDep, SessionDep, SettingsDep, StorageDep, not_found
from app.db.models import (
    Job,
    JobStatus,
    JobType,
    Project,
    ProjectStatus,
    SourceType,
    Transcript,
)
from app.schemas.projects import JobOut, ProjectCreate, ProjectOut, UploadSource
from app.schemas.transcript import ProjectMediaOut, TranscriptOut
from app.services import pipeline
from app.services.keys import project_prefix, proxy_key, upload_prefix
from app.services.storage import StorageError
from app.services.url_guard import UnsafeUrlError, validate_public_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])

_ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)
MEDIA_URL_TTL_S = 6 * 3600


async def get_owned_project(db: SessionDep, user_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if project is None:
        raise not_found("Project")
    return project


async def _latest_jobs(db: SessionDep, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not project_ids:
        return {}
    rows = await db.scalars(
        select(Job)
        .where(Job.project_id.in_(project_ids), Job.clip_id.is_(None))
        .order_by(Job.project_id, Job.created_at.desc())
        .distinct(Job.project_id)
    )
    return {job.project_id: job for job in rows}


def _to_out(project: Project, job: Job | None) -> ProjectOut:
    if project.status in (ProjectStatus.READY, ProjectStatus.FAILED):
        progress = 100 if project.status == ProjectStatus.READY else 0
    else:
        progress = job.progress if job is not None and job.status != JobStatus.SUCCEEDED else 0
    return ProjectOut.model_validate(
        {
            **{c: getattr(project, c) for c in ProjectOut.model_fields if c != "progress"},
            "progress": progress,
        }
    )


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    limiter: RateLimiterDep,
) -> ProjectOut:
    verdict = await limiter.hit(
        f"projects:create:{user.id}",
        settings.project_create_limit,
        settings.project_create_window_s,
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Project creation limit reached. Try again later.",
            headers={"Retry-After": str(verdict.retry_after_s)},
        )

    source = body.source
    if isinstance(source, UploadSource):
        key = source.key
        if not key.startswith(upload_prefix(user.id)) or ".." in key or "//" in key:
            # Someone else's (or a forged) key: indistinguishable from a missing upload.
            raise not_found("Upload")
        try:
            size = await asyncio.to_thread(storage.head_size, key)
        except StorageError:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Storage unavailable"
            ) from None
        if size is None:
            raise not_found("Upload")
        if size > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"File is larger than the {settings.max_upload_gb:g} GB limit",
            )
        project = Project(
            user_id=user.id, title=body.title, source_type=SourceType.UPLOAD, source_key=key
        )
    else:
        try:
            url = await asyncio.to_thread(validate_public_url, str(source.url))
        except UnsafeUrlError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        project = Project(
            user_id=user.id, title=body.title, source_type=SourceType.URL, source_url=url
        )

    project.status = ProjectStatus.PENDING
    db.add(project)
    await db.flush()
    job = Job(project_id=project.id, type=JobType.INGEST, status=JobStatus.QUEUED, progress=0)
    db.add(job)
    await db.flush()
    job.celery_task_id = str(job.id)
    await db.commit()

    try:
        await asyncio.to_thread(pipeline.enqueue_ingest, project.id, job.id)
    except Exception:
        logger.exception("failed to enqueue ingest", extra={"project_id": str(project.id)})
        project.status = ProjectStatus.FAILED
        project.error = "Could not start processing. Please try again."
        job.status = JobStatus.FAILED
        job.error = project.error
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, project.error) from None

    await db.refresh(project)
    return _to_out(project, job)


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: SessionDep) -> list[ProjectOut]:
    projects = list(
        await db.scalars(
            select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc())
        )
    )
    jobs = await _latest_jobs(db, [p.id for p in projects])
    return [_to_out(p, jobs.get(p.id)) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, user: CurrentUser, db: SessionDep) -> ProjectOut:
    project = await get_owned_project(db, user.id, project_id)
    jobs = await _latest_jobs(db, [project.id])
    return _to_out(project, jobs.get(project.id))


@router.get("/{project_id}/jobs", response_model=list[JobOut])
async def list_project_jobs(project_id: uuid.UUID, user: CurrentUser, db: SessionDep) -> list[Job]:
    project = await get_owned_project(db, user.id, project_id)
    return list(
        await db.scalars(
            select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc())
        )
    )


@router.get("/{project_id}/transcript", response_model=TranscriptOut)
async def get_transcript(project_id: uuid.UUID, user: CurrentUser, db: SessionDep) -> TranscriptOut:
    project = await get_owned_project(db, user.id, project_id)
    transcript = await db.scalar(select(Transcript).where(Transcript.project_id == project.id))
    if transcript is None:
        raise not_found("Transcript")
    return TranscriptOut.model_validate(
        {
            "language": transcript.language,
            "duration_s": project.duration_s,
            "words": transcript.words,
            "segments": transcript.segments,
        }
    )


@router.get("/{project_id}/media", response_model=ProjectMediaOut)
async def get_project_media(
    project_id: uuid.UUID, user: CurrentUser, db: SessionDep, storage: StorageDep
) -> ProjectMediaOut:
    """Short-lived URL for the seekable H.264 proxy used by the in-browser player."""
    project = await get_owned_project(db, user.id, project_id)
    if project.duration_s is None:
        raise not_found("Video")
    url = storage.presign_get(proxy_key(project.id), ttl_s=MEDIA_URL_TTL_S)
    return ProjectMediaOut(proxy_url=url, expires_in_s=MEDIA_URL_TTL_S)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, user: CurrentUser, db: SessionDep, storage: StorageDep
) -> Response:
    project = await get_owned_project(db, user.id, project_id)
    active = list(
        await db.scalars(
            select(Job.celery_task_id).where(
                Job.project_id == project.id,
                Job.status.in_(_ACTIVE_JOB_STATUSES),
                Job.celery_task_id.is_not(None),
            )
        )
    )
    try:
        await asyncio.to_thread(pipeline.revoke, [t for t in active if t])
    except Exception:
        # Workers re-check that the project exists, so a missed revoke is harmless.
        logger.warning("revoke failed", extra={"project_id": str(project.id)})
    try:
        await storage.delete_prefix(project_prefix(project.id))
        if project.source_key and project.source_key.startswith(upload_prefix(user.id)):
            await asyncio.to_thread(storage.delete_key, project.source_key)
    except StorageError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Could not delete stored files. Try again."
        ) from None
    await db.delete(project)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
