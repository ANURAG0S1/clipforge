"""Password hashing (argon2id) and session tokens (HS256 JWT)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

_ALGORITHM: Final = "HS256"
AUTH_COOKIE: Final = "clipforge_session"
_hasher = PasswordHasher()

# Hash of a random password, used to equalise timing when the email does not exist.
DUMMY_PASSWORD_HASH: Final = _hasher.hash(uuid.uuid4().hex)


class InvalidTokenError(Exception):
    """The session token is missing, malformed, expired or forged."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, settings: Settings, now: datetime | None = None) -> str:
    issued = now or datetime.now(tz=UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(hours=settings.jwt_ttl_hours)).timestamp()),
        "typ": "session",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("typ") != "session":
        raise InvalidTokenError("wrong token type")
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise InvalidTokenError("invalid subject")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise InvalidTokenError("invalid subject") from exc
