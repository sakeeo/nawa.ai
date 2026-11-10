import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nawa.core.config import Settings, get_settings
from nawa.intelligence.deps import get_llm_client
from nawa.intelligence.gateway import LLMGateway
from nawa.knowledge.chat_service import stream_chat
from nawa.knowledge.ingest import ingest_document
from nawa.knowledge.storage import FileStorage
from tests.fakes import ConceptEmbedder
from tests.integration.helpers import Actor, insert_membership, insert_workspace

MakeActor = Callable[..., Awaitable[Actor]]

DOC = "# Refund\n\nProsedur refund penuh untuk makanan tidak layak. Pengembalian uang segera.\n"
ANSWERABLE = "refund pengembalian uang"
UNANSWERABLE = "bagaimana cara memasak rendang"


def _gateway(fake: ConceptEmbedder) -> LLMGateway:
    settings = Settings(
        _env_file=None, database_url="x", redis_url="x", jwt_secret="s" * 32, llm_fallback_model=""
    )
    return LLMGateway(fake, settings, model="ollama/qwen2.5:7b")


def parse_sse(body: str) -> list[dict]:
    return [json.loads(c[len("data: ") :]) for c in body.strip().split("\n\n") if c]


@pytest.fixture
async def world(
    app: FastAPI,
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
):  # type: ignore[no-untyped-def]
    fake = ConceptEmbedder(reply="Beri refund penuh [1] segera [9].")
    app.dependency_overrides[get_llm_client] = lambda: fake
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE instance_settings SET setup_completed = true, ai_provider = 'ollama'")
        )
    ws = await insert_workspace(owner_engine, "acme")
    storage = FileStorage(tmp_path)
    manager = await make_actor("manager@example.com")
    await insert_membership(owner_engine, ws, manager.user_id, "manager")
    kb, doc = uuid.uuid4(), uuid.uuid4()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO knowledge_bases (id, workspace_id, name) VALUES (:id, :ws, 'D')"),
            {"id": kb, "ws": ws},
        )
        await conn.execute(
            text(
                "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime,"
                " size_bytes, sha256, status, created_by)"
                " VALUES (:id, :ws, :kb, 'refund.md', 'text/markdown', 10, 'x', 'queued', :u)"
            ),
            {"id": doc, "ws": ws, "kb": kb, "u": manager.user_id},
        )
    storage.save(ws, doc, DOC.encode())
    await ingest_document(sessionmaker, storage, _gateway(fake), workspace_id=ws, document_id=doc)
    fake.calls.clear()
    member = await make_actor("member@example.com")
    await insert_membership(owner_engine, ws, member.user_id, "member")
    return {"ws": ws, "fake": fake, "member": member, "manager": manager, "doc": doc}


def _chat(actor: Actor, ws: uuid.UUID, question: str, conversation_id: uuid.UUID | None = None):  # type: ignore[no-untyped-def]
    body: dict = {"question": question}
    if conversation_id:
        body["conversation_id"] = str(conversation_id)
    return actor.client.post(f"/api/v1/workspaces/{ws}/chat", json=body, headers=actor.headers)


def _generator_calls(fake: ConceptEmbedder) -> list[dict]:
    return [c for c in fake.calls if c["kind"] in ("stream", "complete")]


async def test_answerable_question_streams_events_and_is_stored(world) -> None:  # type: ignore[no-untyped-def]
    ws, member = world["ws"], world["member"]
    r = await _chat(member, ws, ANSWERABLE)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache" and r.headers["x-accel-buffering"] == "no"
    events = parse_sse(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "meta" and types[-1] == "done" and types[-2] == "citations"
    assert set(types[1:-2]) == {"token"} and len(types) > 4
    cites = events[-2]
    assert [c["marker"] for c in cites["citations"]] == [1] and cites["invalid_markers"] == [9]
    assert cites["citations"][0]["filename"] == "refund.md"
    assert events[-1]["refused"] is False and events[0]["gate"] == "ok"

    conv_id = events[0]["conversation_id"]
    detail = (await member.client.get(f"/api/v1/workspaces/{ws}/conversations/{conv_id}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    answer = detail["messages"][1]
    assert answer["id"] == events[0]["message_id"] and "refund penuh" in answer["content"]
    assert [c["marker"] for c in answer["citations"]] == [1]
    listing = (await member.client.get(f"/api/v1/workspaces/{ws}/conversations")).json()
    assert [c["id"] for c in listing] == [conv_id] and listing[0]["title"] == ANSWERABLE


async def test_unanswerable_question_refuses_without_calling_the_generator(world) -> None:  # type: ignore[no-untyped-def]
    ws, member, fake = world["ws"], world["member"], world["fake"]
    events = parse_sse((await _chat(member, ws, UNANSWERABLE)).text)
    assert [e["type"] for e in events] == ["meta", "refusal", "done"]
    assert events[2]["refused"] is True and "tidak ditemukan" in events[1]["text"]
    assert _generator_calls(fake) == []
    detail = (
        await member.client.get(
            f"/api/v1/workspaces/{ws}/conversations/{events[0]['conversation_id']}"
        )
    ).json()
    assert detail["messages"][1]["refused"] is True and detail["messages"][1]["citations"] == []


async def test_access_control(world, client_factory, make_actor, owner_engine) -> None:  # type: ignore[no-untyped-def]
    ws = world["ws"]
    viewer = await make_actor("viewer@example.com")
    await insert_membership(owner_engine, ws, viewer.user_id, "viewer")
    assert (await _chat(viewer, ws, ANSWERABLE)).status_code == 403
    outsider = await make_actor("out@example.com")
    assert (await _chat(outsider, ws, ANSWERABLE)).status_code == 403
    anonymous = client_factory()
    r = await anonymous.post(f"/api/v1/workspaces/{ws}/chat", json={"question": "x"})
    assert r.status_code in (401, 403)
    member = world["member"]
    r = await member.client.post(f"/api/v1/workspaces/{ws}/chat", json={"question": "x"})
    assert r.status_code == 403  # no CSRF header


async def test_conversation_is_reused_and_private(world, make_actor, owner_engine) -> None:  # type: ignore[no-untyped-def]
    ws, member = world["ws"], world["member"]
    first = parse_sse((await _chat(member, ws, ANSWERABLE)).text)
    conv = uuid.UUID(first[0]["conversation_id"])
    await _chat(member, ws, "refund lagi", conv)
    detail = (await member.client.get(f"/api/v1/workspaces/{ws}/conversations/{conv}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]

    other = await make_actor("other@example.com")
    await insert_membership(owner_engine, ws, other.user_id, "member")
    assert (await _chat(other, ws, ANSWERABLE, conv)).status_code == 404
    assert (
        await other.client.get(f"/api/v1/workspaces/{ws}/conversations/{conv}")
    ).status_code == 404
    assert (await other.client.get(f"/api/v1/workspaces/{ws}/conversations")).json() == []


async def test_feedback_rules_and_upsert(world, make_actor, owner_engine) -> None:  # type: ignore[no-untyped-def]
    ws, member = world["ws"], world["member"]
    events = parse_sse((await _chat(member, ws, ANSWERABLE)).text)
    message_id, conv = events[0]["message_id"], events[0]["conversation_id"]
    url = f"/api/v1/workspaces/{ws}/messages/{message_id}/feedback"

    r = await member.client.post(url, json={"value": 1}, headers=member.headers)
    assert r.status_code == 204
    r = await member.client.post(
        url, json={"value": -1, "comment": "salah"}, headers=member.headers
    )
    assert r.status_code == 204
    async with owner_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT value, comment FROM feedback"))).all()
    assert [tuple(r) for r in rows] == [(-1, "salah")]
    detail = (await member.client.get(f"/api/v1/workspaces/{ws}/conversations/{conv}")).json()
    assert detail["messages"][1]["feedback"] == -1

    assert (
        await member.client.post(url, json={"value": 2}, headers=member.headers)
    ).status_code == 422
    other = await make_actor("other@example.com")
    await insert_membership(owner_engine, ws, other.user_id, "member")
    assert (
        await other.client.post(url, json={"value": 1}, headers=other.headers)
    ).status_code == 404
    user_message = detail["messages"][0]["id"]
    r = await member.client.post(
        f"/api/v1/workspaces/{ws}/messages/{user_message}/feedback",
        json={"value": 1},
        headers=member.headers,
    )
    assert r.status_code == 404


async def test_model_failure_mid_stream_gives_error_event_and_keeps_user_message(
    world, app
) -> None:  # type: ignore[no-untyped-def]
    ws, member = world["ws"], world["member"]
    broken = ConceptEmbedder(reply="satu dua tiga empat", fail_after_tokens=1)
    app.dependency_overrides[get_llm_client] = lambda: broken
    events = parse_sse((await _chat(member, ws, ANSWERABLE)).text)
    assert events[-1]["type"] == "error" and events[-1]["code"] == "llm_unavailable"
    assert "done" not in [e["type"] for e in events]
    conv = (await member.client.get(f"/api/v1/workspaces/{ws}/conversations")).json()[0]["id"]
    detail = (await member.client.get(f"/api/v1/workspaces/{ws}/conversations/{conv}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user"]


async def test_client_disconnect_leaves_no_half_assistant_message(  # type: ignore[no-untyped-def]
    world, sessionmaker, owner_engine
) -> None:
    ws, member = world["ws"], world["member"]
    conv, message_id = uuid.uuid4(), uuid.uuid4()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO conversations (id, workspace_id, user_id, title)"
                " VALUES (:c, :w, :u, 't')"
            ),
            {"c": conv, "w": ws, "u": member.user_id},
        )
    stream = stream_chat(
        maker=sessionmaker,
        gateway=_gateway(ConceptEmbedder(reply="a b c d e f")),
        settings=get_settings(),
        workspace_id=ws,
        user_id=member.user_id,
        is_admin=False,
        conversation_id=conv,
        message_id=message_id,
        question=ANSWERABLE,
    )
    first = await anext(stream)
    assert json.loads(first.decode()[len("data: ") :])["type"] == "meta"
    await anext(stream)  # first token
    await stream.aclose()  # the client went away
    async with owner_engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM messages"))).scalar_one()
    assert count == 0


async def test_rate_limit_returns_429_problem(world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ws, member = world["ws"], world["member"]
    monkeypatch.setenv("CHAT_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    assert (await _chat(member, ws, ANSWERABLE)).status_code == 200
    assert (await _chat(member, ws, ANSWERABLE)).status_code == 200
    r = await _chat(member, ws, ANSWERABLE)
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_question_length_and_control_characters(world) -> None:  # type: ignore[no-untyped-def]
    ws, member, fake = world["ws"], world["member"], world["fake"]
    assert (await _chat(member, ws, "x" * 2001)).status_code == 422
    assert (await _chat(member, ws, "\x00\x07 ")).status_code == 422
    events = parse_sse((await _chat(member, ws, "refund\x00 \x1b[31mpengembalian uang")).text)
    embed_inputs = [c["inputs"] for c in fake.calls if c["kind"] == "embed"]
    assert embed_inputs and embed_inputs[0] == ["refund pengembalian uang"]
    assert all("\x00" not in i and "\x1b" not in i for batch in embed_inputs for i in batch)
    assert events[0]["type"] == "meta"
