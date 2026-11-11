import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from noesantara_seed.load import TABLES

from nawa.core.config import Settings
from nawa.data import linking
from nawa.data.discovery import ColumnInfo, ForeignKey, TableInfo
from nawa.data.linking import build_link_index, lexical_hits, link_schema
from nawa.data.semantic import (
    SemanticColumn,
    SemanticModel,
    SemanticTable,
    parse_semantic_yaml,
)
from nawa.intelligence.gateway import LLMGateway
from tests.fakes import FakeLLMClient

DEMO_YAML = Path(__file__).resolve().parents[4] / "seed" / "noesantara_semantic.yaml"


def _settings() -> Settings:
    return Settings(_env_file=None, database_url="x", redis_url="x", jwt_secret="s" * 32)  # type: ignore[call-arg]


def _gateway(client: FakeLLMClient | None = None) -> LLMGateway:
    return LLMGateway(client or FakeLLMClient(), _settings(), "deepseek/deepseek-chat")


class ZeroEmbedder(FakeLLMClient):
    async def embed(self, *, model: str, inputs: list[str], api_base: str | None) -> Any:
        self.calls.append({"kind": "embed", "inputs": inputs})
        return [[0.0] * 1024 for _ in inputs]


class MeaningEmbedder(FakeLLMClient):
    """Texts that share a concept group point the same way, whatever words they use."""

    GROUPS = [{"revenue", "penghasilan", "pemasukan"}, {"stock", "stok", "persediaan"}]

    async def embed(self, *, model: str, inputs: list[str], api_base: str | None) -> Any:
        self.calls.append({"kind": "embed", "inputs": inputs})
        out = []
        for text in inputs:
            words = set(re.findall(r"[^\W_]+", text.lower()))
            vector = [0.001] * 1024
            for index, group in enumerate(self.GROUPS):
                vector[index] += len(words & group)
            out.append(vector)
        return out


def _demo_model() -> SemanticModel:
    return parse_semantic_yaml(DEMO_YAML.read_text(encoding="utf-8"))


def _demo_schema() -> list[TableInfo]:
    return [
        TableInfo(table, [ColumnInfo(c, "text", True) for c in columns], [], [], row_estimate=index)
        for index, (table, columns) in enumerate(TABLES)
    ]


async def _link(
    question: str,
    *,
    client: FakeLLMClient | None = None,
    model: SemanticModel | None = None,
    schema: list[TableInfo] | None = None,
    top_tables: int = 4,
    key: tuple[uuid.UUID, int] | None = None,
) -> linking.LinkedSchema:
    gateway = _gateway(client)
    index = await build_link_index(gateway, model or _demo_model(), key or (uuid.uuid4(), 1))
    return await link_schema(
        index, gateway, question, schema or _demo_schema(), top_tables=top_tables
    )


# ---------------------------------------------------------------- lexical


def test_lexical_hits_match_whole_words_and_phrases_not_substrings() -> None:
    terms = {"t:orders": ["orders", "pesanan"], "t:rate": ["rata rata"], "t:cat": ["cat"]}
    assert set(lexical_hits("Berapa pesanan hari ini?", terms)) == {"t:orders"}
    assert set(lexical_hits("rata-rata per hari", terms)) == {"t:rate"}
    assert lexical_hits("category list", terms) == {}  # 'cat' is not a word of the question
    assert set(lexical_hits("jumlah ORDER", terms)) == {"t:orders"}  # case and plural
    assert lexical_hits("", terms) == {}


def test_lexical_hits_ignore_terms_made_of_one_letter_tokens() -> None:
    assert lexical_hits("a b c", {"x": ["a"], "y": ["b c"]}) == {}


def test_lexical_hits_strip_the_indonesian_possessive() -> None:
    assert set(lexical_hits("stoknya habis", {"x": ["stok"]})) == {"x"}


def test_lexical_hits_keep_unicode_letters() -> None:
    assert set(lexical_hits("bagaimana kopi jahé", {"x": ["jahé"]})) == {"x"}


# ---------------------------------------------------------------- selection


async def test_revenue_per_outlet_pulls_the_metric_tables_and_the_bridge() -> None:
    linked = await _link("omzet per outlet")
    assert {"orders", "order_items", "outlets"} <= set(linked.tables)
    assert "revenue" in linked.metrics and "outlet" in linked.dimensions
    assert "recipes" not in linked.tables and "ingredients" not in linked.tables


async def test_most_profitable_menu_selects_menu_and_sales_tables() -> None:
    linked = await _link("menu paling untung")
    assert {"menu_items", "order_items"} <= set(linked.tables)
    assert "gross_profit" in linked.metrics
    assert "recipes" not in linked.tables


async def test_a_pure_sales_question_does_not_drag_in_recipes() -> None:
    linked = await _link("total penjualan bulan ini")
    assert "recipes" not in linked.tables and "ingredient_stock" not in linked.tables
    assert "revenue" in linked.metrics


async def test_bridge_tables_connect_selected_tables_over_foreign_keys() -> None:
    schema = [
        TableInfo("outlets", [ColumnInfo("id", "int", False)], ["id"], [], 3),
        TableInfo(
            "orders",
            [ColumnInfo("id", "int", False), ColumnInfo("outlet_id", "int", False)],
            ["id"],
            [ForeignKey(["outlet_id"], "outlets", ["id"])],
            40,
        ),
        TableInfo(
            "order_items",
            [ColumnInfo("id", "int", False), ColumnInfo("order_id", "int", False)],
            ["id"],
            [ForeignKey(["order_id"], "orders", ["id"])],
            90,
        ),
        TableInfo(
            "menu_items",
            [ColumnInfo("id", "int", False), ColumnInfo("order_item_id", "int", False)],
            ["id"],
            [ForeignKey(["order_item_id"], "order_items", ["id"])],
            9,
        ),
        TableInfo("recipes", [ColumnInfo("id", "int", False)], ["id"], [], 9),
    ]
    model = SemanticModel(
        tables=[
            SemanticTable(
                name=t.name,
                synonyms=[t.name.split("_")[0]],
                columns=[SemanticColumn(name=c.name) for c in t.columns],
            )
            for t in schema
        ]
    )
    linked = await _link("menu per outlet", model=model, schema=schema, top_tables=2)
    assert set(linked.tables) == {"outlets", "orders", "order_items", "menu_items"}
    assert "recipes" not in linked.tables


async def test_many_hits_are_capped_at_top_tables_plus_bridges() -> None:
    leaves = [f"leaf{i}" for i in range(9)]
    schema = [TableInfo("hub", [ColumnInfo("id", "int", False)], ["id"], [], 1)] + [
        TableInfo(
            leaf,
            [ColumnInfo("id", "int", False), ColumnInfo("hub_id", "int", False)],
            ["id"],
            [ForeignKey(["hub_id"], "hub", ["id"])],
            1,
        )
        for leaf in leaves
    ]
    model = SemanticModel(
        tables=[
            SemanticTable(
                name=t.name,
                synonyms=[f"topic{t.name}"],
                columns=[SemanticColumn(name=c.name) for c in t.columns],
            )
            for t in schema
        ]
    )
    question = "topicleaf1 topicleaf3 topicleaf5 topicleaf7 topicleaf8"
    linked = await _link(question, model=model, schema=schema, top_tables=4)
    chosen = [t for t in linked.tables if t != "hub"]
    assert len(chosen) == 4 and "hub" in linked.tables
    assert chosen == ["leaf1", "leaf3", "leaf5", "leaf7"]  # ties broken by name, deterministic


async def test_a_small_schema_returns_every_table() -> None:
    model = _demo_model()
    small = [t for t in _demo_schema() if t.name in {"outlets", "orders", "customers"}]
    model = SemanticModel(
        tables=[t for t in model.tables if t.name in {"outlets", "orders", "customers"}]
    )
    linked = await _link("anything at all", model=model, schema=small, top_tables=4)
    assert set(linked.tables) == {"outlets", "orders", "customers"}


async def test_a_question_without_any_hit_still_returns_tables() -> None:
    linked = await _link("zzz qqq www")
    assert 1 <= len(linked.tables) <= 8


async def test_tables_missing_from_the_semantic_model_never_appear() -> None:
    model = _demo_model()
    trimmed = SemanticModel(
        tables=[t for t in model.tables if t.name != "customers"],
        metrics=model.metrics,
        dimensions=model.dimensions,
        joins=[j for j in model.joins if "customers" not in j.on],
        time_anchor=model.time_anchor,
    )
    linked = await _link("jumlah pelanggan per outlet", model=trimmed)
    assert "customers" not in linked.tables


# ---------------------------------------------------------------- embeddings


async def test_all_zero_embeddings_fall_back_to_lexical_linking() -> None:
    client = ZeroEmbedder()
    gateway = _gateway(client)
    index = await build_link_index(gateway, _demo_model(), (uuid.uuid4(), 1))
    assert index.semantic is False
    linked = await link_schema(index, gateway, "omzet per outlet", _demo_schema())
    assert {"order_items", "outlets"} <= set(linked.tables)
    embeds = [c for c in client.calls if c["kind"] == "embed"]
    assert len(embeds) == 1  # only the index; the question is not embedded without semantics


async def test_an_embedding_failure_degrades_to_lexical_linking_and_is_not_cached() -> None:
    class Broken(FakeLLMClient):
        async def embed(self, *, model: str, inputs: list[str], api_base: str | None) -> Any:
            raise RuntimeError("embedding service is down")

    key = (uuid.uuid4(), 1)
    index = await build_link_index(_gateway(Broken()), _demo_model(), key)
    assert index.semantic is False
    healthy = FakeLLMClient()
    again = await build_link_index(_gateway(healthy), _demo_model(), key)
    assert again.semantic is True
    assert len([c for c in healthy.calls if c["kind"] == "embed"]) == 1


async def test_meaning_can_link_a_table_without_sharing_a_word() -> None:
    client = MeaningEmbedder()
    model = parse_semantic_yaml(
        """
tables:
  outlets: {columns: [id, name]}
  order_items: {columns: [id, quantity, unit_price]}
  expenses: {columns: [id, amount]}
metrics:
  revenue:
    description: revenue of all sales
    sql: SUM(order_items.quantity * order_items.unit_price)
"""
    )
    schema = [
        TableInfo(
            t.name, [ColumnInfo(c.name, "int", False) for c in t.columns], [], [], row_estimate=1
        )
        for t in model.tables
    ]
    linked = await _link(
        "berapa penghasilan kita", client=client, model=model, schema=schema, top_tables=1
    )
    assert linked.tables == ["order_items"]
    assert "revenue" in linked.metrics


async def test_the_index_is_cached_per_model_key() -> None:
    client = FakeLLMClient()
    gateway = _gateway(client)
    key = (uuid.uuid4(), 3)
    first = await build_link_index(gateway, _demo_model(), key)
    second = await build_link_index(gateway, _demo_model(), key)
    assert first is second
    assert len([c for c in client.calls if c["kind"] == "embed"]) == 1
    other = await build_link_index(gateway, _demo_model(), (key[0], 4))
    assert other is not first


async def test_results_are_deterministic() -> None:
    key = (uuid.uuid4(), 1)
    runs = [await _link("laba kotor per kategori menu", key=key) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


@pytest.mark.parametrize("question", ["", "   ", "?!"])
async def test_empty_or_punctuation_only_questions_do_not_crash(question: str) -> None:
    linked = await _link(question)
    assert linked.tables


async def test_a_sample_value_in_the_question_links_its_table() -> None:
    schema = _demo_schema()
    outlets = next(t for t in schema if t.name == "outlets")
    sampled = [
        ColumnInfo("id", "integer", False),
        ColumnInfo("name", "text", False, ["Bandung", "Medan"]),
        ColumnInfo("city", "text", False, ["Bandung", "Medan"]),
    ]
    schema = [
        TableInfo(t.name, sampled, [], [], t.row_estimate) if t is outlets else t for t in schema
    ]
    linked = await _link("jumlah porsi terjual di Bandung", schema=schema)
    assert "outlets" in linked.tables and "order_items" in linked.tables


async def test_samples_of_omitted_columns_are_never_used_for_linking() -> None:
    schema = _demo_schema()
    customers = next(t for t in schema if t.name == "customers")
    leaky = [
        ColumnInfo("id", "integer", False),
        ColumnInfo("name", "text", False, ["Budi Santoso"]),  # customers.name is not allowlisted
        ColumnInfo("outlet_id", "integer", False),
    ]
    schema = [
        TableInfo(t.name, leaky, [], [], t.row_estimate) if t is customers else t for t in schema
    ]
    linked = await _link("apa yang dibeli Budi Santoso", schema=schema)
    assert "customers" not in linked.tables


async def test_indonesian_questions_from_the_demo_story_reach_the_right_tables() -> None:
    for question, expected in [
        ("Menu apa yang paling menguntungkan?", {"menu_items", "order_items"}),
        ("Outlet mana yang memiliki performa terendah?", {"outlets", "orders", "order_items"}),
        ("Bahan baku apa yang stoknya di bawah minimum?", {"ingredients", "ingredient_stock"}),
    ]:
        linked = await _link(question)
        assert expected <= set(linked.tables), question
