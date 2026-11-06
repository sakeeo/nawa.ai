import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nawa.core.security import create_access_token
from tests.integration.helpers import PASSWORD, insert_membership, insert_user, insert_workspace

LOGIN = "/api/v1/auth/login"


async def test_login_sets_cookies_and_returns_profile(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    user_id = await insert_user(owner_engine, "ada@example.com")
    workspace_id = await insert_workspace(owner_engine, "alpha")
    await insert_membership(owner_engine, workspace_id, user_id, "member")

    response = await client.post(LOGIN, json={"email": "Ada@Example.com", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": str(user_id), "email": "ada@example.com", "is_admin": False}
    assert body["memberships"] == [{"workspace_id": str(workspace_id), "role": "member"}]
    cookies = {c.split("=", 1)[0]: c for c in response.headers.get_list("set-cookie")}
    assert "HttpOnly" in cookies["access_token"]
    assert "samesite=lax" in cookies["access_token"].lower()
    assert "HttpOnly" in cookies["refresh_token"]
    assert "Path=/api/v1/auth" in cookies["refresh_token"]
    assert "HttpOnly" not in cookies["csrf_token"]


async def test_login_failure_is_uniform_for_unknown_user_and_wrong_password(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    wrong = await client.post(LOGIN, json={"email": "ada@example.com", "password": "nope"})
    unknown = await client.post(LOGIN, json={"email": "nobody@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert wrong.json()["code"] == "unauthenticated"


async def test_inactive_user_cannot_log_in(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com", is_active=False)
    response = await client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
    assert response.status_code == 401


async def test_login_is_rate_limited_per_email(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    for _ in range(5):
        response = await client.post(LOGIN, json={"email": "ada@example.com", "password": "bad"})
        assert response.status_code == 401
    blocked = await client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"


async def test_login_is_rate_limited_per_ip(client: httpx.AsyncClient) -> None:
    for index in range(10):
        response = await client.post(
            LOGIN, json={"email": f"user{index}@example.com", "password": "bad"}
        )
        assert response.status_code == 401
    blocked = await client.post(LOGIN, json={"email": "another@example.com", "password": "bad"})
    assert blocked.status_code == 429


async def test_successful_login_resets_the_email_counter(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    for _ in range(2):
        for _ in range(4):
            await client.post(LOGIN, json={"email": "ada@example.com", "password": "bad"})
        ok = await client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
        assert ok.status_code == 200


async def test_me_requires_a_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_returns_the_logged_in_user(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    user_id = await insert_user(owner_engine, "ada@example.com", is_admin=True)
    await client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user_id)
    assert response.json()["user"]["is_admin"] is True


async def test_me_rejects_an_expired_access_token(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    user_id = await insert_user(owner_engine, "ada@example.com")
    token = create_access_token(
        user_id=user_id,
        secret=os.environ["JWT_SECRET"],
        ttl_seconds=60,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    response = await client.get("/api/v1/auth/me", headers={"Cookie": f"access_token={token}"})
    assert response.status_code == 401


async def test_me_rejects_a_token_for_a_deleted_user(client: httpx.AsyncClient) -> None:
    token = create_access_token(
        user_id=uuid.uuid4(), secret=os.environ["JWT_SECRET"], ttl_seconds=60
    )
    response = await client.get("/api/v1/auth/me", headers={"Cookie": f"access_token={token}"})
    assert response.status_code == 401


async def test_me_rejects_a_deactivated_user(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    await client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false"))
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_login_and_failed_login_are_audited(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "ada@example.com")
    await client.post(LOGIN, json={"email": "ada@example.com", "password": "bad"})
    await client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
    async with owner_engine.connect() as conn:
        actions = (
            (await conn.execute(text("SELECT action FROM audit_logs ORDER BY created_at")))
            .scalars()
            .all()
        )
    assert actions == ["auth.login_failed", "auth.login"]
