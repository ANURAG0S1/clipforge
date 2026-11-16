from httpx import AsyncClient

from app.core.security import AUTH_COOKIE
from tests.support.fakes import InMemoryRateLimiter


async def test_register_sets_httponly_cookie_and_me_works(anon: AsyncClient) -> None:
    resp = await anon.post(
        "/auth/register", json={"email": "  Dana@Example.com ", "password": "password123"}
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "dana@example.com"
    set_cookie = resp.headers["set-cookie"]
    assert f"{AUTH_COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "password" not in resp.text

    me = await anon.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dana@example.com"


async def test_duplicate_email_conflicts(anon: AsyncClient) -> None:
    body = {"email": "dup@example.com", "password": "password123"}
    assert (await anon.post("/auth/register", json=body)).status_code == 201
    resp = await anon.post("/auth/register", json={**body, "email": "DUP@example.com"})
    assert resp.status_code == 409


async def test_register_validation(anon: AsyncClient) -> None:
    bad_email = await anon.post("/auth/register", json={"email": "nope", "password": "x" * 10})
    assert bad_email.status_code == 422
    short_pw = await anon.post("/auth/register", json={"email": "a@b.co", "password": "short"})
    assert short_pw.status_code == 422


async def test_login_logout_flow(anon: AsyncClient) -> None:
    creds = {"email": "lee@example.com", "password": "password123"}
    await anon.post("/auth/register", json=creds)
    await anon.post("/auth/logout")
    anon.cookies.clear()
    assert (await anon.get("/auth/me")).status_code == 401

    wrong = await anon.post("/auth/login", json={**creds, "password": "wrong-password"})
    assert wrong.status_code == 401
    unknown = await anon.post("/auth/login", json={**creds, "email": "ghost@example.com"})
    assert unknown.status_code == 401
    assert wrong.json() == unknown.json()

    ok = await anon.post("/auth/login", json=creds)
    assert ok.status_code == 200
    assert (await anon.get("/auth/me")).status_code == 200

    out = await anon.post("/auth/logout")
    assert out.status_code == 204
    assert (
        'clipforge_session=""' in out.headers["set-cookie"]
        or "Max-Age=0" in out.headers["set-cookie"]
    )


async def test_invalid_cookie_is_unauthenticated(anon: AsyncClient) -> None:
    anon.cookies.set(AUTH_COOKIE, "not-a-jwt")
    assert (await anon.get("/auth/me")).status_code == 401


async def test_login_rate_limited(anon: AsyncClient, limiter: InMemoryRateLimiter) -> None:
    creds = {"email": "rl@example.com", "password": "password123"}
    for _ in range(10):
        await anon.post("/auth/login", json=creds)
    resp = await anon.post("/auth/login", json=creds)
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
