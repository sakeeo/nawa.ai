from pathlib import Path

import pytest

from nawa.core.config import Settings, get_settings
from nawa.evaluation.__main__ import main
from nawa.evaluation.dataset import GoldenItem
from nawa.evaluation.runner import (
    EvalConfigError,
    RunConfig,
    check_preconditions,
    select_items,
)

JUDGE_REPLY = '{"claims": [{"text": "x", "supported": true}], "supported": true, "followed": false}'


def _settings(**kw: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        llm_fallback_model="",
        deepseek_api_key="test-key",
        **kw,  # type: ignore[arg-type]
    )


def test_select_items_is_round_robin_and_honours_the_limit() -> None:
    items = [GoldenItem(f"A{i}", "answerable", "q") for i in range(5)] + [
        GoldenItem("U0", "unanswerable", "q"),
        GoldenItem("I0", "injection", "q"),
    ]
    assert [i.id for i in select_items(items, 4)] == ["A0", "U0", "I0", "A1"]
    assert select_items(items, None) == items
    assert len(select_items(items, 100)) == 7


def test_preconditions_refuse_offline_and_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)  # may leak in from the repo .env
    assert "OFFLINE_MODE" in (
        check_preconditions(RunConfig("x"), _settings(offline_mode=True)) or ""
    )
    no_key = Settings(_env_file=None, database_url="x", redis_url="x", jwt_secret="s" * 32)
    assert "DEEPSEEK_API_KEY" in (check_preconditions(RunConfig("x"), no_key) or "")
    assert (
        check_preconditions(
            RunConfig("x", judge_enabled=False, generator_model="ollama/q"),
            Settings(
                _env_file=None,
                database_url="x",
                redis_url="x",
                jwt_secret="s" * 32,
                llm_model="ollama/q",
                embedding_model="ollama/bge-m3",
            ),
        )
        is None
    )
    assert "RERANKER" in (
        check_preconditions(
            RunConfig("x", use_rerank=True), _settings(reranker_enabled=False, reranker_url="")
        )
        or ""
    )


def test_config_loading_and_unknown_keys(tmp_path: Path) -> None:
    (tmp_path / "fast.yaml").write_text("chunker: fixed\ngenerate: false\n", encoding="utf-8")
    config = RunConfig.load("fast", tmp_path)
    assert (config.name, config.chunker, config.generate) == ("fast", "fixed", False)
    with pytest.raises(EvalConfigError):
        RunConfig.from_dict({"name": "x", "bogus": 1})
    with pytest.raises(EvalConfigError, match="not found"):
        RunConfig.load("missing", tmp_path)


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({"OFFLINE_MODE": "true", "DEEPSEEK_API_KEY": "k"}, "OFFLINE_MODE"),
        ({"OFFLINE_MODE": "false", "DEEPSEEK_API_KEY": ""}, "DEEPSEEK_API_KEY"),
    ],
)
def test_cli_exits_2_before_touching_the_database(
    env: dict[str, str],
    needle: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://nobody:x@127.0.0.1:1/none"
    )  # unreachable
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        assert main(["run", "--config", "default"]) == 2
    finally:
        get_settings.cache_clear()
    assert needle in capsys.readouterr().err
