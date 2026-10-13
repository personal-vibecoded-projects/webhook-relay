"""Create the first workspace table."""

import sqlalchemy as sa
from alembic import op

revision = "0001_workspaces"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("slug", name=op.f("uq_workspaces_slug")),
        sa.CheckConstraint(
            "char_length(slug) BETWEEN 3 AND 63",
            name=op.f("ck_workspaces_slug_length"),
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'",
            name=op.f("ck_workspaces_slug_format"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) > 0", name=op.f("ck_workspaces_name_not_blank")
        ),
    )


def downgrade() -> None:
    op.drop_table("workspaces")
