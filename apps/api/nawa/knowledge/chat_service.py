import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.core.db import apply_rls
from nawa.intelligence.gateway import LLMGateway, LLMUnavailableError
from nawa.knowledge import repository
from nawa.knowledge.answer import (
    Citation,
    CitationsEvent,
    DoneEvent,
    MetaEvent,
    RefusalEvent,
    TokenEvent,
    answer_question,
)
from nawa.knowledge.models import Citation as CitationRow
from nawa.knowledge.rerank import get_reranker

logger = logging.getLogger("nawa.knowledge.chat")


def format_sse(event: dict[str, object]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()


async def stream_chat(
    *,
    maker: async_sessionmaker[AsyncSession],
    gateway: LLMGateway,
    settings: Settings,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    is_admin: bool,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    question: str,
) -> AsyncIterator[bytes]:
    """SSE bytes for one question. Owns its session, so it does not depend on request teardown.

    The assistant message is stored just before `done` is sent. If the client disconnects the
    generator is closed first and nothing is stored; the user message was committed earlier.
    """
    text_parts: list[str] = []
    citations: list[Citation] = []
    refused = False
    try:
        async with maker() as session, httpx.AsyncClient() as http:
            await apply_rls(session, workspace_id=workspace_id, user_id=user_id, is_admin=is_admin)
            reranker = get_reranker(settings, http)
            async for event in answer_question(
                session,
                gateway,
                reranker,
                question,
                settings=settings,
                user_id=str(user_id),
                workspace_id=str(workspace_id),
            ):
                if isinstance(event, MetaEvent):
                    yield format_sse(
                        {
                            "type": "meta",
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "retrieved": event.retrieved,
                            "reranked": event.reranked,
                            "best_similarity": event.best_similarity,
                            "gate": event.gate,
                        }
                    )
                elif isinstance(event, TokenEvent):
                    text_parts.append(event.text)
                    yield format_sse({"type": "token", "text": event.text})
                elif isinstance(event, RefusalEvent):
                    refused = True
                    text_parts.append(event.text)
                    yield format_sse({"type": "refusal", "text": event.text})
                elif isinstance(event, CitationsEvent):
                    citations = event.citations
                    yield format_sse(
                        {
                            "type": "citations",
                            "citations": [asdict(c) for c in event.citations],
                            "invalid_markers": event.invalid_markers,
                        }
                    )
                elif isinstance(event, DoneEvent):
                    await repository.add_message(
                        session,
                        workspace_id,
                        conversation_id,
                        "assistant",
                        "".join(text_parts),
                        message_id=message_id,
                        refused=refused,
                        model=event.model,
                        prompt_name=event.prompt_name,
                        prompt_version=event.prompt_version,
                        tokens_in=event.tokens_in,
                        tokens_out=event.tokens_out,
                    )
                    session.add_all(
                        CitationRow(
                            workspace_id=workspace_id,
                            message_id=message_id,
                            chunk_id=c.chunk_id,
                            marker=c.marker,
                        )
                        for c in citations
                    )
                    await session.commit()
                    yield format_sse({"type": "done", **asdict(event)})
    except LLMUnavailableError as exc:
        logger.warning("chat failed: model unavailable (%s)", exc)
        yield format_sse(
            {
                "type": "error",
                "code": "llm_unavailable",
                "message": "The AI model is unavailable right now. Please try again shortly.",
            }
        )
    except httpx.HTTPError:
        logger.exception("chat failed: HTTP error")
        yield format_sse({"type": "error", "code": "internal_error", "message": "Chat failed."})
    except Exception:
        logger.exception("chat failed")
        yield format_sse({"type": "error", "code": "internal_error", "message": "Chat failed."})
