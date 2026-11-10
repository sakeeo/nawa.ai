import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.intelligence.gateway import LLMGateway
from nawa.knowledge import api as knowledge_api
from nawa.knowledge.ingest import ingest_document
from nawa.knowledge.storage import FileStorage
from tests.fakes import FakeLLMClient
from tests.integration.helpers import Actor, insert_membership, insert_workspace

MakeActor = Callable[..., Awaitable[Actor]]

_BODY = " ".join(f"Sentence {i} about refunds." for i in range(60))
MD = f"# Refund policy\n\n{_BODY}\n".encode()


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(tmp_path)


@pytest.fixture
def enqueued(app: FastAPI, storage: FileStorage) -> list[tuple[uuid.UUID, uuid.UUID]]:
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def enqueue(workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
        calls.append((workspace_id, document_id))

    app.dependency_overrides[knowledge_api.get_storage] = lambda: storage
    app.dependency_overrides[knowledge_api.get_enqueue] = lambda: enqueue
    return calls


def _gateway() -> LLMGateway:
    settings = Settings(
        _env_file=None, database_url="x", redis_url="x", jwt_secret="s" * 32, llm_fallback_model=""
    )
    return LLMGateway(FakeLLMClient(), settings, model="ollama/qwen2.5:7b")


async def _join(engine: AsyncEngine, actor: Actor, ws: uuid.UUID, role: str) -> None:
    await insert_membership(engine, ws, actor.user_id, role)


def _upload(
    actor: Actor, ws: uuid.UUID, data: bytes = MD, name: str = "policy.md", headers: bool = True
):  # type: ignore[no-untyped-def]
    return actor.client.post(
        f"/api/v1/workspaces/{ws}/documents",
        files={"file": (name, data)},
        headers=actor.headers if headers else {},
    )


async def test_manager_uploads_then_ingestion_makes_it_ready(
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")

    r = await _upload(manager, ws)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["filename"] == "policy.md"
    assert "path" not in body and "sha256" not in body
    doc_id = uuid.UUID(body["id"])
    assert enqueued == [(ws, doc_id)]
    assert storage.exists(ws, doc_id)

    await ingest_document(sessionmaker, storage, _gateway(), workspace_id=ws, document_id=doc_id)

    r = await manager.client.get(f"/api/v1/workspaces/{ws}/documents/{doc_id}")
    assert r.json()["status"] == "ready"
    listing = await manager.client.get(f"/api/v1/workspaces/{ws}/documents")
    assert [d["id"] for d in listing.json()] == [str(doc_id)]

    async with owner_engine.connect() as conn:
        chunk_id = (
            await conn.execute(
                text("SELECT id FROM chunks WHERE document_id = :d LIMIT 1"), {"d": doc_id}
            )
        ).scalar_one()
        audits = (
            await conn.execute(
                text("SELECT action FROM audit_logs WHERE action = 'document.uploaded'")
            )
        ).all()
    assert len(audits) == 1
    chunk = await manager.client.get(f"/api/v1/workspaces/{ws}/chunks/{chunk_id}")
    assert chunk.status_code == 200
    assert chunk.json()["filename"] == "policy.md" and "refunds" in chunk.json()["text"]


async def test_viewer_and_member_cannot_upload_or_delete_but_can_list(
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")
    doc_id = (await _upload(manager, ws)).json()["id"]
    for email, role in (("v@example.com", "viewer"), ("mem@example.com", "member")):
        actor = await make_actor(email)
        await _join(owner_engine, actor, ws, role)
        assert (await _upload(actor, ws, b"other text", "o.md")).status_code == 403
        r = await actor.client.delete(
            f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=actor.headers
        )
        assert r.status_code == 403
        assert (await actor.client.get(f"/api/v1/workspaces/{ws}/documents")).status_code == 200


async def test_fresh_workspace_lists_empty_without_creating_a_knowledge_base(
    make_actor: MakeActor, owner_engine: AsyncEngine, enqueued: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    viewer = await make_actor("v@example.com")
    await _join(owner_engine, viewer, ws, "viewer")
    r = await viewer.client.get(f"/api/v1/workspaces/{ws}/documents")
    assert r.status_code == 200 and r.json() == []
    async with owner_engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM knowledge_bases"))).scalar_one()
    assert count == 0


async def test_duplicate_upload_conflicts(
    make_actor: MakeActor, owner_engine: AsyncEngine, enqueued: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")
    first = await _upload(manager, ws)
    second = await _upload(manager, ws, name="copy.md")
    assert second.status_code == 409
    assert first.json()["id"] in second.json()["detail"]
    assert second.headers["content-type"].startswith("application/problem+json")


async def test_oversized_unsupported_and_empty_uploads_are_rejected(
    app: FastAPI,
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "100")
    from nawa.core.config import get_settings

    get_settings.cache_clear()
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")

    big = await _upload(manager, ws, b"a" * 101)
    assert big.status_code == 413
    assert big.headers["content-type"].startswith("application/problem+json")
    assert (await _upload(manager, ws, b"MZ\x90\x00binary", "x.exe")).status_code == 415
    assert (await _upload(manager, ws, b"", "empty.md")).status_code == 422
    assert enqueued == []


async def test_other_workspace_cannot_see_documents_or_chunks(
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    manager_a = await make_actor("a@example.com")
    await _join(owner_engine, manager_a, ws_a, "manager")
    manager_b = await make_actor("b@example.com")
    await _join(owner_engine, manager_b, ws_b, "manager")
    doc_id = uuid.UUID((await _upload(manager_a, ws_a)).json()["id"])
    await ingest_document(sessionmaker, storage, _gateway(), workspace_id=ws_a, document_id=doc_id)
    async with owner_engine.connect() as conn:
        chunk_id = (await conn.execute(text("SELECT id FROM chunks LIMIT 1"))).scalar_one()

    # Not a member of A: refused outright.
    assert (
        await manager_b.client.get(f"/api/v1/workspaces/{ws_a}/documents/{doc_id}")
    ).status_code == 403
    # Member of B asking B's scope for A's ids: invisible.
    r = await manager_b.client.get(f"/api/v1/workspaces/{ws_b}/documents/{doc_id}")
    assert r.status_code == 404
    assert (
        await manager_b.client.get(f"/api/v1/workspaces/{ws_b}/chunks/{chunk_id}")
    ).status_code == 404
    r = await manager_b.client.delete(
        f"/api/v1/workspaces/{ws_b}/documents/{doc_id}", headers=manager_b.headers
    )
    assert r.status_code == 404
    assert storage.exists(ws_a, doc_id)


async def test_delete_removes_row_chunks_and_file(
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")
    doc_id = uuid.UUID((await _upload(manager, ws)).json()["id"])
    await ingest_document(sessionmaker, storage, _gateway(), workspace_id=ws, document_id=doc_id)

    r = await manager.client.delete(
        f"/api/v1/workspaces/{ws}/documents/{doc_id}", headers=manager.headers
    )
    assert r.status_code == 204
    assert not storage.exists(ws, doc_id)
    async with owner_engine.connect() as conn:
        docs = (await conn.execute(text("SELECT count(*) FROM documents"))).scalar_one()
        chunks = (await conn.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
    assert (docs, chunks) == (0, 0)
    assert (
        await manager.client.get(f"/api/v1/workspaces/{ws}/documents/{doc_id}")
    ).status_code == 404


async def test_retry_only_from_failed(
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")
    doc_id = (await _upload(manager, ws)).json()["id"]
    url = f"/api/v1/workspaces/{ws}/documents/{doc_id}/retry"

    assert (await manager.client.post(url, headers=manager.headers)).status_code == 409

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE documents SET status = 'failed', error = 'x' WHERE id = :d"),
            {"d": uuid.UUID(doc_id)},
        )
    enqueued.clear()
    r = await manager.client.post(url, headers=manager.headers)
    assert r.status_code == 202
    assert r.json()["status"] == "queued" and r.json()["error"] is None
    assert enqueued == [(ws, uuid.UUID(doc_id))]


async def test_enqueue_failure_marks_the_document_failed(
    app: FastAPI,
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    storage: FileStorage,
) -> None:
    async def broken(workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
        raise ConnectionError("redis down")

    app.dependency_overrides[knowledge_api.get_storage] = lambda: storage
    app.dependency_overrides[knowledge_api.get_enqueue] = lambda: broken
    ws = await insert_workspace(owner_engine, "acme")
    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")

    r = await _upload(manager, ws)
    assert r.status_code == 202
    assert r.json()["status"] == "failed" and "retry" in r.json()["error"].lower()


async def test_unauthenticated_and_missing_csrf(
    make_actor: MakeActor,
    client_factory,  # type: ignore[no-untyped-def]
    owner_engine: AsyncEngine,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    ws = await insert_workspace(owner_engine, "acme")
    anonymous = client_factory()
    assert (await anonymous.get(f"/api/v1/workspaces/{ws}/documents")).status_code == 401
    r = await anonymous.post(f"/api/v1/workspaces/{ws}/documents", files={"file": ("a.md", MD)})
    assert r.status_code in (401, 403)

    manager = await make_actor("m@example.com")
    await _join(owner_engine, manager, ws, "manager")
    assert (await _upload(manager, ws, headers=False)).status_code == 403
    assert enqueued == []
