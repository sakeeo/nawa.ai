from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nawa.intelligence.api import get_llm_client
from tests.fakes import FakeLLMClient
from tests.integration.helpers import Actor

MakeActor = Callable[..., Awaitable[Actor]]
URL = "/api/v1/llm/chat"


async def complete_setup(engine: AsyncEngine, provider: str = "ollama") -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE instance_settings SET setup_completed = true, ai_provider = :p"),
            {"p": provider},
        )


async def test_admin_runs_llm_test_with_versioned_prompt(
    app: FastAPI, make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    fake = FakeLLMClient(reply="Halo dari NAWA.AI")
    app.dependency_overrides[get_llm_client] = lambda: fake
    await complete_setup(owner_engine)
    admin = await make_actor("admin@example.com", is_admin=True)

    r = await admin.client.post(URL, json={"message": "ping"}, headers=admin.headers)

    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Halo dari NAWA.AI"
    assert r.json()["model"].startswith("ollama/")
    call = fake.calls[0]
    assert call["messages"][0]["role"] == "system"
    assert call["metadata"]["trace_metadata"]["prompt_name"] == "ping"


async def test_non_admin_cannot_run_llm_test(
    app: FastAPI, make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    await complete_setup(owner_engine)
    member = await make_actor("m@example.com")
    r = await member.client.post(URL, json={"message": "x"}, headers=member.headers)
    assert r.status_code == 403


async def test_llm_test_refused_before_setup(app: FastAPI, make_actor: MakeActor) -> None:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    admin = await make_actor("admin@example.com", is_admin=True)
    r = await admin.client.post(URL, json={"message": "x"}, headers=admin.headers)
    assert r.status_code == 409
