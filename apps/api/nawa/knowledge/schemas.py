import uuid
from datetime import datetime

from pydantic import BaseModel


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
