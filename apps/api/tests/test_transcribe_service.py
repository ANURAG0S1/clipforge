import itertools
import wave
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.schemas.transcript import TranscriptWord
from app.services import ffmpeg
from app.services.transcribe import (
    SAMPLE_RATE,
    AudioFormatError,
    Chunk,
    ChunkResult,
    RawSegment,
    load_wav,
    make_word,
    merge_chunks,
    model_for,
    plan_chunks,
    resolve_device,
)
from tests.support.media import requires_ffmpeg

FIXTURE = Path(__file__).parent / "fixtures" / "speech-sample.mp4"


def _seg(start: float, end: float, *words: str) -> RawSegment:
    step = (end - start) / max(1, len(words))
    return RawSegment(
        start=start,
        end=end,
        text=" ".join(words),
        words=tuple(
            TranscriptWord(w=f" {w}", start=start + i * step, end=start + (i + 1) * step, conf=0.9)
            for i, w in enumerate(words)
        ),
    )


def test_short_audio_is_one_chunk() -> None:
    assert plan_chunks(3599, max_single_pass_s=3600, chunk_s=1800, overlap_s=5) == [
        Chunk(0.0, 3599)
    ]


def test_long_audio_is_split_with_overlap() -> None:
    chunks = plan_chunks(4000, max_single_pass_s=3600, chunk_s=1800, overlap_s=5)
    assert [c.start_s for c in chunks] == [0.0, 1795.0, 3590.0]
    assert chunks[0].duration_s == 1800
    assert chunks[-1].end_s == pytest.approx(4000)
    for a, b in itertools.pairwise(chunks):
        assert a.end_s - b.start_s == pytest.approx(5)


def test_plan_chunks_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="positive"):
        plan_chunks(0, max_single_pass_s=10, chunk_s=5, overlap_s=1)
    with pytest.raises(ValueError, match="exceed"):
        plan_chunks(100, max_single_pass_s=10, chunk_s=5, overlap_s=5)


def test_merge_keeps_each_overlap_segment_once() -> None:
    chunks = [Chunk(0, 100), Chunk(95, 100)]
    first = ChunkResult("en", 0.9, [_seg(0, 5, "hello", "world"), _seg(96, 99, "edge", "case")])
    # The second chunk re-transcribes the overlap [95, 100); the cut is at 97.5.
    second = ChunkResult("en", 0.9, [_seg(96.2, 99, "edge", "case"), _seg(150, 152, "later")])
    merged = merge_chunks([first, second], chunks)
    assert [w.w.strip() for w in merged.words] == ["hello", "world", "edge", "case", "later"]
    assert [(s.first_word, s.word_count) for s in merged.segments] == [(0, 2), (2, 2), (4, 1)]
    assert merged.language == "en"


def test_merge_drops_empty_segments_and_sorts() -> None:
    result = ChunkResult(
        "de",
        0.8,
        [_seg(10, 12, "zwei"), RawSegment(5, 6, " ", ()), _seg(1, 2, "eins")],
    )
    merged = merge_chunks([result], [Chunk(0, 20)])
    assert [w.w.strip() for w in merged.words] == ["eins", "zwei"]
    assert len(merged.segments) == 2


def test_language_weighted_by_duration_and_confidence() -> None:
    chunks = [Chunk(0, 100), Chunk(95, 30)]
    merged = merge_chunks([ChunkResult("es", 0.9, []), ChunkResult("en", 0.99, [])], chunks)
    assert merged.language == "es"
    assert merge_chunks([], []).language == "und"


def test_make_word_applies_offset_and_clamps() -> None:
    w = make_word(" hi", 1.0, 0.5, 1.7, offset_s=10)
    assert (w.start, w.end, w.conf) == (11.0, 11.0, 1.0)
    w2 = make_word(" x", -0.5, 0.2, -1, offset_s=0)
    assert (w2.start, w2.end, w2.conf) == (0.0, 0.2, 0.0)


def test_device_and_model_selection() -> None:
    settings = get_settings()
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("cuda") == "cuda"
    assert resolve_device("auto") in ("cpu", "cuda")
    assert model_for(settings, "cuda") == ("large-v3", "float16")
    assert model_for(settings, "cpu") == ("small", "int8")


def _write_wav(
    path: Path, samples: list[int], *, rate: int = SAMPLE_RATE, channels: int = 1
) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.array(samples, dtype="<i2").tobytes())


def test_load_wav_scales_pcm_to_float(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    _write_wav(path, [0, 16384, -32768, 32767])
    audio = load_wav(path)
    assert audio.dtype == np.float32
    assert audio.tolist() == pytest.approx([0.0, 0.5, -1.0, 32767 / 32768])


@pytest.mark.parametrize(("rate", "channels"), [(44_100, 1), (SAMPLE_RATE, 2)])
def test_load_wav_rejects_wrong_format(tmp_path: Path, rate: int, channels: int) -> None:
    path = tmp_path / "bad.wav"
    _write_wav(path, [0, 0, 0, 0], rate=rate, channels=channels)
    with pytest.raises(AudioFormatError, match="expected 16000 Hz mono"):
        load_wav(path)


def test_load_wav_rejects_non_wav(tmp_path: Path) -> None:
    path = tmp_path / "junk.wav"
    path.write_bytes(b"not a wav file at all")
    with pytest.raises(AudioFormatError, match="not a PCM WAV"):
        load_wav(path)


@requires_ffmpeg
def test_extract_audio_output_loads_for_whisper(tmp_path: Path) -> None:
    """The ffmpeg extraction and the loader agree on format, end to end, on the real fixture."""
    wav = tmp_path / "speech.wav"
    ffmpeg.extract_audio(FIXTURE, wav, timeout_s=30)
    audio = load_wav(wav)
    assert 7.0 < len(audio) / SAMPLE_RATE < 8.0
    assert float(np.abs(audio).max()) > 0.05
