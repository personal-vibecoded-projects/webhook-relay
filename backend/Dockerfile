FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.0
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev && useradd --create-home relay
USER relay
EXPOSE 8000
CMD [".venv/bin/uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8000"]
