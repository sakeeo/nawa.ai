import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]


class DataSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr = Field(min_length=1, max_length=512)
    ssl_mode: SslMode = "prefer"


class DataSourceRead(BaseModel):
    """Never carries the password, encrypted or not."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    host: str
    port: int
    database: str
    username: str
    ssl_mode: str
    status: str
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ConnectionReportRead(BaseModel):
    ok: bool
    server_version: str | None
    problems: list[str]


class DataSourceCreated(BaseModel):
    source: DataSourceRead
    report: ConnectionReportRead


class DiscoveryRead(BaseModel):
    tables: int
    columns: int
    sampled_columns: int
    has_semantic_model: bool
    created_at: datetime


class SemanticModelRead(BaseModel):
    version: int
    yaml: str
    created_at: datetime


class SemanticModelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yaml: str = Field(min_length=1, max_length=200_000)


class SemanticDraftRead(BaseModel):
    yaml: str


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_source_id: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)


class ChartRead(BaseModel):
    kind: Literal["kpi", "bar", "line", "table"]
    x: str | None
    y: list[str]
    title: str


class AskResponse(BaseModel):
    query_id: uuid.UUID
    status: Literal["ok", "blocked", "error", "clarification"]
    sql: str | None
    assumptions: list[str]
    clarification: str | None
    blocked_reason: str | None
    error: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    chart: ChartRead | None
    attempts: int
    linked_tables: list[str]


class InsightRead(BaseModel):
    text: str
    grounded: bool
    cached: bool


class QueryFeedbackWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Literal[-1, 1]


class QueryLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    question: str
    sql: str | None
    status: str
    blocked_reason: str | None
    attempts: int
    row_count: int | None
    duration_ms: int
    insight: str | None
    insight_grounded: bool | None
    feedback: int | None
    created_at: datetime
