"""Database engine and session management.

SQLite is the zero-configuration default so the whole system runs end to end
with nothing to install. PostgreSQL is fully supported and is the intended
production target: set RECONGUARD_DATABASE_URL and nothing else changes,
because the schema uses only portable column types.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()


def _build_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # The API serves requests on a threadpool, so the connection must not be
        # pinned to the creating thread.
        kwargs["connect_args"] = {"check_same_thread": False}
        path = url.split("sqlite:///")[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, **kwargs)


engine: Engine = _build_engine()


def get_engine() -> Engine:
    global engine
    current_url = get_settings().database_url
    if str(engine.url) != current_url:
        engine = _build_engine()
        from app.models.base import Base
        Base.metadata.create_all(bind=engine)
    return engine


def SessionLocal() -> Session:
    eng = get_engine()
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """WAL plus enforced foreign keys. Harmless and skipped on other backends."""
    module = type(dbapi_connection).__module__
    if "sqlite" not in module:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    get_engine()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
