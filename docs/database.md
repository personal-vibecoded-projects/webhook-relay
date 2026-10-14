# Database foundation

The first schema contains only `workspaces`: database-generated UUID primary key,
unique lowercase slug (3–63 characters, single hyphens between segments), name
(1–120 characters, not entirely spaces), and a timezone-aware creation timestamp.
Alembic owns schema changes; application startup does not create tables.

The authenticated workspace API uses the restricted `relay_app` role. Membership,
ownership, session, invitation, and audit tables are added by migration `0002`.
See [workspace access](workspace-access.md) for those invariants and the role demo.

## Local PostgreSQL

```sh
python3 scripts/init_dev_secrets.py
docker compose up --wait db
docker compose run --build --rm migrate
docker compose up --build --wait
```

The initializer checks that `.secrets/postgres_password` is gitignored and
untracked before creating it. It preserves existing credentials and never prints
their values. The parent directory is private; the file is readable inside the
non-root migration container through a read-only Compose secret mount.

PostgreSQL has no published host port. Its data is in the `postgres_data` named
volume. `docker compose down` keeps the volume. Do not remove the volume or use
`down --volumes` unless you intend to discard local data. Changing the password
file alone does not rotate the password of an already initialized database.

This Compose database is for local development. Its initialization role owns the
cluster and is used only by migration tooling and isolated tests. The application
uses a separate restricted role and secret. Hosted deployments also require secure
transport and a separately controlled migration/provisioning identity.

## Migration workflow

The `migrate` service runs `alembic upgrade head` and runtime-role provisioning. Repeating that command is safe
when the database is already at head. To inspect the revision or check drift:

```sh
docker compose run --rm migrate .venv/bin/alembic current
docker compose run --rm migrate .venv/bin/alembic check
```

To author a future migration, install the backend dev dependencies and use
`uv run alembic revision --autogenerate -m "describe the change"` against a local
database using the `RELAY_DB_HOST`, `RELAY_DB_PORT`, `RELAY_DB_NAME`,
`RELAY_DB_USER`, and `RELAY_DB_PASSWORD_FILE` environment variables.
The password file is required. Connection credentials stay out of `alembic.ini`.

Downgrading the first migration drops `workspaces` and its data. Upgrade/downgrade
tests exercise this only in disposable test databases; do not downgrade a database
whose workspace data you need to keep.

## Demo walkthrough

1. Run the setup commands above.
2. Run `docker compose run --rm migrate .venv/bin/alembic current` to see the first revision.
3. Run `docker compose run --build --rm database-tests` to exercise database-generated
   values, invalid slugs/names, duplicate rejection, rollback, drift detection,
   repeated upgrade, and downgrade/re-upgrade.
4. Open the dashboard at http://localhost:5173 and follow the workspace-access demo.
5. Address CodeRabbit findings and merge the current increment before starting subscriptions.
