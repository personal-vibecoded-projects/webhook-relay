"""Users, sessions, memberships, invitations, and workspace audit history.

Existing workspaces remain unclaimed and are never assigned to an invented user.
New active workspaces must reference an owner membership at transaction commit.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_workspace_access"
down_revision = "0001_workspaces"
branch_labels = None
depends_on = None


def uuid_column(name, *args, **kwargs):
    return sa.Column(name, sa.Uuid(), *args, **kwargs)


def identifier():
    return uuid_column(
        "id", primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def created():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade():
    op.create_table(
        "users",
        identifier(),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        created(),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.CheckConstraint(
            "username ~ '^[a-z][a-z0-9_-]{2,31}$'",
            name=op.f("ck_users_username_format"),
        ),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        uuid_column(
            "user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        created(),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_throttles",
        sa.Column("scope_hash", sa.String(64), primary_key=True),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.add_column("workspaces", uuid_column("owner_user_id", nullable=True))
    op.add_column(
        "workspaces",
        sa.Column(
            "ownership_state", sa.String(12), nullable=False, server_default="unclaimed"
        ),
    )
    op.alter_column("workspaces", "ownership_state", server_default="active")
    op.create_check_constraint(
        op.f("ck_workspaces_ownership_state"),
        "workspaces",
        "(ownership_state = 'active' AND owner_user_id IS NOT NULL) OR "
        "(ownership_state = 'unclaimed' AND owner_user_id IS NULL)",
    )
    op.create_table(
        "memberships",
        uuid_column(
            "workspace_id",
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        uuid_column(
            "user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role", sa.String(12), nullable=False),
        created(),
        sa.CheckConstraint(
            "role IN ('admin', 'member', 'viewer')", name=op.f("ck_memberships_role")
        ),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_foreign_key(
        "fk_workspaces_owner_membership",
        "workspaces",
        "memberships",
        ["id", "owner_user_id"],
        ["workspace_id", "user_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "invitations",
        identifier(),
        uuid_column(
            "workspace_id",
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        uuid_column(
            "invitee_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        uuid_column("inviter_id", sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        created(),
        sa.CheckConstraint(
            "role IN ('admin', 'member', 'viewer')", name=op.f("ck_invitations_role")
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL) OR "
            "(status IN ('accepted', 'revoked') AND resolved_at IS NOT NULL)",
            name=op.f("ck_invitations_resolution"),
        ),
    )
    op.create_index(
        "uq_invitations_pending",
        "invitations",
        ["workspace_id", "invitee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_invitations_invitee_id", "invitations", ["invitee_id"])
    op.create_table(
        "audit_events",
        identifier(),
        uuid_column(
            "workspace_id",
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        uuid_column("actor_id", sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        created(),
    )
    op.create_index(
        "ix_audit_events_workspace_time",
        "audit_events",
        ["workspace_id", "created_at", "id"],
    )


def downgrade():
    op.drop_table("audit_events")
    op.drop_table("invitations")
    op.drop_constraint(
        "fk_workspaces_owner_membership", "workspaces", type_="foreignkey"
    )
    op.drop_table("memberships")
    op.drop_constraint(
        op.f("ck_workspaces_ownership_state"), "workspaces", type_="check"
    )
    op.drop_column("workspaces", "ownership_state")
    op.drop_column("workspaces", "owner_user_id")
    op.drop_table("auth_throttles")
    op.drop_table("auth_sessions")
    op.drop_table("users")
