import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime: str
    size_bytes: int
    status: str
    error: str | None
    page_count: int | None
    created_at: datetime


class ChunkOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page: int | None
    section_path: str | None
    heading: str | None
    text: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class FeedbackIn(BaseModel):
    value: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)


class CitationOut(BaseModel):
    marker: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page: int | None
    section_path: str | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    refused: bool
    created_at: datetime
    citations: list[CitationOut]
    feedback: int | None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    last_message_at: datetime


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str
    messages: list[MessageOut]
