"""Shared SQLite connection helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event


def configure_sqlite_foreign_keys(engine: Any) -> Any:
    """Ensure SQLite enforces foreign keys for this engine."""
    target = engine.sync_engine if hasattr(engine, "sync_engine") else engine

    @event.listens_for(target, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine
