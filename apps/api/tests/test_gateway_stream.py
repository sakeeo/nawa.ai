from typing import Any

import pytest

from nawa.core.config import Settings
from nawa.intelligence.gateway import (
    ChatMessage,
    DoneEvent,
    LLMGateway,
    LLMUnavailableError,
    StreamEvent,
    TokenEvent,
    TraceInfo,
)
from nawa.intelligence.offline import OfflineModeError
from tests.fakes import FakeLLMClient

TRACE = TraceInfo(
    name="answer", user_id="u1", workspace_id="w1", prompt_name="answer", prompt_version=1
)
MESSAGES = [ChatMessage("user", "halo")]


def _settings(**overrides: Any) -> Settings:
    base = {"database_url": "x", "redis_url": "x", "jwt_secret": "s" * 32, "llm_fallback_model": ""}
    return Settings(_env_file=None, **{**base, **overrides})


async def collect(gateway: LLMGateway) -> list[StreamEvent]:
    return [event async for event in gateway.chat_stream(MESSAGES, TRACE)]


async def test_tokens_arrive_in_order_then_done_with_usage() -> None:
    fake = FakeLLMClient(reply="satu dua tiga")
    events = await collect(LLMGateway(fake, _settings(), model="deepseek/deepseek-chat"))
    assert [e.text for e in events if isinstance(e, TokenEvent)] == ["satu ", "dua ", "tiga"]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.model == "deepseek/deepseek-chat"
    assert done.prompt_tokens == 3 and done.completion_tokens == 3


async def test_trace_metadata_carries_prompt_name_and_version() -> None:
    fake = FakeLLMClient()
    await collect(LLMGateway(fake, _settings(), model="deepseek/deepseek-chat"))
    metadata = fake.calls[0]["metadata"]
    assert metadata["generation_name"] == "answer"
    assert metadata["trace_metadata"]["prompt_name"] == "answer"
    assert metadata["trace_metadata"]["prompt_version"] == 1


async def test_failure_before_first_token_falls_back() -> None:
    fake = FakeLLMClient(reply="ok", fail_models={"deepseek/deepseek-chat"})
    gateway = LLMGateway(
        fake, _settings(llm_fallback_model="openai/gpt-4o-mini"), model="deepseek/deepseek-chat"
    )
    events = await collect(gateway)
    assert [c["model"] for c in fake.calls] == ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]
    done = events[-1]
    assert isinstance(done, DoneEvent) and done.model == "openai/gpt-4o-mini"


async def test_failure_after_first_token_does_not_switch_model() -> None:
    fake = FakeLLMClient(reply="a b c d", fail_after_tokens=2)
    gateway = LLMGateway(
        fake, _settings(llm_fallback_model="openai/gpt-4o-mini"), model="deepseek/deepseek-chat"
    )
    seen: list[str] = []
    with pytest.raises(LLMUnavailableError):
        async for event in gateway.chat_stream(MESSAGES, TRACE):
            if isinstance(event, TokenEvent):
                seen.append(event.text)
    assert seen == ["a ", "b "]
    assert [c["model"] for c in fake.calls] == ["deepseek/deepseek-chat"]


async def test_all_models_failing_raises_unavailable() -> None:
    fake = FakeLLMClient(fail_models={"deepseek/deepseek-chat"})
    with pytest.raises(LLMUnavailableError):
        await collect(LLMGateway(fake, _settings(), model="deepseek/deepseek-chat"))


async def test_offline_mode_blocks_external_model_before_any_call() -> None:
    fake = FakeLLMClient()
    gateway = LLMGateway(fake, _settings(offline_mode=True), model="deepseek/deepseek-chat")
    with pytest.raises(OfflineModeError):
        await collect(gateway)
    assert fake.calls == []


async def test_offline_mode_allows_local_model_with_api_base() -> None:
    fake = FakeLLMClient()
    gateway = LLMGateway(
        fake, _settings(offline_mode=True, ollama_api_base="http://ollama:11434"), model="ollama/q"
    )
    await collect(gateway)
    assert fake.calls[0]["api_base"] == "http://ollama:11434"


async def test_early_close_releases_the_underlying_stream() -> None:
    fake = FakeLLMClient(reply="a b c d e")
    gateway = LLMGateway(fake, _settings(), model="deepseek/deepseek-chat")
    stream = gateway.chat_stream(MESSAGES, TRACE)
    first = await anext(stream)
    assert isinstance(first, TokenEvent)
    await stream.aclose()
    assert fake.open_streams == 0
