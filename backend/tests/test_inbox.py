import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from conftest import migrate
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relay.inbox import (
    EventCursor,
    IdempotencyConflict,
    accept_event,
    list_events,
    purge_events,
)
from relay.models import Event, Workspace

pytestmark = [
    pytest.mark.database,
    pytest.mark.skipif(
        os.environ.get("RUN_DATABASE_TESTS") != "1",
        reason="Requires PostgreSQL",
    ),
]


@pytest.fixture
def tenants(database):
    with Session(database) as session, session.begin():
        first = Workspace(slug="first-team", name="First")
        second = Workspace(slug="second-team", name="Second")
        session.add_all([first, second])
        session.flush()
        return first.id, second.id


def test_idempotency_and_conflicting_content(database, tenants):
    with Session(database) as session, session.begin():
        first = accept_event(session, tenants[0], "evt1", "invoice.paid", {"a": 1})
        again = accept_event(session, tenants[0], "evt1", "invoice.paid", {"a": 1})
        assert first.created and not again.created
        assert first.event_id == again.event_id
        for kind, payload in [("invoice.paid", {"a": 2}), ("invoice.void", {"a": 1})]:
            with pytest.raises(IdempotencyConflict):
                accept_event(session, tenants[0], "evt1", kind, payload)
        assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_source_ids_are_workspace_scoped(database, tenants):
    with Session(database) as session, session.begin():
        results = [
            accept_event(session, tenant, "same", "invoice.paid", {})
            for tenant in tenants
        ]
        assert all(result.created for result in results)
        assert results[0].event_id != results[1].event_id
        for tenant in tenants:
            page = list_events(session, tenant)
            assert len(page.items) == 1 and page.items[0].workspace_id == tenant


def test_concurrent_duplicate_creates_one_event(database, tenants):
    ready = Barrier(2)

    def intake():
        with Session(database) as session, session.begin():
            ready.wait(timeout=10)
            return accept_event(session, tenants[0], "race", "invoice.paid", {})

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(intake)
        second = workers.submit(intake)
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert sorted(result.created for result in results) == [False, True]
    assert len({result.event_id for result in results}) == 1


def test_caller_rollback_removes_intake(database, tenants):
    with Session(database) as session:
        accept_event(session, tenants[0], "rollback", "invoice.paid", {})
        session.rollback()
        assert list_events(session, tenants[0]).items == ()


def test_stable_keyset_pagination_with_tied_timestamps(database, tenants):
    with Session(database) as session, session.begin():
        for number in range(5):
            accept_event(session, tenants[0], f"evt{number}", "invoice.paid", {})
        # now() is transaction-stable: all five rows have identical timestamps.
        seen = []
        cursor = None
        while True:
            page = list_events(session, tenants[0], limit=2, cursor=cursor)
            seen.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 5
        assert seen == sorted(seen, reverse=True)


def test_cursor_is_tenant_bound_and_limits_are_validated(database, tenants):
    with Session(database) as session:
        foreign = EventCursor(tenants[1], datetime.now(UTC), uuid4())
        with pytest.raises(ValueError, match="another workspace"):
            list_events(session, tenants[0], cursor=foreign)
        for limit in [0, 201, True]:
            with pytest.raises(ValueError):
                list_events(session, tenants[0], limit=limit)


def test_retention_is_batched_tenant_scoped_and_skips_locked_rows(database, tenants):
    old = datetime(2020, 1, 1, tzinfo=UTC)
    with Session(database) as session, session.begin():
        ids = [
            accept_event(session, tenants[0], f"old{i}", "invoice.paid", {}).event_id
            for i in range(3)
        ]
        accept_event(session, tenants[1], "other", "invoice.paid", {})
        session.execute(update(Event).values(created_at=old))
    with Session(database) as locker, locker.begin():
        locker.scalar(select(Event).where(Event.id == ids[0]).with_for_update())
        with Session(database) as session, session.begin():
            assert (
                purge_events(
                    session, tenants[0], before=old + timedelta(days=1), batch_size=1
                )
                == 1
            )
            assert (
                purge_events(session, tenants[0], before=old + timedelta(days=1)) == 1
            )
            assert len(list_events(session, tenants[0]).items) == 1
            assert len(list_events(session, tenants[1]).items) == 1
    with Session(database) as session, session.begin():
        assert purge_events(session, tenants[0], before=old + timedelta(days=1)) == 1
        assert purge_events(session, tenants[0], before=old + timedelta(days=1)) == 0


def test_database_rejects_invalid_payload_and_unknown_workspace(database, tenants):
    for payload, tenant in [([], tenants[0]), ({}, uuid4())]:
        with Session(database) as session:
            session.add(
                Event(
                    workspace_id=tenant,
                    source_id="evt",
                    event_type="valid",
                    content_hash="0" * 64,
                    payload=payload,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()


def test_workspace_delete_cascades_events(database, tenants):
    with Session(database) as session, session.begin():
        accept_event(session, tenants[0], "evt", "invoice.paid", {})
        session.delete(session.get(Workspace, tenants[0]))
    with Session(database) as session:
        assert list_events(session, tenants[0]).items == ()


def test_downgrade_preserves_existing_workspaces(database, tenants):
    migrate(database, command.downgrade, "0001_workspaces")
    assert inspect(database).has_table("workspaces")
    assert not inspect(database).has_table("events")
    migrate(database, command.upgrade, "head")
    migrate(database, command.check)
    with Session(database) as session:
        assert session.get(Workspace, tenants[0]).slug == "first-team"
