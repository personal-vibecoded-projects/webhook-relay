# Webhook Relay

A webhook delivery platform built through sequential CodeRabbit-reviewed PRs.

The baseline contains a React dashboard, FastAPI liveness endpoint, Docker Compose,
and automated checks. Event delivery and persistence are planned, not implemented.

## Run

With Docker and Compose:

```sh
docker compose up --build
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

## Review sequence

One implementation PR at a time: CodeRabbit review, fix findings, pass checks,
merge, then start the next increment. See [the roadmap](docs/roadmap.md).
No customer data or credentials belong in this public repository.
