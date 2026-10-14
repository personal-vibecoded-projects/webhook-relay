"""Transactional event inbox. Callers authorize access and own commit/rollback."""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from relay.models import Event

_TYPE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class InvalidEvent(ValueError):
    pass


class IdempotencyConflict(ValueError):
    """A source identifier was reused with different content."""


@dataclass(frozen=True)
class IntakeResult:
    event_id: UUID
    created: bool


@dataclass(frozen=True)
class EventCursor:
    workspace_id: UUID
    created_at: datetime
    event_id: UUID


@dataclass(frozen=True)
class EventRecord:
    id: UUID
    workspace_id: UUID
    source_id: str
    event_type: str
    created_at: datetime
    payload: dict = field(repr=False)


@dataclass(frozen=True)
class EventPage:
    items: tuple[EventRecord, ...]
    next_cursor: EventCursor | None


def _snapshot(event_type, source_id, payload):
    if (
        not isinstance(event_type, str)
        or len(event_type) > 128
        or not _TYPE.fullmatch(event_type)
        or not isinstance(source_id, str)
        or not _SOURCE.fullmatch(source_id)
        or not isinstance(payload, dict)
    ):
        raise InvalidEvent("Invalid event envelope")
    # Restrict Python inputs to real JSON values; json.dumps alone coerces keys
    # and tuples, which can create surprising idempotency equivalences.
    stack = [(payload, 0)]
    count = 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if depth > 32 or count > 10_000:
            raise InvalidEvent("Event structure exceeds limits")
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise InvalidEvent("JSON keys must be strings")
            stack.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif type(value) is list:
            stack.extend((item, depth + 1) for item in value)
        elif type(value) is float:
            if not math.isfinite(value):
                raise InvalidEvent("Invalid JSON number")
        elif type(value) is str:
            if "\x00" in value:
                raise InvalidEvent("Unicode NUL cannot be stored in JSONB")
        elif value is not None and type(value) not in (str, int, bool):
            raise InvalidEvent("Invalid JSON value")
    try:
        canonical = json.dumps(
            {"event_type": event_type, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise InvalidEvent("Invalid JSON payload") from None
    if len(canonical) > 128 * 1024:
        raise InvalidEvent("Event payload exceeds storage limits")
    return json.loads(canonical)["payload"], hashlib.sha256(canonical).hexdigest()


def accept_event(
    session: Session,
    workspace_id: UUID,
    source_id: str,
    event_type: str,
    payload: dict,
) -> IntakeResult:
    """Atomic duplicate handling under PostgreSQL READ COMMITTED isolation."""
    snapshot, digest = _snapshot(event_type, source_id, payload)
    if session.connection().get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("Inbox intake requires READ COMMITTED isolation")
    inserted = session.scalar(
        insert(Event)
        .values(
            workspace_id=workspace_id,
            source_id=source_id,
            event_type=event_type,
            payload=snapshot,
            content_hash=digest,
        )
        .on_conflict_do_nothing(constraint="uq_events_workspace_source")
        .returning(Event.id)
    )
    if inserted is not None:
        return IntakeResult(inserted, True)
    # ON CONFLICT waits for concurrent intake. A fresh statement sees its commit.
    existing = session.execute(
        select(Event.id, Event.content_hash)
        .where(Event.workspace_id == workspace_id, Event.source_id == source_id)
        .with_for_update()
    ).one_or_none()
    if existing is None:
        # Retention may remove a row between the conflict and this lookup.
        raise IdempotencyConflict("Event changed during intake; retry transaction")
    if existing.content_hash != digest:
        raise IdempotencyConflict("Source identifier already has different content")
    return IntakeResult(existing.id, False)


def _aware(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")


def list_events(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int = 50,
    cursor: EventCursor | None = None,
) -> EventPage:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Page size must be between 1 and 200")
    statement = select(Event).where(Event.workspace_id == workspace_id)
    if cursor is not None:
        if cursor.workspace_id != workspace_id:
            raise ValueError("Cursor belongs to another workspace")
        _aware(cursor.created_at)
        statement = statement.where(
            tuple_(Event.created_at, Event.id)
            < tuple_(cursor.created_at, cursor.event_id)
        )
    rows = session.scalars(
        statement.order_by(Event.created_at.desc(), Event.id.desc()).limit(limit + 1)
    ).all()
    items = tuple(
        EventRecord(
            row.id,
            row.workspace_id,
            row.source_id,
            row.event_type,
            row.created_at,
            row.payload,
        )
        for row in rows[:limit]
    )
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = EventCursor(workspace_id, last.created_at, last.id)
    return EventPage(items, next_cursor)


def purge_events(
    session: Session,
    workspace_id: UUID,
    *,
    before: datetime,
    batch_size: int = 500,
) -> int:
    """Delete one bounded tenant batch; locked events are skipped for later runs."""
    _aware(before)
    if before > datetime.now(UTC):
        raise ValueError("Retention cutoff cannot be in the future")
    if type(batch_size) is not int or not 1 <= batch_size <= 1000:
        raise ValueError("Retention batch size must be between 1 and 1000")
    candidates = session.scalars(
        select(Event.id)
        .where(Event.workspace_id == workspace_id, Event.created_at < before)
        .order_by(Event.created_at, Event.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    if not candidates:
        return 0
    return session.execute(
        delete(Event).where(
            Event.workspace_id == workspace_id, Event.id.in_(candidates)
        )
    ).rowcount
