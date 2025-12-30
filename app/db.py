"""SQLAlchemy v2 core helpers for Inventory IQ.

This module centralizes engine/session/base creation so the codebase can move
away from Flask-SQLAlchemy. It exposes:
- init_db(app): initialize engine and session factory using Flask config
- get_session(): contextmanager yielding a SQLAlchemy Session (scoped)
- Base: declarative base for models to inherit from
- create_all(): helper to create tables (used by app factory in dev)

We use SQLAlchemy 1.4+/2.0 style (future=True, sessionmaker) and a scoped
session so existing code can call get_session() and get a Session instance.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

try:
    # SQLAlchemy 2.0 style
    from sqlalchemy.orm import DeclarativeBase as _DeclarativeBase  # type: ignore
except Exception:  # pragma: no cover - fallback for older versions
    from sqlalchemy.orm import declarative_base as _declarative_base

# Module-level objects that will be initialized by init_db
engine: Engine | None = None
SessionLocal: scoped_session | None = None
try:

    class Base(_DeclarativeBase):
        """Declarative base for ORM models (preferred SQLAlchemy 2.0 API)."""

except Exception:
    Base = _declarative_base()


def init_db(app) -> None:
    """Initialize the SQLAlchemy Engine and Session using Flask app config.

    Parameters
    ----------
    app: Flask
        The Flask application instance whose config contains
        SQLALCHEMY_DATABASE_URI and optional SQLALCHEMY_ENGINE_OPTIONS.
    """
    global engine, SessionLocal

    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        raise RuntimeError("SQLALCHEMY_DATABASE_URI is not configured")

    engine_options = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}) or {}

    # Set sensible defaults for PostgreSQL connection pooling if not overridden
    # These prevent connection exhaustion and improve production stability
    if "pool_size" not in engine_options:
        engine_options["pool_size"] = 10  # Keep 10 connections in pool
    if "max_overflow" not in engine_options:
        engine_options["max_overflow"] = (
            20  # Allow up to 20 additional overflow connections
        )
    if "pool_recycle" not in engine_options:
        engine_options["pool_recycle"] = (
            3600  # Recycle connections every hour (default 1h)
        )
    if "pool_pre_ping" not in engine_options:
        engine_options["pool_pre_ping"] = (
            True  # Test connections before using (detects stale connections)
        )

    # Create engine in SQLAlchemy 2.0 compatible `future` mode
    engine = create_engine(database_uri, future=True, **engine_options)

    # Create a scoped session factory. expire_on_commit=False keeps objects usable
    SessionLocal = scoped_session(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    )


@contextmanager
def get_session() -> Iterator[Session]:
    """Context manager that yields a SQLAlchemy Session and handles cleanup.

    Usage:
        with get_session() as session:
            session.add(obj)
            session.commit()

    Returns
    -------
    Session
        A SQLAlchemy Session instance from the scoped factory.
    """
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db(app) first.")

    session: Session = SessionLocal()
    try:
        yield session
        # Caller controls commit/rollback; we avoid auto-commit here.
    finally:
        try:
            session.close()
        finally:
            # Remove session from scoped registry for safety
            SessionLocal.remove()


@contextmanager
def managed_session(session: Session | None) -> Iterator[Session]:
    """Yield a Session and manage commit/rollback only if we own it.

    - If `session` is None, open via `get_session()`; commit on success,
      rollback on exception, and close.
    - If `session` is provided, yield it without committing/rolling back.
    """
    ctx = get_session() if session is None else None
    if ctx is not None:
        _s: Session = ctx.__enter__()
    else:
        if session is None:
            raise RuntimeError("Session management error: expected a Session")
        _s = session
    try:
        yield _s
        if ctx is not None:
            _s.commit()
    except Exception:
        if ctx is not None:
            _s.rollback()
        raise
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)


def create_all() -> None:
    """Create all tables for the declarative Base using the initialized engine.

    Note: In production, prefer Alembic for migrations. This helper is useful
    for local development and tests.
    """
    if engine is None:
        raise RuntimeError(
            "Database engine is not initialized. Call init_db(app) first."
        )
    Base.metadata.create_all(bind=engine)
