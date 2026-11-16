import re
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SettingsDep, StorageDep
from app.schemas.uploads import PresignRequest, PresignResponse

router = APIRouter(prefix="/uploads", tags=["uploads"])

PRESIGN_TTL_S = 3600
_SAFE_EXT = re.compile(r"^\.[a-z0-9]{1,8}$")


def upload_prefix(user_id: uuid.UUID) -> str:
    return f"uploads/{user_id}/"


def build_upload_key(user_id: uuid.UUID, filename: str) -> str:
    """Server-chosen key; only a sanitised extension survives from the client's filename."""
    ext = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if not _SAFE_EXT.fullmatch(ext):
        ext = ".bin"
    return f"{upload_prefix(user_id)}{uuid.uuid4()}/source{ext}"


@router.post("/presign", response_model=PresignResponse, status_code=status.HTTP_201_CREATED)
async def presign_upload(
    body: PresignRequest, user: CurrentUser, settings: SettingsDep, storage: StorageDep
) -> PresignResponse:
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File is larger than the {settings.max_upload_gb:g} GB limit",
        )
    key = build_upload_key(user.id, body.filename)
    url = storage.presign_put(key, body.content_type, ttl_s=PRESIGN_TTL_S)
    return PresignResponse(
        upload_url=url, key=key, content_type=body.content_type, expires_in_s=PRESIGN_TTL_S
    )
