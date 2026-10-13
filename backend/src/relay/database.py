"""Database configuration for migration tooling; no public data access yet."""

import os
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine


def database_url() -> URL:
    """Build a URL in memory without placing credentials in config or logs."""
    password_path = os.environ.get("RELAY_DB_PASSWORD_FILE")
    if not password_path:
        raise RuntimeError("Set RELAY_DB_PASSWORD_FILE to a database secret file")
    try:
        password = Path(password_path).read_text().rstrip("\r\n")
    except OSError:
        raise RuntimeError("Database password file is not readable") from None
    if not password:
        raise RuntimeError("Database password file is empty")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("RELAY_DB_USER", "relay_migrator"),
        password=password,
        host=os.environ.get("RELAY_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("RELAY_DB_PORT", "5432")),
        database=os.environ.get("RELAY_DB_NAME", "relay"),
    )


def migration_engine(url: URL | None = None) -> Engine:
    return create_engine(
        url if url is not None else database_url(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000"},
    )
