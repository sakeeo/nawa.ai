import logging
from typing import TypeVar

from pydantic import BaseModel

from nawa.core.config import Settings
from nawa.intelligence.gateway import (
    ChatMessage,
    LLMClient,
    LLMGateway,
    LLMUnavailableError,
    TraceInfo,
)
from nawa.intelligence.prompts import PromptRegistry

logger = logging.getLogger("nawa.evaluation.judge")

JUDGE_MODEL = "deepseek/deepseek-chat"
T = TypeVar("T", bound=BaseModel)


class JudgeError(RuntimeError):
    """The judge could not produce a usable verdict; the item is excluded and counted."""


class ClaimVerdict(BaseModel):
    text: str
    supported: bool


class ClaimsOut(BaseModel):
    claims: list[ClaimVerdict]


class SupportOut(BaseModel):
    supported: bool


class FollowedOut(BaseModel):
    followed: bool


def _numbered(passages: list[str]) -> str:
    return "\n\n".join(f"[{i}] {text}" for i, text in enumerate(passages, start=1))


class Judge:
    """LLM-as-judge on a second gateway pinned to DeepSeek (spec D3, P12). Synthetic data only."""

    def __init__(self, gateway: LLMGateway, registry: PromptRegistry | None = None) -> None:
        self._gateway = gateway
        self._prompts = registry or PromptRegistry()

    @classmethod
    def create(cls, client: LLMClient, settings: Settings) -> "Judge":
        pinned = settings.model_copy(update={"llm_fallback_model": ""})
        return cls(LLMGateway(client, pinned, model=JUDGE_MODEL))

    async def _ask(self, prompt_name: str, user: str, schema: type[T]) -> T:
        prompt = self._prompts.get(prompt_name)
        messages = [ChatMessage("system", prompt.render()), ChatMessage("user", user)]
        trace = TraceInfo(
            name=f"eval-{prompt.name}", prompt_name=prompt.name, prompt_version=prompt.version
        )
        last: Exception | None = None
        for attempt in (1, 2):  # one retry on invalid JSON
            try:
                return await self._gateway.chat_json(messages, schema, trace)
            except LLMUnavailableError as exc:
                raise JudgeError(f"judge model unavailable: {exc}") from exc
            except ValueError as exc:  # invalid JSON or wrong shape
                last = exc
                logger.warning("judge returned invalid JSON (attempt %d)", attempt)
        raise JudgeError("judge returned invalid JSON twice") from last

    async def faithfulness(self, question: str, answer: str, passages: list[str]) -> float:
        """Fraction of the answer's claims that the passages support (1.0 when it makes none)."""
        user = f"PASSAGES:\n{_numbered(passages)}\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}"
        out = await self._ask("judge_faithfulness", user, ClaimsOut)
        if not out.claims:
            return 1.0
        return sum(1 for c in out.claims if c.supported) / len(out.claims)

    async def supports(self, answer: str, passage: str) -> bool:
        user = f"PASSAGE:\n{passage}\n\nANSWER:\n{answer}"
        return (await self._ask("judge_support", user, SupportOut)).supported

    async def followed_injection(self, answer: str, passage: str) -> bool:
        user = f"PASSAGE:\n{passage}\n\nANSWER:\n{answer}"
        return (await self._ask("judge_injection", user, FollowedOut)).followed
