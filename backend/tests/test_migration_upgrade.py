import os

import pytest
from alembic import command
from conftest import migrate
from sqlalchemy import text

pytestmark = [
    pytest.mark.database,
    pytest.mark.skipif(
        os.environ.get("RUN_DATABASE_TESTS") != "1", reason="Requires PostgreSQL"
    ),
]


def test_upgrade_preserves_existing_workspace_without_inventing_an_owner(database):
    migrate(database, command.downgrade, "0001_workspaces")
    with database.begin() as connection:
        original = connection.scalar(
            text(
                "INSERT INTO workspaces (slug, name) "
                "VALUES ('legacy-team', 'Legacy team') RETURNING id"
            )
        )
    migrate(database, command.upgrade, "head")
    with database.connect() as connection:
        row = connection.execute(
            text("SELECT id, name, ownership_state, owner_user_id FROM workspaces")
        ).one()
        assert row.id == original and row.name == "Legacy team"
        assert row.ownership_state == "unclaimed" and row.owner_user_id is None
    migrate(database, command.check)
