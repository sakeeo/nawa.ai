import uuid
from datetime import datetime
from typing import Literal

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
