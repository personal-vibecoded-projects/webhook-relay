from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relay.models import AuditEvent, Invitation, Membership, User, Workspace
from relay.pagination import next_cursor, paginate
from relay.schemas import InviteView, MemberView, Page, WorkspaceView


def effective_role(workspace, membership):
    return "owner" if workspace.owner_user_id == membership.user_id else membership.role


def workspace_view(workspace, membership):
    return WorkspaceView(
        id=workspace.id,
        slug=workspace.slug,
        name=workspace.name,
        owner_user_id=workspace.owner_user_id,
        role=effective_role(workspace, membership),
        created_at=workspace.created_at,
    )


def workspace_for(session: Session, workspace_id: UUID, actor: User, *, lock=False):
    statement = (
        select(Workspace, Membership)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(
            Workspace.id == workspace_id,
            Membership.user_id == actor.id,
            Workspace.ownership_state == "active",
        )
    )
    if lock:
        visible = session.scalar(
            select(Membership.user_id).where(
                Membership.workspace_id == workspace_id, Membership.user_id == actor.id
            )
        )
        if visible is None:
            raise HTTPException(404, "Workspace not found")
        workspace = session.scalar(
            select(Workspace)
            .where(Workspace.id == workspace_id, Workspace.ownership_state == "active")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        membership = session.scalar(
            select(Membership)
            .where(
                Membership.workspace_id == workspace_id, Membership.user_id == actor.id
            )
            .execution_options(populate_existing=True)
        )
        if workspace is None or membership is None:
            raise HTTPException(404, "Workspace not found")
        return workspace, membership
    row = session.execute(statement).one_or_none()
    if row is None:
        raise HTTPException(404, "Workspace not found")
    return row


def manager(workspace, membership):
    if effective_role(workspace, membership) not in {"owner", "admin"}:
        raise HTTPException(403, "Workspace management permission required")


def may_manage_role(workspace, membership, role):
    manager(workspace, membership)
    if role == "admin" and effective_role(workspace, membership) != "owner":
        raise HTTPException(403, "Only the owner can manage administrators")


def audit(session, workspace, actor, action, **details):
    session.add(
        AuditEvent(
            workspace_id=workspace.id, actor_id=actor.id, action=action, details=details
        )
    )


def create_workspace(session, actor, body):
    workspace = Workspace(
        slug=body.slug, name=body.name, owner_user_id=actor.id, ownership_state="active"
    )
    session.add(workspace)
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(409, "Workspace slug already exists") from None
    membership = Membership(workspace_id=workspace.id, user_id=actor.id, role="admin")
    session.add(membership)
    audit(session, workspace, actor, "workspace.created", slug=workspace.slug)
    session.flush()
    return workspace_view(workspace, membership)


def list_workspaces(session, actor, cursor, limit):
    statement = (
        select(Workspace, Membership)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == actor.id, Workspace.ownership_state == "active")
    )
    rows = session.execute(paginate(statement, Workspace, cursor, limit)).all()
    return Page(
        items=[workspace_view(w, m) for w, m in rows[:limit]],
        next_cursor=next_cursor([w for w, _ in rows], limit),
    )


def list_members(session, actor, workspace_id, cursor, limit):
    workspace, _ = workspace_for(session, workspace_id, actor)
    statement = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace.id)
    )
    rows = session.execute(
        paginate(statement, Membership, cursor, limit, "user_id")
    ).all()
    return Page(
        items=[
            MemberView(id=u.id, username=u.username, role=effective_role(workspace, m))
            for m, u in rows[:limit]
        ],
        next_cursor=next_cursor([m for m, _ in rows], limit, "user_id"),
    )


def rename_workspace(session, actor, workspace_id, body):
    workspace, membership = workspace_for(session, workspace_id, actor, lock=True)
    manager(workspace, membership)
    if workspace.name != body.name:
        previous = workspace.name
        workspace.name = body.name
        audit(
            session,
            workspace,
            actor,
            "workspace.renamed",
            previous_name=previous,
            name=body.name,
        )
    return workspace_view(workspace, membership)


def change_role(session, actor, workspace_id, user_id, role):
    workspace, caller = workspace_for(session, workspace_id, actor, lock=True)
    member = session.get(Membership, (workspace.id, user_id))
    if member is None:
        raise HTTPException(404, "Member not found")
    if user_id == workspace.owner_user_id:
        raise HTTPException(409, "Transfer ownership before changing the owner")
    may_manage_role(workspace, caller, member.role)
    may_manage_role(workspace, caller, role)
    if member.role != role:
        old_role = member.role
        member.role = role
        audit(
            session,
            workspace,
            actor,
            "membership.role_changed",
            user_id=str(user_id),
            previous_role=old_role,
            role=role,
        )
    user = session.get(User, user_id)
    return MemberView(id=user.id, username=user.username, role=role)


def remove_member(session, actor, workspace_id, user_id):
    workspace, caller = workspace_for(session, workspace_id, actor, lock=True)
    member = session.get(Membership, (workspace.id, user_id))
    if member is None:
        raise HTTPException(404, "Member not found")
    if user_id == workspace.owner_user_id:
        raise HTTPException(409, "Transfer ownership before leaving")
    if actor.id != user_id:
        may_manage_role(workspace, caller, member.role)
    session.delete(member)
    audit(session, workspace, actor, "membership.removed", user_id=str(user_id))


def transfer_owner(session, actor, workspace_id, target_id):
    workspace, caller = workspace_for(session, workspace_id, actor, lock=True)
    if effective_role(workspace, caller) != "owner":
        raise HTTPException(403, "Only the owner can transfer ownership")
    target = session.get(Membership, (workspace.id, target_id))
    if target is None:
        raise HTTPException(409, "New owner must already be a workspace member")
    target_user = session.get(User, target_id)
    if not target_user.enabled:
        raise HTTPException(409, "New owner must be an enabled user")
    if target_id != workspace.owner_user_id:
        previous = workspace.owner_user_id
        target.role = "admin"
        workspace.owner_user_id = target_id
        audit(
            session,
            workspace,
            actor,
            "workspace.ownership_transferred",
            from_user_id=str(previous),
            to_user_id=str(target_id),
        )
    return workspace_view(workspace, caller)


def invite_view(invitation, workspace_name, username, now):
    status = invitation.status
    if status == "pending" and invitation.expires_at <= now:
        status = "expired"
    return InviteView(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        workspace_name=workspace_name,
        username=username,
        role=invitation.role,
        status=status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


def inviter_authorized(session, workspace, invitation):
    inviter = session.get(Membership, (workspace.id, invitation.inviter_id))
    user = session.get(User, invitation.inviter_id)
    if inviter is None or user is None or not user.enabled:
        return False
    if invitation.role == "admin":
        return workspace.owner_user_id == invitation.inviter_id
    return effective_role(workspace, inviter) in {"owner", "admin"}


def create_invitation(session, actor, workspace_id, body):
    workspace, caller = workspace_for(session, workspace_id, actor, lock=True)
    may_manage_role(workspace, caller, body.role)
    invitee = session.scalar(
        select(User).where(User.username == body.username, User.enabled.is_(True))
    )
    if invitee is None:
        raise HTTPException(404, "Ask this person to create an account first")
    if session.get(Membership, (workspace.id, invitee.id)) is not None:
        raise HTTPException(409, "User is already a member")
    now = session.scalar(select(func.clock_timestamp()))
    existing = session.scalar(
        select(Invitation).where(
            Invitation.workspace_id == workspace.id,
            Invitation.invitee_id == invitee.id,
            Invitation.status == "pending",
        )
    )
    if existing is not None:
        if (
            existing.expires_at > now
            and existing.role == body.role
            and inviter_authorized(session, workspace, existing)
        ):
            return invite_view(existing, workspace.name, invitee.username, now)
        existing.status, existing.resolved_at = "revoked", now
        audit(
            session,
            workspace,
            actor,
            "invitation.revoked",
            invitation_id=str(existing.id),
        )
        session.flush()
    invitation = Invitation(
        workspace_id=workspace.id,
        invitee_id=invitee.id,
        inviter_id=actor.id,
        role=body.role,
        status="pending",
        expires_at=now + timedelta(days=7),
    )
    session.add(invitation)
    session.flush()
    audit(
        session,
        workspace,
        actor,
        "invitation.created",
        invitation_id=str(invitation.id),
        user_id=str(invitee.id),
        role=body.role,
    )
    return invite_view(invitation, workspace.name, invitee.username, now)


def list_invitations(session, actor, workspace_id, cursor, limit):
    statement = (
        select(Invitation, Workspace.name, User.username)
        .join(Workspace, Workspace.id == Invitation.workspace_id)
        .join(User, User.id == Invitation.invitee_id)
    )
    if workspace_id is None:
        statement = statement.where(
            Invitation.invitee_id == actor.id,
            Invitation.status == "pending",
            Invitation.expires_at > func.clock_timestamp(),
        )
    else:
        workspace, caller = workspace_for(session, workspace_id, actor)
        manager(workspace, caller)
        statement = statement.where(Invitation.workspace_id == workspace.id)
    rows = session.execute(paginate(statement, Invitation, cursor, limit)).all()
    now = session.scalar(select(func.clock_timestamp()))
    return Page(
        items=[
            invite_view(i, name, username, now) for i, name, username in rows[:limit]
        ],
        next_cursor=next_cursor([i for i, _, _ in rows], limit),
    )


def accept_invitation(session, actor, invitation_id):
    invitation = session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.invitee_id == actor.id
        )
    )
    if invitation is None:
        raise HTTPException(404, "Invitation not found")
    # All aggregate mutations take the workspace lock before any invitation lock.
    workspace = session.scalar(
        select(Workspace)
        .where(Workspace.id == invitation.workspace_id)
        .with_for_update()
    )
    session.refresh(invitation, with_for_update=True)
    member = session.get(Membership, (workspace.id, actor.id))
    if invitation.status == "accepted":
        if member is None:
            raise HTTPException(409, "Membership is no longer active")
        return workspace_view(workspace, member)
    now = session.scalar(select(func.clock_timestamp()))
    authorized = inviter_authorized(session, workspace, invitation)
    if invitation.status != "pending" or invitation.expires_at <= now or not authorized:
        raise HTTPException(410, "Invitation is no longer valid")
    if member is not None:
        raise HTTPException(409, "User is already a member")
    member = Membership(
        workspace_id=workspace.id, user_id=actor.id, role=invitation.role
    )
    session.add(member)
    invitation.status, invitation.resolved_at = "accepted", now
    audit(
        session,
        workspace,
        actor,
        "invitation.accepted",
        invitation_id=str(invitation.id),
        role=invitation.role,
    )
    session.flush()
    return workspace_view(workspace, member)


def revoke_invitation(session, actor, workspace_id, invitation_id):
    workspace, caller = workspace_for(session, workspace_id, actor, lock=True)
    invitation = session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.workspace_id == workspace.id
        )
    )
    if invitation is None:
        raise HTTPException(404, "Invitation not found")
    may_manage_role(workspace, caller, invitation.role)
    if invitation.status == "accepted":
        raise HTTPException(
            409, "Invitation was accepted; manage the membership instead"
        )
    if invitation.status != "revoked":
        invitation.status, invitation.resolved_at = (
            "revoked",
            session.scalar(select(func.clock_timestamp())),
        )
        audit(
            session,
            workspace,
            actor,
            "invitation.revoked",
            invitation_id=str(invitation.id),
        )


def list_audit(session, actor, workspace_id, cursor, limit):
    workspace, caller = workspace_for(session, workspace_id, actor)
    manager(workspace, caller)
    rows = session.scalars(
        paginate(
            select(AuditEvent).where(AuditEvent.workspace_id == workspace.id),
            AuditEvent,
            cursor,
            limit,
        )
    ).all()
    return {"items": rows[:limit], "next_cursor": next_cursor(rows, limit)}
