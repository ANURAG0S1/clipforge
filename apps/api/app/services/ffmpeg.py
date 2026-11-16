"""The single entry point for running ffmpeg/ffprobe.

Commands are always argument lists (never shell strings), always bounded by a timeout, and
failures carry the tail of stderr so errors are diagnosable.
"""

import json
import logging
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

FFMPEG: Final = "ffmpeg"
FFPROBE: Final = "ffprobe"
_STDERR_TAIL_LINES: Final = 25

ProgressCallback = Callable[[float], None]


class FFmpegError(RuntimeError):
    """ffmpeg/ffprobe exited non-zero, timed out, or could not be started."""

    def __init__(self, message: str, *, returncode: int | None, stderr_tail: str) -> None:
        detail = f"{message} (exit={returncode})"
        if stderr_tail:
            detail = f"{detail}: {stderr_tail}"
        super().__init__(detail)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class MediaProbeError(ValueError):
    """The file is not a usable video (no video stream, no duration, unreadable)."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    duration_s: float
    width: int
    height: int
    fps: float
    video_codec: str
    has_audio: bool
    size_bytes: int


def _tail(lines: deque[str]) -> str:
    return "\n".join(line.rstrip() for line in lines if line.strip())[-4000:]


def run_ffmpeg(
    args: Sequence[str],
    *,
    timeout_s: float,
    duration_s: float | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Run ffmpeg with ``args``. Reports progress in [0, 1] when ``duration_s`` is known."""
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    if on_progress is not None:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += list(args)

    stderr_lines: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
    try:
        proc = subprocess.Popen(  # noqa: S603 - argument list, binary is fixed
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise FFmpegError("could not start ffmpeg", returncode=None, stderr_tail=str(exc)) from exc

    if proc.stdout is None or proc.stderr is None:
        proc.kill()
        raise FFmpegError("ffmpeg pipes unavailable", returncode=None, stderr_tail="")
    stdout = proc.stdout
    stderr = proc.stderr

    def _drain_stderr() -> None:
        for line in stderr:
            stderr_lines.append(line)

    drain = threading.Thread(target=_drain_stderr, daemon=True)
    drain.start()

    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout_s, _kill)
    timer.start()
    last_report = 0.0
    try:
        for line in stdout:
            if on_progress is None or not duration_s or duration_s <= 0:
                continue
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit():
                fraction = min(1.0, int(value) / 1_000_000 / duration_s)
                now = time.monotonic()
                if now - last_report >= 1.0 or fraction >= 1.0:
                    last_report = now
                    on_progress(fraction)
        returncode = proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        drain.join(timeout=5)

    if timed_out.is_set():
        raise FFmpegError(
            f"ffmpeg timed out after {timeout_s:.0f}s",
            returncode=proc.returncode,
            stderr_tail=_tail(stderr_lines),
        )
    if returncode != 0:
        raise FFmpegError("ffmpeg failed", returncode=returncode, stderr_tail=_tail(stderr_lines))
    if on_progress is not None:
        on_progress(1.0)


def _parse_fps(rate: str | None) -> float:
    if not rate or rate in {"0/0", "0"}:
        return 0.0
    try:
        return float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path, *, timeout_s: float = 60) -> ProbeResult:
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, binary is fixed
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(
            f"ffprobe timed out after {timeout_s:.0f}s", returncode=None, stderr_tail=""
        ) from exc
    except OSError as exc:
        raise FFmpegError("could not start ffprobe", returncode=None, stderr_tail=str(exc)) from exc
    if completed.returncode != 0:
        raise MediaProbeError(
            f"File is not a readable media file: {completed.stderr.strip()[-500:]}"
        )
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProbeError("ffprobe returned invalid JSON") from exc
    return parse_probe_json(data, size_fallback=path.stat().st_size)


def _as_dict(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_probe_json(data: object, *, size_fallback: int) -> ProbeResult:
    """Extract typed metadata from ffprobe's JSON. Pure function, unit-tested."""
    root = _as_dict(data)
    raw_streams = root.get("streams")
    streams = [_as_dict(s) for s in raw_streams] if isinstance(raw_streams, list) else []
    fmt = _as_dict(root.get("format"))

    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and _as_dict(s.get("disposition")).get("attached_pic") != 1
        ),
        None,
    )
    if video is None:
        raise MediaProbeError("File has no video stream")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    width = video.get("width")
    height = video.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise MediaProbeError("Video stream has no valid resolution")

    tags = _as_dict(video.get("tags"))
    side = video.get("side_data_list")
    rotation = _as_float(tags.get("rotate")) or 0.0
    if isinstance(side, list):
        for item in side:
            r = _as_float(_as_dict(item).get("rotation"))
            if r is not None:
                rotation = r
    if int(abs(rotation)) % 180 == 90:
        width, height = height, width

    duration = _as_float(fmt.get("duration")) or _as_float(video.get("duration"))
    if duration is None or duration <= 0:
        raise MediaProbeError("Could not determine video duration")

    fps = _parse_fps(str(video.get("avg_frame_rate") or "")) or _parse_fps(
        str(video.get("r_frame_rate") or "")
    )
    size = _as_float(fmt.get("size"))
    return ProbeResult(
        duration_s=round(duration, 3),
        width=width,
        height=height,
        fps=round(fps, 3),
        video_codec=str(video.get("codec_name") or "unknown"),
        has_audio=has_audio,
        size_bytes=int(size) if size is not None else size_fallback,
    )


def proxy_args(src: Path, dst: Path) -> list[str]:
    """H.264/AAC proxy for fast, accurate seeking. Downscales to fit 1920x1920, never upscales."""
    return [
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=w='min(iw,1920)':h='min(ih,1920)':force_original_aspect_ratio=decrease:"
        "force_divisible_by=2,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-g",
        "60",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(dst),
    ]


def make_proxy(
    src: Path,
    dst: Path,
    *,
    duration_s: float,
    timeout_s: float,
    on_progress: ProgressCallback | None = None,
) -> None:
    run_ffmpeg(
        proxy_args(src, dst), timeout_s=timeout_s, duration_s=duration_s, on_progress=on_progress
    )


def extract_audio(
    src: Path,
    dst: Path,
    *,
    start_s: float = 0.0,
    duration_s: float | None = None,
    timeout_s: float,
) -> None:
    """16 kHz mono PCM WAV (what Whisper expects), optionally a [start, start+duration) window."""
    args: list[str] = []
    if start_s > 0:
        args += ["-ss", f"{start_s:.3f}"]
    if duration_s is not None:
        args += ["-t", f"{duration_s:.3f}"]
    args += ["-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000"]
    args += ["-c:a", "pcm_s16le", str(dst)]
    run_ffmpeg(args, timeout_s=timeout_s)
