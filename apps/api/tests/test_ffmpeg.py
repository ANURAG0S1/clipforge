from pathlib import Path

import pytest

from app.services import ffmpeg
from tests.support.media import make_test_video, requires_ffmpeg


def _probe_json(**overrides: object) -> dict[str, object]:
    video: dict[str, object] = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30000/1001",
        "r_frame_rate": "30000/1001",
    }
    video.update(overrides)
    return {
        "streams": [video, {"codec_type": "audio", "codec_name": "aac"}],
        "format": {"duration": "301.5", "size": "12345678"},
    }


def test_parse_probe_basic() -> None:
    result = ffmpeg.parse_probe_json(_probe_json(), size_fallback=0)
    assert result == ffmpeg.ProbeResult(
        duration_s=301.5,
        width=1920,
        height=1080,
        fps=29.97,
        video_codec="h264",
        has_audio=True,
        size_bytes=12345678,
    )


def test_parse_probe_rotation_swaps_dimensions() -> None:
    rotated = ffmpeg.parse_probe_json(
        _probe_json(side_data_list=[{"rotation": -90}]), size_fallback=0
    )
    assert (rotated.width, rotated.height) == (1080, 1920)
    legacy = ffmpeg.parse_probe_json(_probe_json(tags={"rotate": "270"}), size_fallback=0)
    assert (legacy.width, legacy.height) == (1080, 1920)


def test_parse_probe_falls_back_to_r_frame_rate() -> None:
    result = ffmpeg.parse_probe_json(
        _probe_json(avg_frame_rate="0/0", r_frame_rate="25/1"), size_fallback=0
    )
    assert result.fps == 25.0


@pytest.mark.parametrize(
    "data",
    [
        {"streams": [{"codec_type": "audio"}], "format": {"duration": "10"}},
        {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 600,
                    "height": 600,
                    "disposition": {"attached_pic": 1},
                }
            ],
            "format": {"duration": "10"},
        },
        {
            "streams": [{"codec_type": "video", "width": 0, "height": 0}],
            "format": {"duration": "1"},
        },
        {"streams": [{"codec_type": "video", "width": 10, "height": 10}], "format": {}},
        {"nonsense": True},
        "not even a dict",
    ],
)
def test_parse_probe_rejects_unusable_media(data: object) -> None:
    with pytest.raises(ffmpeg.MediaProbeError):
        ffmpeg.parse_probe_json(data, size_fallback=0)


def test_proxy_args_are_a_list_without_shell() -> None:
    args = ffmpeg.proxy_args(Path("/in; rm -rf /.mp4"), Path("/out.mp4"))
    assert args[1] == "/in; rm -rf /.mp4"
    assert "libx264" in args
    assert args[args.index("-crf") + 1] == "23"
    assert args[args.index("-preset") + 1] == "veryfast"
    assert "+faststart" in args


@requires_ffmpeg
def test_probe_and_proxy_real_file(tmp_path: Path) -> None:
    src = make_test_video(tmp_path / "in.mp4", seconds=2, width=320, height=180)
    probe = ffmpeg.probe(src)
    assert probe.width == 320
    assert probe.height == 180
    assert probe.fps == 25.0
    assert probe.has_audio
    assert 1.9 <= probe.duration_s <= 2.2

    seen: list[float] = []
    out = tmp_path / "proxy.mp4"
    ffmpeg.make_proxy(src, out, duration_s=probe.duration_s, timeout_s=60, on_progress=seen.append)
    assert seen
    assert seen[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in seen)
    proxy = ffmpeg.probe(out)
    assert proxy.video_codec == "h264"
    assert (proxy.width, proxy.height) == (320, 180)


@requires_ffmpeg
def test_proxy_without_audio_stream(tmp_path: Path) -> None:
    src = make_test_video(tmp_path / "silent.mp4", seconds=1, audio=False)
    out = tmp_path / "proxy.mp4"
    ffmpeg.make_proxy(src, out, duration_s=1, timeout_s=60)
    assert not ffmpeg.probe(out).has_audio


@requires_ffmpeg
def test_probe_rejects_non_media(tmp_path: Path) -> None:
    junk = tmp_path / "fake.mp4"
    junk.write_bytes(b"this is not a video")
    with pytest.raises(ffmpeg.MediaProbeError):
        ffmpeg.probe(junk)


@requires_ffmpeg
def test_ffmpeg_failure_surfaces_stderr(tmp_path: Path) -> None:
    with pytest.raises(ffmpeg.FFmpegError) as exc:
        ffmpeg.run_ffmpeg(
            ["-i", str(tmp_path / "missing.mp4"), str(tmp_path / "o.mp4")], timeout_s=30
        )
    assert exc.value.returncode not in (0, None)
    assert "missing.mp4" in exc.value.stderr_tail


@requires_ffmpeg
def test_ffmpeg_timeout_kills_process(tmp_path: Path) -> None:
    with pytest.raises(ffmpeg.FFmpegError, match="timed out"):
        ffmpeg.run_ffmpeg(
            ["-re", "-f", "lavfi", "-i", "testsrc2=duration=30", "-f", "null", "-"],
            timeout_s=1,
        )
