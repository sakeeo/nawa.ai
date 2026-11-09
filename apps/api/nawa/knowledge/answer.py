import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.config import Settings
from nawa.intelligence.gateway import ChatMessage, LLMGateway, TraceInfo
from nawa.intelligence.gateway import DoneEvent as GatewayDone
from nawa.intelligence.gateway import TokenEvent as GatewayToken
from nawa.intelligence.prompts import PromptRegistry
from nawa.knowledge.context import ContextPassage, assemble_context
from nawa.knowledge.gate import GateDecision, relevance_gate
from nawa.knowledge.guardrails import Passage, detect_injection, sanitize_question, wrap_untrusted
from nawa.knowledge.rerank import Reranker, rerank_with_fallback
from nawa.knowledge.retrieval import Candidate, Strategy, retrieve

logger = logging.getLogger("nawa.knowledge.answer")

_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

RetrieveFn = Callable[..., Awaitable[list[Candidate]]]


@dataclass(frozen=True)
class Citation:
    marker: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page: int | None
    section_path: str


@dataclass(frozen=True)
class MetaEvent:
    retrieved: int
    reranked: bool
    best_similarity: float | None
    gate: str
    injection_flags: dict[int, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class RefusalEvent:
    text: str


@dataclass(frozen=True)
class CitationsEvent:
    citations: list[Citation]
    invalid_markers: list[int]


@dataclass(frozen=True)
class DoneEvent:
    model: str | None
    prompt_name: str
    prompt_version: int
    tokens_in: int
    tokens_out: int
    ttft_ms: float
    total_ms: float
    refused: bool


AnswerEvent = MetaEvent | TokenEvent | RefusalEvent | CitationsEvent | DoneEvent


def extract_citations(
    answer_text: str, context: list[ContextPassage]
) -> tuple[list[Citation], list[int]]:
    """Citations for `[n]` / `[n, m]` markers that exist in the context, plus invalid markers."""
    by_marker = {p.marker: p.candidate for p in context}
    citations: list[Citation] = []
    invalid: list[int] = []
    seen: set[int] = set()
    for match in _MARKER.finditer(answer_text):
        for raw in match.group(1).split(","):
            marker = int(raw)
            if marker in seen:
                continue
            seen.add(marker)
            candidate = by_marker.get(marker)
            if candidate is None:
                invalid.append(marker)
                continue
            citations.append(
                Citation(
                    marker=marker,
                    chunk_id=candidate.chunk_id,
                    document_id=candidate.document_id,
                    filename=candidate.filename,
                    page=candidate.page,
                    section_path=candidate.section_path,
                )
            )
    return citations, invalid


def strip_invalid_markers(text: str, invalid: list[int]) -> str:
    """Remove markers that point to passages that were never provided."""
    if not invalid:
        return text
    bad = set(invalid)

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in match.group(1).split(",")]
        kept = [n for n in numbers if n not in bad]
        return f"[{', '.join(map(str, kept))}]" if kept else ""

    return _MARKER.sub(replace, text)


def _elapsed_ms(start: float) -> float:
    return max((time.perf_counter() - start) * 1000, 0.0)


async def answer_question(
    session: AsyncSession,
    gateway: LLMGateway,
    reranker: Reranker,
    question: str,
    *,
    settings: Settings,
    strategy: Strategy = "hybrid",
    use_rerank: bool = True,
    user_id: str | None = None,
    workspace_id: str | None = None,
    registry: PromptRegistry | None = None,
    retrieve_fn: RetrieveFn = retrieve,
) -> AsyncIterator[AnswerEvent]:
    """Retrieve, gate, rerank, assemble context, then stream an answer with citations."""
    start = time.perf_counter()
    prompts = registry or PromptRegistry()
    answer_prompt = prompts.get("answer")
    clean = sanitize_question(question)

    fused = await retrieve_fn(session, gateway, clean, settings=settings, strategy=strategy)
    gate: GateDecision = relevance_gate(fused, min_similarity=settings.rag_min_similarity)
    if not gate.answerable:
        refuse_prompt = prompts.get("refuse")
        yield MetaEvent(len(fused), False, gate.best_similarity, gate.reason)
        yield RefusalEvent(refuse_prompt.render())
        elapsed = _elapsed_ms(start)
        yield DoneEvent(
            None, refuse_prompt.name, refuse_prompt.version, 0, 0, elapsed, elapsed, True
        )
        return

    reranked = False
    ordered = fused
    if use_rerank:
        ordered, reranked = await rerank_with_fallback(
            reranker, clean, fused, top_n=settings.rag_rerank_top_n, log=logger
        )
    context = assemble_context(
        ordered, max_tokens=settings.rag_context_max_tokens, final_k=settings.rag_context_k
    )
    flags = {p.marker: labels for p in context if (labels := detect_injection(p.candidate.text))}
    if flags:
        logger.warning("injection patterns in retrieved passages: markers %s", sorted(flags))
    yield MetaEvent(len(fused), reranked, gate.best_similarity, gate.reason, flags)

    wrapped = wrap_untrusted(
        [
            Passage(p.marker, p.candidate.filename, p.candidate.page, p.candidate.text)
            for p in context
        ]
    )
    messages = [
        ChatMessage("system", answer_prompt.render()),
        ChatMessage("user", f"{wrapped}\n\nPertanyaan: {clean}"),
    ]
    trace = TraceInfo(
        name="answer",
        user_id=user_id,
        workspace_id=workspace_id,
        prompt_name=answer_prompt.name,
        prompt_version=answer_prompt.version,
    )
    parts: list[str] = []
    ttft: float | None = None
    done: GatewayDone | None = None
    async for event in gateway.chat_stream(messages, trace):
        if isinstance(event, GatewayToken):
            if ttft is None:
                ttft = _elapsed_ms(start)
            parts.append(event.text)
            yield TokenEvent(event.text)
        elif isinstance(event, GatewayDone):
            done = event
    citations, invalid = extract_citations("".join(parts), context)
    if not citations:
        logger.info("answer carried no valid citation markers")
    yield CitationsEvent(citations, invalid)
    total = _elapsed_ms(start)
    yield DoneEvent(
        done.model if done else None,
        answer_prompt.name,
        answer_prompt.version,
        done.prompt_tokens if done else 0,
        done.completion_tokens if done else 0,
        ttft if ttft is not None else total,
        total,
        False,
    )
