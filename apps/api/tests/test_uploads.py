from httpx import AsyncClient

from app.api.routes.uploads import build_upload_key
from tests.support.fakes import FakeStorage


async def test_presign_returns_user_scoped_key(alice: AsyncClient, storage: FakeStorage) -> None:
    me = (await alice.get("/auth/me")).json()
    resp = await alice.post(
        "/uploads/presign",
        json={"filename": "My Talk.MP4", "content_type": "video/mp4", "size_bytes": 1_000_000},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"].startswith(f"uploads/{me['id']}/")
    assert body["key"].endswith("/source.mp4")
    assert body["upload_url"].startswith("http://storage.test/")
    assert storage.presigned == [(body["key"], "video/mp4")]


async def test_presign_rejects_non_video(alice: AsyncClient) -> None:
    for content_type in ["image/png", "application/octet-stream", "video/", "text/html"]:
        resp = await alice.post(
            "/uploads/presign",
            json={"filename": "x.mp4", "content_type": content_type, "size_bytes": 10},
        )
        assert resp.status_code == 422, content_type


async def test_presign_rejects_oversize_and_empty(alice: AsyncClient) -> None:
    too_big = await alice.post(
        "/uploads/presign",
        json={"filename": "x.mp4", "content_type": "video/mp4", "size_bytes": 5 * 1024**3},
    )
    assert too_big.status_code == 413
    empty = await alice.post(
        "/uploads/presign",
        json={"filename": "x.mp4", "content_type": "video/mp4", "size_bytes": 0},
    )
    assert empty.status_code == 422


async def test_presign_requires_auth(anon: AsyncClient) -> None:
    resp = await anon.post(
        "/uploads/presign",
        json={"filename": "x.mp4", "content_type": "video/mp4", "size_bytes": 10},
    )
    assert resp.status_code == 401


def test_upload_key_sanitises_filename() -> None:
    import uuid

    uid = uuid.uuid4()
    assert build_upload_key(uid, "../../etc/passwd").endswith("/source.bin")
    assert build_upload_key(uid, "clip.MOV").endswith("/source.mov")
    assert build_upload_key(uid, "weird.m p4").endswith("/source.bin")
    assert build_upload_key(uid, "a\\b\\c.webm").endswith("/source.webm")
    assert build_upload_key(uid, "x.mp4").startswith(f"uploads/{uid}/")
