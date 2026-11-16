"""Object-storage key layout. Every project-owned object lives under ``projects/{id}/``."""

import uuid


def project_prefix(project_id: uuid.UUID) -> str:
    return f"projects/{project_id}/"


def proxy_key(project_id: uuid.UUID) -> str:
    return f"{project_prefix(project_id)}proxy.mp4"


def source_key(project_id: uuid.UUID, suffix: str) -> str:
    return f"{project_prefix(project_id)}source{suffix or '.mp4'}"


def upload_prefix(user_id: uuid.UUID) -> str:
    return f"uploads/{user_id}/"
