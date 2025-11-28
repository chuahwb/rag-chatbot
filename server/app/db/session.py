from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        backend = (settings.outlets_db_backend or "sqlite").strip().lower()
        if backend == "postgres":
            db_url = (settings.outlets_postgres_url or "").strip()
            if not db_url:
                raise ValueError("OUTLETS_POSTGRES_URL must be configured when OUTLETS_DB_BACKEND=postgres.")
        elif backend == "sqlite":
            db_url = (settings.outlets_sqlite_url or "").strip()
            if not db_url:
                raise ValueError("OUTLETS_SQLITE_URL / SQLITE_URL must be configured when OUTLETS_DB_BACKEND=sqlite.")
        else:
            raise ValueError(f"Unsupported OUTLETS_DB_BACKEND: {settings.outlets_db_backend}")
        kwargs: dict[str, object] = {}
        if db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(db_url, **kwargs)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def get_session() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()



