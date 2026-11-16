from pathlib import Path
from typing import Any, ClassVar

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

from app.services import downloader
from app.services.downloader import DownloadRejectedError, TransientDownloadError, download_url


def test_private_url_rejected_before_any_network(tmp_path: Path) -> None:
    with pytest.raises(DownloadRejectedError, match="private"):
        download_url("http://127.0.0.1/v.mp4", tmp_path, max_bytes=10, max_duration_s=10)
    with pytest.raises(DownloadRejectedError, match="Only http"):
        download_url("file:///etc/passwd", tmp_path, max_bytes=10, max_duration_s=10)


class _FakeYDL:
    """Minimal YoutubeDL stand-in driven by a canned info dict."""

    info: ClassVar[dict[str, Any]] = {}
    error: ClassVar[Exception | None] = None

    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts

    def __enter__(self) -> "_FakeYDL":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        if _FakeYDL.error is not None:
            raise _FakeYDL.error
        return _FakeYDL.info

    def process_ie_result(self, info: dict[str, Any], download: bool) -> dict[str, Any]:
        out = Path(str(self.opts["outtmpl"]).replace("%(ext)s", "mp4"))
        out.write_bytes(b"video")
        return info


@pytest.fixture
def fake_ydl(monkeypatch: pytest.MonkeyPatch) -> type[_FakeYDL]:
    monkeypatch.setattr(downloader, "validate_public_url", lambda url: url)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    _FakeYDL.info = {"title": "Talk", "duration": 300, "url": "https://cdn.example.com/v.mp4"}
    _FakeYDL.error = None
    return _FakeYDL


def test_successful_download(tmp_path: Path, fake_ydl: type[_FakeYDL]) -> None:
    media = download_url(
        "https://videos.example.com/a", tmp_path, max_bytes=10**9, max_duration_s=600
    )
    assert media.path == tmp_path / "source.mp4"
    assert media.title == "Talk"


def test_too_long_rejected_before_download(tmp_path: Path, fake_ydl: type[_FakeYDL]) -> None:
    fake_ydl.info = {**fake_ydl.info, "duration": 4 * 3600}
    with pytest.raises(DownloadRejectedError, match="too long"):
        download_url("https://videos.example.com/a", tmp_path, max_bytes=10, max_duration_s=600)
    assert list(tmp_path.iterdir()) == []


def test_live_stream_rejected(tmp_path: Path, fake_ydl: type[_FakeYDL]) -> None:
    fake_ydl.info = {**fake_ydl.info, "is_live": True}
    with pytest.raises(DownloadRejectedError, match="Live"):
        download_url("https://videos.example.com/a", tmp_path, max_bytes=10, max_duration_s=600)


def test_media_url_redirecting_to_private_network_rejected(
    tmp_path: Path, fake_ydl: type[_FakeYDL], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.url_guard import validate_public_url

    fake_ydl.info = {
        **fake_ydl.info,
        "requested_formats": [
            {"url": "https://cdn.example.com/video.mp4"},
            {"url": "http://169.254.169.254/latest/meta-data/"},
        ],
    }
    monkeypatch.setattr(
        downloader,
        "validate_public_url",
        lambda url: (
            url if "videos.example.com" in url or "cdn." in url else validate_public_url(url)
        ),
    )
    with pytest.raises(DownloadRejectedError, match="private"):
        download_url("https://videos.example.com/a", tmp_path, max_bytes=10, max_duration_s=600)


def test_network_errors_are_transient(tmp_path: Path, fake_ydl: type[_FakeYDL]) -> None:
    fake_ydl.error = DownloadError("Read timed out")
    with pytest.raises(TransientDownloadError):
        download_url("https://videos.example.com/a", tmp_path, max_bytes=10, max_duration_s=600)
    fake_ydl.error = DownloadError("Unsupported URL")
    with pytest.raises(DownloadRejectedError, match="Could not download"):
        download_url("https://videos.example.com/a", tmp_path, max_bytes=10, max_duration_s=600)
