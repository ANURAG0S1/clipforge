"""In-memory stand-ins for external services used by API and worker tests."""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from app.services.rate_limit import RateLimitResult
from app.services.storage import Storage, StorageError

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


class FakeStorage(Storage):
    """Object store backed by a local directory. Failure injection via ``fail_with``."""

    root: Path
    fail_with: StorageError | None
    presigned: list[tuple[str, str]]

    def __init__(self, root: Path) -> None:
        super().__init__(
            bucket="test-bucket",
            internal=cast("S3Client", MagicMock()),
            public=cast("S3Client", MagicMock()),
        )
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "fail_with", None)
        object.__setattr__(self, "presigned", [])

    def _path(self, key: str) -> Path:
        return self.root / key

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def put_bytes(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def put_file(self, key: str, src: Path) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)

    def all_keys(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())

    async def ping(self) -> None:
        self._maybe_fail()

    def head_size(self, key: str) -> int | None:
        self._maybe_fail()
        path = self._path(key)
        return path.stat().st_size if path.is_file() else None

    def download_file(self, key: str, dest: Path) -> None:
        self._maybe_fail()
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"missing {key}")
        shutil.copyfile(path, dest)

    def upload_file(self, src: Path, key: str, content_type: str) -> None:
        self._maybe_fail()
        self.put_file(key, src)

    def delete_key(self, key: str) -> None:
        self._maybe_fail()
        self._path(key).unlink(missing_ok=True)

    async def delete_prefix(self, prefix: str) -> int:
        if not prefix or not prefix.endswith("/"):
            raise ValueError("prefix must be non-empty and end with '/'")
        self._maybe_fail()
        removed = 0
        target = self._path(prefix)
        if target.is_dir():
            removed = sum(1 for p in target.rglob("*") if p.is_file())
            shutil.rmtree(target)
        return removed

    def presign_put(self, key: str, content_type: str, ttl_s: int = 3600) -> str:
        self.presigned.append((key, content_type))
        return f"http://storage.test/{key}?signed=put"

    def presign_get(self, key: str, download_name: str | None = None, ttl_s: int = 3600) -> str:
        return f"http://storage.test/{key}?signed=get"


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def hit(self, key: str, limit: int, window_s: int) -> RateLimitResult:
        self.counts[key] = self.counts.get(key, 0) + 1
        used = self.counts[key]
        return RateLimitResult(
            allowed=used <= limit, remaining=max(0, limit - used), retry_after_s=window_s
        )
