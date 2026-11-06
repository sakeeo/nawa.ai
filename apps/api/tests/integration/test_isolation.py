import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import Actor, insert_membership, insert_user, insert_workspace

MakeActor = Callable[..., Awaitable[Actor]]


def iter_api_routes(routes: list[Any]) -> Iterator[APIRoute]:
    """Flatten the route tree.

    Since FastAPI 0.117 `app.routes` contains nested `_IncludedRouter` wrappers, not a
    flat list of APIRoute objects.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):  # _IncludedRouter
            yield from iter_api_routes(route.original_router.routes)
        elif hasattr(route, "routes"):  # bare APIRouter
            yield from iter_api_routes(route.routes)


async def test_every_workspace_route_rejects_another_tenants_workspace(
    app: FastAPI, make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    """Future-proof: any new route under /workspaces/{workspace_id} is covered automatically."""
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    manager_a = await make_actor("manager-a@example.com")
    await insert_membership(owner_engine, ws_a, manager_a.user_id, "manager")

    routes = [
        r
        for r in iter_api_routes(app.routes)
        if isinstance(r, APIRoute) and "{workspace_id}" in r.path
    ]
    # Real count: GET workspace, GET/PATCH/DELETE members, POST invites (5 route objects).
    assert len(routes) >= 5
    for route in routes:
        path = route.path.replace("{workspace_id}", str(ws_b)).replace(
            "{user_id}", str(uuid.uuid4())
        )
        for method in route.methods:
            response = await manager_a.client.request(
                method, path, headers=manager_a.headers, json={}
            )
            assert response.status_code == 403, (method, route.path, response.text)


async def test_users_never_see_each_others_workspaces_or_members(
    make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user_a = await make_actor("a@example.com")
    user_b = await make_actor("b@example.com")
    await insert_membership(owner_engine, ws_a, user_a.user_id, "member")
    await insert_membership(owner_engine, ws_b, user_b.user_id, "member")

    listed_a = (await user_a.client.get("/api/v1/workspaces")).json()
    members_a = (await user_a.client.get(f"/api/v1/workspaces/{ws_a}/members")).json()

    assert [w["id"] for w in listed_a] == [str(ws_a)]
    assert [m["email"] for m in members_a] == ["a@example.com"]
    assert (await user_a.client.get(f"/api/v1/workspaces/{ws_b}/members")).status_code == 403


async def test_audit_logs_are_scoped_per_workspace_at_the_database_level(
    make_actor: MakeActor, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nawa.core.db import apply_rls

    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    admin = await make_actor("root@example.com", is_admin=True)
    await admin.client.post(
        f"/api/v1/workspaces/{ws_a}/invites",
        json={"email": "x@example.com", "role": "member"},
        headers=admin.headers,
    )
    await admin.client.post(
        f"/api/v1/workspaces/{ws_b}/invites",
        json={"email": "y@example.com", "role": "member"},
        headers=admin.headers,
    )
    await insert_user(owner_engine, "unused@example.com")

    async with AsyncSession(app_engine) as session:
        await apply_rls(session, workspace_id=ws_a)
        rows = (await session.execute(text("SELECT workspace_id, action FROM audit_logs"))).all()
    assert {(r[0], r[1]) for r in rows} == {(ws_a, "invite.created")}
