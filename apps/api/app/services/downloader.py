"""Fetch remote media with yt-dlp after SSRF validation."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import yt_dlp
from yt_dlp.utils import DownloadError

from app.services.url_guard import UnsafeUrlError, validate_public_url

if TYPE_CHECKING:
    from yt_dlp import _YoutubeDLOptions

logger = logging.getLogger(__name__)

# Best MP4 at or below 1080p; fall back to anything at or below 1080p, remuxed to MP4.
FORMAT_SELECTOR: Final = "/".join(
    (
        "bv*[height<=1080][ext=mp4]+ba[ext=m4a]",
        "b[height<=1080][ext=mp4]",
        "bv*[height<=1080]+ba",
        "b[height<=1080]",
    )
)

ProgressCallback = Callable[[float], None]


class DownloadRejectedError(ValueError):
    """The URL is valid but the media is not acceptable (too long, too large, unsupported)."""


class TransientDownloadError(RuntimeError):
    """A network-level failure that is worth retrying."""


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    path: Path
    title: str | None


def _check_media_urls(info: Mapping[str, object]) -> None:
    """Every URL yt-dlp will actually fetch must also be public (defence against redirects)."""
    urls: list[str] = []
    requested = info.get("requested_formats")
    if isinstance(requested, list):
        for fmt in requested:
            if isinstance(fmt, dict) and isinstance(fmt.get("url"), str):
                urls.append(cast(str, fmt["url"]))
    elif isinstance(info.get("url"), str):
        urls.append(cast(str, info["url"]))
    for url in urls:
        validate_public_url(url)


def download_url(
    url: str,
    dest_dir: Path,
    *,
    max_bytes: int,
    max_duration_s: float,
    socket_timeout_s: float = 30,
    on_progress: ProgressCallback | None = None,
) -> DownloadedMedia:
    try:
        safe_url = validate_public_url(url)
    except UnsafeUrlError as exc:
        raise DownloadRejectedError(str(exc)) from exc

    def _hook(d: Mapping[str, Any]) -> None:
        if on_progress is None or d.get("status") != "downloading":
            return
        done = d.get("downloaded_bytes")
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if isinstance(done, int | float) and isinstance(total, int | float) and total > 0:
            on_progress(min(1.0, float(done) / float(total)))

    def _match_filter(info: Mapping[str, Any], incomplete: bool) -> str | None:
        duration = info.get("duration")
        if isinstance(duration, int | float) and duration > max_duration_s:
            return f"Video is too long ({duration / 60:.0f} min, max {max_duration_s / 60:.0f})"
        if info.get("is_live"):
            return "Live streams are not supported"
        return None

    opts: _YoutubeDLOptions = {
        "format": FORMAT_SELECTOR,
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "noplaylist": True,
        "max_filesize": max_bytes,
        "match_filter": _match_filter,
        "socket_timeout": int(socket_timeout_s),
        "retries": 3,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [_hook],
        "restrictfilenames": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(safe_url, download=False)
            if not isinstance(info, dict):
                raise DownloadRejectedError("Could not read media information from the URL")
            reason = _match_filter(info, False)
            if reason is not None:
                raise DownloadRejectedError(reason)
            _check_media_urls(info)
            processed = ydl.process_ie_result(info, download=True)
    except UnsafeUrlError as exc:
        raise DownloadRejectedError(str(exc)) from exc
    except DownloadError as exc:
        message = str(exc)
        if any(
            m in message for m in ("timed out", "Connection reset", "HTTP Error 5", "Temporary")
        ):
            raise TransientDownloadError(message) from exc
        raise DownloadRejectedError(f"Could not download this URL: {message[-300:]}") from exc

    files = sorted(p for p in dest_dir.glob("source.*") if p.suffix not in {".part", ".ytdl"})
    if not files:
        raise DownloadRejectedError("No file was downloaded (the media may exceed the size limit)")
    title = processed.get("title") if isinstance(processed, dict) else None
    return DownloadedMedia(path=files[0], title=title if isinstance(title, str) else None)
