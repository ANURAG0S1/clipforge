"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import AUTH_COOKIE, InvalidTokenError, decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.services.rate_limit import RateLimiter, get_rate_limiter
from app.services.storage import Storage, get_storage

SessionDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[Storage, Depends(get_storage)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)


async def get_current_user(
    db: SessionDep,
    settings: SettingsDep,
    session_token: Annotated[str | None, Cookie(alias=AUTH_COOKIE)] = None,
) -> User:
    if not session_token:
        raise _UNAUTHENTICATED
    try:
        user_id = decode_access_token(session_token, settings)
    except InvalidTokenError:
        raise _UNAUTHENTICATED from None
    user = await db.get(User, user_id)
    if user is None:
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def not_found(resource: str) -> HTTPException:
    """Ownership failures are reported as 404 so resource existence is never leaked."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")
