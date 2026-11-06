import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import Actor, insert_membership, insert_user, insert_workspace

MakeActor = Callable[..., Awaitable[Actor]]

# (actor role or "outsider"/"admin", expected status) per endpoint.
READ = {"viewer": 200, "member": 200, "manager": 200, "admin": 200, "outsider": 403}
WRITE = {"viewer": 403, "member": 403, "manager": 200, "admin": 200, "outsider": 403}


async def actor_with_role(
    make_actor: MakeActor, owner_engine: AsyncEngine, workspace_id: uuid.UUID, role: str
) -> Actor:
    actor = await make_actor(f"{role}@example.com", is_admin=(role == "admin"))
    if role not in {"admin", "outsider"}:
        await insert_membership(owner_engine, workspace_id, actor.user_id, role)
    return actor


@pytest.mark.parametrize(("role", "expected"), READ.items())
async def test_list_members_matrix(
    make_actor: MakeActor, owner_engine: AsyncEngine, role: str, expected: int
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    actor = await actor_with_role(make_actor, owner_engine, ws, role)
    response = await actor.client.get(f"/api/v1/workspaces/{ws}/members")
    assert response.status_code == expected


@pytest.mark.parametrize(("role", "expected"), WRITE.items())
async def test_change_role_matrix(
    make_actor: MakeActor, owner_engine: AsyncEngine, role: str, expected: int
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    target = await insert_user(owner_engine, "target@example.com")
    await insert_membership(owner_engine, ws, target, "member")
    actor = await actor_with_role(make_actor, owner_engine, ws, role)
    response = await actor.client.patch(
        f"/api/v1/workspaces/{ws}/members/{target}", json={"role": "viewer"}, headers=actor.headers
    )
    assert response.status_code == expected


@pytest.mark.parametrize(("role", "expected"), WRITE.items())
async def test_remove_member_matrix(
    make_actor: MakeActor, owner_engine: AsyncEngine, role: str, expected: int
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    target = await insert_user(owner_engine, "target@example.com")
    await insert_membership(owner_engine, ws, target, "member")
    actor = await actor_with_role(make_actor, owner_engine, ws, role)
    response = await actor.client.delete(
        f"/api/v1/workspaces/{ws}/members/{target}", headers=actor.headers
    )
    assert response.status_code == (204 if expected == 200 else expected)


async def test_list_members_returns_emails_and_roles(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    manager = await actor_with_role(make_actor, owner_engine, ws, "manager")
    other = await insert_user(owner_engine, "other@example.com")
    await insert_membership(owner_engine, ws, other, "viewer")
    rows = (await manager.client.get(f"/api/v1/workspaces/{ws}/members")).json()
    assert {(r["email"], r["role"]) for r in rows} == {
        ("manager@example.com", "manager"),
        ("other@example.com", "viewer"),
    }


async def test_role_change_and_removal_take_effect_and_are_audited(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    manager = await actor_with_role(make_actor, owner_engine, ws, "manager")
    target = await insert_user(owner_engine, "target@example.com")
    await insert_membership(owner_engine, ws, target, "member")

    changed = await manager.client.patch(
        f"/api/v1/workspaces/{ws}/members/{target}",
        json={"role": "manager"},
        headers=manager.headers,
    )
    assert changed.json() == {
        "user_id": str(target),
        "email": "target@example.com",
        "role": "manager",
    }
    await manager.client.delete(
        f"/api/v1/workspaces/{ws}/members/{target}", headers=manager.headers
    )

    async with owner_engine.connect() as conn:
        remaining = (await conn.execute(text("SELECT count(*) FROM memberships"))).scalar_one()
        actions = (await conn.execute(text("SELECT action FROM audit_logs"))).scalars().all()
    assert remaining == 1
    assert {"member.role_changed", "member.removed"} <= set(actions)


async def test_unknown_member_is_404(make_actor: MakeActor, owner_engine: AsyncEngine) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    manager = await actor_with_role(make_actor, owner_engine, ws, "manager")
    missing = uuid.uuid4()
    patch = await manager.client.patch(
        f"/api/v1/workspaces/{ws}/members/{missing}",
        json={"role": "viewer"},
        headers=manager.headers,
    )
    delete = await manager.client.delete(
        f"/api/v1/workspaces/{ws}/members/{missing}", headers=manager.headers
    )
    assert patch.status_code == delete.status_code == 404


async def test_invalid_role_is_rejected(make_actor: MakeActor, owner_engine: AsyncEngine) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    manager = await actor_with_role(make_actor, owner_engine, ws, "manager")
    response = await manager.client.patch(
        f"/api/v1/workspaces/{ws}/members/{manager.user_id}",
        json={"role": "admin"},
        headers=manager.headers,
    )
    assert response.status_code == 422


async def test_manager_cannot_touch_another_workspace(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    manager = await actor_with_role(make_actor, owner_engine, ws_a, "manager")
    victim = await insert_user(owner_engine, "victim@example.com")
    await insert_membership(owner_engine, ws_b, victim, "member")

    # Wrong workspace in the path.
    blocked = await manager.client.delete(
        f"/api/v1/workspaces/{ws_b}/members/{victim}", headers=manager.headers
    )
    # Right workspace, but the user belongs to another one.
    absent = await manager.client.delete(
        f"/api/v1/workspaces/{ws_a}/members/{victim}", headers=manager.headers
    )
    assert blocked.status_code == 403
    assert absent.status_code == 404
    async with owner_engine.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": victim}
            )
        ).scalar_one()
    assert count == 1
