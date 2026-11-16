import re

from pydantic import BaseModel, Field, field_validator

_VIDEO_TYPE = re.compile(r"^video/[a-z0-9][a-z0-9.+-]{0,63}$")


class PresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(max_length=80)
    size_bytes: int = Field(gt=0)

    @field_validator("content_type")
    @classmethod
    def _video_only(cls, v: str) -> str:
        normalised = v.strip().lower()
        if not _VIDEO_TYPE.fullmatch(normalised):
            raise ValueError("content_type must be a video/* MIME type")
        return normalised


class PresignResponse(BaseModel):
    upload_url: str
    key: str
    content_type: str
    expires_in_s: int
