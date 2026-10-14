"""Add a workspace-scoped immutable event inbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_event_inbox"
down_revision = "0001_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "events",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_events_workspace_id_workspaces"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "source_id", name="uq_events_workspace_source"
        ),
        sa.CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9]*([._-][a-z0-9]+)*$'",
            name=op.f("ck_events_event_type_format"),
        ),
        sa.CheckConstraint(
            "source_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name=op.f("ck_events_source_id_format"),
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_events_content_hash_format"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_events_payload_object")
        ),
        sa.CheckConstraint(
            "octet_length(payload::text) <= 262144", name=op.f("ck_events_payload_size")
        ),
    )
    op.create_index(
        "ix_events_workspace_created_id", "events", ["workspace_id", "created_at", "id"]
    )


def downgrade():
    op.drop_index("ix_events_workspace_created_id", table_name="events")
    op.drop_table("events")
