from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from app.services.storage import Storage

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


class _AlreadyOwnedError(Exception):
    pass


def _storage(internal: MagicMock) -> Storage:
    internal.exceptions.BucketAlreadyOwnedByYou = _AlreadyOwnedError
    return Storage(
        bucket="clipforge",
        internal=cast("S3Client", internal),
        public=cast("S3Client", MagicMock()),
    )


async def test_ensure_bucket_creates_when_missing() -> None:
    internal = MagicMock()
    internal.list_buckets.return_value = {"Buckets": [{"Name": "other"}]}
    assert await _storage(internal).ensure_bucket() is True
    internal.create_bucket.assert_called_once_with(Bucket="clipforge")


async def test_ensure_bucket_is_idempotent() -> None:
    internal = MagicMock()
    internal.list_buckets.return_value = {"Buckets": [{"Name": "clipforge"}]}
    assert await _storage(internal).ensure_bucket() is False
    internal.create_bucket.assert_not_called()


async def test_ensure_bucket_tolerates_concurrent_create() -> None:
    internal = MagicMock()
    internal.list_buckets.return_value = {"Buckets": []}
    internal.create_bucket.side_effect = _AlreadyOwnedError()
    assert await _storage(internal).ensure_bucket() is False


async def test_delete_prefix_requires_directory_prefix() -> None:
    storage = _storage(MagicMock())
    with pytest.raises(ValueError, match="end with '/'"):
        await storage.delete_prefix("projects/abc")
    with pytest.raises(ValueError, match="non-empty"):
        await storage.delete_prefix("")


async def test_delete_prefix_batches_and_counts() -> None:
    internal = MagicMock()
    page = {"Contents": [{"Key": f"projects/p/{i}"} for i in range(1500)]}
    internal.get_paginator.return_value.paginate.return_value = [page]
    internal.delete_objects.return_value = {}
    assert await _storage(internal).delete_prefix("projects/p/") == 1500
    assert internal.delete_objects.call_count == 2


def test_presign_get_sanitizes_download_name() -> None:
    public = MagicMock()
    public.generate_presigned_url.return_value = "http://signed"
    storage = Storage(
        bucket="clipforge",
        internal=cast("S3Client", MagicMock()),
        public=cast("S3Client", public),
    )
    assert storage.presign_get("k", download_name='evil"\r\nname.mp4') == "http://signed"
    params = public.generate_presigned_url.call_args.kwargs["Params"]
    assert params["ResponseContentDisposition"] == 'attachment; filename="evil  name.mp4"'
