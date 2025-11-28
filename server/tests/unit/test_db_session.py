from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from app.db import session as session_module


def _reset_session_state() -> None:
    session_module._engine = None
    session_module._SessionLocal = None


@pytest.fixture(autouse=True)
def _reset_session_globals():
    _reset_session_state()
    yield
    _reset_session_state()


def test_get_engine_uses_sqlite_url_and_connect_args(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(
            outlets_db_backend="sqlite",
            outlets_sqlite_url=" sqlite:///tmp/outlets.db ",
            outlets_postgres_url=None,
        ),
    )

    session_module._get_engine()

    assert captured["url"] == "sqlite:///tmp/outlets.db"
    assert captured["kwargs"]["connect_args"] == {"check_same_thread": False}


def test_get_engine_uses_postgres_url_without_sqlite_connect_args(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(
            outlets_db_backend="postgres",
            outlets_sqlite_url="sqlite:///unused.db",
            outlets_postgres_url="postgresql+psycopg://example",
        ),
    )

    session_module._get_engine()

    assert captured["url"] == "postgresql+psycopg://example"
    assert "connect_args" not in captured["kwargs"]


def test_get_engine_raises_when_postgres_backend_missing_url(monkeypatch) -> None:
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(
            outlets_db_backend="postgres",
            outlets_sqlite_url="sqlite:///unused.db",
            outlets_postgres_url=None,
        ),
    )

    with pytest.raises(ValueError):
        session_module._get_engine()


