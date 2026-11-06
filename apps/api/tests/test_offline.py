import pytest

from nawa.intelligence.offline import OfflineModeError, ensure_allowed, is_local_model


@pytest.mark.parametrize(
    ("model", "local"),
    [
        ("ollama/qwen2.5:7b", True),
        ("ollama_chat/llama3.1", True),
        ("hosted_vllm/qwen", True),
        ("deepseek/deepseek-chat", False),
        ("gpt-4o", False),
        ("anthropic/claude", False),
    ],
)
def test_is_local_model(model: str, local: bool) -> None:
    assert is_local_model(model) is local


def test_external_model_blocked_when_offline() -> None:
    with pytest.raises(OfflineModeError, match="deepseek/deepseek-chat"):
        ensure_allowed("deepseek/deepseek-chat", offline=True)


def test_external_model_allowed_when_online() -> None:
    ensure_allowed("deepseek/deepseek-chat", offline=False)


def test_local_model_allowed_when_offline() -> None:
    ensure_allowed("ollama/qwen2.5:7b", offline=True)
