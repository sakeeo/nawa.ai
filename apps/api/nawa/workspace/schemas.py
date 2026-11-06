import uuid

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
