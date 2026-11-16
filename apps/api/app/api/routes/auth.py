from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, RateLimiterDep, SessionDep, SettingsDep
from app.core.config import Settings
from app.core.security import (
    AUTH_COOKIE,
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.schemas.auth import Credentials, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_LIMIT = 10
_LOGIN_WINDOW_S = 300


def _set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    response.set_cookie(
        key=AUTH_COOKIE,
        value=create_access_token(user.id, settings),
        max_age=settings.jwt_ttl_hours * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: Credentials,
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> User:
    verdict = await limiter.hit(f"register:{_client_ip(request)}", _LOGIN_LIMIT, _LOGIN_WINDOW_S)
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts",
            headers={"Retry-After": str(verdict.retry_after_s)},
        )
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists"
        ) from None
    await db.refresh(user)
    _set_session_cookie(response, user, settings)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> User:
    verdict = await limiter.hit(
        f"login:{_client_ip(request)}:{body.email}", _LOGIN_LIMIT, _LOGIN_WINDOW_S
    )
    if not verdict.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts",
            headers={"Retry-After": str(verdict.retry_after_s)},
        )
    user = await db.scalar(select(User).where(User.email == body.email))
    # Always run one argon2 verification so response time does not reveal whether the email exists.
    valid = verify_password(user.password_hash if user else DUMMY_PASSWORD_HASH, body.password)
    if user is None or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    _set_session_cookie(response, user, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        AUTH_COOKIE, path="/", httponly=True, secure=settings.auth_cookie_secure, samesite="lax"
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
