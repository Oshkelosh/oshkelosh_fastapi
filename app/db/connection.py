"""
Database connection utilities.

Provides ``get_session`` for SQLite or D1 HTTP backends.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.backends.d1_binding import D1BindingNotConfiguredError, get_d1_binding
from app.db.backends.d1_http_session import d1_http_session
from app.db.d1_binding_connection import D1BindingConnection
from app.db.d1_client import D1Connection
from app.db.sqlite_utils import configure_sqlite_foreign_keys

# Re-export for callers that use get_d1()
__all__ = [
    "D1Connection",
    "get_session",
    "session_scope",
    "get_session_factory",
    "get_d1",
    "close_all_connections",
    "reset_session_factory",
    "reset_d1",
    "mark_instance_dirty",
]

_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_sqlite_engine: Any = None


def _create_sqlite_session_factory() -> async_sessionmaker[AsyncSession]:
    global _sqlite_engine
    db_path = f"sqlite+aiosqlite:///{settings.d1_local_db_path}"
    _sqlite_engine = create_async_engine(
        db_path,
        echo=settings.debug,
        connect_args={"check_same_thread": False},
    )
    configure_sqlite_foreign_keys(_sqlite_engine)
    return async_sessionmaker(_sqlite_engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return SQLAlchemy async session factory (sqlite backend only)."""
    if settings.database_backend == "d1_binding":
        get_d1_binding()
        raise RuntimeError("Use get_session() for d1_binding backend")
    if settings.database_backend == "d1_http":
        raise RuntimeError("Use get_session() for d1_http backend")

    global _session_factory
    if _session_factory is None:
        _session_factory = _create_sqlite_session_factory()
    return _session_factory


def reset_session_factory() -> None:
    global _session_factory
    _session_factory = None


def mark_instance_dirty(session: Any, instance: Any) -> None:
    """Track an ORM instance for UPDATE on flush (D1 HTTP backend)."""
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(instance)


@asynccontextmanager
async def session_scope() -> AsyncIterator[Any]:
    """Yield a DB session (for ``async with session_scope() as session:``)."""
    if settings.database_backend == "d1_binding":
        d1 = D1BindingConnection()
        async with d1_http_session(d1) as session:
            yield session
        return

    if settings.database_backend == "d1_http":
        d1 = get_d1()
        async with d1_http_session(d1) as session:
            yield session
        return

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(text("PRAGMA foreign_keys=ON"))
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_session() -> AsyncIterator[Any]:
    """FastAPI dependency — async generator, not ``@asynccontextmanager``."""
    async with session_scope() as session:
        yield session


_d1: Optional[D1Connection] = None


def get_d1() -> D1Connection:
    global _d1
    if _d1 is None:
        _d1 = D1Connection()
    return _d1


def reset_d1() -> None:
    global _d1
    _d1 = None


async def close_all_connections() -> None:
    global _d1, _session_factory, _sqlite_engine
    if _d1:
        await _d1.close()
        _d1 = None
    if _sqlite_engine is not None:
        await _sqlite_engine.dispose()
        _sqlite_engine = None
    _session_factory = None
