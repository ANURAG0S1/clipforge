"""Application settings, loaded from the environment and validated at startup."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PLACEHOLDER_PREFIX = "<"


def _reject_placeholder(name: str, value: SecretStr) -> SecretStr:
    raw = value.get_secret_value().strip()
    if not raw or raw.startswith(_PLACEHOLDER_PREFIX):
        raise ValueError(f"{name} must be set to a real value, not a placeholder")
    return value


class Settings(BaseSettings):
    """Every field without a default is required; startup fails if it is missing."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint: str
    s3_public_endpoint: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = Field(min_length=3, max_length=63)
    s3_region: str = "us-east-1"

    anthropic_api_key: SecretStr
    llm_model: str = "claude-sonnet-5-5"

    whisper_model: str = "large-v3"
    whisper_device: Literal["cuda", "cpu", "auto"] = "auto"

    max_upload_gb: float = Field(default=4, gt=0)
    max_duration_min: int = Field(default=180, gt=0)

    jwt_secret: SecretStr
    jwt_ttl_hours: int = Field(default=24 * 7, gt=0)
    # Set true behind HTTPS. Defaults false so http://localhost works out of the box.
    auth_cookie_secure: bool = False

    project_create_limit: int = Field(default=20, gt=0)
    project_create_window_s: int = Field(default=3600, gt=0)
    ingest_download_timeout_s: int = Field(default=3600, gt=0)
    ffmpeg_timeout_s: int = Field(default=4 * 3600, gt=0)
    temp_dir: str | None = None

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    health_check_timeout_s: float = Field(default=2.0, gt=0)

    @field_validator("anthropic_api_key")
    @classmethod
    def _anthropic_key_set(cls, v: SecretStr) -> SecretStr:
        return _reject_placeholder("ANTHROPIC_API_KEY", v)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strong(cls, v: SecretStr) -> SecretStr:
        _reject_placeholder("JWT_SECRET", v)
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: PostgresDsn) -> PostgresDsn:
        if v.scheme != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_gb * 1024**3)

    @property
    def max_duration_s(self) -> float:
        return float(self.max_duration_min * 60)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # pydantic-settings populates required fields from the environment.
    return Settings()
