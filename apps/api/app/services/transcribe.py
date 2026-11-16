"""Speech-to-text with faster-whisper: word timestamps, VAD, and chunking for long audio.

Pure planning/merging logic lives here alongside the model wrapper so it can be unit-tested
without loading a model.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from app.core.config import Settings
from app.schemas.transcript import TranscriptSegment, TranscriptWord

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

Device = Literal["cuda", "cpu"]
ProgressCallback = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class Chunk:
    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass(frozen=True, slots=True)
class RawSegment:
    """A transcribed segment with absolute timestamps and its words."""

    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...]


@dataclass(slots=True)
class ChunkResult:
    language: str
    language_probability: float
    segments: list[RawSegment] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Transcript:
    language: str
    words: list[TranscriptWord]
    segments: list[TranscriptSegment]


class NoSpeechError(ValueError):
    """The audio contained no detectable speech."""


class ModelUnavailableError(ConnectionError):
    """The Whisper model could not be downloaded or loaded. Retried as transient."""

    def __init__(self, model: str, cause: BaseException) -> None:
        super().__init__(f"could not load whisper model {model!r}: {type(cause).__name__}")
        self.model = model


class Transcriber(Protocol):
    def transcribe(
        self, wav: Path, *, offset_s: float, on_progress: ProgressCallback
    ) -> ChunkResult: ...


# ---------------------------------------------------------------- pure helpers


def plan_chunks(
    duration_s: float, *, max_single_pass_s: float, chunk_s: float, overlap_s: float
) -> list[Chunk]:
    """One chunk for short audio; otherwise fixed-size windows that overlap by ``overlap_s``."""
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    if duration_s <= max_single_pass_s:
        return [Chunk(0.0, duration_s)]
    if chunk_s <= overlap_s:
        raise ValueError("chunk_s must exceed overlap_s")
    chunks: list[Chunk] = []
    start = 0.0
    while start < duration_s:
        length = min(chunk_s, duration_s - start)
        chunks.append(Chunk(start, length))
        if start + length >= duration_s:
            break
        start += chunk_s - overlap_s
    return chunks


def merge_chunks(results: Sequence[ChunkResult], chunks: Sequence[Chunk]) -> Transcript:
    """Stitch chunk results, keeping each overlap's words exactly once.

    Every overlap is cut at its midpoint: chunk k keeps segments starting before the cut and
    chunk k+1 keeps segments starting at or after it. Cutting by segment keeps sentences intact.
    """
    if len(results) != len(chunks):
        raise ValueError("results and chunks must align")
    kept: list[RawSegment] = []
    for i, (result, chunk) in enumerate(zip(results, chunks, strict=True)):
        lower = 0.0 if i == 0 else (chunk.start_s + chunks[i - 1].end_s) / 2
        upper = float("inf") if i == len(chunks) - 1 else (chunks[i + 1].start_s + chunk.end_s) / 2
        kept.extend(s for s in result.segments if lower <= s.start < upper)
    kept.sort(key=lambda s: s.start)

    words: list[TranscriptWord] = []
    segments: list[TranscriptSegment] = []
    for seg in kept:
        seg_words = [w for w in seg.words if w.w.strip()]
        if not seg_words:
            continue
        segments.append(
            TranscriptSegment(
                start=round(seg.start, 3),
                end=round(seg.end, 3),
                text=seg.text.strip(),
                first_word=len(words),
                word_count=len(seg_words),
            )
        )
        words.extend(seg_words)

    weights: dict[str, float] = {}
    for result, chunk in zip(results, chunks, strict=True):
        weights[result.language] = (
            weights.get(result.language, 0.0) + chunk.duration_s * result.language_probability
        )
    language = max(weights, key=lambda k: weights[k]) if weights else "und"
    return Transcript(language=language, words=words, segments=segments)


def make_word(
    text: str, start: float, end: float, probability: float, offset_s: float
) -> TranscriptWord:
    s = max(0.0, start + offset_s)
    e = max(s, end + offset_s)
    return TranscriptWord(
        w=text, start=round(s, 3), end=round(e, 3), conf=round(min(1.0, max(0.0, probability)), 4)
    )


# ---------------------------------------------------------------- model selection


def resolve_device(setting: Literal["cuda", "cpu", "auto"]) -> Device:
    if setting != "auto":
        return setting
    try:
        import ctranslate2

        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except (ImportError, RuntimeError, OSError):
        return "cpu"


def model_for(settings: Settings, device: Device) -> tuple[str, str]:
    """(model name, compute type). CPU uses the smaller CPU model with int8 quantisation."""
    if device == "cuda":
        return settings.whisper_model, "float16"
    return settings.whisper_cpu_model, "int8"


_model_lock = threading.Lock()


@lru_cache(maxsize=2)
def _load_model(name: str, device: Device, compute_type: str, root: str | None) -> "WhisperModel":
    from faster_whisper import WhisperModel

    logger.info("loading whisper model", extra={"model": name, "device": device})
    return WhisperModel(name, device=device, compute_type=compute_type, download_root=root)


class WhisperTranscriber:
    """faster-whisper wrapper. Models are cached per process, so loading happens once per worker."""

    def __init__(self, settings: Settings) -> None:
        device = resolve_device(settings.whisper_device)
        name, compute_type = model_for(settings, device)
        with _model_lock:
            try:
                self._model = _load_model(name, device, compute_type, settings.whisper_model_dir)
            except Exception as exc:
                # Hub/network errors (httpx, huggingface_hub) share no common base with OSError.
                raise ModelUnavailableError(name, exc) from exc
        self._beam_size = settings.whisper_beam_size
        self.model_name = name
        self.device = device

    def transcribe(
        self, wav: Path, *, offset_s: float, on_progress: ProgressCallback
    ) -> ChunkResult:
        segments_iter, info = self._model.transcribe(
            str(wav),
            beam_size=self._beam_size,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        result = ChunkResult(
            language=info.language, language_probability=float(info.language_probability)
        )
        total = float(info.duration) or 1.0
        for seg in segments_iter:
            words = tuple(
                make_word(w.word, w.start, w.end, w.probability, offset_s)
                for w in (seg.words or [])
            )
            result.segments.append(
                RawSegment(
                    start=max(0.0, seg.start + offset_s),
                    end=max(0.0, seg.end + offset_s),
                    text=seg.text,
                    words=words,
                )
            )
            on_progress(min(1.0, seg.end / total))
        on_progress(1.0)
        return result
