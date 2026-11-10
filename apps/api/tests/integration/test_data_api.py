import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nawa.core.config import get_settings
from nawa.data.connector import ConnectionParams, open_engine
from nawa.intelligence.deps import get_llm_client
from tests.fakes import ScriptedLLMClient
from tests.integration.conftest import TargetDb
from tests.integration.helpers import Actor, insert_membership, insert_workspace

MakeActor = Callable[..., Awaitable[Actor]]

SEMANTIC = """
tables:
  outlets:
    synonyms: [outlet, cabang]
    columns: [id, name, city]
  orders:
    synonyms: [pesanan]
    columns: [id, outlet_id, channel, amount, created_at]
metrics:
  revenue:
    synonyms: [omzet]
    sql: SUM(orders.amount)
dimensions:
  outlet: outlets.name
joins:
  - orders.outlet_id = outlets.id
time_anchor: SELECT MAX(created_at)::date FROM orders
"""
GOOD_SQL = (
    "SELECT outlets.name, SUM(orders.amount) AS revenue FROM orders"
    " JOIN outlets ON orders.outlet_id = outlets.id GROUP BY outlets.name ORDER BY revenue DESC"
)


def reply(sql: str | None, clarification: str | None = None) -> str:
    return json.dumps({"sql": sql, "assumptions": ["per outlet"], "clarification": clarification})


@dataclass
class World:
    ws: uuid.UUID
    manager: Actor
    member: Actor
    other_member: Actor
    viewer: Actor
    fake: ScriptedLLMClient
    target: TargetDb
    owner_engine: AsyncEngine
    app: FastAPI

    def url(self, path: str = "") -> str:
        return f"/api/v1/workspaces/{self.ws}{path}"

    @property
    def readonly(self) -> ConnectionParams:
        assert isinstance(self.target.readonly, ConnectionParams)
        return self.target.readonly

    @property
    def owner_params(self) -> ConnectionParams:
        assert isinstance(self.target.owner, ConnectionParams)
        return self.target.owner

    def body(self, params: ConnectionParams, name: str = "demo") -> dict[str, Any]:
        return {
            "name": name,
            "host": params.host,
            "port": params.port,
            "database": params.database,
            "username": params.username,
            "password": params.password,
            "ssl_mode": "prefer",
        }

    async def create_source(
        self, params: ConnectionParams | None = None, name: str = "demo"
    ) -> str:
        response = await self.manager.client.post(
            self.url("/data-sources"),
            json=self.body(params or self.readonly, name),
            headers=self.manager.headers,
        )
        assert response.status_code == 201, response.text
        return str(response.json()["source"]["id"])

    async def discover(self, source_id: str) -> httpx.Response:
        return await self.manager.client.post(
            self.url(f"/data-sources/{source_id}/discover"), headers=self.manager.headers
        )

    async def put_semantic(self, source_id: str, yaml_text: str = SEMANTIC) -> httpx.Response:
        return await self.manager.client.put(
            self.url(f"/data-sources/{source_id}/semantic-model"),
            json={"yaml": yaml_text},
            headers=self.manager.headers,
        )

    async def prepare(self) -> str:
        source_id = await self.create_source()
        assert (await self.discover(source_id)).status_code == 200
        assert (await self.put_semantic(source_id)).status_code == 200
        return source_id

    async def ask(
        self, actor: Actor, source_id: str, question: str = "omzet per outlet"
    ) -> httpx.Response:
        return await actor.client.post(
            self.url("/data/ask"),
            json={"data_source_id": source_id, "question": question},
            headers=actor.headers,
        )

    async def scalar(self, statement: str, **params: Any) -> Any:
        async with self.owner_engine.connect() as conn:
            return (await conn.execute(text(statement), params)).scalar()


@pytest.fixture
async def world(
    app: FastAPI,
    make_actor: MakeActor,
    owner_engine: AsyncEngine,
    target_database: TargetDb,
    monkeypatch: pytest.MonkeyPatch,
) -> World:
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    fake = ScriptedLLMClient([])
    app.dependency_overrides[get_llm_client] = lambda: fake
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE instance_settings SET setup_completed = true, ai_provider = 'ollama'")
        )
    ws = await insert_workspace(owner_engine, "acme")
    actors: dict[str, Actor] = {}
    for name, role in (
        ("manager", "manager"),
        ("member", "member"),
        ("other", "member"),
        ("viewer", "viewer"),
    ):
        actors[name] = await make_actor(f"{name}@example.com")
        await insert_membership(owner_engine, ws, actors[name].user_id, role)
    return World(
        ws,
        actors["manager"],
        actors["member"],
        actors["other"],
        actors["viewer"],
        fake,
        target_database,
        owner_engine,
        app,
    )


# ---------------------------------------------------------------- data sources


async def test_creating_a_source_tests_it_and_never_returns_the_password(world: World) -> None:
    response = await world.manager.client.post(
        world.url("/data-sources"), json=world.body(world.readonly), headers=world.manager.headers
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["source"]["status"] == "ok" and created["report"]["ok"] is True
    assert created["source"]["username"] == world.readonly.username
    listing = await world.manager.client.get(world.url("/data-sources"))
    secret = world.readonly.password
    assert secret not in response.text and secret not in listing.text
    assert "password" not in created["source"]
    stored = await world.scalar("SELECT password_encrypted FROM data_sources")
    assert stored and secret not in stored
    action = await world.scalar("SELECT action FROM audit_logs WHERE action = 'data_source.create'")
    assert action == "data_source.create"
    audit_target = await world.scalar(
        "SELECT target FROM audit_logs WHERE action = 'data_source.create'"
    )
    assert world.readonly.host in audit_target and secret not in audit_target


async def test_a_writable_role_fails_the_test_and_cannot_be_asked(world: World) -> None:
    source_id = await world.create_source(world.owner_params, name="unsafe")
    listing = (await world.manager.client.get(world.url("/data-sources"))).json()
    assert listing[0]["status"] == "failed" and "superuser" in listing[0]["last_error"].lower()
    refused = await world.ask(world.member, source_id)
    assert refused.status_code == 409


async def test_duplicate_source_names_conflict(world: World) -> None:
    await world.create_source()
    response = await world.manager.client.post(
        world.url("/data-sources"), json=world.body(world.readonly), headers=world.manager.headers
    )
    assert response.status_code == 409


async def test_create_validates_input_strictly(world: World) -> None:
    for patch in ({"port": 0}, {"port": 99999}, {"host": ""}, {"extra": 1}, {"ssl_mode": "weird"}):
        response = await world.manager.client.post(
            world.url("/data-sources"),
            json={**world.body(world.readonly), **patch},
            headers=world.manager.headers,
        )
        assert response.status_code == 422, patch


async def test_without_an_encryption_key_creation_is_unavailable_but_listing_works(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATA_ENCRYPTION_KEY")
    get_settings.cache_clear()
    response = await world.manager.client.post(
        world.url("/data-sources"), json=world.body(world.readonly), headers=world.manager.headers
    )
    assert response.status_code == 503
    assert "DATA_ENCRYPTION_KEY" in response.json()["detail"]
    assert (await world.manager.client.get(world.url("/data-sources"))).status_code == 200


async def test_retest_updates_the_status(world: World) -> None:
    source_id = await world.create_source()
    await world.scalar("SELECT 1")
    async with world.owner_engine.begin() as conn:
        await conn.execute(text("UPDATE data_sources SET status = 'failed', last_error = 'x'"))
    response = await world.manager.client.post(
        world.url(f"/data-sources/{source_id}/test"), headers=world.manager.headers
    )
    assert response.status_code == 200 and response.json()["ok"] is True
    assert await world.scalar("SELECT status FROM data_sources") == "ok"


async def test_delete_removes_the_source_and_keeps_the_query_history(world: World) -> None:
    source_id = await world.prepare()
    world.fake.replies = [reply(GOOD_SQL)]
    assert (await world.ask(world.member, source_id)).status_code == 200
    deleted = await world.manager.client.delete(
        world.url(f"/data-sources/{source_id}"), headers=world.manager.headers
    )
    assert deleted.status_code == 204
    assert await world.scalar("SELECT count(*) FROM data_sources") == 0
    assert await world.scalar("SELECT count(*) FROM semantic_models") == 0
    assert await world.scalar("SELECT count(*) FROM query_logs WHERE data_source_id IS NULL") == 1
    again = await world.manager.client.delete(
        world.url(f"/data-sources/{source_id}"), headers=world.manager.headers
    )
    assert again.status_code == 404
    assert (
        await world.scalar("SELECT count(*) FROM audit_logs WHERE action = 'data_source.delete'")
        == 1
    )


# ---------------------------------------------------------------- permissions and isolation


async def test_roles_unauthenticated_and_csrf(world: World, client: httpx.AsyncClient) -> None:
    source_id = await world.prepare()
    manager_calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("POST", "/data-sources", world.body(world.readonly, "other")),
        ("POST", f"/data-sources/{source_id}/test", None),
        ("POST", f"/data-sources/{source_id}/discover", None),
        ("DELETE", f"/data-sources/{source_id}", None),
        ("POST", f"/data-sources/{source_id}/semantic-model/draft", None),
        ("PUT", f"/data-sources/{source_id}/semantic-model", {"yaml": SEMANTIC}),
    ]
    for actor in (world.member, world.viewer):
        for method, path, body in manager_calls:
            response = await actor.client.request(
                method, world.url(path), json=body, headers=actor.headers
            )
            assert response.status_code == 403, (actor.email, method, path)
    ask_body = {"data_source_id": source_id, "question": "omzet"}
    assert (
        await world.viewer.client.post(
            world.url("/data/ask"), json=ask_body, headers=world.viewer.headers
        )
    ).status_code == 403
    for actor in (world.member, world.viewer):  # viewers may read, never change
        assert (await actor.client.get(world.url("/data-sources"))).status_code == 200
        assert (
            await actor.client.get(world.url(f"/data-sources/{source_id}/semantic-model"))
        ).status_code == 200
    # Unsafe methods hit the CSRF check before authentication, so an anonymous POST is a 403.
    assert (await client.post(world.url("/data/ask"), json=ask_body)).status_code == 403
    assert (await client.get(world.url("/data-sources"))).status_code == 401
    no_csrf = await world.manager.client.post(world.url(f"/data-sources/{source_id}/test"))
    assert no_csrf.status_code == 403


async def test_another_workspace_cannot_reach_a_source(
    world: World, make_actor: MakeActor, owner_engine: AsyncEngine
) -> None:
    source_id = await world.prepare()
    ws_b = await insert_workspace(owner_engine, "beta")
    manager_b = await make_actor("manager-b@example.com")
    await insert_membership(owner_engine, ws_b, manager_b.user_id, "manager")
    base_b = f"/api/v1/workspaces/{ws_b}"
    assert (await manager_b.client.get(f"{base_b}/data-sources")).json() == []
    for method, path in (
        ("POST", f"/data-sources/{source_id}/test"),
        ("POST", f"/data-sources/{source_id}/discover"),
        ("DELETE", f"/data-sources/{source_id}"),
        ("GET", f"/data-sources/{source_id}/semantic-model"),
        ("POST", f"/data-sources/{source_id}/semantic-model/draft"),
    ):
        response = await manager_b.client.request(method, base_b + path, headers=manager_b.headers)
        assert response.status_code == 404, (method, path)
    asked = await manager_b.client.post(
        f"{base_b}/data/ask",
        json={"data_source_id": source_id, "question": "omzet"},
        headers=manager_b.headers,
    )
    assert asked.status_code == 404
    assert await world.scalar("SELECT count(*) FROM data_sources") == 1


# ---------------------------------------------------------------- discovery and semantic model


async def test_discovery_summarises_the_schema_and_samples_nothing_without_a_model(
    world: World,
) -> None:
    source_id = await world.create_source()
    response = await world.discover(source_id)
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["tables"] == 2 and summary["columns"] == 9
    assert summary["sampled_columns"] == 0 and summary["has_semantic_model"] is False
    snapshot = await world.scalar("SELECT snapshot::text FROM schema_snapshots")
    assert "Bandung" not in snapshot  # no allowlist yet, so no sample values were stored


async def test_rediscovery_samples_only_allowlisted_columns(world: World) -> None:
    source_id = await world.prepare()
    summary = (await world.discover(source_id)).json()
    assert summary["has_semantic_model"] is True and summary["sampled_columns"] >= 2
    snapshot = await world.scalar(
        "SELECT snapshot::text FROM schema_snapshots ORDER BY created_at DESC LIMIT 1"
    )
    assert "Bandung" in snapshot and "dine_in" in snapshot
    assert "free text note" not in snapshot  # orders.note is not in the semantic model


async def test_a_draft_needs_a_snapshot_and_is_valid_yaml(world: World) -> None:
    source_id = await world.create_source()
    early = await world.manager.client.post(
        world.url(f"/data-sources/{source_id}/semantic-model/draft"), headers=world.manager.headers
    )
    assert early.status_code == 409
    await world.discover(source_id)
    draft = await world.manager.client.post(
        world.url(f"/data-sources/{source_id}/semantic-model/draft"), headers=world.manager.headers
    )
    assert draft.status_code == 200
    saved = await world.put_semantic(source_id, draft.json()["yaml"])
    assert saved.status_code == 200 and saved.json()["version"] == 1


async def test_invalid_yaml_returns_the_list_of_problems(world: World) -> None:
    source_id = await world.create_source()
    await world.discover(source_id)
    for bad, needle in (
        ("tables: [", "YAML"),
        ("surprise: 1", "surprise"),
        (SEMANTIC.replace("columns: [id, name, city]", "columns: [id, name, ghost]"), "ghost"),
        (SEMANTIC.replace("SUM(orders.amount)", "SUM(orders.nope)"), "nope"),
    ):
        response = await world.put_semantic(source_id, bad)
        assert response.status_code == 422, bad
        body = response.json()
        assert body["code"] == "validation_failed"
        assert any(needle in problem for problem in body["problems"]), (bad, body)
    assert await world.scalar("SELECT count(*) FROM semantic_models") == 0


async def test_saving_needs_a_discovery_first(world: World) -> None:
    source_id = await world.create_source()
    assert (await world.put_semantic(source_id)).status_code == 409


async def test_a_new_version_replaces_the_active_one(world: World) -> None:
    source_id = await world.prepare()
    second = await world.put_semantic(source_id, SEMANTIC + "\n# second version\n")
    assert second.status_code == 200 and second.json()["version"] == 2
    assert await world.scalar("SELECT count(*) FROM semantic_models WHERE is_active") == 1
    assert await world.scalar("SELECT version FROM semantic_models WHERE is_active") == 2
    current = (
        await world.member.client.get(world.url(f"/data-sources/{source_id}/semantic-model"))
    ).json()
    assert current["version"] == 2 and "second version" in current["yaml"]
    assert (
        await world.scalar(
            "SELECT count(*) FROM audit_logs WHERE action = 'semantic_model.activate'"
        )
        == 2
    )


async def test_reading_a_missing_model_is_404(world: World) -> None:
    source_id = await world.create_source()
    response = await world.member.client.get(world.url(f"/data-sources/{source_id}/semantic-model"))
    assert response.status_code == 404


async def test_oversized_yaml_is_rejected(world: World) -> None:
    source_id = await world.create_source()
    await world.discover(source_id)
    assert (await world.put_semantic(source_id, "# " + "x" * 300_000)).status_code == 422


# ---------------------------------------------------------------- ask


async def test_ask_returns_sql_rows_chart_and_logs_the_query(world: World) -> None:
    source_id = await world.prepare()
    world.fake.replies = [reply(GOOD_SQL)]
    response = await world.ask(world.member, source_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok" and body["attempts"] == 1
    assert body["columns"] == ["name", "revenue"] and body["row_count"] == 3
    assert [row[0] for row in body["rows"]] == ["Bandung", "Jakarta", "Medan"]
    assert body["chart"]["kind"] == "bar" and body["chart"]["x"] == "name"
    assert body["sql"].upper().rstrip().endswith("LIMIT 1000")
    assert body["assumptions"] == ["per outlet"] and body["truncated"] is False
    assert (
        await world.scalar("SELECT status FROM query_logs WHERE id = :i", i=body["query_id"])
        == "ok"
    )


async def test_a_dangerous_model_reply_is_blocked_logged_and_nothing_runs(world: World) -> None:
    source_id = await world.prepare()
    world.fake.replies = [reply("DROP TABLE orders")]
    response = await world.ask(world.member, source_id, "hapus tabel pesanan")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked" and body["blocked_reason"] and body["sql"] is None
    assert body["rows"] == [] and body["chart"] is None
    assert (
        await world.scalar("SELECT status FROM query_logs WHERE id = :i", i=body["query_id"])
        == "blocked"
    )
    async with open_engine(world.owner_params) as engine, engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM orders"))).scalar_one() == 40
    assert len(world.fake.completions) == 1


async def test_a_clarification_is_a_normal_answer(world: World) -> None:
    source_id = await world.prepare()
    world.fake.replies = [reply(None, "Data apa yang ingin dilihat?")]
    body = (await world.ask(world.member, source_id, "bagaimana kabarnya?")).json()
    assert body["status"] == "clarification" and body["clarification"] and body["rows"] == []


async def test_ask_needs_a_tested_source_a_snapshot_and_an_active_model(world: World) -> None:
    source_id = await world.create_source()
    assert (await world.ask(world.member, source_id)).status_code == 409  # no snapshot
    await world.discover(source_id)
    assert (await world.ask(world.member, source_id)).status_code == 409  # no semantic model
    assert world.fake.completions == []
    unknown = await world.ask(world.member, str(uuid.uuid4()))
    assert unknown.status_code == 404


async def test_ask_validates_the_body(world: World) -> None:
    source_id = await world.prepare()
    for body in (
        {"data_source_id": source_id},
        {"question": "x"},
        {"data_source_id": source_id, "question": ""},
        {"data_source_id": source_id, "question": "x" * 2001},
        {"data_source_id": "not-a-uuid", "question": "x"},
        {"data_source_id": source_id, "question": "x", "extra": 1},
    ):
        response = await world.member.client.post(
            world.url("/data/ask"), json=body, headers=world.member.headers
        )
        assert response.status_code == 422, body


async def test_ask_is_rate_limited(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    source_id = await world.prepare()
    monkeypatch.setenv("DATA_ASK_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    world.fake.replies = [reply(GOOD_SQL), reply(GOOD_SQL)]
    assert (await world.ask(world.member, source_id)).status_code == 200
    assert (await world.ask(world.member, source_id)).status_code == 200
    assert (await world.ask(world.member, source_id)).status_code == 429
    assert len(world.fake.completions) == 2


async def test_an_unavailable_model_is_a_503_not_a_500(world: World) -> None:
    source_id = await world.prepare()
    world.fake.fail_models = {"ollama/qwen2.5:7b"}
    assert (await world.ask(world.member, source_id)).status_code == 503


# ---------------------------------------------------------------- history, insight, feedback


async def _ask_ok(world: World, source_id: str, actor: Actor) -> str:
    world.fake.replies.append(reply(GOOD_SQL))
    response = await world.ask(actor, source_id)
    assert response.json()["status"] == "ok"
    return str(response.json()["query_id"])


async def test_history_is_private_for_members_and_complete_for_managers(world: World) -> None:
    source_id = await world.prepare()
    mine = await _ask_ok(world, source_id, world.member)
    theirs = await _ask_ok(world, source_id, world.other_member)
    own = (await world.member.client.get(world.url("/data/queries"))).json()
    assert [q["id"] for q in own] == [mine]
    assert {"question", "sql", "status", "attempts", "row_count", "created_at"} <= set(own[0])
    everything = (await world.manager.client.get(world.url("/data/queries"))).json()
    assert {q["id"] for q in everything} == {mine, theirs}
    limited = (await world.manager.client.get(world.url("/data/queries?limit=1"))).json()
    assert len(limited) == 1
    assert (await world.manager.client.get(world.url("/data/queries?limit=0"))).status_code == 422


async def test_insight_is_grounded_cached_and_visible_only_to_the_owner_or_a_manager(
    world: World,
) -> None:
    source_id = await world.prepare()
    query_id = await _ask_ok(world, source_id, world.member)
    world.fake.replies.append("Bandung tertinggi dengan 287, Medan terendah dengan 260.")
    first = await world.member.client.post(
        world.url(f"/data/queries/{query_id}/insight"), headers=world.member.headers
    )
    assert first.status_code == 200, first.text
    assert first.json() == {
        "text": "Bandung tertinggi dengan 287, Medan terendah dengan 260.",
        "grounded": True,
        "cached": False,
    }
    calls = len(world.fake.completions)
    second = await world.member.client.post(
        world.url(f"/data/queries/{query_id}/insight"), headers=world.member.headers
    )
    assert second.json()["cached"] is True and len(world.fake.completions) == calls
    assert (
        await world.scalar("SELECT insight_grounded FROM query_logs WHERE id = :i", i=query_id)
        is True
    )
    stranger = await world.other_member.client.post(
        world.url(f"/data/queries/{query_id}/insight"), headers=world.other_member.headers
    )
    assert stranger.status_code == 404
    manager = await world.manager.client.post(
        world.url(f"/data/queries/{query_id}/insight"), headers=world.manager.headers
    )
    assert manager.status_code == 200


async def test_an_invented_number_is_replaced_and_flagged(world: World) -> None:
    source_id = await world.prepare()
    query_id = await _ask_ok(world, source_id, world.member)
    world.fake.replies.append("Bandung naik 99% dari bulan lalu.")
    body = (
        await world.member.client.post(
            world.url(f"/data/queries/{query_id}/insight"), headers=world.member.headers
        )
    ).json()
    assert body["grounded"] is False and "99" not in body["text"]


async def test_only_a_successful_query_has_an_insight(world: World) -> None:
    source_id = await world.prepare()
    world.fake.replies = [reply("DROP TABLE orders")]
    blocked = (await world.ask(world.member, source_id)).json()["query_id"]
    response = await world.member.client.post(
        world.url(f"/data/queries/{blocked}/insight"), headers=world.member.headers
    )
    assert response.status_code == 409
    missing = await world.member.client.post(
        world.url(f"/data/queries/{uuid.uuid4()}/insight"), headers=world.member.headers
    )
    assert missing.status_code == 404


async def test_insight_needs_the_source_to_still_exist(world: World) -> None:
    source_id = await world.prepare()
    query_id = await _ask_ok(world, source_id, world.member)
    await world.manager.client.delete(
        world.url(f"/data-sources/{source_id}"), headers=world.manager.headers
    )
    response = await world.member.client.post(
        world.url(f"/data/queries/{query_id}/insight"), headers=world.member.headers
    )
    assert response.status_code == 409


async def test_feedback_is_stored_for_the_owner_only(world: World) -> None:
    source_id = await world.prepare()
    query_id = await _ask_ok(world, source_id, world.member)
    url = world.url(f"/data/queries/{query_id}/feedback")
    ok = await world.member.client.post(url, json={"value": 1}, headers=world.member.headers)
    assert ok.status_code == 204
    assert await world.scalar("SELECT feedback FROM query_logs WHERE id = :i", i=query_id) == 1
    flipped = await world.member.client.post(url, json={"value": -1}, headers=world.member.headers)
    assert flipped.status_code == 204
    assert await world.scalar("SELECT feedback FROM query_logs WHERE id = :i", i=query_id) == -1
    other = await world.other_member.client.post(
        url, json={"value": 1}, headers=world.other_member.headers
    )
    assert other.status_code == 404
    for bad in ({"value": 0}, {"value": 5}, {}, {"value": 1, "x": 1}):
        response = await world.member.client.post(url, json=bad, headers=world.member.headers)
        assert response.status_code == 422, bad
