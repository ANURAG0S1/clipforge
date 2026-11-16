from pydantic import BaseModel, ConfigDict, Field


class TranscriptWord(BaseModel):
    model_config = ConfigDict(frozen=True)

    w: str = Field(description="The word, including any leading space or punctuation")
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    conf: float = Field(ge=0, le=1)


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    first_word: int = Field(ge=0, description="Index of the segment's first word in `words`")
    word_count: int = Field(ge=0)


class TranscriptOut(BaseModel):
    language: str
    duration_s: float | None
    words: list[TranscriptWord]
    segments: list[TranscriptSegment]


class ProjectMediaOut(BaseModel):
    proxy_url: str
    expires_in_s: int
