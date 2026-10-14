# Webhook Relay

A webhook delivery platform built through sequential CodeRabbit-reviewed PRs.

The app contains a React dashboard and authenticated FastAPI workspace API backed
by PostgreSQL. Manage workspace roles, invitations, ownership, and audit history.
Alembic manages schema changes. Event delivery is the next increment.

## Run

With Docker and Compose:

```sh
python3 scripts/init_dev_secrets.py
docker compose up --wait db
docker compose run --build --rm migrate
docker compose up --build --wait
```

Open http://localhost:5173. API docs: http://localhost:8000/docs.
Ports bind to localhost; this is a development setup.

Or use Python 3.12+, uv, and Node 24. In one terminal:

```sh
cd backend
uv sync --locked --group dev
uv run uvicorn relay.main:app --reload --host 127.0.0.1 --port 8000
```

In another:

```sh
cd frontend
npm ci
npm run dev
```

## Check

```sh
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

```sh
cd frontend
npm ci
npm run build
npx playwright install chromium
npm test
```

Browser tests start both services; install the backend first.

Database migration, constraint, and schema-drift tests run against PostgreSQL:

```sh
docker compose run --build --rm database-tests
```

Each database test creates and drops its own randomly named database. The `relay`
database is not modified by tests. Tests require database-creation privileges.
Ordinary `pytest` skips these tests; the container CI job runs them explicitly.

See [workspace access](docs/workspace-access.md) for the account/role demo and
security contract, and [the database guide](docs/database.md) for migrations.

## Review sequence

One implementation PR at a time: CodeRabbit review, fix findings, pass checks,
merge, then start the next increment. See [the roadmap](docs/roadmap.md).
No customer data or credentials belong in this public repository.
