import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nawa.core.security import hash_password

PASSWORD = "correct horse battery staple"

_PASSWORD_HASH = hash_password(PASSWORD)


@dataclass
class Actor:
    user_id: uuid.UUID
    email: str
    client: httpx.AsyncClient
    csrf: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}


async def insert_user(
    engine: AsyncEngine,
    email: str,
    *,
    password: str | None = None,
    is_admin: bool = False,
    is_active: bool = True,
) -> uuid.UUID:
    user_id = uuid.uuid4()
    password_hash = _PASSWORD_HASH if password is None else hash_password(password)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, is_admin, is_active)"
                " VALUES (:id, :email, :hash, :admin, :active)"
            ),
            {
                "id": user_id,
                "email": email,
                "hash": password_hash,
                "admin": is_admin,
                "active": is_active,
            },
        )
    return user_id


async def insert_workspace(engine: AsyncEngine, slug: str, name: str | None = None) -> uuid.UUID:
    workspace_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": workspace_id, "name": name or slug.title(), "slug": slug},
        )
    return workspace_id


async def insert_membership(
    engine: AsyncEngine, workspace_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (id, workspace_id, user_id, role)"
                " VALUES (:id, :ws, :user, :role)"
            ),
            {"id": uuid.uuid4(), "ws": workspace_id, "user": user_id, "role": role},
        )


async def log_in(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("csrf_token")
    assert csrf
    return csrf
