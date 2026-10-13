from alembic import context
from sqlalchemy import URL

from relay.database import migration_engine
from relay.models import Base


def configure(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    # Offline SQL generation needs no credentials or running database.
    context.configure(
        url=URL.create("postgresql+psycopg"),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        configure(connection)
    else:
        engine = migration_engine()
        try:
            with engine.connect() as connection:
                configure(connection)
        finally:
            engine.dispose()
