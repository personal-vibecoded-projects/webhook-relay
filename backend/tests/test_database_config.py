import pytest

from relay.database import database_url


def test_missing_secret_configuration_is_clear(monkeypatch):
    monkeypatch.delenv("RELAY_DB_PASSWORD_FILE", raising=False)
    with pytest.raises(RuntimeError, match="Set RELAY_DB_PASSWORD_FILE"):
        database_url()


def test_unreadable_secret_has_no_underlying_exception(monkeypatch):
    monkeypatch.setenv("RELAY_DB_PASSWORD_FILE", "/nonexistent/relay-secret")
    with pytest.raises(RuntimeError, match="not readable") as error:
        database_url()
    assert error.value.__suppress_context__
