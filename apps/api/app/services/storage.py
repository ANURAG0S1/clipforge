"""S3-compatible object storage (MinIO locally).

Two clients are kept: an internal one for server-side operations and a public one
whose endpoint is reachable from browsers, used only to sign presigned URLs.
"""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from app.core.config import Settings, get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

_PRESIGN_TTL_S = 3600
_DELETE_BATCH = 1000


class StorageError(RuntimeError):
    """Raised when an object storage operation fails."""


def _client(settings: Settings, endpoint: str) -> "S3Client":
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=60,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


@dataclass(frozen=True, slots=True)
class Storage:
    bucket: str
    internal: "S3Client"
    public: "S3Client"

    async def ping(self) -> None:
        """Raise if the bucket is unreachable."""
        try:
            await asyncio.to_thread(self.internal.head_bucket, Bucket=self.bucket)
        except Exception as exc:
            raise StorageError(f"bucket {self.bucket!r} unreachable: {exc}") from exc

    async def ensure_bucket(self) -> bool:
        """Create the bucket if it does not exist. Returns True when it was created."""
        return await asyncio.to_thread(self._ensure_bucket_sync)

    def _ensure_bucket_sync(self) -> bool:
        existing = {b.get("Name") for b in self.internal.list_buckets().get("Buckets", [])}
        if self.bucket in existing:
            return False
        try:
            self.internal.create_bucket(Bucket=self.bucket)
        except self.internal.exceptions.BucketAlreadyOwnedByYou:
            return False
        return True

    def presign_put(self, key: str, content_type: str, ttl_s: int = _PRESIGN_TTL_S) -> str:
        return self.public.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=ttl_s,
        )

    def presign_get(
        self, key: str, download_name: str | None = None, ttl_s: int = _PRESIGN_TTL_S
    ) -> str:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if download_name is not None:
            safe = download_name.replace('"', "").replace("\n", " ").replace("\r", " ")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return self.public.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_s)

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix``. Returns the number of objects removed."""
        if not prefix or not prefix.endswith("/"):
            raise ValueError("prefix must be non-empty and end with '/'")
        return await asyncio.to_thread(self._delete_prefix_sync, prefix)

    def _delete_prefix_sync(self, prefix: str) -> int:
        deleted = 0
        paginator = self.internal.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys: list[ObjectIdentifierTypeDef] = [
                {"Key": obj["Key"]} for obj in page.get("Contents", []) if "Key" in obj
            ]
            for i in range(0, len(keys), _DELETE_BATCH):
                batch = keys[i : i + _DELETE_BATCH]
                resp = self.internal.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": batch, "Quiet": True}
                )
                errors = resp.get("Errors", [])
                if errors:
                    raise StorageError(f"failed to delete {len(errors)} objects under {prefix}")
                deleted += len(batch)
        return deleted


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    settings = get_settings()
    return Storage(
        bucket=settings.s3_bucket,
        internal=_client(settings, settings.s3_endpoint),
        public=_client(settings, settings.s3_public_endpoint),
    )
