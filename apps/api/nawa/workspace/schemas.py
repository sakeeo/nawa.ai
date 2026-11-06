import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: uuid.UUID
    role: str


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(max_length=50, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str


class MemberUpdate(BaseModel):
    role: Literal["manager", "member", "viewer"]


class InviteCreate(BaseModel):
    email: EmailStr
    role: Literal["manager", "member", "viewer"]


class InviteCreated(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    token: str
    accept_path: str


class InvitePreview(BaseModel):
    email: str
    workspace_name: str
    role: str


class InviteAccept(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=128)


class InviteAccepted(BaseModel):
    email: str
    workspace_id: uuid.UUID
    role: str
