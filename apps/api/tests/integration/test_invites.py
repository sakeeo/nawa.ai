import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import (
    PASSWORD,
    Actor,
    insert_membership,
    insert_user,
    insert_workspace,
    log_in,
)

MakeActor = Callable[..., Awaitable[Actor]]
NEW_PASSWORD = "a brand new passphrase"


async def create_invite(
    admin: Actor, workspace_id: Any, email: str, role: str = "member"
) -> dict[str, Any]:
    response = await admin.client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


async def test_admin_creates_an_invite_and_only_the_hash_is_stored(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    admin = await make_actor("root@example.com", is_admin=True)

    invite = await create_invite(admin, ws, "New@Example.com", "viewer")

    assert invite["email"] == "new@example.com"
    assert invite["accept_path"] == f"/invite/{invite['token']}"
    async with owner_engine.connect() as conn:
        stored = (await conn.execute(text("SELECT token_hash FROM invites"))).scalar_one()
    assert stored == hashlib.sha256(invite["token"].encode()).hexdigest()
    assert stored != invite["token"]


async def test_only_installation_admins_can_invite(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    manager = await make_actor("manager@example.com")
    await insert_membership(owner_engine, ws, manager.user_id, "manager")
    response = await manager.client.post(
        f"/api/v1/workspaces/{ws}/invites",
        json={"email": "x@example.com", "role": "member"},
        headers=manager.headers,
    )
    assert response.status_code == 403


async def test_preview_shows_invite_details_and_hides_bad_tokens(
    make_actor: MakeActor, owner_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    ws = await insert_workspace(owner_engine, "alpha", name="Alpha Team")
    admin = await make_actor("root@example.com", is_admin=True)
    invite = await create_invite(admin, ws, "new@example.com", "viewer")

    good = await client.get(f"/api/v1/invites/{invite['token']}")
    bad = await client.get("/api/v1/invites/not-a-real-token")

    assert good.json() == {
        "email": "new@example.com",
        "workspace_name": "Alpha Team",
        "role": "viewer",
    }
    assert bad.status_code == 404


async def test_accept_creates_user_membership_and_allows_login(
    make_actor: MakeActor, owner_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    admin = await make_actor("root@example.com", is_admin=True)
    invite = await create_invite(admin, ws, "new@example.com", "manager")

    accepted = await client.post(
        "/api/v1/invites/accept", json={"token": invite["token"], "password": NEW_PASSWORD}
    )

    assert accepted.status_code == 200
    assert accepted.json() == {
        "email": "new@example.com",
        "workspace_id": str(ws),
        "role": "manager",
    }
    await log_in(client, "new@example.com", NEW_PASSWORD)
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["memberships"] == [{"workspace_id": str(ws), "role": "manager"}]
    assert me["user"]["is_admin"] is False
    async with owner_engine.connect() as conn:
        actions = (await conn.execute(text("SELECT action FROM audit_logs"))).scalars().all()
    assert {"invite.created", "invite.accepted"} <= set(actions)


async def test_an_invite_is_single_use(
    make_actor: MakeActor, owner_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    admin = await make_actor("root@example.com", is_admin=True)
    invite = await create_invite(admin, ws, "new@example.com")
    payload = {"token": invite["token"], "password": NEW_PASSWORD}
    assert (await client.post("/api/v1/invites/accept", json=payload)).status_code == 200
    assert (await client.post("/api/v1/invites/accept", json=payload)).status_code == 404
    assert (await client.get(f"/api/v1/invites/{invite['token']}")).status_code == 404


async def test_an_expired_invite_is_rejected(
    make_actor: MakeActor, owner_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    admin = await make_actor("root@example.com", is_admin=True)
    invite = await create_invite(admin, ws, "new@example.com")
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE invites SET expires_at = now() - interval '1 minute'"))
    response = await client.post(
        "/api/v1/invites/accept", json={"token": invite["token"], "password": NEW_PASSWORD}
    )
    assert response.status_code == 404


async def test_a_new_user_needs_a_strong_enough_password_and_the_invite_survives(
    make_actor: MakeActor, owner_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    admin = await make_actor("root@example.com", is_admin=True)
    invite = await create_invite(admin, ws, "new@example.com")

    missing = await client.post("/api/v1/invites/accept", json={"token": invite["token"]})
    short = await client.post(
        "/api/v1/invites/accept", json={"token": invite["token"], "password": "short"}
    )
    assert missing.status_code == 422
    assert short.status_code == 422
    ok = await client.post(
        "/api/v1/invites/accept", json={"token": invite["token"], "password": NEW_PASSWORD}
    )
    assert ok.status_code == 200


async def test_existing_user_joins_another_workspace_without_a_password(
    make_actor: MakeActor, owner_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    existing = await insert_user(owner_engine, "ada@example.com")
    await insert_membership(owner_engine, ws_a, existing, "member")
    admin = await make_actor("root@example.com", is_admin=True)
    invite = await create_invite(admin, ws_b, "ada@example.com", "viewer")

    response = await client.post("/api/v1/invites/accept", json={"token": invite["token"]})

    assert response.status_code == 200
    await log_in(client, "ada@example.com", PASSWORD)  # password unchanged
    me = await client.get("/api/v1/auth/me")
    roles = {
        m["workspace_id"]: m["role"]
        for m in me.json()["memberships"]  # type: ignore[index]
    }
    assert roles == {str(ws_a): "member", str(ws_b): "viewer"}
