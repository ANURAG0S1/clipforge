# Minimal typing for the parts of faster-whisper that ClipForge uses.
from collections.abc import Iterable, Iterator
from typing import Any, NamedTuple

import numpy as np
from numpy.typing import NDArray

class Word(NamedTuple):
    start: float
    end: float
    word: str
    probability: float

class Segment(NamedTuple):
    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: list[int]
    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float
    words: list[Word] | None
    temperature: float | None

class TranscriptionInfo(NamedTuple):
    language: str
    language_probability: float
    duration: float
    duration_after_vad: float
    all_language_probs: list[tuple[str, float]] | None
    transcription_options: Any
    vad_options: Any

class WhisperModel:
    def __init__(
        self,
        model_size_or_path: str,
        device: str = ...,
        device_index: int | list[int] = ...,
        compute_type: str = ...,
        cpu_threads: int = ...,
        num_workers: int = ...,
        download_root: str | None = ...,
        local_files_only: bool = ...,
    ) -> None: ...
    def transcribe(
        self,
        audio: str | NDArray[np.float32],
        language: str | None = ...,
        task: str = ...,
        beam_size: int = ...,
        word_timestamps: bool = ...,
        vad_filter: bool = ...,
        vad_parameters: dict[str, Any] | None = ...,
        condition_on_previous_text: bool = ...,
        **kwargs: Any,
    ) -> tuple[Iterator[Segment], TranscriptionInfo]: ...

__all__ = ["Iterable", "Segment", "TranscriptionInfo", "WhisperModel", "Word"]
