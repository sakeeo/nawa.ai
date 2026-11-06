import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import Actor, insert_membership, insert_workspace

MakeActor = Callable[..., Awaitable[Actor]]


async def test_admin_creates_a_workspace(make_actor: MakeActor, owner_engine: AsyncEngine) -> None:
    admin = await make_actor("root@example.com", is_admin=True)
    response = await admin.client.post(
        "/api/v1/workspaces", json={"name": "Finance", "slug": "finance"}, headers=admin.headers
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["slug"], body["role"]) == ("Finance", "finance", "admin")
    async with owner_engine.connect() as conn:
        actions = (await conn.execute(text("SELECT action FROM audit_logs"))).scalars().all()
    assert "workspace.created" in actions


async def test_duplicate_slug_conflicts(make_actor: MakeActor) -> None:
    admin = await make_actor("root@example.com", is_admin=True)
    payload = {"name": "Finance", "slug": "finance"}
    assert (
        await admin.client.post("/api/v1/workspaces", json=payload, headers=admin.headers)
    ).status_code == 201
    again = await admin.client.post("/api/v1/workspaces", json=payload, headers=admin.headers)
    assert again.status_code == 409
    assert again.json()["code"] == "conflict"


@pytest.mark.parametrize("slug", ["Bad Slug", "UPPER", "-lead", "trail-", "a" * 51, ""])
async def test_invalid_slug_is_rejected(make_actor: MakeActor, slug: str) -> None:
    admin = await make_actor("root@example.com", is_admin=True)
    response = await admin.client.post(
        "/api/v1/workspaces", json={"name": "X", "slug": slug}, headers=admin.headers
    )
    assert response.status_code == 422


async def test_non_admin_cannot_create_workspaces(make_actor: MakeActor) -> None:
    user = await make_actor("user@example.com")
    response = await user.client.post(
        "/api/v1/workspaces", json={"name": "X", "slug": "x"}, headers=user.headers
    )
    assert response.status_code == 403


async def test_creating_a_workspace_needs_a_session_and_csrf(
    make_actor: MakeActor, client_factory: Callable[[], object]
) -> None:
    admin = await make_actor("root@example.com", is_admin=True)
    no_csrf = await admin.client.post("/api/v1/workspaces", json={"name": "X", "slug": "x"})
    assert no_csrf.status_code == 403


async def test_list_shows_only_my_workspaces_and_admin_sees_all(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    await insert_workspace(owner_engine, "beta")
    user = await make_actor("user@example.com")
    admin = await make_actor("root@example.com", is_admin=True)
    await insert_membership(owner_engine, ws_a, user.user_id, "viewer")

    mine = (await user.client.get("/api/v1/workspaces")).json()
    everything = (await admin.client.get("/api/v1/workspaces")).json()

    assert [(w["slug"], w["role"]) for w in mine] == [("alpha", "viewer")]
    assert sorted(w["slug"] for w in everything) == ["alpha", "beta"]


@pytest.mark.parametrize("role", ["viewer", "member", "manager"])
async def test_members_of_any_role_can_read_their_workspace(
    make_actor: MakeActor, owner_engine: AsyncEngine, role: str
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await make_actor("user@example.com")
    await insert_membership(owner_engine, ws, user.user_id, role)
    response = await user.client.get(f"/api/v1/workspaces/{ws}")
    assert response.status_code == 200
    assert response.json()["role"] == role


async def test_non_member_gets_403_and_unknown_workspace_looks_the_same(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    other = await insert_workspace(owner_engine, "other")
    user = await make_actor("user@example.com")
    forbidden = await user.client.get(f"/api/v1/workspaces/{other}")
    missing = await user.client.get(f"/api/v1/workspaces/{uuid.uuid4()}")
    assert forbidden.status_code == missing.status_code == 403


async def test_admin_reads_any_workspace_and_gets_404_for_unknown(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    admin = await make_actor("root@example.com", is_admin=True)
    assert (await admin.client.get(f"/api/v1/workspaces/{ws}")).json()["role"] == "admin"
    assert (await admin.client.get(f"/api/v1/workspaces/{uuid.uuid4()}")).status_code == 404


async def test_unauthenticated_requests_are_rejected(
    client_factory: Callable[[], object], owner_engine: AsyncEngine
) -> None:
    import httpx

    client = client_factory()
    assert isinstance(client, httpx.AsyncClient)
    ws = await insert_workspace(owner_engine, "alpha")
    assert (await client.get("/api/v1/workspaces")).status_code == 401
    assert (await client.get(f"/api/v1/workspaces/{ws}")).status_code == 401
