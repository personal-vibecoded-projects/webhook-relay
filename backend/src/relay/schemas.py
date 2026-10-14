from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
)


def normalize_username(value):
    return value.strip().lower() if isinstance(value, str) else value


Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=r"^[a-z][a-z0-9_-]{2,31}$",
        min_length=3,
        max_length=32,
    ),
    BeforeValidator(normalize_username),
]
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
Role = Literal["admin", "member", "viewer"]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Username
    password: SecretStr = Field(min_length=12, max_length=128)


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: Annotated[
        str,
        StringConstraints(
            pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", min_length=3, max_length=63
        ),
    ]
    name: Name


class WorkspaceRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name


class WorkspaceView(BaseModel):
    id: UUID
    slug: str
    name: str
    owner_user_id: UUID
    role: Literal["owner", "admin", "member", "viewer"]
    created_at: datetime


class MemberView(UserView):
    role: Literal["owner", "admin", "member", "viewer"]


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Username
    role: Role = "member"


class InviteView(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_name: str
    username: str
    role: Role
    status: Literal["pending", "accepted", "revoked", "expired"]
    expires_at: datetime
    created_at: datetime


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class OwnershipTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor_id: UUID | None
    action: str
    details: dict
    created_at: datetime


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
