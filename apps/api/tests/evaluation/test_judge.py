import pytest

from nawa.core.config import Settings
from nawa.evaluation.judge import JUDGE_MODEL, Judge, JudgeError
from tests.fakes import FakeLLMClient


def _judge(reply: str, **kw: object) -> tuple[Judge, FakeLLMClient]:
    fake = FakeLLMClient(reply=reply, **kw)  # type: ignore[arg-type]
    settings = Settings(
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        llm_fallback_model="ollama/qwen2.5:7b",
    )
    return Judge.create(fake, settings), fake


async def test_faithfulness_is_the_supported_fraction() -> None:
    judge, fake = _judge(
        '{"claims": [{"text": "a", "supported": true}, {"text": "b", "supported": false},'
        ' {"text": "c", "supported": true}, {"text": "d", "supported": true}]}'
    )
    assert await judge.faithfulness("q", "jawaban", ["passage"]) == 0.75
    call = fake.calls[0]
    assert call["model"] == JUDGE_MODEL  # pinned, never the fallback
    assert call["response_format"] == {"type": "json_object"}
    assert call["metadata"]["trace_metadata"]["prompt_name"] == "judge_faithfulness"


async def test_no_claims_counts_as_fully_faithful() -> None:
    judge, _ = _judge('{"claims": []}')
    assert await judge.faithfulness("q", "ok", ["p"]) == 1.0


async def test_supports_and_followed_injection() -> None:
    judge, _ = _judge('{"supported": true}')
    assert await judge.supports("a", "p") is True
    judge, _ = _judge('{"followed": true}')
    assert await judge.followed_injection("a", "p") is True


async def test_invalid_json_is_retried_once_then_reported() -> None:
    judge, fake = _judge("not json at all")
    with pytest.raises(JudgeError, match="invalid JSON twice"):
        await judge.supports("a", "p")
    assert len(fake.calls) == 2


async def test_wrong_shape_counts_as_invalid() -> None:
    judge, _ = _judge('{"unexpected": 1}')
    with pytest.raises(JudgeError):
        await judge.faithfulness("q", "a", ["p"])


async def test_model_outage_becomes_a_judge_error() -> None:
    judge, _ = _judge("{}", fail_models={JUDGE_MODEL})
    with pytest.raises(JudgeError, match="unavailable"):
        await judge.supports("a", "p")
