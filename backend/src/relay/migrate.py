"""Run explicit schema upgrades, then provision the restricted runtime role."""

import os

from alembic import command
from alembic.config import Config

from relay.database import migration_engine
from relay.provision import grant_runtime_access


def main():
    password_file = os.environ.get("RELAY_RUNTIME_PASSWORD_FILE")
    if not password_file:
        raise RuntimeError(
            "Set RELAY_RUNTIME_PASSWORD_FILE for application provisioning"
        )
    command.upgrade(Config("alembic.ini"), "head")
    engine = migration_engine()
    try:
        grant_runtime_access(engine, password_file)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
