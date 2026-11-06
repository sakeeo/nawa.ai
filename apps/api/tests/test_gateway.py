import socket
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from nawa.core.config import Settings
from nawa.intelligence.gateway import (
    ChatMessage,
    LiteLLMClient,
    LLMGateway,
    LLMUnavailableError,
    TraceInfo,
)
from nawa.intelligence.offline import OfflineModeError
from tests.fakes import FakeLLMClient

TRACE = TraceInfo(
    name="test", user_id="u1", workspace_id="w1", prompt_name="ping", prompt_version=1
)
MESSAGES = [ChatMessage("user", "hello")]


def _settings(**overrides: Any) -> Settings:
    base = {"database_url": "x", "redis_url": "x", "jwt_secret": "s" * 32, "llm_fallback_model": ""}
    return Settings(_env_file=None, **{**base, **overrides})


async def test_chat_uses_primary_model_and_passes_trace_metadata() -> None:
    fake = FakeLLMClient()
    gw = LLMGateway(fake, _settings(), model="deepseek/deepseek-chat")
    result = await gw.chat(MESSAGES, TRACE)
    assert result.content == "pong"
    call = fake.calls[0]
    assert call["model"] == "deepseek/deepseek-chat"
    assert call["api_base"] is None
    assert call["metadata"]["generation_name"] == "test"
    assert call["metadata"]["trace_user_id"] == "u1"
    assert call["metadata"]["trace_metadata"] == {
        "workspace_id": "w1",
        "prompt_name": "ping",
        "prompt_version": 1,
    }


async def test_ollama_model_gets_local_api_base() -> None:
    fake = FakeLLMClient()
    gw = LLMGateway(fake, _settings(ollama_api_base="http://ollama:11434"), model="ollama/qwen")
    await gw.chat(MESSAGES, TRACE)
    assert fake.calls[0]["api_base"] == "http://ollama:11434"


async def test_falls_back_when_primary_fails() -> None:
    fake = FakeLLMClient(fail_models={"deepseek/deepseek-chat"})
    gw = LLMGateway(
        fake, _settings(llm_fallback_model="ollama/qwen"), model="deepseek/deepseek-chat"
    )
    result = await gw.chat(MESSAGES, TRACE)
    assert result.model == "ollama/qwen"


async def test_all_models_failing_raises_unavailable() -> None:
    fake = FakeLLMClient(fail_models={"deepseek/deepseek-chat"})
    gw = LLMGateway(fake, _settings(), model="deepseek/deepseek-chat")
    with pytest.raises(LLMUnavailableError):
        await gw.chat(MESSAGES, TRACE)


async def test_offline_skips_external_primary_and_uses_local_fallback() -> None:
    fake = FakeLLMClient()
    gw = LLMGateway(
        fake,
        _settings(offline_mode=True, llm_fallback_model="ollama/qwen"),
        model="deepseek/deepseek-chat",
    )
    result = await gw.chat(MESSAGES, TRACE)
    assert result.model == "ollama/qwen"
    assert [c["model"] for c in fake.calls] == ["ollama/qwen"]


async def test_offline_with_only_external_model_raises() -> None:
    fake = FakeLLMClient()
    gw = LLMGateway(fake, _settings(offline_mode=True), model="deepseek/deepseek-chat")
    with pytest.raises(OfflineModeError):
        await gw.chat(MESSAGES, TRACE)
    assert fake.calls == []


async def test_chat_json_validates_schema() -> None:
    class Answer(BaseModel):
        answer: str

    fake = FakeLLMClient(reply='{"answer": "42"}')
    gw = LLMGateway(fake, _settings(), model="deepseek/deepseek-chat")
    result = await gw.chat_json(MESSAGES, Answer, TRACE)
    assert result == Answer(answer="42")
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


async def test_embed_uses_local_embedding_model() -> None:
    fake = FakeLLMClient()
    gw = LLMGateway(fake, _settings(offline_mode=True), model="ollama/qwen")
    vectors = await gw.embed(["a", "b"])
    assert len(vectors) == 2
    assert fake.calls[0]["model"] == "ollama/bge-m3"


@pytest.fixture
def outbound_attempts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """Record and refuse every non-loopback socket connect."""
    attempts: list[Any] = []
    original = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost") or not isinstance(address, tuple):
            return original(self, address)
        attempts.append(address)
        raise OSError("outbound network disabled in test")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield attempts


async def test_offline_mode_makes_no_outbound_connection(outbound_attempts: list[Any]) -> None:
    gw = LLMGateway(LiteLLMClient(), _settings(offline_mode=True), model="deepseek/deepseek-chat")
    with pytest.raises(OfflineModeError):
        await gw.chat(MESSAGES, TRACE)
    assert outbound_attempts == []
