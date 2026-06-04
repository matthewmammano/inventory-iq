"""SQLAlchemy engine, session factory, and Base declaration."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, scoped_session, sessionmaker

_engine: Engine | None = None
_SessionLocal: scoped_session | None = None


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def init_db(database_url: str, *, pool_size: int = 10, max_overflow: int = 20) -> None:
    """Initialize engine and session factory. Call once at app startup."""
    global _engine, _SessionLocal

    _engine = create_engine(
        normalize_database_url(database_url),
        future=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    _SessionLocal = scoped_session(sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True))


def normalize_database_url(database_url: str) -> str:
    """Use the installed psycopg driver for Railway/Postgres URLs."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def create_all() -> None:
    """Create all tables (dev/test only — use Alembic in production)."""
    if _engine is None:
        raise RuntimeError("Call init_db() first.")
    Base.metadata.create_all(bind=_engine)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a bare session. Caller handles commit/rollback."""
    if _SessionLocal is None:
        raise RuntimeError("Call init_db() first.")
    session: Session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
        _SessionLocal.remove()


@contextmanager
def managed_session(session: Session | None = None) -> Iterator[Session]:
    """Yield a session with auto commit/rollback.

    Pass an existing session to reuse it (caller owns lifecycle).
    Pass None to open a new session that auto-commits/rolls back.
    """
    if session is not None:
        yield session
        return

    with get_session() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
