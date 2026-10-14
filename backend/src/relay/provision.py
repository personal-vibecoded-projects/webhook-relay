"""Provision only the application's documented table privileges."""

from pathlib import Path

from psycopg import sql
from sqlalchemy import Engine

from relay.models import AuditEvent, Base


def grant_runtime_access(engine: Engine, password_file: str, role="relay_app"):
    try:
        password = Path(password_file).read_text().rstrip("\r\n")
        if not password:
            raise ValueError
        with engine.begin() as connection:
            with connection.connection.driver_connection.cursor() as cursor:
                # This development bootstrap runs as the cluster initializer.
                # Prevent password-bearing role DDL from appearing in server logs.
                cursor.execute("SET LOCAL log_statement = 'none'")
                cursor.execute("SET LOCAL log_min_error_statement = 'panic'")
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is None:
                    cursor.execute(
                        sql.SQL("CREATE ROLE {} ").format(sql.Identifier(role))
                    )
                # Role DDL cannot use bind parameters; identifiers and literals are
                # quoted by Psycopg, and exceptions never reveal the SQL/password.
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(engine.url.database), sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(role)
                    )
                )
                for table in Base.metadata.tables.values():
                    if table.name == AuditEvent.__tablename__:
                        cursor.execute(
                            sql.SQL("REVOKE ALL ON TABLE {} FROM {}").format(
                                sql.Identifier("public", table.name),
                                sql.Identifier(role),
                            )
                        )
                    privileges = (
                        "SELECT, INSERT"
                        if table.name == AuditEvent.__tablename__
                        else "SELECT, INSERT, UPDATE, DELETE"
                    )
                    cursor.execute(
                        sql.SQL("GRANT " + privileges + " ON TABLE {} TO {}").format(
                            sql.Identifier("public", table.name), sql.Identifier(role)
                        )
                    )
                cursor.execute(
                    sql.SQL(
                        "REVOKE ALL ON TABLE public.alembic_version FROM {}"
                    ).format(sql.Identifier(role))
                )
    except Exception:
        raise RuntimeError("Runtime database role provisioning failed") from None
