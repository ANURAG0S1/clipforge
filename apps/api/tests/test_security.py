import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "anything")


def test_token_roundtrip() -> None:
    settings = get_settings()
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid, settings), settings) == uid


def test_expired_token_rejected() -> None:
    settings = get_settings()
    old = datetime.now(tz=UTC) - timedelta(hours=settings.jwt_ttl_hours + 1)
    token = create_access_token(uuid.uuid4(), settings, now=old)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings)


def test_forged_and_wrong_type_tokens_rejected() -> None:
    settings = get_settings()
    now = int(datetime.now(tz=UTC).timestamp())
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + 60, "typ": "session"},
        "some-other-secret-that-is-long-enough-xx",
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, settings)
    wrong_type = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + 60, "typ": "reset"},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(wrong_type, settings)
    with pytest.raises(InvalidTokenError):
        decode_access_token("garbage", settings)
