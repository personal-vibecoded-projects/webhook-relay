"""Real PostgreSQL checks, isolated in a newly created database per test."""

import os
from uuid import UUID

import pytest
from alembic import command
from conftest import migrate
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from relay.models import Workspace

pytestmark = [
    pytest.mark.database,
    pytest.mark.skipif(
        os.environ.get("RUN_DATABASE_TESTS") != "1",
        reason="Run using the Compose database-tests service",
    ),
]


def test_upgrade_is_repeatable_and_matches_models(database):
    migrate(database, command.upgrade, "head")
    migrate(database, command.check)
    assert inspect(database).has_table("workspaces")
    with database.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0002_event_inbox"
        )


def test_database_generates_uuid_and_timezone_timestamp(database):
    with database.begin() as connection:
        row = connection.execute(
            text(
                "INSERT INTO workspaces (slug, name) VALUES (:slug, :name) "
                "RETURNING id, created_at"
            ),
            {"slug": "demo-team", "name": "Demo team"},
        ).one()
    assert isinstance(row.id, UUID)
    assert row.created_at.utcoffset() is not None
    with Session(database) as session:
        workspace = session.get(Workspace, row.id)
        assert workspace.slug == "demo-team"


def test_slug_is_unique_and_failed_insert_does_not_remove_existing_row(database):
    with Session(database) as session:
        session.add(Workspace(slug="demo-team", name="First team"))
        session.commit()
        session.add(Workspace(slug="demo-team", name="Duplicate team"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.scalars(select(Workspace)).one().name == "First team"


@pytest.mark.parametrize(
    ("slug", "name"),
    [
        ("UPPER-case", "Team"),
        ("ab", "Team"),
        ("a" * 64, "Team"),
        ("double--hyphen", "Team"),
        ("demo-team", "   "),
        ("demo-team", "x" * 121),
    ],
)
def test_invalid_workspace_values_are_rejected(database, slug, name):
    with Session(database) as session:
        session.add(Workspace(slug=slug, name=name))
        with pytest.raises((IntegrityError, DataError)):
            session.commit()
        session.rollback()


def test_downgrade_and_reupgrade(database):
    migrate(database, command.downgrade, "base")
    assert not inspect(database).has_table("workspaces")
    migrate(database, command.upgrade, "head")
    assert inspect(database).has_table("workspaces")
