import logging

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nawa.core.config import get_settings
from nawa.core.security import hash_token
from nawa.workspace.setup_service import ensure_setup_token
from tests.integration.helpers import insert_user, log_in

SETUP = "/api/v1/setup"
STATUS = "/api/v1/setup/status"
PASSWORD = "a very long admin passphrase"


def payload(token: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "setup_token": token,
        "email": "Admin@Example.com",
        "password": PASSWORD,
        "provider": "ollama",
        "load_demo_data": False,
    }
    body.update(overrides)
    return body


async def test_status_requires_setup_on_a_fresh_instance(client: httpx.AsyncClient) -> None:
    body = (await client.get(STATUS)).json()
    assert body["setup_required"] is True
    assert body["providers"] == ["ollama"]


async def test_setup_token_is_generated_logged_once_and_stored_hashed(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="nawa.setup"):
        token = await ensure_setup_token(sessionmaker)
    assert token
    assert token in caplog.text
    async with owner_engine.connect() as conn:
        stored = (
            await conn.execute(text("SELECT setup_token_hash FROM instance_settings"))
        ).scalar_one()
    assert stored == hash_token(token)


async def test_no_setup_token_when_users_exist(
    sessionmaker: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine
) -> None:
    await insert_user(owner_engine, "someone@example.com")
    assert await ensure_setup_token(sessionmaker) is None


async def test_complete_setup_creates_an_admin_who_can_log_in(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    token = await ensure_setup_token(sessionmaker)
    assert token

    response = await client.post(SETUP, json=payload(token, load_demo_data=True))

    assert response.status_code == 201
    assert response.json()["email"] == "admin@example.com"
    assert response.json()["is_admin"] is True
    await log_in(client, "admin@example.com", PASSWORD)
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT setup_completed, ai_provider, demo_data_requested, setup_token_hash"
                    " FROM instance_settings"
                )
            )
        ).one()
        actions = (await conn.execute(text("SELECT action FROM audit_logs"))).scalars().all()
    assert tuple(row) == (True, "ollama", True, None)
    assert "setup.completed" in actions
    assert (await client.get(STATUS)).json()["setup_required"] is False


async def test_setup_is_disabled_after_completion(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    token = await ensure_setup_token(sessionmaker)
    assert token
    assert (await client.post(SETUP, json=payload(token))).status_code == 201
    again = await client.post(SETUP, json=payload(token, email="second@example.com"))
    assert again.status_code == 409


async def test_wrong_setup_token_is_rejected(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await ensure_setup_token(sessionmaker)
    response = await client.post(SETUP, json=payload("guess"))
    assert response.status_code == 403


async def test_setup_without_a_generated_token_is_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.post(SETUP, json=payload("anything"))).status_code == 403


async def test_setup_is_refused_when_a_user_already_exists(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    token = await ensure_setup_token(sessionmaker)
    assert token
    await insert_user(owner_engine, "someone@example.com")
    assert (await client.post(SETUP, json=payload(token))).status_code == 409


async def test_provider_must_be_configured_on_the_server(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    token = await ensure_setup_token(sessionmaker)
    assert token
    response = await client.post(SETUP, json=payload(token, provider="deepseek"))
    assert response.status_code == 422


async def test_deepseek_is_offered_when_a_key_is_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    get_settings.cache_clear()
    assert (await client.get(STATUS)).json()["providers"] == ["ollama", "deepseek"]
    monkeypatch.setenv("OFFLINE_MODE", "true")
    get_settings.cache_clear()
    assert (await client.get(STATUS)).json()["providers"] == ["ollama"]


async def test_the_wizard_never_accepts_an_api_key(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    token = await ensure_setup_token(sessionmaker)
    assert token
    response = await client.post(SETUP, json=payload(token, api_key="sk-secret"))
    assert response.status_code == 422


async def test_weak_admin_password_is_rejected(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    token = await ensure_setup_token(sessionmaker)
    assert token
    assert (await client.post(SETUP, json=payload(token, password="short"))).status_code == 422
