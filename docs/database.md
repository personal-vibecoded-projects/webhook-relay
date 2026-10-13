# Database foundation

The first schema contains only `workspaces`: database-generated UUID primary key,
unique lowercase slug (3–63 characters, single hyphens between segments), name
(1–120 characters, not entirely spaces), and a timezone-aware creation timestamp.
Alembic owns schema changes; application startup does not create tables.

No endpoint reads or writes workspace data yet. The API container is not given
database credentials in this increment. Membership and authenticated access come
next, before any public workspace routes.

## Local PostgreSQL

```sh
python3 scripts/init_dev_secrets.py
docker compose up --build --wait
docker compose run --build --rm migrate
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
receives no credential. Before connecting an application to a deployed database,
provision separate least-privilege runtime and migration roles and secure transport.

## Migration workflow

The `migrate` service runs `alembic upgrade head`. Repeating that command is safe
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

1. Run the three setup commands above.
2. Run `docker compose run --rm migrate .venv/bin/alembic current` to see the first revision.
3. Run `docker compose run --build --rm database-tests` to exercise database-generated
   values, invalid slugs/names, duplicate rejection, rollback, drift detection,
   repeated upgrade, and downgrade/re-upgrade.
4. Open the dashboard at http://localhost:5173. It still checks API liveness;
   database readiness and workspace management are not exposed yet.
5. Review this migration PR, address CodeRabbit findings, then merge it before
   beginning membership/authentication.
