import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import TEST_ENV


def _make(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> Settings:
    for key, value in {**TEST_ENV, **overrides}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_valid_env_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make(monkeypatch, MAX_UPLOAD_GB="2", CORS_ORIGINS="http://a.test, http://b.test")
    assert settings.max_upload_bytes == 2 * 1024**3
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
    assert settings.llm_model == "claude-sonnet-5-5"


@pytest.mark.parametrize(
    "missing", ["DATABASE_URL", "REDIS_URL", "S3_ENDPOINT", "ANTHROPIC_API_KEY", "JWT_SECRET"]
)
def test_missing_required_var_fails_fast(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _make(monkeypatch, **{missing: None})
    assert missing.lower() in str(exc.value).lower()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("JWT_SECRET", "<generate>"),
        ("JWT_SECRET", "too-short"),
        ("ANTHROPIC_API_KEY", "<your-key>"),
        ("DATABASE_URL", "postgresql://u:p@localhost:5432/db"),
        ("WHISPER_DEVICE", "tpu"),
    ],
)
def test_invalid_values_rejected(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _make(monkeypatch, **{key: value})


def test_secrets_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make(monkeypatch)
    rendered = repr(settings) + str(settings.model_dump())
    assert TEST_ENV["JWT_SECRET"] not in rendered
    assert TEST_ENV["ANTHROPIC_API_KEY"] not in rendered
