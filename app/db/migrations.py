"""Apply SQL migrations for D1 and SQLite backends."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from app.config import settings

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "d1"
_TRACKER_TABLE = "schema_migrations"


async def apply_migrations_async() -> None:
    """Run idempotent SQL migrations from migrations/d1/."""
    if not _MIGRATIONS_DIR.exists():
        return

    sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        return

    if settings.database_backend == "d1_http":
        from app.db.d1_client import D1Connection

        d1 = D1Connection()
        await _ensure_tracker_d1(d1)
        applied = await _applied_filenames_d1(d1)
        for path in sql_files:
            if path.name in applied:
                logger.debug("Skipping already applied migration: {}", path.name)
                continue
            await _run_sql_file_async(d1.execute, path)
            await _record_migration_d1(d1, path.name)
    elif settings.database_backend == "sqlite":
        db_path = settings.d1_local_db_path
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_tracker_sqlite(conn)
            applied = _applied_filenames_sqlite(conn)
            for path in sql_files:
                if path.name in applied:
                    logger.debug("Skipping already applied migration: {}", path.name)
                    continue
                _run_sql_file(lambda sql: _sqlite_exec(conn, sql), path)
                _record_migration_sqlite(conn, path.name)
            conn.commit()
        finally:
            conn.close()


async def _ensure_tracker_d1(d1: object) -> None:
    await d1.execute(  # type: ignore[attr-defined]
        f"CREATE TABLE IF NOT EXISTS {_TRACKER_TABLE} ("
        "filename TEXT PRIMARY KEY NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )


def _ensure_tracker_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_TRACKER_TABLE} ("
        "filename TEXT PRIMARY KEY NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )


async def _applied_filenames_d1(d1: object) -> set[str]:
    rows = await d1.execute(  # type: ignore[attr-defined]
        f"SELECT filename FROM {_TRACKER_TABLE}"
    )
    names: set[str] = set()
    for batch in rows if isinstance(rows, list) else []:
        for row in batch.get("results", []):
            if "filename" in row:
                names.add(row["filename"])
    return names


def _applied_filenames_sqlite(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(f"SELECT filename FROM {_TRACKER_TABLE}")
    return {row[0] for row in cur.fetchall()}


async def _record_migration_d1(d1: object, filename: str) -> None:
    applied_at = datetime.now(tz=timezone.utc).isoformat()
    await d1.execute(  # type: ignore[attr-defined]
        f"INSERT OR IGNORE INTO {_TRACKER_TABLE} (filename, applied_at) VALUES (?, ?)",
        [filename, applied_at],
    )


def _record_migration_sqlite(conn: sqlite3.Connection, filename: str) -> None:
    applied_at = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        f"INSERT OR IGNORE INTO {_TRACKER_TABLE} (filename, applied_at) VALUES (?, ?)",
        (filename, applied_at),
    )


def _sqlite_exec(conn: sqlite3.Connection, sql: str) -> None:
    for statement in _split_statements(sql):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                logger.debug("Skipping duplicate column migration: {}", exc)
                continue
            raise


def _run_sql_file(execute_fn: Callable[[str], None], path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    for statement in _split_statements(sql):
        execute_fn(statement)
    logger.info("Applied migration: {}", path.name)


async def _run_sql_file_async(
    execute_fn: Callable[[str], Awaitable[object]],
    path: Path,
) -> None:
    sql = path.read_text(encoding="utf-8")
    for statement in _split_statements(sql):
        try:
            await execute_fn(statement)
        except Exception as exc:  # noqa: BLE001 - tolerate idempotent re-adds on D1
            if "duplicate column name" in str(exc).lower():
                logger.debug("Skipping duplicate column migration: {}", exc)
                continue
            raise
    logger.info("Applied migration: {}", path.name)


def _strip_sql_comments(sql: str) -> str:
    """Remove ``--`` line comments, ignoring ``--`` inside single-quoted strings.

    The previous implementation dropped any semicolon-delimited chunk that merely
    *started* with ``--``, which silently discarded the DDL that followed a comment
    header (every ALTER in 001-003, plus indexes/backfills in 000). Stripping the
    comment text instead preserves the statements.
    """
    out_lines: list[str] = []
    for line in sql.splitlines():
        result: list[str] = []
        in_string = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'":
                in_string = not in_string
                result.append(ch)
            elif ch == "-" and not in_string and line[i + 1 : i + 2] == "-":
                break
            else:
                result.append(ch)
            i += 1
        out_lines.append("".join(result))
    return "\n".join(out_lines)


def _split_statements(sql: str) -> list[str]:
    cleaned = _strip_sql_comments(sql)
    parts = [part.strip() for part in cleaned.split(";")]
    return [part for part in parts if part]
