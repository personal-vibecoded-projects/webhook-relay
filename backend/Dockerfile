FROM python:3.12-slim AS runtime
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.0
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --locked --no-dev && useradd --create-home relay
USER relay
EXPOSE 8000
CMD [".venv/bin/uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS database-tests
USER root
COPY tests ./tests
RUN uv sync --locked --group dev
USER relay
CMD [".venv/bin/pytest", "-m", "database", "-p", "no:cacheprovider"]
