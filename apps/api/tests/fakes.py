import re
from collections.abc import AsyncGenerator
from typing import Any

from nawa.intelligence.gateway import ChatResult, StreamUsage


class FakeLLMClient:
    """Deterministic stand-in for LiteLLM. Tests never call a real model."""

    def __init__(
        self,
        reply: str = "pong",
        fail_models: set[str] | None = None,
        fail_after_tokens: int | None = None,
    ) -> None:
        self.reply = reply
        self.fail_models = fail_models or set()
        self.fail_after_tokens = fail_after_tokens
        self.calls: list[dict[str, Any]] = []
        self.open_streams = 0

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        metadata: dict[str, Any],
        api_base: str | None,
    ) -> AsyncGenerator[str | StreamUsage, None]:
        self.calls.append(
            {
                "kind": "stream",
                "model": model,
                "messages": messages,
                "metadata": metadata,
                "api_base": api_base,
            }
        )
        if model in self.fail_models:
            raise RuntimeError(f"{model} is down")
        self.open_streams += 1
        try:
            tokens = re.findall(r"\S+\s*", self.reply)
            for index, token in enumerate(tokens):
                if self.fail_after_tokens is not None and index >= self.fail_after_tokens:
                    raise RuntimeError("stream broke")
                yield token
            yield StreamUsage(prompt_tokens=3, completion_tokens=len(tokens), cost_usd=0.0)
        finally:
            self.open_streams -= 1

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None,
        metadata: dict[str, Any],
        api_base: str | None,
    ) -> ChatResult:
        self.calls.append(
            {
                "kind": "complete",
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "metadata": metadata,
                "api_base": api_base,
            }
        )
        if model in self.fail_models:
            raise RuntimeError(f"{model} is down")
        return ChatResult(
            content=self.reply, model=model, prompt_tokens=3, completion_tokens=1, cost_usd=0.0
        )

    async def embed(
        self, *, model: str, inputs: list[str], api_base: str | None
    ) -> list[list[float]]:
        self.calls.append({"kind": "embed", "model": model, "inputs": inputs, "api_base": api_base})
        return [[0.0, 0.0, 0.0, 0.0] for _ in inputs]
