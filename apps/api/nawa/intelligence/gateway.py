from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

import litellm
from pydantic import BaseModel

from nawa.core.config import Settings
from nawa.core.errors import ServiceUnavailableError
from nawa.intelligence.offline import OfflineModeError, ensure_allowed, is_local_model

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class TraceInfo:
    name: str
    user_id: str | None = None
    workspace_id: str | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None


class LLMUnavailableError(ServiceUnavailableError):
    title = "LLM Unavailable"


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None,
        metadata: dict[str, Any],
        api_base: str | None,
    ) -> ChatResult: ...

    async def embed(
        self, *, model: str, inputs: list[str], api_base: str | None
    ) -> list[list[float]]: ...


class LiteLLMClient:
    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None,
        metadata: dict[str, Any],
        api_base: str | None,
    ) -> ChatResult:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            response_format=response_format,
            metadata=metadata,
            api_base=api_base,
        )
        try:
            cost = float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:  # unknown model price (e.g. a local model) costs nothing here
            cost = 0.0
        usage = response.usage
        return ChatResult(
            content=response.choices[0].message.content or "",
            model=model,
            prompt_tokens=int(usage.prompt_tokens),
            completion_tokens=int(usage.completion_tokens),
            cost_usd=cost,
        )

    async def embed(
        self, *, model: str, inputs: list[str], api_base: str | None
    ) -> list[list[float]]:
        response = await litellm.aembedding(model=model, input=inputs, api_base=api_base)
        return [list(item["embedding"]) for item in response.data]


class LLMGateway:
    """The only entry point for model calls: offline policy, fallback, tracing metadata."""

    def __init__(self, client: LLMClient, settings: Settings, model: str) -> None:
        self._client = client
        self._settings = settings
        self._model = model

    def _api_base(self, model: str) -> str | None:
        return (
            self._settings.ollama_api_base
            if model.startswith(("ollama/", "ollama_chat/"))
            else None
        )

    def _candidates(self) -> list[str]:
        models = [self._model]
        fallback = self._settings.llm_fallback_model
        if fallback and fallback != self._model:
            models.append(fallback)
        if self._settings.offline_mode:
            allowed = [m for m in models if is_local_model(m)]
            if not allowed:
                ensure_allowed(self._model, offline=True)  # raises OfflineModeError
            return allowed
        return models

    @staticmethod
    def _metadata(trace: TraceInfo) -> dict[str, Any]:
        return {
            "generation_name": trace.name,
            "trace_name": trace.name,
            "trace_user_id": trace.user_id,
            "trace_metadata": {
                "workspace_id": trace.workspace_id,
                "prompt_name": trace.prompt_name,
                "prompt_version": trace.prompt_version,
            },
        }

    async def chat(
        self,
        messages: list[ChatMessage],
        trace: TraceInfo,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult:
        payload = [{"role": m.role, "content": m.content} for m in messages]
        last_error: Exception | None = None
        for model in self._candidates():
            try:
                return await self._client.complete(
                    model=model,
                    messages=payload,
                    response_format=response_format,
                    metadata=self._metadata(trace),
                    api_base=self._api_base(model),
                )
            except OfflineModeError:
                raise
            except Exception as exc:  # provider error: try the next model
                last_error = exc
        raise LLMUnavailableError("All configured models failed") from last_error

    async def chat_json(self, messages: list[ChatMessage], schema: type[T], trace: TraceInfo) -> T:
        result = await self.chat(messages, trace, response_format={"type": "json_object"})
        return schema.model_validate_json(result.content)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._settings.embedding_model
        ensure_allowed(model, self._settings.offline_mode)
        return await self._client.embed(model=model, inputs=texts, api_base=self._api_base(model))
