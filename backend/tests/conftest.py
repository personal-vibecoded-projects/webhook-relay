from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from relay.database import database_url, migration_engine


def migrate(engine, operation, target=None):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if target is None:
            operation(config)
        else:
            operation(config, target)


@pytest.fixture
def database():
    name = "relay_test_" + uuid4().hex
    admin = migration_engine(database_url().set(database="postgres"))
    engine = None
    created = False
    try:
        with admin.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(name))
                )
        created = True
        engine = migration_engine(database_url().set(database=name))
        migrate(engine, command.upgrade, "head")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                with connection.connection.driver_connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(name)
                        )
                    )
        admin.dispose()
