import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import PASSWORD, insert_user, log_in

REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


def csrf_headers(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf}


async def post_with_refresh_cookie(
    client: httpx.AsyncClient, refresh_token: str, csrf: str
) -> httpx.Response:
    """Send a specific (possibly stale) refresh token, bypassing the client's cookie jar."""
    return await client.post(
        REFRESH,
        headers={
            "Cookie": f"refresh_token={refresh_token}; csrf_token={csrf}",
            "X-CSRF-Token": csrf,
        },
    )


async def test_refresh_rotates_the_token_and_keeps_the_session_usable(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    old_refresh = client.cookies.get("refresh_token")

    response = await client.post(REFRESH, headers=csrf_headers(csrf))

    assert response.status_code == 200
    assert client.cookies.get("refresh_token") != old_refresh
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_reusing_a_rotated_token_revokes_the_whole_chain(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    stale = client.cookies.get("refresh_token")
    assert stale
    assert (await client.post(REFRESH, headers=csrf_headers(csrf))).status_code == 200
    fresh = client.cookies.get("refresh_token")
    assert fresh

    replay = await post_with_refresh_cookie(client, stale, csrf)
    assert replay.status_code == 401

    # The legitimate, newer token is now dead too.
    after = await post_with_refresh_cookie(client, fresh, csrf)
    assert after.status_code == 401
    async with owner_engine.connect() as conn:
        live = (
            await conn.execute(text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))
        ).scalar_one()
        actions = (await conn.execute(text("SELECT action FROM audit_logs"))).scalars().all()
    assert live == 0
    assert "auth.refresh_reuse_detected" in actions


async def test_expired_refresh_token_is_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 hour'"))
    response = await client.post(REFRESH, headers=csrf_headers(csrf))
    assert response.status_code == 401


async def test_refresh_requires_csrf_and_a_cookie(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    assert (await client.post(REFRESH)).status_code == 403
    assert (await client.post(REFRESH, headers=csrf_headers("wrong-token"))).status_code == 403
    bare = httpx.AsyncClient(transport=client._transport, base_url="http://test")  # noqa: SLF001
    try:
        response = await bare.post(
            REFRESH, headers={"Cookie": f"csrf_token={csrf}", "X-CSRF-Token": csrf}
        )
    finally:
        await bare.aclose()
    assert response.status_code == 401


async def test_deactivated_user_cannot_refresh(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false"))
    assert (await client.post(REFRESH, headers=csrf_headers(csrf))).status_code == 401


async def test_logout_revokes_the_session_and_clears_cookies(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    refresh = client.cookies.get("refresh_token")
    assert refresh

    response = await client.post(LOGOUT, headers=csrf_headers(csrf))

    assert response.status_code == 204
    cleared = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "max-age=0" in cleared
    assert (await post_with_refresh_cookie(client, refresh, csrf)).status_code == 401
    async with owner_engine.connect() as conn:
        live = (
            await conn.execute(text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL"))
        ).scalar_one()
    assert live == 0


async def test_logout_requires_csrf(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    await insert_user(owner_engine, "ada@example.com")
    await log_in(client, "ada@example.com")
    assert (await client.post(LOGOUT)).status_code == 403


async def test_login_after_logout_works(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    csrf = await log_in(client, "ada@example.com")
    await client.post(LOGOUT, headers=csrf_headers(csrf))
    again = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    )
    assert again.status_code == 200
