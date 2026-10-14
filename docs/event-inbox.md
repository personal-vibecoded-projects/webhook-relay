# Durable event inbox

The `events` table records provider identifiers, event types, JSONB payloads,
content fingerprints, and database-generated IDs/timestamps per workspace.
A unique `(workspace_id, source_id)` constraint enforces tenant-scoped intake.
Workspace deletion cascades to its events. There is no public intake endpoint
yet: callers must authorize the workspace before using this service.

`accept_event` uses `INSERT ... ON CONFLICT DO NOTHING`, followed by a fresh,
locking read for duplicates. Concurrent identical submissions return the same
ID; reusing an identifier with different event type or content raises
`IdempotencyConflict`. Requires READ COMMITTED. Callers own the transaction:
the service never commits or catches database transaction errors.

Fingerprints use sorted-key, compact UTF-8 JSON for event type and payload.
Object key order is ignored; array order and numeric representation are
significant. Python values must be actual JSON values, with string keys,
finite numbers, no Unicode NUL or invalid surrogates, at most 32 levels and
10,000 nodes. Canonical envelope size is capped at 128 KiB; the database also
limits stored JSONB text to 256 KiB. Intake snapshots mutable payloads.

`list_events` orders by `(created_at, id)` descending and uses tenant-bound
keyset cursors. The UUID breaks timestamp ties. Pages contain at most 200
events; pagination is a live view, not a snapshot of concurrent writes.

`purge_events` deletes at most `batch_size` old events from one workspace per
call (default 500, maximum 1,000), skipping rows held by other transactions.
Callers should commit between calls to bound transaction lock and WAL growth;
multiple calls in one transaction can delete more than 1,000 events.
Repeated runs drain eligible rows. Retention ends the deduplication window:
a purged provider ID
can be accepted again. A concurrent purge between conflict detection and
duplicate lookup raises a retryable conflict. The cutoff cannot be future.

Migration `0002_event_inbox` follows merged database foundation `0001_workspaces`.
It is independent of the open workspace-access PR: rebase the migration onto
the then-current Alembic head before merging both features. Downgrade drops
event data while preserving workspace rows; it is a development rollback.

Run `docker compose --profile test run --build --rm database-tests` to exercise
real PostgreSQL race, transaction, pagination, retention, constraints, and
migration drift tests. Each test gets a disposable database.
