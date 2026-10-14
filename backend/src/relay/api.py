from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete

from relay import access, auth
from relay.dependencies import DB, Actor
from relay.models import AuthSession
from relay.schemas import (
    AuditView,
    Credentials,
    InviteCreate,
    InviteView,
    MemberView,
    OwnershipTransfer,
    Page,
    RoleChange,
    UserView,
    WorkspaceCreate,
    WorkspaceRename,
    WorkspaceView,
)
from relay.security import COOKIE, digest, require_origin

router = APIRouter(prefix="/api", dependencies=[Depends(require_origin)])
Cursor = Annotated[str | None, Query(max_length=512)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.post("/auth/register", response_model=UserView, status_code=201)
def register(body: Credentials, request: Request, response: Response, session: DB):
    return auth.register(session, body, request, response)


@router.post("/auth/login", response_model=UserView)
def login(body: Credentials, request: Request, response: Response, session: DB):
    return auth.login(session, body, request, response)


@router.get("/auth/me", response_model=UserView)
def me(actor: Actor):
    return actor


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: DB, actor: Actor):
    session.execute(
        delete(AuthSession).where(
            AuthSession.token_hash == digest(request.cookies[COOKIE])
        )
    )
    response.delete_cookie(
        COOKIE,
        path="/api",
        httponly=True,
        secure=not request.app.state.security.allow_http_cookie,
        samesite="lax",
    )


@router.post("/workspaces", response_model=WorkspaceView, status_code=201)
def create_workspace(body: WorkspaceCreate, session: DB, actor: Actor):
    return access.create_workspace(session, actor, body)


@router.get("/workspaces", response_model=Page[WorkspaceView])
def workspaces(session: DB, actor: Actor, cursor: Cursor = None, limit: Limit = 25):
    return access.list_workspaces(session, actor, cursor, limit)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceView)
def workspace(workspace_id: UUID, session: DB, actor: Actor):
    return access.workspace_view(*access.workspace_for(session, workspace_id, actor))


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceView)
def rename(workspace_id: UUID, body: WorkspaceRename, session: DB, actor: Actor):
    return access.rename_workspace(session, actor, workspace_id, body)


@router.get("/workspaces/{workspace_id}/members", response_model=Page[MemberView])
def members(
    workspace_id: UUID,
    session: DB,
    actor: Actor,
    cursor: Cursor = None,
    limit: Limit = 25,
):
    return access.list_members(session, actor, workspace_id, cursor, limit)


@router.patch("/workspaces/{workspace_id}/members/{user_id}", response_model=MemberView)
def change_role(
    workspace_id: UUID, user_id: UUID, body: RoleChange, session: DB, actor: Actor
):
    return access.change_role(session, actor, workspace_id, user_id, body.role)


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: UUID, user_id: UUID, session: DB, actor: Actor):
    access.remove_member(session, actor, workspace_id, user_id)


@router.post("/workspaces/{workspace_id}/ownership", response_model=WorkspaceView)
def transfer(workspace_id: UUID, body: OwnershipTransfer, session: DB, actor: Actor):
    return access.transfer_owner(session, actor, workspace_id, body.user_id)


@router.post(
    "/workspaces/{workspace_id}/invitations", response_model=InviteView, status_code=201
)
def invite(workspace_id: UUID, body: InviteCreate, session: DB, actor: Actor):
    return access.create_invitation(session, actor, workspace_id, body)


@router.get("/workspaces/{workspace_id}/invitations", response_model=Page[InviteView])
def workspace_invitations(
    workspace_id: UUID,
    session: DB,
    actor: Actor,
    cursor: Cursor = None,
    limit: Limit = 25,
):
    return access.list_invitations(session, actor, workspace_id, cursor, limit)


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}", status_code=204
)
def revoke(workspace_id: UUID, invitation_id: UUID, session: DB, actor: Actor):
    access.revoke_invitation(session, actor, workspace_id, invitation_id)


@router.get("/invitations", response_model=Page[InviteView])
def invitations(session: DB, actor: Actor, cursor: Cursor = None, limit: Limit = 25):
    return access.list_invitations(session, actor, None, cursor, limit)


@router.post("/invitations/{invitation_id}/accept", response_model=WorkspaceView)
def accept(invitation_id: UUID, session: DB, actor: Actor):
    return access.accept_invitation(session, actor, invitation_id)


@router.get("/workspaces/{workspace_id}/audit", response_model=Page[AuditView])
def audit(
    workspace_id: UUID,
    session: DB,
    actor: Actor,
    cursor: Cursor = None,
    limit: Limit = 25,
):
    return access.list_audit(session, actor, workspace_id, cursor, limit)
