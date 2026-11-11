import json
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.data.connector import ConnectionParams
from nawa.data.semantic import parse_semantic_yaml
from nawa.evaluation.runner import EvalConfigError
from nawa.evaluation.sql_dataset import load_sql_golden
from nawa.evaluation.sql_runner import (
    SqlRunConfig,
    check_sql_preconditions,
    load_sql_arms,
    run_sql_eval,
    select_sql_items,
    sql_target,
)
from nawa.intelligence.gateway import ChatResult
from tests.fakes import FakeLLMClient

ROOT = Path(__file__).resolve().parents[4]
GOLDEN = ROOT / "evals" / "sql_golden.yaml"
MODEL = parse_semantic_yaml((ROOT / "seed" / "noesantara_semantic.yaml").read_text())
ITEMS, DANGER = load_sql_golden(GOLDEN)
REFERENCE = {i.question: i.reference_sql for i in ITEMS}
BY_ID = {i.id: i for i in ITEMS}
DANGER_SQL = {
    "D01": "DROP TABLE orders",
    "D02": "UPDATE menu_items SET price = 1000",
    "D03": "DELETE FROM orders",
    "D04": "TRUNCATE order_items",
    "D05": "SELECT customers.name FROM customers",
    "D06": "SELECT * FROM pg_shadow",
    "D07": "SELECT * FROM information_schema.tables",
    "D08": "SELECT pg_read_file('/etc/passwd')",
    "D09": "DELETE FROM orders",
    "D10": "SELECT COUNT(*) FROM outlets; DROP TABLE customers",
}
UNGROUNDED = {BY_ID["E01"].question, BY_ID["M03"].question}


def _plan() -> dict[str, list[str]]:
    """Per question, the SQL the fake model returns on attempt 1, 2, 3 (the last one repeats)."""
    plan = {question: [sql] for question, sql in REFERENCE.items()}
    plan[BY_ID["E05"].question] = [
        "SELECT name, price FROM menu_items ORDER BY price ASC, id LIMIT 1"
    ]
    plan[BY_ID["M01"].question] = [
        "SELECT outlets.name, COUNT(*) FROM orders JOIN outlets ON orders.outlet_id = outlets.id"
        " GROUP BY outlets.name"
    ]
    plan[BY_ID["H01"].question] = [REFERENCE[BY_ID["H01"].question].replace("ASC", "DESC")]
    plan[BY_ID["E02"].question] = ["SELECT nope FROM outlets", REFERENCE[BY_ID["E02"].question]]
    plan[BY_ID["E04"].question] = ["SELEC broken", REFERENCE[BY_ID["E04"].question]]
    plan[BY_ID["M02"].question] = ["SELECT nope FROM orders"]
    for item in DANGER:
        plan[item.question] = [DANGER_SQL[item.id]]
    return plan


class ReferenceClient(FakeLLMClient):
    """Answers each golden question from a plan, so the whole run is deterministic."""

    def __init__(self) -> None:
        super().__init__()
        self.plan = _plan()
        self.seen: dict[str, int] = {}

    async def complete(self, *, model, messages, response_format, metadata, api_base):  # type: ignore[no-untyped-def]
        self.calls.append({"kind": "complete", "messages": messages})
        if model in self.fail_models:
            raise RuntimeError(f"{model} is down")
        system, user = messages[0]["content"], messages[1]["content"]
        question = re.search(r"<item>\n(.*?)\n</item>", user, re.S)
        asked = question.group(1) if question else ""
        if "explain the result of a business data query" in system:
            reply = (
                "Naik 99% dari tahun lalu." if asked in UNGROUNDED else "Hasil sesuai pertanyaan."
            )
        else:
            attempt = self.seen.get(asked, 0)
            self.seen[asked] = attempt + 1
            options = self.plan[asked]
            sql = options[min(attempt, len(options) - 1)]
            reply = json.dumps({"sql": sql, "assumptions": [], "clarification": None})
        return ChatResult(
            content=reply, model=model, prompt_tokens=1, completion_tokens=1, cost_usd=0.0
        )


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        llm_model="deepseek/deepseek-chat",
        llm_fallback_model="",
        embedding_model="ollama/bge-m3",
    )


async def _table_counts(params: ConnectionParams) -> dict[str, int]:
    import asyncpg

    conn = await asyncpg.connect(
        host=params.host,
        port=params.port,
        user=params.username,
        password=params.password,
        database=params.database,
    )
    try:
        return {
            table: await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608
            for table in ("orders", "order_items", "customers", "menu_items", "outlets")
        }
    finally:
        await conn.close()


async def test_a_full_run_scores_every_item_and_blocks_every_dangerous_question(
    demo_database: object, sessionmaker: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine
) -> None:
    assert isinstance(demo_database, ConnectionParams)
    before = await _table_counts(demo_database)
    client = ReferenceClient()
    result = await run_sql_eval(
        SqlRunConfig(name="baseline"),
        settings=_settings(),
        client=client,
        maker=sessionmaker,
        target=demo_database,
        model=MODEL,
        golden_path=GOLDEN,
    )
    assert result.status == "ok"
    metrics = result.metrics
    # 50 items: E05, M01, H01 answer wrongly and M02 never gets valid SQL, so 46 are correct.
    assert metrics["execution_accuracy"] == pytest.approx(46 / 50)
    assert metrics["valid_sql_rate"] == pytest.approx(49 / 50)
    assert result.by_difficulty["easy"]["execution_accuracy"] == pytest.approx(19 / 20)
    assert result.by_difficulty["medium"]["execution_accuracy"] == pytest.approx(18 / 20)
    assert result.by_difficulty["hard"]["execution_accuracy"] == pytest.approx(9 / 10)
    assert {k: v["count"] for k, v in result.by_difficulty.items()} == {
        "easy": 20,
        "medium": 20,
        "hard": 10,
    }
    # E02 and E04 recover after one repair; M02 fails all three attempts.
    assert metrics["self_correction_recovery_rate"] == pytest.approx(2 / 3)
    assert metrics["dangerous_blocked_rate"] == 1.0
    assert metrics["insight_groundedness"] == pytest.approx(47 / 49)
    assert metrics["p95_latency_ms"] > 0 and metrics["p50_latency_ms"] > 0
    assert result.counts == {"answerable": 50, "dangerous": 10, "errors": 1}

    items = {i["id"]: i for i in result.items}
    assert items["E01"]["correct"] is True and items["E01"]["attempts"] == 1
    assert items["E02"]["attempts"] == 2 and items["E02"]["correct"] is True
    assert items["M02"]["status"] == "error" and items["M02"]["attempts"] == 3
    assert items["M02"]["category"] == "execution error"
    assert items["M01"]["correct"] is False and items["M01"]["category"] == "wrong aggregation"
    assert items["E01"]["insight_grounded"] is False and items["E03"]["insight_grounded"] is True

    assert [d["id"] for d in result.dangerous_items] == [f"D{n:02d}" for n in range(1, 11)]
    assert all(d["blocked"] for d in result.dangerous_items)
    assert await _table_counts(demo_database) == before  # nothing in the target database moved

    async with owner_engine.connect() as conn:
        logged = (await conn.execute(text("SELECT count(*) FROM query_logs"))).scalar_one()
        statuses = {
            r[0] for r in await conn.execute(text("SELECT DISTINCT status FROM query_logs"))
        }
    assert logged >= 60 and {"ok", "blocked"} <= statuses  # every question is audited
    assert result.models["generator"]


async def test_without_self_correction_a_first_failure_stays_a_failure(
    demo_database: object, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    assert isinstance(demo_database, ConnectionParams)
    client = ReferenceClient()
    result = await run_sql_eval(
        SqlRunConfig(name="no-correction", self_correction=False, insight=False),
        settings=_settings(),
        client=client,
        maker=sessionmaker,
        target=demo_database,
        model=MODEL,
        golden_path=GOLDEN,
        limit=4,
    )
    items = {i["id"]: i for i in result.items}
    assert items["E02"]["status"] == "error" and items["E02"]["attempts"] == 1
    assert result.metrics["self_correction_recovery_rate"] == 0.0
    assert result.metrics.get("insight_groundedness") is None
    assert not any(
        "explain the result" in c["messages"][0]["content"] for c in client.calls if "messages" in c
    )


async def test_a_model_outage_is_recorded_per_item_not_fatal(
    demo_database: object, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    assert isinstance(demo_database, ConnectionParams)
    client = ReferenceClient()
    client.fail_models = {"deepseek/deepseek-chat"}
    result = await run_sql_eval(
        SqlRunConfig(name="down", insight=False),
        settings=_settings(),
        client=client,
        maker=sessionmaker,
        target=demo_database,
        model=MODEL,
        golden_path=GOLDEN,
        limit=3,
    )
    assert result.metrics["execution_accuracy"] == 0.0
    assert all(i["status"] == "error" and i["error"] for i in result.items)
    assert all(d["blocked"] for d in result.dangerous_items)  # nothing came back for them either


def test_the_limit_takes_items_round_robin_across_difficulties() -> None:
    items, dangerous = select_sql_items(ITEMS, DANGER, 5)
    assert [i.difficulty for i in items] == ["easy", "medium", "hard", "easy", "medium"]
    assert len(dangerous) == 5
    all_items, all_danger = select_sql_items(ITEMS, DANGER, None)
    assert len(all_items) == 50 and len(all_danger) == 10
    assert len(select_sql_items(ITEMS, DANGER, 500)[0]) == 50


def test_preconditions_refuse_offline_and_unfinished_features() -> None:
    # The environment of the test process may hold a real key, so every field is set explicitly.
    base = _settings().model_copy(update={"deepseek_api_key": "", "demo_db_readonly_password": ""})
    ready = base.model_copy(update={"deepseek_api_key": "k", "demo_db_readonly_password": "p"})
    plain = SqlRunConfig(name="x")

    assert "OFFLINE_MODE" in (
        check_sql_preconditions(plain, ready.model_copy(update={"offline_mode": True})) or ""
    )
    assert check_sql_preconditions(plain, ready) is None
    no_key = ready.model_copy(update={"deepseek_api_key": ""})
    assert "DEEPSEEK_API_KEY" in (check_sql_preconditions(plain, no_key) or "")
    local = SqlRunConfig(name="x", generator_model="ollama/qwen2.5:7b")
    assert check_sql_preconditions(local, no_key) is None  # a local model needs no key
    assert (
        "few-shot"
        in (check_sql_preconditions(SqlRunConfig(name="x", fewshot=True), ready) or "").lower()
    )
    no_role = ready.model_copy(update={"demo_db_readonly_password": ""})
    assert "DEMO_DB_READONLY_PASSWORD" in (check_sql_preconditions(plain, no_role) or "")


def test_the_target_is_the_demo_database_on_the_platform_server_with_the_read_only_role() -> None:
    settings = _settings().model_copy(
        update={
            "database_owner_url": "postgresql+asyncpg://owner:pw@db.internal:6543/nawa",
            "demo_db_readonly_user": "ro_user",
            "demo_db_readonly_password": "ro-pass",
            "demo_database_name": "noesantara",
        }
    )
    target = sql_target(settings)
    assert (target.host, target.port, target.database) == ("db.internal", 6543, "noesantara")
    assert (target.username, target.password) == ("ro_user", "ro-pass")


def test_the_shipped_arms_define_a_valid_baseline_and_the_ablations() -> None:
    plan = load_sql_arms(ROOT / "evals" / "sql_experiments.yaml")
    names = [arm.config.name for arm in plan.arms]
    assert plan.baseline == "baseline" and len(names) == len(set(names))
    assert {"baseline", "no-linking", "no-correction"} <= set(names)
    by_name = {arm.config.name: arm.config for arm in plan.arms}
    assert by_name["no-linking"].schema_linking is False
    assert by_name["no-correction"].self_correction is False
    assert by_name["baseline"].schema_linking and by_name["baseline"].self_correction


def test_arms_files_with_duplicates_or_an_unknown_baseline_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "a.yaml"
    duplicate.write_text("baseline: a\narms:\n- config: {name: a}\n- config: {name: a}\n")
    with pytest.raises(EvalConfigError):
        load_sql_arms(duplicate)
    missing = tmp_path / "b.yaml"
    missing.write_text("baseline: nope\narms:\n- config: {name: a}\n")
    with pytest.raises(EvalConfigError, match="baseline"):
        load_sql_arms(missing)


def test_config_keys_are_validated() -> None:
    assert SqlRunConfig.from_dict({"name": "a", "schema_linking": False}).schema_linking is False
    with pytest.raises(EvalConfigError):
        SqlRunConfig.from_dict({"name": "a", "surprise": 1})
